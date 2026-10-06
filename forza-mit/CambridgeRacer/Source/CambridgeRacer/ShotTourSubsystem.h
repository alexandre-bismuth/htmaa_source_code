// Rendered screenshot tour for visual iteration. Inactive unless launched with -ShotTour.
//
//   -ShotTour=<path to json>   [{ "name": "...", "loc": [x,y,z] cm, "rot": [pitch,yaw,roll], "fov": 75 }, ...]
//                              a shot whose name starts with "chase" uses the player vehicle's own camera;
//                              optional "settle": seconds (overrides -ShotTourSettle), "exec": console command at shot start
//   -ShotTourRecordAudio       record the main audio mix to Saved/BouncedWavFiles/shottour.wav (run without -nosound)
//   -ShotTourUI                include UI (menus, overlay) in the screenshots
//   -ShotTourProfile           also run ProfileGPU on each shot (per-pass GPU timings in the log)
//   -ShotTourSettle=N          seconds to hold each camera before capturing (default 4, lets Lumen converge)
//
// Optional per-shot fields (gameplay stills and clips; for clips run with -benchmark -fps=60 = fixed timestep):
//   "ui": true|false           overrides -ShotTourUI for this shot
//   "exec": "a; b"             several console commands, separated by ';'
//   "car": [x, y, yaw]         put the car there (cm, deg) on the ground; placed again once streaming is done
//   "drive": km/h              then cruise at that speed (>= 250: full throttle), holding the heading in free roam
//                              (in an event the autopilot of -TimeTrialAuto steers); starts at that speed
//   "drive_s": s               in an event: hand the pedals back to the autopilot this long after GO
//   "pace": true               in an event, after "drive_s": pedals follow the event line's braking-guide speeds
//                              (flat out on straights, brake into the corners; the autopilot still steers)
//   "orbit": [m, deg, m]       camera relative to the car: distance, bearing from the car's heading, height;
//                              "look": [pitch, yaw] offsets from looking at the car
//   "wait": "finished"         settle only once the time trial is finished (results screen)
//   "frames": N                capture N consecutive frames <name>/f0000.png ... instead of one still;
//                              "seq_exec" runs at the first frame; -ShotTourRecordAudio records <name>.wav
//                              for exactly those frames (Saved/BouncedWavFiles; sync needs -DeterministicAudio)
//
// Waits for shader compilation, distance fields and texture streaming to finish, then for each
// shot waits for World Partition cells around the camera, measures the average frame time
// (total, game thread, render thread, GPU), saves Saved/Screenshots/ShotTour/<name>.png, and quits.
// A summary (frame times) is written to Saved/Screenshots/ShotTour/summary.json.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "ShotTourSubsystem.generated.h"

class ACameraActor;

UCLASS()
class UShotTourSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bActive; }
	virtual bool IsTickableWhenPaused() const override { return bActive; }   // e.g. screenshots of the pause menu

private:
	struct FShot
	{
		FString Name;
		FVector Loc = FVector::ZeroVector;
		FRotator Rot = FRotator::ZeroRotator;
		float Fov = 75.0f;
		float Settle = -1.0f;      // per-shot settle (s); -1 = -ShotTourSettle
		FString Exec;              // console command(s) run when the shot starts (e.g. "cr.Menu")
		int32 UI = -1;             // -1 = -ShotTourUI
		bool bCar = false;
		FVector Car = FVector::ZeroVector;   // x, y, yaw
		float DriveKmh = 0.0f;
		float DriveSeconds = 0.0f;   // > 0: override only this long after the race starts
		bool bPace = false;
		bool bOrbit = false;
		FVector Orbit = FVector::ZeroVector; // m, deg, m
		FVector2D Look = FVector2D::ZeroVector;
		FString Wait;
		int32 Frames = 0;
		FString SeqExec;
	};

	bool IsWorldReady() const;
	bool IsLevelStreamingDone() const;
	void LogCar() const;
	void LogSettings() const;
	void BeginShot(int32 Index);
	void Finish();
	void ExecAll(const FString& Commands);
	void PlaceCar(const FShot& S, bool bOnGround);
	void PlaceOrbitCamera(const FShot& S);
	bool ShowUI(const FShot& S) const;
	void PreActorTick(UWorld* World, ELevelTick TickType, float DeltaSeconds);

	bool bActive = false;
	TArray<FShot> Shots;
	int32 Current = -1;
	float SettleSeconds = 4.0f;
	float PhaseTime = 0.0f;
	float WaitTime = 0.0f;
	bool bCaptureRequested = false;
	double FrameTimeAccum = 0.0, GameMsAccum = 0.0, RenderMsAccum = 0.0, GpuMsAccum = 0.0;
	bool bStreamed = false;
	bool bRecordingAudio = false;
	float StreamWait = 0.0f;
	int32 FrameCount = 0;
	TArray<FString> Summary;
	bool bDriving = false;
	FVector DriveOrigin = FVector::ZeroVector;
	float DriveYaw = 0.0f;
	double RaceGoAt = -1.0;        // world time the race state was first seen Running in this shot
	int32 PaceIndex = -1;          // "pace": nearest line point last frame
	int32 SeqFrame = -1;           // frame-sequence shot: next frame index (-1 = not started)
	int32 SeqDropped = 0;
	bool bSeqAudio = false;
	float FinishWait = 0.0f;
	FDelegateHandle PreTickHandle;

	UPROPERTY(Transient) TObjectPtr<ACameraActor> Camera;
};
