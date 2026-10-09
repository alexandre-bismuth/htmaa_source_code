// Solo time trials + the driving HUD.
//
// Events come from CambridgeRacer/Tracks/<map>.json (tools/mapgen/tracks.py: routes on the real
// street network). In free roam each event has a start gantry with a start box painted on the road;
// drive into the box and press
//   Enter / gamepad A / wheel: both paddles together (its start)   start the event
// During an event (keyboard / gamepad):
//   R / Y / D-pad down (tap)       back on track: just before the next checkpoint, held for a 3-2-1
//   R / Y / D-pad down / Enter (hold)  restart the event
//   Backspace / D-pad up (hold)    leave the event (gamepad B is shift up while driving: Forza layout)
//   wheel (no start button: both paddles together are its start): tap back on track, hold 1 s restart. On the results one paddle picks the button and both together press it. The key hints switch
//   to the wheel's controls while it is connected.
// Results window: Left / Right (arrows, D-pad, stick) pick RETRY / NEXT EVENT / FREE ROAM, Enter / A
// confirm; shortcuts R (retry), N (next event), Backspace / B (free roam).
// (Gamepad A is the handbrake while driving: it starts an event only with the car stopped in the box,
// never restarts a running one, and the results ignore it for ResultsArmSeconds after the finish.)
// Full gamepad / keyboard scheme: ACambridgeRacerPlayerController.cpp (ApplyControlScheme).
//
// Gates are crossed in order (segment test, robust at speed). The next one is bright with a light
// curtain, the two after it are dimmed, the finish is a checkered arch; passing one flashes it and
// chimes. The route is tracked along the racing line: position-on-route bar (checkpoint ticks, a ghost
// of the best run), WRONG WAY detection, and a "missed checkpoint" guidance arrow. Splits at every
// checkpoint are compared with the best run, which is saved (Saved/Config/<platform>/Game.ini).
//
// The HUD (Slate, "Luna Glass" style from CambridgeUIStyle) shows the race panel (timer, lap,
// checkpoints, best, route bar), split popups, lap / final-lap callouts, start lights + countdown with
// beeps, the back-on-track dialog, the results window and, bottom right, speed / gear / rpm / boost.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "TimeTrialSubsystem.generated.h"

class ATimeTrialGate;
class FTimeTrialInput;
class SWidget;
class USoundBase;

struct FTimeTrialGateDef
{
	FVector Location = FVector::ZeroVector;
	float Yaw = 0.0f;
	float Width = 1000.0f;
	/** How far the checkpoint counts left / right of the centre (cm): the road at the gate, at least the gate itself. */
	float TriggerLeft = 500.0f;
	float TriggerRight = 500.0f;
};

struct FTimeTrialTrack
{
	FString Id, Name;
	bool bCircuit = false;
	int32 Laps = 1;
	float LengthM = 0.0f;
	FVector StartLocation = FVector::ZeroVector;
	float StartYaw = 0.0f;
	FVector2D StartLocal = FVector2D::ZeroVector;   // the grid in the start gate's frame (X along, Y right; cm)
	TArray<FTimeTrialGateDef> Gates;
	TArray<FVector4> Line;      // braking guide: x, y (cm), -, target speed (km/h)
};

/** Everything the position-on-route bar draws, as fractions (0..1) of the whole run. */
struct FTimeTrialRouteBar
{
	TArray<float> Checkpoints;  // every route entry after the start line
	TArray<float> LapLines;     // circuits: lap boundaries (not the finish)
	int32 Passed = 0;           // checkpoints already driven through
	float Car = 0.0f;
	float Ghost = -1.0f;        // best run at the same race time (-1: no best yet)
};

UENUM()
enum class ETimeTrialState : uint8 { FreeRoam, Countdown, Running, Finished };

UCLASS(config = Game)
class UTimeTrialSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bReady; }

	/** Input from the preprocessor; return true if the key was used. */
	bool OnKeyDown(const struct FKey& Key);
	bool OnKeyUp(const struct FKey& Key);
	/** Enter / gamepad A / wheel start: start the event at the start box, or pick the focused results button
	 *  (nothing during an event: restarting there is a hold). */
	bool OnConfirm(bool bGamepadA = false);
	/** Test / debug (cr.TT.GoToStart N): car into event N's start box, without starting it. */
	void PlaceAtStart(int32 TrackIndex);
	/** Test / debug (cr.TT.Start N): start event N right away (car onto its grid, countdown). */
	void StartEventByIndex(int32 TrackIndex) { if (Tracks.IsValidIndex(TrackIndex)) { StartEvent(TrackIndex); } }
	/** Test / debug (cr.TT.Preview <what>): show a race HUD element now, for screenshots of states the autopilot
	 *  never reaches: flash (pass flash + an "ahead" split), lap / finallap / fastest (callouts), wrongway, missed, hold. */
	void PreviewHUD(const FString& What);
	/** Test / debug (cr.TT.Result N): press results button N (0 retry, 1 next event, 2 free roam) now. */
	void PressResult(int32 Choice) { if (State == ETimeTrialState::Finished) { ActivateResult(Choice); } }
	/** Test (cr.TT.Finish): finish the running event now, for the results screen (the time is never saved). */
	void FinishForTest();
	/** Back to free roam if an event (countdown, race or results) is on: the launch menu's Main menu. */
	void LeaveEvent() { if (IsInEvent()) { EndEvent(); } }
	/** One of the race UI sounds (SoundNames in the .cpp: ui_select, ui_confirm, ...), 2D. */
	void PlayUISound(FName Name, float Volume = 1.0f) const;
	/** Perf A/B (cr.TT.Markers 0|1): hide the free-roam start markers. */
	void SetMarkersHidden(bool bHidden);
	/** Puts the car back on the racing line just before the next gate, lined up with it (R during an event). */
	void ResetToLastGate();
	/** Test (cr.Test.ResetSpots "x:y:yaw:roll:manual:waypoint|..."): in free roam, put the car at each spot in turn (cm, deg;
	 *  e.g. inside a building, upside down in a park, in the river), then reset it (manual 1) or leave it to the flip check
	 *  (manual 0), and log where it ends up; waypoint 1: then a GPS waypoint on the spot (off the streets), which must
	 *  count as reached from the street the car was put on. */
	void StartResetTest(const FString& Spec);

	// HUD text
	FText GetEventTitle() const;
	FText GetTimerText() const;
	FText GetSpeedText() const;
	FText GetGearText() const;
	float GetRpmFraction() const;
	FText GetRpmText() const;
	float GetBoostFraction() const;
	FText GetAssistShortText() const;   // "TC SPORT   AUTO   ABS ON" (HUD header)
	FText GetLapBadgeText() const;      // "LAP 1/2" or "SPRINT"
	FText GetGateText() const;          // "CHECKPOINT 7/40"
	FText GetBestText() const;          // "BEST  1:41.183"
	bool IsResetHolding() const { return bResetHold; }
	/** Free roam: index of the event whose start box the car is in (-1 if none). */
	int32 GetNearMarker() const { return NearMarker; }
	bool IsInEvent() const { return State != ETimeTrialState::FreeRoam; }
	ETimeTrialState GetState() const { return State; }

	// race HUD widgets (TimeTrialWidgets)
	bool GetRouteBar(FTimeTrialRouteBar& Out) const;
	/** The gate to drive through now (countdown / running). */
	bool GetNextGate(FVector& OutLocation, bool& bOutFinish) const;
	bool IsWrongWay() const { return bWrongWay; }
	bool IsCheckpointMissed() const { return bMissed; }

	// map / GPS (UMinimapSubsystem)
	const TArray<FTimeTrialTrack>& GetTracks() const { return Tracks; }
	/** Track index of the running event (countdown, running or results), -1 in free roam. */
	int32 GetActiveTrack() const { return State != ETimeTrialState::FreeRoam ? Active : -1; }
	/** Gate indices (into the active track's Gates) still to drive, next first, at most Max (countdown and race). */
	void GetUpcomingGates(TArray<int32>& Out, int32 Max) const
	{
		Out.Reset();
		const bool bLive = State == ETimeTrialState::Running || State == ETimeTrialState::Countdown;
		for (int32 k = RouteIndex; k < Route.Num() && Out.Num() < Max && bLive; ++k) { Out.Add(Route[k]); }
	}
	/** Number of gate crossings left in the run (1 = the next gate is the finish). */
	int32 GetGatesLeft() const { return Route.Num() - RouteIndex; }
	/** Best total time of a track in seconds (0 = none yet). Cached: the map and the HUD ask every frame. */
	double GetBestTime(int32 TrackIndex) const;
	/** Free roam: the car was put back on the nearest street (ACambridgeRacerPawn::DoResetVehicle): a short toast. */
	void NotifyRoadReset(const FString& Street);

	// best runs: "total;split1,split2,..." per track id
	UPROPERTY(config) TMap<FString, FString> BestRuns;

private:
	void LoadTracks();
	void LoadSounds();
	void SpawnMarkers();
	/** Road height under a point (trace against the loaded world, the car ignored); false if nothing is loaded there. */
	bool GroundZ(const FVector& At, float& OutZ) const;
	TArray<bool> MarkerGrounded;  // start markers already dropped onto the road (done once their cell is loaded)
	void StartEvent(int32 TrackIndex);
	void EndEvent();
	void ShowGates();
	void TickGates();
	void PassGate();
	void Finish();
	bool CrossedGate(const FTimeTrialGateDef& Gate, const FVector& From, const FVector& To) const;
	class AImprezaSTi* GetCar() const;
	/** The home-built wheel is connected: the key hints show its controls. */
	bool IsWheelActive() const;
	bool bFinishForTest = false;   // cr.TT.Finish: the results without saving a best
	double Now() const;
	/** The saved best run of T (empty / 0 if none, or if it was set on a different layout of T: other checkpoint count). */
	TArray<double> BestSplits(const FTimeTrialTrack& T, double& OutTotal) const;
	mutable TArray<double> BestTimeCache;   // GetBestTime per track (-1: not parsed yet); emptied when a best is saved
	void AttachHUD();
	void ShowResults();          // builds the results window (+ confetti on a new best) into ResultsHost
	void ClearResults();
	void ActivateResult(int32 Choice);   // 0 retry, 1 next event, 2 free roam
	void Autopilot(class AImprezaSTi* Car);
	bool IsUIBlocking() const;   // pause menu / full map open: leave the keys to them

	// route geometry of the active event, along the racing line (cm)
	void BuildRoute();
	void UpdateRouteProgress(const FVector& Loc, const FVector& Forward, float SpeedKmh, float DeltaTime);
	/** Point + direction on the racing line at a route distance (laps unrolled). */
	void RoutePoint(float RouteS, FVector2D& OutPoint, FVector2D& OutDir) const;
	float GhostRouteS(double RaceTime) const;
	TArray<FVector2D> LinePts;  // closed for circuits (last = first)
	TArray<float> LineS;        // cumulative distance at each point
	float LapLength = 1.0f;
	TArray<float> RouteS;       // route distance of each Route entry
	TArray<double> GhostSplits; // best run's split times (empty: no best yet)
	float CarRouteS = 0.0f;
	float CarLineDist = 0.0f;
	FVector2D CarLineDir = FVector2D(1.0, 0.0);
	float WrongWayTimer = 0.0f;
	bool bWrongWay = false;
	bool bMissed = false;
	double PreviewUntil = -100.0;   // cr.TT.Preview: route tracking leaves the warning flags alone until then

	// ---- test harness only (command line / console; inactive in normal play)
	FString AutoTrack;          // -TimeTrialAuto=<id>
	double AutoDelay = 2.0;     // -TimeTrialAutoDelay=<s>: world time before the autopilot starts
	bool bAutoDone = false;
	float AutoStuck = 0.0f;
	bool bAutoPlaced = false;
	FVector AutoAimOffset = FVector::ZeroVector;   // sideways shift of a blocked reset, kept until that gate
	int32 AutoAimOffsetEntry = -1;
	struct FResetTestSpot { FVector2D At = FVector2D::ZeroVector; float Yaw = 0.0f, Roll = 0.0f; bool bManual = true; bool bWaypoint = false; };
	TArray<FResetTestSpot> ResetTestSpots;
	int32 ResetTestIndex = -1;
	int32 ResetTestPhase = 0;
	double ResetTestNext = 0.0;
	void TickResetTest(class AImprezaSTi* Car);
	FString AutoAfter;          // -TimeTrialAutoAfter=step[,step...] (retry|next|freeroam|stay): one per finish
	double AutoAfterDelay = 4.0; // -TimeTrialAutoAfterDelay=<s>: results shown this long before the step

	bool bReady = false;
	TArray<FTimeTrialTrack> Tracks;
	UPROPERTY() TArray<TObjectPtr<ATimeTrialGate>> Markers;
	// gate pool: route entry k uses Gates[k % 4] (the passed one flashes while the next three show)
	UPROPERTY() TArray<TObjectPtr<ATimeTrialGate>> Gates;
	int32 PoolEntry[4] = { -1, -1, -1, -1 };
	UPROPERTY() TObjectPtr<class ARacingLineActor> RacingLine;
	UPROPERTY() TMap<FName, TObjectPtr<USoundBase>> Sounds;
	bool bResetHold = false;    // R pressed: car held for a 3-2-1 before it may go (the clock keeps running)
	double ResetHoldStart = -100.0;
	double ResetReleased = -100.0;
	int32 LastBeep = -1;        // countdown second already beeped
	int32 HintMarker = -1;      // free roam: nearest event start within hint range
	float HintDistanceM = 0.0f;

	// hold-to-restart (R / D-pad down / Enter) and hold-to-leave (Backspace / B), real time
	double RestartHeldSince = -1.0;
	double LeaveHeldSince = -1.0;
	FText HoldLabel;
	float GetHoldFraction() const;

	ETimeTrialState State = ETimeTrialState::FreeRoam;
	int32 Active = -1;          // track index of the running event
	int32 NearMarker = -1;      // free roam: event whose start box the car is in
	TArray<int32> Route;        // gate indices in driving order (start line first)
	int32 RouteIndex = 0;       // next entry of Route to drive through
	int32 Lap = 1;
	bool bBothPaddlesHeld = false;
	bool bWheelHold = false;        // the wheel's start button / both paddles are driving RestartHeldSince
	bool bWheelHoldIsStart = false; // (the start button: a tap is "back on track"; both paddles: a tap does nothing)
	double StateStart = 0.0;    // countdown start / run start (world time)
	double FinishTime = 0.0;
	TArray<double> Splits;      // run time at each gate passed
	TArray<double> LapTimes;
	double LastSplitDelta = 0.0;
	bool bLastSplitHasBest = false;
	double LastSplitTime = 0.0;
	int32 LastSplitIndex = 0;            // checkpoint number of the split on show (1-based)
	double LastSplitShown = -100.0;
	double LastPassAt = -100.0;          // pass flash (gate + screen edge)
	int32 LastPassEntry = -1;
	FText CalloutTitle, CalloutBody;     // lap / final lap / fastest lap banner
	bool bCalloutGold = false;
	double CalloutAt = -100.0;
	bool bNewBest = false;
	double PreviousBest = 0.0;           // best total before this run (kept for the results screen)
	TArray<double> PreviousBestSplits;
	double FinishedAt = -100.0;          // world time the run finished (results animate in)
	int32 ResultsFocus = 0;              // 0 retry, 1 next event, 2 free roam
	int32 LastNearMarker = -1;
	double NearSince = -100.0;           // world time the car entered the current start box (prompt animates in)
	FVector LastCarLocation = FVector::ZeroVector;
	int32 TestHitchLeft = 0;             // cr.TT.TestHitchFrames
	double TestHitchNext = 0.0;
	bool bTestHitchHold = false;
	// a start whose road isn't streamed in yet (NEXT EVENT across the map): the car is held on the grid and the
	// countdown waits until the ground under it is there (a blocking streaming flush is requested at once)
	bool bAwaitGround = false;
	double AwaitGroundSince = 0.0;       // real time
	// free roam: "back on the road" toast after a reset
	double RoadResetAt = -100.0;
	FString RoadResetStreet;

	TSharedPtr<FTimeTrialInput> Input;
	TSharedPtr<SWidget> HUD;
	TSharedPtr<class SBox> ResultsHost;
	TWeakObjectPtr<class UGameViewportClient> HUDViewport;
};
