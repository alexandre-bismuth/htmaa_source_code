// The home-built steering wheel / pedals / paddle shifters, over USB CDC serial.
// Protocol (ASCII lines, see docs/wheel_protocol.md):
//   device -> game   "W <steer_centideg> <throttle_raw> <brake_raw> <buttons>"   ~500 Hz
//                    buttons: bit0 upshift paddle, bit1 downshift paddle, bit2 start/menu (optional: this wheel has
//                    none; both paddles pressed together are its start everywhere)
//   game -> device   "F <torque_permille>"   -1000..1000, + turns the rim clockwise. Once per frame
//                    (50-120 Hz, capped at 250 Hz): the firmware should smooth it and do fast damping itself.
//                    The firmware must drop the motor torque to 0 if no F line came for 100 ms.
// Port: auto-detects /dev/cu.usbmodem* (a port that sends no samples for 3 s is skipped: another USB
// serial board), or the Port in Input.ini (ignored if it doesn't exist), or -WheelPort=<path> (e.g. the
// wheel_sim.py pseudo-terminal; test runs with it save nothing). Reconnects on unplug. Reading runs on its
// own thread; the game thread reads the latest sample.
// Pedals calibrate themselves each session (min / max seen); the saved calibration is only written by the
// menu's calibration rows (Recalibrate pedals, Centre wheel), when the menu closes.

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

	/** True while a wheel is connected and has sent data recently: it then drives the car. */
	bool IsActive() const;
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
	 *  (1 right paddle, 2 left, 4 start) and the pedals read Throttle and Brake (0..1), whatever the device sends. */
	void SetTestInput(float Seconds, float Throttle, int32 Buttons, float Brake = 0.0f);

	/** Force feedback for the next frame, -1..1 (+ = clockwise); scaled by the strength setting. */
	void SetForceFeedback(float Torque);
	/** Declares the current rim angle as straight ahead (menu: "Centre wheel"). */
	void CentreWheel();
	/** Menu: forgets the pedal travel; press both pedals fully, then close the menu to save it. */
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
	bool OpenPort();
	void ClosePort();
	FString FindPort();
	void ParseLine(const char* Line);
	void Write(const FString& Text);
	bool ConsumeEdge(bool& bEdge, double EdgeTime);

	FRunnableThread* Thread = nullptr;
	TAtomic<bool> bStopping { false };
	mutable FCriticalSection Lock;
	int32 Fd = -1;                   // POSIX file descriptor (owned by the reader thread)
	FString OpenPath;
	FString PortOverride;            // -WheelPort (never saved)
	bool bSessionOnly = false;       // test run: never save the settings
	bool bLogStatus = false;         // -WheelLog
	// reader thread only: ports that were opened but sent no samples (skipped by the auto-detection)
	TSet<FString> SilentPorts;
	bool bConfigPortFailed = false;
	double OpenTime = 0.0;

	// raw latest sample (under Lock)
	int32 RawSteer = 0, RawThrottle = 0, RawBrake = 0, Buttons = 0;
	double LastSampleTime = 0.0;
	int32 SampleCount = 0;
	int32 BadLines = 0;
	int32 LastButtons = 0;
	bool bEdgeUp = false, bEdgeDown = false, bEdgeStart = false;
	double EdgeUpTime = 0.0, EdgeDownTime = 0.0, EdgeStartTime = 0.0;
	// this session's pedal travel (under Lock): starts from the saved calibration when it is valid
	int32 CalThrottleMin = MAX_int32, CalThrottleMax = MIN_int32, CalBrakeMin = MAX_int32, CalBrakeMax = MIN_int32;
	bool bPedalCalibrationRequested = false;

	// test override (under Lock): cr.Wheel.Test
	double TestUntil = 0.0;
	float TestThrottle = 0.0f;
	float TestBrake = 0.0f;
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
