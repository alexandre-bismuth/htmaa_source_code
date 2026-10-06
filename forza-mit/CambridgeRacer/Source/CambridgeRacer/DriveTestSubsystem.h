// Headless vehicle test harness. Inactive unless the game is launched with -DriveTest.
//
//   -DriveTest                   settle the player vehicle for 3 s and log where it rests; on a map
//                                whose name contains "DriveTest", then run a manoeuvre:
//   -DriveTestMode=accel         (default) full throttle in a straight line: 0-100, 0-200, 400 m, top speed
//   -DriveTestMode=brake         accelerate past 100 km/h, full brake: 100-0 km/h distance
//   -DriveTestMode=skidpad       hold -DriveTestSpeed (km/h, default 50) while slowly winding on
//                                steering: peak sustained lateral acceleration
//   -DriveTestSeconds=N          max length of the manoeuvre (default 40)
//   -DriveTestTC=off|sport|full  traction control setting for the run (default off: the real car had none)
//
// Writes Saved/DriveTest/<map>_<mode>_<timestamp>.csv and a DRIVETEST_RESULT log line, then quits.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "DriveTestSubsystem.generated.h"

class ACambridgeRacerPawn;

UCLASS()
class UDriveTestSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bActive; }

private:
	void Finish(const TCHAR* Reason);
	void RunAccel(float T, float Kmh, float DistM, float YawErr);
	void RunBrake(float T, float Kmh, float DistM, float YawErr);
	void RunSkidpad(float T, float Kmh, float DeltaTime);

	bool bActive = false;
	bool bManoeuvre = false;
	FString Mode = TEXT("accel");
	float SettleTime = 3.0f;
	float ManoeuvreSeconds = 40.0f;
	float SkidpadKmh = 50.0f;
	float Elapsed = 0.0f;
	float StartTime = -1.0f;
	float StartYaw = 0.0f;
	FVector StartPos = FVector::ZeroVector;

	// results
	float T100 = -1.0f, T200 = -1.0f, T400m = -1.0f, TopKmh = 0.0f;
	float T3Reverse = -1.0f;   // "reverse" mode: speed after 3 s
	bool bBraking = false;
	float BrakeStartDist = -1.0f, BrakeDistM = -1.0f;
	float SpeedHoldI = 0.0f;
	float Steer = 0.0f, LatAccelAvg = 0.0f, PeakLatG = 0.0f, PeakLatSteer = 0.0f;

	TArray<FString> Rows;
	TWeakObjectPtr<ACambridgeRacerPawn> Vehicle;
};
