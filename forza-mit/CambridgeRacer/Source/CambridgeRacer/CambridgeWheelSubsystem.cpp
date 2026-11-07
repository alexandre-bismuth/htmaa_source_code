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
	constexpr double FfbActiveTimeout = 0.5;   // s without a heartbeat (10 Hz) -> force-feedback board considered gone
	constexpr double FfbSilentTimeout = 3.0;   // s without a heartbeat -> its port is closed and looked for again
	constexpr int32 MinPedalSpan = 200;        // raw counts before a pedal counts as calibrated
	constexpr double NoDataTimeout = 3.0;      // s after opening without being identified -> not one of our boards
	constexpr double AskInterval = 1.0;        // s between "?" while a port is being identified
	constexpr double ReconnectDelay = 1.0;     // s between connection attempts (hot-plug)
	constexpr double MaxEdgeAge = 0.5;         // s: older paddle / button presses are dropped

	// test: drive the wheel's buttons / throttle from a shot tour step (a wheel or wheel_sim.py must be connected)
	FAutoConsoleCommandWithWorldAndArgs WheelTestCmd(TEXT("cr.Wheel.Test"),
		TEXT("Test: cr.Wheel.Test <seconds> <throttle 0..1> <buttons: 1 right paddle, 2 left, 3 both, 4 start> [brake 0..1] [handbrake 0..1] (needs a connected wheel or wheel_sim.py)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
			if (UCambridgeWheelSubsystem* W = GI ? GI->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr; W && Args.Num() >= 3)
			{
				W->SetTestInput(FCString::Atof(*Args[0]), FCString::Atof(*Args[1]), FCString::Atoi(*Args[2]), Args.Num() > 3 ? FCString::Atof(*Args[3]) : 0.0f,
					Args.Num() > 4 ? FCString::Atof(*Args[4]) : 0.0f);
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
	// ports from the command line are for this run only (tests with tools/wheel/wheel_sim.py): they are never
	// written into Port, and nothing is saved in such runs, so they can't overwrite the player's calibration
	for (const TCHAR* Key : { TEXT("WheelPort="), TEXT("WheelFFBPort=") })
	{
		FString Override;
		if (FParse::Value(Cmd, Key, Override) && !Override.IsEmpty())
		{
			PortOverrides.AddUnique(Override);
		}
	}
	bSessionOnly = !PortOverrides.IsEmpty() || FCString::Strifind(Cmd, TEXT("-ShotTour")) || FCString::Strifind(Cmd, TEXT("-DriveTest"));
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
	if (ValidPedalRange(HandbrakeMin, HandbrakeMax))
	{
		CalHandbrakeMin = HandbrakeMin;
		CalHandbrakeMax = HandbrakeMax;
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
	for (int32 i = 0; i < MaxLinks; ++i)
	{
		CloseLink(i, TEXT("game closing"));     // (sends F 0 first)
	}
	Super::Deinitialize();
}

TStatId UCambridgeWheelSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UCambridgeWheelSubsystem, STATGROUP_Tickables);
}

bool UCambridgeWheelSubsystem::IsActive() const
{
	FScopeLock L(&Lock);
	return FindLinkLocked(ELinkRole::Input) >= 0 && SampleCount > 0 && FPlatformTime::Seconds() - LastSampleTime < ActiveTimeout;
}

bool UCambridgeWheelSubsystem::IsForceFeedbackActive() const
{
	FScopeLock L(&Lock);
	const int32 i = FindLinkLocked(ELinkRole::Ffb);
	return i >= 0 && FPlatformTime::Seconds() - Links[i].LastHeard < FfbActiveTimeout;
}

int32 UCambridgeWheelSubsystem::FindLinkLocked(ELinkRole Role) const
{
	for (int32 i = 0; i < MaxLinks; ++i)
	{
		if (Links[i].Fd >= 0 && Links[i].Role == Role)
		{
			return i;
		}
	}
	return INDEX_NONE;
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
	S.Handbrake = FPlatformTime::Seconds() < TestUntil ? TestHandbrake : Pedal(RawHandbrake, CalHandbrakeMin, CalHandbrakeMax);
	return S;
}

bool UCambridgeWheelSubsystem::ConsumeEdge(bool& bEdge, const double& EdgeTime)
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

void UCambridgeWheelSubsystem::SetTestInput(float Seconds, float Throttle, int32 InButtons, float Brake, float Handbrake)
{
	FScopeLock L(&Lock);
	TestUntil = FPlatformTime::Seconds() + FMath::Max(0.0f, Seconds);
	TestThrottle = FMath::Clamp(Throttle, 0.0f, 1.0f);
	TestButtons = InButtons & 7;
	TestBrake = FMath::Clamp(Brake, 0.0f, 1.0f);
	TestHandbrake = FMath::Clamp(Handbrake, 0.0f, 1.0f);
	UE_LOG(LogWheel, Display, TEXT("wheel: test input %.2f s, throttle %.2f, buttons %d, brake %.2f, handbrake %.2f"), Seconds, TestThrottle, TestButtons,
		TestBrake, TestHandbrake);
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
	CalThrottleMin = CalBrakeMin = CalHandbrakeMin = MAX_int32;
	CalThrottleMax = CalBrakeMax = CalHandbrakeMax = MIN_int32;
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
		if (ValidPedalRange(CalHandbrakeMin, CalHandbrakeMax))
		{
			HandbrakeMin = CalHandbrakeMin;
			HandbrakeMax = CalHandbrakeMax;
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
	// the force-feedback board, after the input: "FFB" (its soft end stops armed), "FFB, turn to find the centre"
	FString Ffb;
	if (IsForceFeedbackActive())
	{
		FScopeLock L(&Lock);
		Ffb = (FfbFlags & 2) ? TEXT("  FFB") : TEXT("  FFB, turn to find the centre");
	}
	if (!IsActive())
	{
		FScopeLock L(&Lock);
		const int32 i = FindLinkLocked(ELinkRole::Input);
		return (i >= 0 ? FString::Printf(TEXT("%s (no data)"), *FPaths::GetCleanFilename(Links[i].Path))
			: Ffb.IsEmpty() ? FString(TEXT("not connected")) : FString(TEXT("no input board"))) + Ffb;
	}
	const FWheelInputState S = GetState();
	bool bPedalsCalibrated, bHandbrakeCalibrated;
	{
		FScopeLock L(&Lock);
		bPedalsCalibrated = ValidPedalRange(CalThrottleMin, CalThrottleMax) && ValidPedalRange(CalBrakeMin, CalBrakeMax);
		bHandbrakeCalibrated = ValidPedalRange(CalHandbrakeMin, CalHandbrakeMax);
	}
	const FString Handbrake = bHandbrakeCalibrated ? FString::Printf(TEXT("  H %.0f%%"), S.Handbrake * 100.0f) : FString();
	return (bPedalsCalibrated
		? FString::Printf(TEXT("%.0f deg  T %.0f%%  B %.0f%%%s"), S.SteerDeg, S.Throttle * 100.0f, S.Brake * 100.0f, *Handbrake)
		: FString::Printf(TEXT("%.0f deg  press both pedals%s"), S.SteerDeg, *Handbrake)) + Ffb;
}

void UCambridgeWheelSubsystem::Tick(float DeltaTime)
{
	const double Now = FPlatformTime::Seconds();
	const bool bInput = IsActive();
	float Torque;
	{
		FScopeLock L(&Lock);
		// the car's torque while the wheel drives it; 0 when that is stale (the game paused, a menu, the car gone) or the
		// keyboard drives: the force-feedback board then gets F 0 (its damping and soft stops stay on)
		Torque = (bInput && Now - LastTorqueTime < FFBStale) ? PendingTorque : 0.0f;
		const int32 Target = ForceFeedbackLinkLocked();
		if (Target != FfbTarget)
		{
			FfbTarget = Target;
			UE_LOG(LogWheel, Display, TEXT("wheel: force feedback -> %s"), Target < 0 ? TEXT("none")
				: *FString::Printf(TEXT("%s (%s)"), *Links[Target].Path,
					Links[Target].Role == ELinkRole::Ffb ? TEXT("force-feedback board") : TEXT("the input board's port: single-board wheel")));
		}
		if (Target >= 0 && Now - LastSendTime >= FFBPeriod)
		{
			LastSendTime = Now;
			const int32 Permille = FMath::Clamp(FMath::RoundToInt(Torque * FMath::Clamp(ForceFeedbackStrength, 0.0f, 1.0f) * 1000.0f), -1000, 1000);
			ANSICHAR Buf[24];
			const int32 N = FCStringAnsi::Snprintf(Buf, sizeof(Buf), "F %d\n", Permille);
			WriteLinkLocked(Target, Buf, N);
		}
	}
	if (bLogStatus && Now - LastLogTime > 1.0 && (bInput || IsForceFeedbackActive()))
	{
		LastLogTime = Now;
		int32 Bad;
		FString Ffb = TEXT("no ffb board");
		{
			FScopeLock L(&Lock);
			Bad = BadLines;
			if (const int32 i = FindLinkLocked(ELinkRole::Ffb); i >= 0)
			{
				Ffb = FString::Printf(TEXT("ffb board %s flags %d %d mA"), *FPaths::GetCleanFilename(Links[i].Path), FfbFlags, FfbMilliamps);
			}
		}
		UE_LOG(LogWheel, Display, TEXT("wheel: %s  ffb %.2f  bad lines %d  %s"), *GetStatusText(), Torque, Bad, *Ffb);
	}
}

int32 UCambridgeWheelSubsystem::ForceFeedbackLinkLocked() const
{
	const int32 Ffb = FindLinkLocked(ELinkRole::Ffb);
	if (Ffb >= 0)
	{
		return Ffb;
	}
	// no force-feedback board: the input board's port, for a single-board wheel (the old reference firmware takes F
	// there) - never in a rig that had a force-feedback board this session (it is only unplugged for now), and only once
	// no port is still being identified (the force-feedback board may be one of them)
	return bSeenFfbBoard || FindLinkLocked(ELinkRole::Probing) >= 0 ? INDEX_NONE : FindLinkLocked(ELinkRole::Input);
}

// ------------------------------------------------------------------ serial (reader thread)

TArray<FString> UCambridgeWheelSubsystem::CandidatePorts()
{
	TArray<FString> Out;
#if CAMBRIDGE_WHEEL_POSIX
	if (!PortOverrides.IsEmpty())
	{
		return PortOverrides;      // test run: exactly these, never a scan
	}
	// a port set in Input.ini first, if it exists. Never a pseudo-terminal (/dev/ttys*): that is somebody's
	// terminal window (a leftover from a wheel_sim.py test), and the game would type into it
	if (!Port.IsEmpty() && Port != TEXT("auto") && !bConfigPortFailed)
	{
		struct stat St;
		if (!Port.StartsWith(TEXT("/dev/ttys")) && stat(TCHAR_TO_UTF8(*Port), &St) == 0 && S_ISCHR(St.st_mode))
		{
			Out.Add(Port);
		}
		else
		{
			UE_LOG(LogWheel, Display, TEXT("wheel: port %s from Input.ini is not usable, auto-detecting"), *Port);
			bConfigPortFailed = true;
		}
	}
	// auto: USB CDC devices (macOS cu.usbmodem*, Linux ttyACM*), skipping the ones that never answered.
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
	// a silent port that was unplugged is forgotten: plugged back in, it is asked again
	for (auto It = SilentPorts.CreateIterator(); It; ++It)
	{
		if (!Found.Contains(*It))
		{
			It.RemoveCurrent();
		}
	}
	for (const FString& P : Found)
	{
		if (!SilentPorts.Contains(P))
		{
			Out.AddUnique(P);
		}
	}
#endif
	return Out;
}

void UCambridgeWheelSubsystem::DiscoverPorts()
{
	bool bHaveInput, bHaveFfb, bProbing;
	TSet<FString> Open;
	{
		FScopeLock L(&Lock);
		bHaveInput = FindLinkLocked(ELinkRole::Input) >= 0;
		bHaveFfb = FindLinkLocked(ELinkRole::Ffb) >= 0;
		bProbing = FindLinkLocked(ELinkRole::Probing) >= 0;
		for (const FLink& K : Links)
		{
			if (K.Fd >= 0)
			{
				Open.Add(K.Path);
			}
		}
	}
	if (bHaveInput && bHaveFfb)
	{
		return;
	}
	int32 Opened = 0;
	for (const FString& P : CandidatePorts())
	{
		if (!Open.Contains(P) && OpenLink(P))
		{
			++Opened;
		}
	}
	// nothing new to ask and still no input board: every port was silent, so ask them all again (the wheel may have
	// been busy). Not for a missing force-feedback board alone: unrelated USB serial boards would be asked forever
	if (Opened == 0 && !bHaveInput && !bProbing && !SilentPorts.IsEmpty())
	{
		SilentPorts.Reset();
	}
}

bool UCambridgeWheelSubsystem::OpenLink(const FString& Path)
{
#if CAMBRIDGE_WHEEL_POSIX
	int32 Slot = INDEX_NONE;
	{
		FScopeLock L(&Lock);
		for (int32 i = 0; i < MaxLinks && Slot < 0; ++i)
		{
			Slot = Links[i].Fd < 0 ? i : INDEX_NONE;
		}
	}
	if (Slot < 0)
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
		FLink& K = Links[Slot];
		K = FLink();
		K.Fd = NewFd;
		K.Path = Path;
		K.OpenTime = K.LastAsk = FPlatformTime::Seconds();
		WriteLinkLocked(Slot, "?\n", 2);
	}
	UE_LOG(LogWheel, Display, TEXT("wheel: opened %s"), *Path);
	return true;
#else
	return false;
#endif
}

void UCambridgeWheelSubsystem::CloseLink(int32 Index, const TCHAR* Why)
{
#if CAMBRIDGE_WHEEL_POSIX
	FScopeLock L(&Lock);
	FLink& K = Links[Index];
	if (K.Fd < 0)
	{
		return;
	}
	if (Index == ForceFeedbackLinkLocked() || K.Role == ELinkRole::Ffb)
	{
		const char Zero[] = "F 0\n";
		write(K.Fd, Zero, sizeof(Zero) - 1);     // release the rim before letting go
	}
	close(K.Fd);
	UE_LOG(LogWheel, Display, TEXT("wheel: closed %s (%s)"), *K.Path, Why);
	K = FLink();
#endif
}

void UCambridgeWheelSubsystem::WriteLinkLocked(int32 Index, const char* Text, int32 Len)
{
#if CAMBRIDGE_WHEEL_POSIX
	FLink& K = Links[Index];
	if (K.Fd >= 0 && write(K.Fd, Text, Len) < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
	{
		K.bDrop = true;        // (a full buffer just drops this update; a real error is an unplug: the reader thread closes it)
	}
#endif
}

void UCambridgeWheelSubsystem::ParseLine(int32 Index, const char* Line)
{
	const double Now = FPlatformTime::Seconds();
	// a port proves to be the force-feedback board ("I cambridge-ffb", or its heartbeat if that reply was lost); a second
	// one is ignored
	auto BecomeFfbLocked = [this, Index, Now]()
	{
		FLink& K = Links[Index];
		if (K.Role != ELinkRole::Probing)
		{
			return K.Role == ELinkRole::Ffb;     // (an input board's stray line changes nothing)
		}
		if (FindLinkLocked(ELinkRole::Ffb) >= 0)
		{
			UE_LOG(LogWheel, Display, TEXT("wheel: %s is a second force-feedback board: ignored"), *K.Path);
			SilentPorts.Add(K.Path);
			K.bDrop = true;
			return false;
		}
		K.Role = ELinkRole::Ffb;
		K.LastHeard = Now;
		bSeenFfbBoard = true;
		FfbFlags = 0;
		FfbMilliamps = 0;
		LoggedFfbFlags = -1;
		UE_LOG(LogWheel, Display, TEXT("wheel: force-feedback board on %s"), *K.Path);
		return true;
	};

	// "W <steer> <throttle> <brake> <buttons> [<handbrake>]", strictly: a damaged line (noise, half a line after a
	// reconnect) must not move the pedal calibration
	if (Line[0] == 'W' && (Line[1] == ' ' || Line[1] == '\t'))
	{
		const char* P = Line + 1;
		int32 Steer, Throttle, Brake, Btn, Handbrake = 0;
		bool bOk = ParseField(P, -10000000, 10000000, Steer) && ParseField(P, 0, 65535, Throttle)
			&& ParseField(P, 0, 65535, Brake) && ParseField(P, 0, 255, Btn);
		while (bOk && (*P == ' ' || *P == '\t')) { ++P; }
		const bool bHasHandbrake = bOk && *P != 0;
		if (bHasHandbrake)
		{
			bOk = ParseField(P, 0, 65535, Handbrake);
			while (bOk && (*P == ' ' || *P == '\t')) { ++P; }
		}
		FScopeLock L(&Lock);
		FLink& K = Links[Index];
		if (!bOk || *P != 0 || K.Role == ELinkRole::Ffb)
		{
			++BadLines;
			return;
		}
		if (K.Role == ELinkRole::Probing)
		{
			if (FindLinkLocked(ELinkRole::Input) >= 0)
			{
				UE_LOG(LogWheel, Display, TEXT("wheel: %s sends samples too, but there already is an input board: ignored"), *K.Path);
				SilentPorts.Add(K.Path);
				K.bDrop = true;
				return;
			}
			K.Role = ELinkRole::Input;
			SampleCount = 0;
			LastButtons = 0;
			bEdgeUp = bEdgeDown = bEdgeStart = false;
			UE_LOG(LogWheel, Display, TEXT("wheel: input board on %s"), *K.Path);
		}
		K.LastHeard = Now;
		RawSteer = Steer;
		RawThrottle = Throttle;
		RawBrake = Brake;
		RawHandbrake = Handbrake;
		Buttons = Now < TestUntil ? TestButtons : Btn;     // (cr.Wheel.Test)
		// pedals calibrate themselves: remember the travel seen this session
		CalThrottleMin = FMath::Min(CalThrottleMin, RawThrottle);
		CalThrottleMax = FMath::Max(CalThrottleMax, RawThrottle);
		CalBrakeMin = FMath::Min(CalBrakeMin, RawBrake);
		CalBrakeMax = FMath::Max(CalBrakeMax, RawBrake);
		if (bHasHandbrake)
		{
			CalHandbrakeMin = FMath::Min(CalHandbrakeMin, RawHandbrake);
			CalHandbrakeMax = FMath::Max(CalHandbrakeMax, RawHandbrake);
		}
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
		FScopeLock L(&Lock);
		UE_LOG(LogWheel, Display, TEXT("wheel: %s says \"%s\""), *Links[Index].Path, UTF8_TO_TCHAR(Line));
		if (FCStringAnsi::Strstr(Line, "cambridge-ffb"))
		{
			BecomeFfbLocked();
		}
	}
	else if (Line[0] == 'H' && (Line[1] == ' ' || Line[1] == '\t'))
	{
		// the force-feedback board's heartbeat: "H <flags> <milliamps>"
		const char* P = Line + 1;
		int32 Flags, Milliamps;
		bool bOk = ParseField(P, 0, 255, Flags) && ParseField(P, 0, 100000, Milliamps);
		while (bOk && (*P == ' ' || *P == '\t')) { ++P; }
		FScopeLock L(&Lock);
		if (!bOk || *P != 0 || Links[Index].Role == ELinkRole::Input)
		{
			++BadLines;
			return;
		}
		if (!BecomeFfbLocked())
		{
			return;
		}
		Links[Index].LastHeard = Now;
		FfbFlags = Flags;
		FfbMilliamps = Milliamps;
		if (Flags != LoggedFfbFlags)
		{
			LoggedFfbFlags = Flags;
			UE_LOG(LogWheel, Display, TEXT("wheel: force-feedback board: %s%s%s%s"), (Flags & 1) ? TEXT("driving") : TEXT("limp"),
				(Flags & 2) ? TEXT(", soft stops armed") : TEXT(", centre not found yet (turn the rim through it)"),
				(Flags & 4) ? TEXT(", current guard backing off") : TEXT(""), (Flags & 8) ? TEXT(", overspeed brake") : TEXT(""));
		}
	}
	else if (Line[0] == 'S' && (Line[1] == ' ' || Line[1] == 0))
	{
		// the force-feedback board's bench status line (only sent when asked, which the game never does)
	}
	else
	{
		FScopeLock L(&Lock);
		++BadLines;
	}
}

void UCambridgeWheelSubsystem::ReadLink(int32 Index)
{
#if CAMBRIDGE_WHEEL_POSIX
	FLink& K = Links[Index];          // (the line buffer is this thread's alone, and only this thread changes Fd)
	char Buf[512];
	const ssize_t N = read(K.Fd, Buf, sizeof(Buf));
	if (N <= 0)
	{
		if (N == 0 || (errno != EAGAIN && errno != EINTR))
		{
			CloseLink(Index, TEXT("read error"));
			LastDiscovery = FPlatformTime::Seconds();
		}
		return;
	}
	for (ssize_t i = 0; i < N && !K.bDrop; ++i)
	{
		if (Buf[i] == '\n' || Buf[i] == '\r')
		{
			if (K.PendingLen > 0 && !K.bOverlong)
			{
				K.Pending[K.PendingLen] = 0;
				ParseLine(Index, K.Pending);
			}
			K.PendingLen = 0;
			K.bOverlong = false;
		}
		else if (K.PendingLen < MaxLineLength)
		{
			K.Pending[K.PendingLen++] = Buf[i];
		}
		else
		{
			K.bOverlong = true;     // dropped whole, not parsed truncated
		}
	}
#endif
}

uint32 UCambridgeWheelSubsystem::Run()
{
#if CAMBRIDGE_WHEEL_POSIX
	while (!bStopping)
	{
		const double Now = FPlatformTime::Seconds();
		// 1. links to close: a failed write (unplugged) or a second board of a kind; a port never identified as one of the
		// boards (another USB serial board); a force-feedback board whose heartbeat stopped. Probing ports are asked again
		for (int32 i = 0; i < MaxLinks; ++i)
		{
			int32 LinkFd;
			ELinkRole Role;
			bool bDrop;
			double OpenTime, LastAsk, LastHeard;
			FString Path;
			{
				FScopeLock L(&Lock);
				const FLink& K = Links[i];
				LinkFd = K.Fd; Role = K.Role; bDrop = K.bDrop; OpenTime = K.OpenTime; LastAsk = K.LastAsk; LastHeard = K.LastHeard; Path = K.Path;
			}
			if (LinkFd < 0)
			{
				continue;
			}
			if (bDrop)
			{
				CloseLink(i, TEXT("dropped"));
				LastDiscovery = Now;
			}
			else if (Role == ELinkRole::Probing && PortOverrides.IsEmpty() && Now - OpenTime > NoDataTimeout)
			{
				UE_LOG(LogWheel, Display, TEXT("wheel: nothing from %s in %.0f s that looks like the wheel, trying another port"), *Path, NoDataTimeout);
				SilentPorts.Add(Path);
				bConfigPortFailed |= Path == Port;
				CloseLink(i, TEXT("not a wheel board"));
			}
			else if (Role == ELinkRole::Probing && Now - LastAsk >= AskInterval)
			{
				FScopeLock L(&Lock);
				Links[i].LastAsk = Now;
				WriteLinkLocked(i, "?\n", 2);
			}
			else if (Role == ELinkRole::Ffb && Now - LastHeard > FfbSilentTimeout)
			{
				CloseLink(i, TEXT("no heartbeat"));
				LastDiscovery = Now;
			}
		}
		// 2. look for the boards still missing (hot-plug)
		if (Now - LastDiscovery >= ReconnectDelay)
		{
			LastDiscovery = Now;
			DiscoverPorts();
		}
		// 3. read whatever came in
		pollfd P[MaxLinks];
		int32 Index[MaxLinks];
		int32 Num = 0;
		{
			FScopeLock L(&Lock);
			for (int32 i = 0; i < MaxLinks; ++i)
			{
				if (Links[i].Fd >= 0)
				{
					P[Num] = { Links[i].Fd, POLLIN, 0 };
					Index[Num++] = i;
				}
			}
		}
		if (Num == 0)
		{
			FPlatformProcess::Sleep(0.05f);
			continue;
		}
		const int32 R = poll(P, Num, 20);
		if (R < 0)
		{
			if (errno != EINTR)
			{
				FPlatformProcess::Sleep(0.02f);
			}
			continue;
		}
		for (int32 k = 0; k < Num && R > 0; ++k)
		{
			if (P[k].revents & (POLLERR | POLLHUP | POLLNVAL))
			{
				CloseLink(Index[k], TEXT("unplugged"));
				LastDiscovery = FPlatformTime::Seconds();
			}
			else if (P[k].revents & POLLIN)
			{
				ReadLink(Index[k]);
			}
		}
	}
#endif
	return 0;
}
