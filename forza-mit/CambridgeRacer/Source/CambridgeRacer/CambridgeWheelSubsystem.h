// The home-built steering wheel / pedals / paddle shifters and its force-feedback base, over USB CDC serial: two boards
// (the input board and the force-feedback board), or one board doing both (the old reference firmware).
// Protocol (ASCII lines, see docs/wheel_protocol.md):
//   input board -> game  "W <steer_centideg> <throttle_raw> <brake_raw> <buttons> [<handbrake_raw>]"   ~500 Hz
//                    buttons: bit0 upshift paddle, bit1 downshift paddle, bit2 start/menu (optional: this wheel has
//                    none; both paddles pressed together are its start everywhere). handbrake_raw: optional, a lever
//                    read like the pedals
//   ffb board -> game    "I cambridge-ffb 1" (the reply to "?"), "H <flags> <milliamps>" heartbeat at 10 Hz
//   game -> ffb board    "F <torque_permille>"   -1000..1000, + turns the rim clockwise. Once per frame
//                    (50-120 Hz, capped at 250 Hz): the firmware smooths it and does fast damping itself, and drops
//                    the motor torque to 0 if no F line came for 100 ms. F 0 while paused, and when the game closes.
//                    Without a force-feedback board (none seen this session), F goes to the input board's port: a
//                    single-board wheel (the input board ignores it).
// Ports: every /dev/cu.usbmodem* (and the Port in Input.ini first, if it exists) is opened and asked "?"; a port is the
// input board once it sends W samples, the force-feedback board once it says "I cambridge-ffb" (or sends H). A port that
// is neither within 3 s is skipped (another USB serial board). -WheelPort=<path> and -WheelFFBPort=<path> (e.g. the
// wheel_sim.py pseudo-terminals) replace the scan for one run; such test runs save nothing. Each board reconnects on its
// own, and the game works with either one missing. Reading runs on its own thread; the game thread reads the latest
// sample.
// Pedals (and the handbrake) calibrate themselves each session (min / max seen); the saved calibration is only
// written by the menu's calibration rows (Recalibrate pedals, Centre wheel), when the menu closes.

#pragma once

#include "CoreMinimal.h"
#include "HAL/CriticalSection.h"
#include "HAL/Runnable.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Tickable.h"
#include "CambridgeWheelSubsystem.generated.h"

class FRunnableThread;

/** What the wheel's paddles (and start button, if any) mean in a menu: UCambridgeWheelSubsystem::ConsumeMenuAction. */
enum class EWheelMenuAction : uint8 { None, Up, Down, Go, Back };

/** One decoded sample from the wheel, already calibrated. */
struct FWheelInputState
{
	float SteerDeg = 0.0f;      // rim angle from centre, + = right
	float Throttle = 0.0f;      // 0..1
	float Brake = 0.0f;         // 0..1
	bool bUpshift = false;
	bool bDownshift = false;
	bool bStart = false;
	float Handbrake = 0.0f;     // 0..1 (0 if the device sends none)
};

UCLASS(config = Input)
class UCambridgeWheelSubsystem : public UGameInstanceSubsystem, public FTickableGameObject, public FRunnable
{
	GENERATED_BODY()

public:
	static UCambridgeWheelSubsystem* Get(const UObject* WorldContext);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** True while the input board (or a single-board wheel) is connected and has sent data recently: it then drives the car. */
	bool IsActive() const;
	/** True while the force-feedback board is connected and its heartbeat is coming. */
	bool IsForceFeedbackActive() const;
	FWheelInputState GetState() const;
	/** Rising edges since the last call (paddles, start button). Presses older than half a second (e.g. made
	 *  while the game was paused) are dropped, so they can't shift the car after the pause. */
	bool ConsumeUpshift();
	bool ConsumeDownshift();
	bool ConsumeStart();
	/** Menus (launch menu, settings, results): the wheel has no start button, so both paddles together are its
	 *  start. One paddle = Up (left) / Down (right), reported after a short wait in case the other one joins (so
	 *  pressing both never moves the selection first); both paddles tapped = Go (= start), held 0.8 s = Back; a start
	 *  button, if one is ever added, = Go. Game thread, one caller per frame; a query after a gap (another screen)
	 *  starts clean (presses made before are dropped). */
	EWheelMenuAction ConsumeMenuAction();
	/** Test (cr.Wheel.Test, with a wheel connected: wheel_sim.py --script idle): for Seconds the buttons read Buttons
	 *  (1 right paddle, 2 left, 4 start) and the pedals read Throttle, Brake and Handbrake (0..1), whatever the device sends. */
	void SetTestInput(float Seconds, float Throttle, int32 Buttons, float Brake = 0.0f, float Handbrake = 0.0f);

	/** Force feedback for the next frame, -1..1 (+ = clockwise); scaled by the strength setting. */
	void SetForceFeedback(float Torque);
	/** Declares the current rim angle as straight ahead (menu: "Centre wheel"). */
	void CentreWheel();
	/** Menu: forgets the pedal travel; press both pedals (and the handbrake) fully, then close the menu to save it. */
	void ResetPedalCalibration();
	/** Saves the wheel settings (menu close). Does nothing in test runs (-WheelPort, -ShotTour, -DriveTest). */
	void SaveSettings();
	FString GetStatusText() const;

	// settings (Saved/Config/<Platform>/Input.ini)
	UPROPERTY(config) FString Port = TEXT("auto");
	UPROPERTY(config) float RotationRangeDeg = 540.0f;   // lock to lock
	UPROPERTY(config) float ForceFeedbackStrength = 0.7f;
	UPROPERTY(config) float SteerCentreCentideg = 0.0f;
	UPROPERTY(config) int32 ThrottleMin = 4095;   // saved calibration (Max - Min < 200: none)
	UPROPERTY(config) int32 ThrottleMax = 0;
	UPROPERTY(config) int32 BrakeMin = 4095;
	UPROPERTY(config) int32 BrakeMax = 0;
	UPROPERTY(config) int32 HandbrakeMin = 4095;
	UPROPERTY(config) int32 HandbrakeMax = 0;

	// FTickableGameObject
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return !IsTemplate(); }
	virtual bool IsTickableWhenPaused() const override { return true; }
	virtual ETickableTickType GetTickableTickType() const override { return IsTemplate() ? ETickableTickType::Never : ETickableTickType::Always; }

	// FRunnable (serial reader thread)
	virtual uint32 Run() override;
	virtual void Stop() override { bStopping = true; }

private:
	/** What an open port turned out to be. */
	enum class ELinkRole : uint8 { Probing, Input, Ffb };
	static constexpr int32 MaxLinks = 4;          // ports open at once (probing several boards together)
	static constexpr int32 MaxLineLength = 120;   // longer lines are garbage
	/** One open serial port. The reader thread owns it; Fd, Path, Role and LastHeard change under Lock (the game thread
	 *  writes F and reads the status), the line buffer is the reader thread's alone. */
	struct FLink
	{
		int32 Fd = -1;                // POSIX file descriptor
		FString Path;
		ELinkRole Role = ELinkRole::Probing;
		double OpenTime = 0.0;
		double LastAsk = 0.0;         // the last "?" (asked again every second while probing: one sent too early is lost)
		double LastHeard = 0.0;       // the last valid line of its role
		bool bDrop = false;           // to be closed by the reader thread (a second board of the same kind, a write error)
		char Pending[MaxLineLength + 1];
		int32 PendingLen = 0;
		bool bOverlong = false;
	};

	TArray<FString> CandidatePorts();
	void DiscoverPorts();
	bool OpenLink(const FString& Path);
	void CloseLink(int32 Index, const TCHAR* Why);
	void ReadLink(int32 Index);
	void ParseLine(int32 Index, const char* Line);
	int32 FindLinkLocked(ELinkRole Role) const;
	/** Where F goes: the force-feedback board; without one (and no port still being identified), the input board's port. */
	int32 ForceFeedbackLinkLocked() const;
	void WriteLinkLocked(int32 Index, const char* Text, int32 Len);
	bool ConsumeEdge(bool& bEdge, const double& EdgeTime);   // (the time by reference: read under the lock)

	FRunnableThread* Thread = nullptr;
	TAtomic<bool> bStopping { false };
	mutable FCriticalSection Lock;
	FLink Links[MaxLinks];
	TArray<FString> PortOverrides;   // -WheelPort, -WheelFFBPort (never saved): exactly these ports, no scan
	bool bSessionOnly = false;       // test run: never save the settings
	bool bLogStatus = false;         // -WheelLog
	// reader thread only: ports that were opened but never identified (skipped by the auto-detection until unplugged)
	TSet<FString> SilentPorts;
	bool bConfigPortFailed = false;
	double LastDiscovery = -100.0;

	// the force-feedback board's heartbeat (under Lock)
	bool bSeenFfbBoard = false;      // a force-feedback board was connected this session: F never goes to the input board
	int32 FfbFlags = 0;
	int32 FfbMilliamps = 0;
	int32 LoggedFfbFlags = -1;
	int32 FfbTarget = INDEX_NONE;    // game thread: the link F went to last (logged when it changes)

	// raw latest sample (under Lock)
	int32 RawSteer = 0, RawThrottle = 0, RawBrake = 0, RawHandbrake = 0, Buttons = 0;
	double LastSampleTime = 0.0;
	int32 SampleCount = 0;
	int32 BadLines = 0;
	int32 LastButtons = 0;
	bool bEdgeUp = false, bEdgeDown = false, bEdgeStart = false;
	double EdgeUpTime = 0.0, EdgeDownTime = 0.0, EdgeStartTime = 0.0;
	// this session's pedal travel (under Lock): starts from the saved calibration when it is valid
	int32 CalThrottleMin = MAX_int32, CalThrottleMax = MIN_int32, CalBrakeMin = MAX_int32, CalBrakeMax = MIN_int32;
	int32 CalHandbrakeMin = MAX_int32, CalHandbrakeMax = MIN_int32;
	bool bPedalCalibrationRequested = false;

	// test override (under Lock): cr.Wheel.Test
	double TestUntil = 0.0;
	float TestThrottle = 0.0f;
	float TestBrake = 0.0f;
	float TestHandbrake = 0.0f;
	int32 TestButtons = 0;

	// menu actions (game thread)
	double LastMenuQuery = -1.0;
	int32 PendingPaddle = 0;          // 1 right, 2 left: a single press waiting for the chord window
	double PendingPaddleAt = 0.0;
	bool bChord = false;              // both paddles are down
	double ChordSince = 0.0;
	bool bChordHoldFired = false;

	float PendingTorque = 0.0f;
	double LastTorqueTime = 0.0;
	double LastSendTime = 0.0;
	double LastLogTime = 0.0;
};
