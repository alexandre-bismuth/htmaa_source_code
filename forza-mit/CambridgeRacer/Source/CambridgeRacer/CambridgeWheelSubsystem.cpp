#include "CambridgeWheelSubsystem.h"

#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "HAL/RunnableThread.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

#if PLATFORM_MAC || PLATFORM_LINUX
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>
#define CAMBRIDGE_WHEEL_POSIX 1
#else
#define CAMBRIDGE_WHEEL_POSIX 0
#endif

DEFINE_LOG_CATEGORY_STATIC(LogWheel, Log, All);

namespace
{
	constexpr double ActiveTimeout = 0.5;      // s without samples -> wheel considered gone
	constexpr double FFBPeriod = 1.0 / 250.0;
	constexpr double FFBStale = 0.1;           // s without a fresh torque from the car -> send 0
	constexpr int32 MinPedalSpan = 200;        // raw counts before a pedal counts as calibrated
	constexpr double NoDataTimeout = 3.0;      // s after opening without one valid sample -> not the wheel
	constexpr double ReconnectDelay = 1.0;     // s between connection attempts (hot-plug)
	constexpr double MaxEdgeAge = 0.5;         // s: older paddle / button presses are dropped
	constexpr int32 MaxLine = 120;             // longer lines are garbage

	// test: drive the wheel's buttons / throttle from a shot tour step (a wheel or wheel_sim.py must be connected)
	FAutoConsoleCommandWithWorldAndArgs WheelTestCmd(TEXT("cr.Wheel.Test"),
		TEXT("Test: cr.Wheel.Test <seconds> <throttle 0..1> <buttons: 1 right paddle, 2 left, 3 both, 4 start> [brake 0..1] (needs a connected wheel or wheel_sim.py)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
			if (UCambridgeWheelSubsystem* W = GI ? GI->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr; W && Args.Num() >= 3)
			{
				W->SetTestInput(FCString::Atof(*Args[0]), FCString::Atof(*Args[1]), FCString::Atoi(*Args[2]), Args.Num() > 3 ? FCString::Atof(*Args[3]) : 0.0f);
			}
		}));

	bool ValidPedalRange(int32 Min, int32 Max)
	{
		return Max > Min && int64(Max) - int64(Min) >= MinPedalSpan;
	}

	float Pedal(int32 Raw, int32 Min, int32 Max)
	{
		if (!ValidPedalRange(Min, Max))
		{
			return 0.0f;
		}
		const double T = (double(Raw) - Min) / (double(Max) - Min);
		return FMath::Clamp(float((T - 0.03) / 0.94), 0.0f, 1.0f);   // 3 % dead zone at both ends
	}

	/** Strict integer field: optional sign, digits, in [Lo, Hi]. Advances P past it. */
	bool ParseField(const char*& P, long Lo, long Hi, int32& Out)
	{
		while (*P == ' ' || *P == '\t') { ++P; }
		char* End = nullptr;
		errno = 0;
		const long V = strtol(P, &End, 10);
		if (End == P || errno != 0 || V < Lo || V > Hi || (*End != ' ' && *End != '\t' && *End != 0))
		{
			return false;
		}
		P = End;
		Out = int32(V);
		return true;
	}
}

UCambridgeWheelSubsystem* UCambridgeWheelSubsystem::Get(const UObject* WorldContext)
{
	const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
	const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr;
}

bool UCambridgeWheelSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return CAMBRIDGE_WHEEL_POSIX && !IsRunningCommandlet() && Super::ShouldCreateSubsystem(Outer);
}

void UCambridgeWheelSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	const TCHAR* Cmd = FCommandLine::Get();
	// a port from the command line is for this run only (tests with tools/wheel/wheel_sim.py): it is never
	// written into Port, and nothing is saved in such runs, so they can't overwrite the player's calibration
	FParse::Value(Cmd, TEXT("WheelPort="), PortOverride);
	bSessionOnly = !PortOverride.IsEmpty() || FCString::Strifind(Cmd, TEXT("-ShotTour")) || FCString::Strifind(Cmd, TEXT("-DriveTest"));
	bLogStatus = FParse::Param(Cmd, TEXT("WheelLog"));
	// sanitize what Input.ini gave us: a broken calibration is ignored (the pedals calibrate themselves)
	RotationRangeDeg = FMath::Clamp(FMath::IsFinite(RotationRangeDeg) ? RotationRangeDeg : 540.0f, 180.0f, 1080.0f);
	ForceFeedbackStrength = FMath::Clamp(FMath::IsFinite(ForceFeedbackStrength) ? ForceFeedbackStrength : 0.7f, 0.0f, 1.0f);
	SteerCentreCentideg = FMath::Clamp(FMath::IsFinite(SteerCentreCentideg) ? SteerCentreCentideg : 0.0f, -100000.0f, 100000.0f);
	if (ValidPedalRange(ThrottleMin, ThrottleMax))
	{
		CalThrottleMin = ThrottleMin;
		CalThrottleMax = ThrottleMax;
	}
	if (ValidPedalRange(BrakeMin, BrakeMax))
	{
		CalBrakeMin = BrakeMin;
		CalBrakeMax = BrakeMax;
	}
	Thread = FRunnableThread::Create(this, TEXT("CambridgeWheel"), 0, TPri_AboveNormal);
}

void UCambridgeWheelSubsystem::Deinitialize()
{
	if (Thread)
	{
		bStopping = true;
		Thread->WaitForCompletion();
		delete Thread;
		Thread = nullptr;
	}
	ClosePort();
	Super::Deinitialize();
}

TStatId UCambridgeWheelSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UCambridgeWheelSubsystem, STATGROUP_Tickables);
}

bool UCambridgeWheelSubsystem::IsActive() const
{
	FScopeLock L(&Lock);
	return Fd >= 0 && SampleCount > 0 && FPlatformTime::Seconds() - LastSampleTime < ActiveTimeout;
}

FWheelInputState UCambridgeWheelSubsystem::GetState() const
{
	FScopeLock L(&Lock);
	FWheelInputState S;
	S.SteerDeg = (RawSteer - SteerCentreCentideg) / 100.0f;
	S.Throttle = FPlatformTime::Seconds() < TestUntil ? TestThrottle : Pedal(RawThrottle, CalThrottleMin, CalThrottleMax);
	S.Brake = FPlatformTime::Seconds() < TestUntil ? TestBrake : Pedal(RawBrake, CalBrakeMin, CalBrakeMax);
	S.bUpshift = (Buttons & 1) != 0;
	S.bDownshift = (Buttons & 2) != 0;
	S.bStart = (Buttons & 4) != 0;
	return S;
}

bool UCambridgeWheelSubsystem::ConsumeEdge(bool& bEdge, double EdgeTime)
{
	FScopeLock L(&Lock);
	const bool B = bEdge && FPlatformTime::Seconds() - EdgeTime < MaxEdgeAge;
	bEdge = false;
	return B;
}

bool UCambridgeWheelSubsystem::ConsumeUpshift() { return ConsumeEdge(bEdgeUp, EdgeUpTime); }
bool UCambridgeWheelSubsystem::ConsumeDownshift() { return ConsumeEdge(bEdgeDown, EdgeDownTime); }
bool UCambridgeWheelSubsystem::ConsumeStart() { return ConsumeEdge(bEdgeStart, EdgeStartTime); }

EWheelMenuAction UCambridgeWheelSubsystem::ConsumeMenuAction()
{
	constexpr double ChordWindow = 0.12;     // s: a single paddle waits this long for the other one
	constexpr double HoldSeconds = 0.8;      // both paddles held this long = Back
	constexpr double Fresh = 0.25;           // s: a longer gap since the last query = a new screen
	const double Now = FPlatformTime::Seconds();
	const bool bNewScreen = Now - LastMenuQuery > Fresh;
	LastMenuQuery = Now;
	const bool bEdgeR = ConsumeUpshift();
	const bool bEdgeL = ConsumeDownshift();
	const bool bStartPress = ConsumeStart();
	const FWheelInputState S = GetState();
	const bool bBoth = S.bUpshift && S.bDownshift;
	if (bNewScreen)
	{
		// (presses made before this screen asked are dropped; paddles already down must be released first)
		PendingPaddle = 0;
		bChord = bBoth;
		ChordSince = Now;
		bChordHoldFired = true;
		return EWheelMenuAction::None;
	}
	if (bStartPress)
	{
		return EWheelMenuAction::Go;
	}
	if (bChord)
	{
		if (bBoth)
		{
			if (!bChordHoldFired && Now - ChordSince >= HoldSeconds)
			{
				bChordHoldFired = true;
				return EWheelMenuAction::Back;
			}
			return EWheelMenuAction::None;
		}
		const bool bWasHold = bChordHoldFired;     // released: a tap is Go (a hold already went Back)
		bChord = bChordHoldFired = false;
		PendingPaddle = 0;
		return bWasHold ? EWheelMenuAction::None : EWheelMenuAction::Go;
	}
	if (bBoth)
	{
		bChord = true;
		ChordSince = Now;
		bChordHoldFired = false;
		PendingPaddle = 0;
		return EWheelMenuAction::None;
	}
	if (bEdgeR && bEdgeL)
	{
		PendingPaddle = 0;
		return EWheelMenuAction::Go;          // (both pressed and released between two frames)
	}
	if ((bEdgeR || bEdgeL) && PendingPaddle == 0)
	{
		PendingPaddle = bEdgeR ? 1 : 2;
		PendingPaddleAt = Now;
	}
	if (PendingPaddle != 0 && Now - PendingPaddleAt >= ChordWindow)
	{
		const int32 Paddle = PendingPaddle;
		PendingPaddle = 0;
		return Paddle == 1 ? EWheelMenuAction::Down : EWheelMenuAction::Up;
	}
	return EWheelMenuAction::None;
}

void UCambridgeWheelSubsystem::SetTestInput(float Seconds, float Throttle, int32 InButtons, float Brake)
{
	FScopeLock L(&Lock);
	TestUntil = FPlatformTime::Seconds() + FMath::Max(0.0f, Seconds);
	TestThrottle = FMath::Clamp(Throttle, 0.0f, 1.0f);
	TestButtons = InButtons & 7;
	TestBrake = FMath::Clamp(Brake, 0.0f, 1.0f);
	UE_LOG(LogWheel, Display, TEXT("wheel: test input %.2f s, throttle %.2f, buttons %d, brake %.2f"), Seconds, TestThrottle, TestButtons, TestBrake);
}

void UCambridgeWheelSubsystem::SetForceFeedback(float Torque)
{
	FScopeLock L(&Lock);
	PendingTorque = FMath::IsFinite(Torque) ? FMath::Clamp(Torque, -1.0f, 1.0f) : 0.0f;
	LastTorqueTime = FPlatformTime::Seconds();
}

void UCambridgeWheelSubsystem::CentreWheel()
{
	FScopeLock L(&Lock);
	if (SampleCount > 0)        // (no wheel: keep the saved centre)
	{
		SteerCentreCentideg = RawSteer;
	}
}

void UCambridgeWheelSubsystem::ResetPedalCalibration()
{
	FScopeLock L(&Lock);
	CalThrottleMin = CalBrakeMin = MAX_int32;
	CalThrottleMax = CalBrakeMax = MIN_int32;
	bPedalCalibrationRequested = true;
}

void UCambridgeWheelSubsystem::SaveSettings()
{
	FScopeLock L(&Lock);
	if (bPedalCalibrationRequested)
	{
		// only a pedal that went through enough travel replaces its saved range
		if (ValidPedalRange(CalThrottleMin, CalThrottleMax))
		{
			ThrottleMin = CalThrottleMin;
			ThrottleMax = CalThrottleMax;
		}
		if (ValidPedalRange(CalBrakeMin, CalBrakeMax))
		{
			BrakeMin = CalBrakeMin;
			BrakeMax = CalBrakeMax;
		}
		bPedalCalibrationRequested = !ValidPedalRange(CalThrottleMin, CalThrottleMax) || !ValidPedalRange(CalBrakeMin, CalBrakeMax);
	}
	if (bSessionOnly)
	{
		UE_LOG(LogWheel, Display, TEXT("wheel: test run (-WheelPort / automated), settings not saved"));
		return;
	}
	SaveConfig();
}

FString UCambridgeWheelSubsystem::GetStatusText() const
{
	if (!IsActive())
	{
		FScopeLock L(&Lock);
		return Fd >= 0 ? FString::Printf(TEXT("%s (no data)"), *FPaths::GetCleanFilename(OpenPath)) : TEXT("not connected");
	}
	const FWheelInputState S = GetState();
	bool bPedalsCalibrated;
	{
		FScopeLock L(&Lock);
		bPedalsCalibrated = ValidPedalRange(CalThrottleMin, CalThrottleMax) && ValidPedalRange(CalBrakeMin, CalBrakeMax);
	}
	return bPedalsCalibrated
		? FString::Printf(TEXT("%.0f deg  T %.0f%%  B %.0f%%"), S.SteerDeg, S.Throttle * 100.0f, S.Brake * 100.0f)
		: FString::Printf(TEXT("%.0f deg  press both pedals"), S.SteerDeg);
}

void UCambridgeWheelSubsystem::Tick(float DeltaTime)
{
	const double Now = FPlatformTime::Seconds();
	if (IsActive())
	{
		float Torque;
		{
			FScopeLock L(&Lock);
			Torque = (Now - LastTorqueTime < FFBStale) ? PendingTorque : 0.0f;   // car gone / paused -> no force
		}
		if (Now - LastSendTime >= FFBPeriod)
		{
			LastSendTime = Now;
			const int32 Permille = FMath::Clamp(FMath::RoundToInt(Torque * FMath::Clamp(ForceFeedbackStrength, 0.0f, 1.0f) * 1000.0f), -1000, 1000);
			Write(FString::Printf(TEXT("F %d\n"), Permille));
		}
		if (bLogStatus && Now - LastLogTime > 1.0)
		{
			LastLogTime = Now;
			int32 Bad;
			{
				FScopeLock L(&Lock);
				Bad = BadLines;
			}
			UE_LOG(LogWheel, Display, TEXT("wheel: %s  ffb %.2f  bad lines %d"), *GetStatusText(), Torque, Bad);
		}
	}
}

// ------------------------------------------------------------------ serial (reader thread)

FString UCambridgeWheelSubsystem::FindPort()
{
#if CAMBRIDGE_WHEEL_POSIX
	if (!PortOverride.IsEmpty())
	{
		return PortOverride;
	}
	// a port set in Input.ini, if it exists. Never a pseudo-terminal (/dev/ttys*): that is somebody's
	// terminal window (a leftover from a wheel_sim.py test), and the game would type into it
	if (!Port.IsEmpty() && Port != TEXT("auto") && !bConfigPortFailed)
	{
		struct stat St;
		if (!Port.StartsWith(TEXT("/dev/ttys")) && stat(TCHAR_TO_UTF8(*Port), &St) == 0 && S_ISCHR(St.st_mode))
		{
			return Port;
		}
		UE_LOG(LogWheel, Display, TEXT("wheel: port %s from Input.ini is not usable, auto-detecting"), *Port);
		bConfigPortFailed = true;
	}
	// auto: USB CDC devices (macOS cu.usbmodem*, Linux ttyACM*), skipping the ones that sent nothing.
	// (IFileManager::FindFiles can't be used: /dev entries are neither files nor directories to it.)
	TArray<FString> Found;
	if (DIR* Dir = opendir("/dev"))
	{
		while (const dirent* E = readdir(Dir))
		{
			if (FCStringAnsi::Strncmp(E->d_name, "cu.usbmodem", 11) == 0 || FCStringAnsi::Strncmp(E->d_name, "ttyACM", 6) == 0)
			{
				Found.Add(FString(TEXT("/dev/")) + UTF8_TO_TCHAR(E->d_name));
			}
		}
		closedir(Dir);
	}
	Found.Sort();
	for (const FString& P : Found)
	{
		if (!SilentPorts.Contains(P))
		{
			return P;
		}
	}
	SilentPorts.Reset();      // all of them were silent: try them all again (the wheel may have been busy)
	return Found.Num() ? Found[0] : FString();
#else
	return FString();
#endif
}

bool UCambridgeWheelSubsystem::OpenPort()
{
#if CAMBRIDGE_WHEEL_POSIX
	const FString Path = FindPort();
	if (Path.IsEmpty())
	{
		return false;
	}
	const int32 NewFd = open(TCHAR_TO_UTF8(*Path), O_RDWR | O_NOCTTY | O_NONBLOCK);
	if (NewFd < 0)
	{
		return false;
	}
	termios T;
	if (tcgetattr(NewFd, &T) == 0)
	{
		cfmakeraw(&T);
		cfsetspeed(&T, B115200);    // ignored by USB CDC, needed by UART bridges
		T.c_cflag |= CLOCAL | CREAD;
		T.c_cc[VMIN] = 0;
		T.c_cc[VTIME] = 0;
		tcsetattr(NewFd, TCSANOW, &T);
	}
	{
		FScopeLock L(&Lock);
		Fd = NewFd;
		OpenPath = Path;
		SampleCount = 0;
		LastButtons = 0;
		bEdgeUp = bEdgeDown = bEdgeStart = false;
	}
	OpenTime = FPlatformTime::Seconds();
	UE_LOG(LogWheel, Display, TEXT("wheel: opened %s"), *Path);
	Write(TEXT("?\n"));
	return true;
#else
	return false;
#endif
}

void UCambridgeWheelSubsystem::ClosePort()
{
#if CAMBRIDGE_WHEEL_POSIX
	FScopeLock L(&Lock);
	if (Fd >= 0)
	{
		const char Zero[] = "F 0\n";
		write(Fd, Zero, sizeof(Zero) - 1);     // release the rim before letting go
		close(Fd);
		Fd = -1;
		UE_LOG(LogWheel, Display, TEXT("wheel: closed %s"), *OpenPath);
	}
#endif
}

void UCambridgeWheelSubsystem::Write(const FString& Text)
{
#if CAMBRIDGE_WHEEL_POSIX
	FScopeLock L(&Lock);
	if (Fd >= 0)
	{
		const FTCHARToUTF8 Utf8(*Text);
		write(Fd, Utf8.Get(), Utf8.Length());   // non-blocking; a full buffer just drops this update
	}
#endif
}

void UCambridgeWheelSubsystem::ParseLine(const char* Line)
{
	// "W <steer> <throttle> <brake> <buttons>", strictly: a damaged line (noise, half a line after a
	// reconnect) must not move the pedal calibration
	if (Line[0] == 'W' && (Line[1] == ' ' || Line[1] == '\t'))
	{
		const char* P = Line + 1;
		int32 Steer, Throttle, Brake, Btn;
		const bool bOk = ParseField(P, -10000000, 10000000, Steer) && ParseField(P, 0, 65535, Throttle)
			&& ParseField(P, 0, 65535, Brake) && ParseField(P, 0, 255, Btn);
		while (bOk && (*P == ' ' || *P == '\t')) { ++P; }
		FScopeLock L(&Lock);
		if (!bOk || *P != 0)
		{
			++BadLines;
			return;
		}
		RawSteer = Steer;
		RawThrottle = Throttle;
		RawBrake = Brake;
		Buttons = FPlatformTime::Seconds() < TestUntil ? TestButtons : Btn;     // (cr.Wheel.Test)
		// pedals calibrate themselves: remember the travel seen this session
		CalThrottleMin = FMath::Min(CalThrottleMin, RawThrottle);
		CalThrottleMax = FMath::Max(CalThrottleMax, RawThrottle);
		CalBrakeMin = FMath::Min(CalBrakeMin, RawBrake);
		CalBrakeMax = FMath::Max(CalBrakeMax, RawBrake);
		const double Now = FPlatformTime::Seconds();
		const int32 Rising = Buttons & ~LastButtons;
		if (Rising & 1) { bEdgeUp = true; EdgeUpTime = Now; }
		if (Rising & 2) { bEdgeDown = true; EdgeDownTime = Now; }
		if (Rising & 4) { bEdgeStart = true; EdgeStartTime = Now; }
		LastButtons = Buttons;
		LastSampleTime = Now;
		++SampleCount;
	}
	else if (Line[0] == 'I' && Line[1] == ' ')
	{
		UE_LOG(LogWheel, Display, TEXT("wheel: device says \"%s\""), UTF8_TO_TCHAR(Line));
	}
	else
	{
		FScopeLock L(&Lock);
		++BadLines;
	}
}

uint32 UCambridgeWheelSubsystem::Run()
{
#if CAMBRIDGE_WHEEL_POSIX
	char Pending[MaxLine + 1];
	int32 PendingLen = 0;
	bool bOverlong = false;
	auto Wait = [this](double Seconds)
	{
		for (double T = 0.0; T < Seconds && !bStopping; T += 0.05)
		{
			FPlatformProcess::Sleep(0.05f);
		}
	};
	while (!bStopping)
	{
		int32 LocalFd, Samples;
		{
			FScopeLock L(&Lock);
			LocalFd = Fd;
			Samples = SampleCount;
		}
		if (LocalFd < 0)
		{
			PendingLen = 0;            // a new connection starts on a fresh line
			bOverlong = false;
			if (!OpenPort())
			{
				Wait(ReconnectDelay);
			}
			continue;
		}
		// opened, but nothing that looks like the wheel: another USB serial board, or a stale port
		if (Samples == 0 && PortOverride.IsEmpty() && FPlatformTime::Seconds() - OpenTime > NoDataTimeout)
		{
			FString Silent;
			{
				FScopeLock L(&Lock);
				Silent = OpenPath;
			}
			UE_LOG(LogWheel, Display, TEXT("wheel: no samples from %s in %.0f s, trying another port"), *Silent, NoDataTimeout);
			SilentPorts.Add(Silent);
			bConfigPortFailed |= Silent == Port;
			ClosePort();
			Wait(ReconnectDelay);
			continue;
		}
		pollfd P { LocalFd, POLLIN, 0 };
		const int32 R = poll(&P, 1, 20);
		if (R < 0 && errno == EINTR)
		{
			continue;
		}
		if (R < 0 || (P.revents & (POLLERR | POLLHUP | POLLNVAL)))
		{
			ClosePort();         // unplugged
			Wait(ReconnectDelay);
			continue;
		}
		if (R == 0)
		{
			continue;
		}
		char Buf[512];
		const ssize_t N = read(LocalFd, Buf, sizeof(Buf));
		if (N <= 0)
		{
			if (N == 0 || (errno != EAGAIN && errno != EINTR))
			{
				ClosePort();
				Wait(ReconnectDelay);
			}
			continue;
		}
		for (ssize_t i = 0; i < N; ++i)
		{
			if (Buf[i] == '\n' || Buf[i] == '\r')
			{
				if (PendingLen > 0 && !bOverlong)
				{
					Pending[PendingLen] = 0;
					ParseLine(Pending);
				}
				PendingLen = 0;
				bOverlong = false;
			}
			else if (PendingLen < MaxLine)
			{
				Pending[PendingLen++] = Buf[i];
			}
			else
			{
				bOverlong = true;     // dropped whole, not parsed truncated
			}
		}
	}
#endif
	return 0;
}
