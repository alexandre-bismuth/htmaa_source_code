#include "DriveTestSubsystem.h"

#include "CambridgeRacerPawn.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Engine/World.h"
#include "HAL/PlatformMisc.h"
#include "ImprezaSTi.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

DEFINE_LOG_CATEGORY_STATIC(LogDriveTest, Log, All);

bool UDriveTestSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return FParse::Param(FCommandLine::Get(), TEXT("DriveTest")) && Super::ShouldCreateSubsystem(Outer);
}

void UDriveTestSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!InWorld.IsGameWorld())
	{
		return;
	}
	FParse::Value(FCommandLine::Get(), TEXT("DriveTestSeconds="), ManoeuvreSeconds);
	FParse::Value(FCommandLine::Get(), TEXT("DriveTestMode="), Mode);
	FParse::Value(FCommandLine::Get(), TEXT("DriveTestSpeed="), SkidpadKmh);
	bManoeuvre = InWorld.GetMapName().Contains(TEXT("DriveTest"));
	bActive = true;
	Rows.Add(TEXT("t,phase,speed_kmh,rpm,gear,x_cm,y_cm,z_cm,yaw_deg,dist_m,wheels_on_ground,steer,lat_g"));
	UE_LOG(LogDriveTest, Display, TEXT("DriveTest active on %s (mode: %s)"), *InWorld.GetMapName(), bManoeuvre ? *Mode : TEXT("settle"));
}

TStatId UDriveTestSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UDriveTestSubsystem, STATGROUP_Tickables);
}

void UDriveTestSubsystem::Tick(float DeltaTime)
{
	// use world time: the subsystem can be ticked more than once per frame
	const float Now = GetWorld()->GetTimeSeconds();
	if (Now <= Elapsed)
	{
		return;
	}
	const float Dt = Now - Elapsed;
	Elapsed = Now;

	if (!Vehicle.IsValid())
	{
		Vehicle = Cast<ACambridgeRacerPawn>(UGameplayStatics::GetPlayerPawn(GetWorld(), 0));
		if (!Vehicle.IsValid())
		{
			if (Elapsed > 10.0f) { Finish(TEXT("no player vehicle spawned")); }
			return;
		}
		if (AImprezaSTi* STi = Cast<AImprezaSTi>(Vehicle.Get()))
		{
			FString TC = TEXT("off");
			FParse::Value(FCommandLine::Get(), TEXT("DriveTestTC="), TC);
			STi->TractionControl = TC == TEXT("full") ? ETractionControlMode::Full
				: TC == TEXT("sport") ? ETractionControlMode::Sport : ETractionControlMode::Off;
		}
		// tuning overrides: -DriveTestFriction=F (all wheels) -DriveTestFrictionFront/Rear=F -DriveTestSplit=S
		UChaosWheeledVehicleMovementComponent* M = Cast<UChaosWheeledVehicleMovementComponent>(Vehicle->GetVehicleMovementComponent());
		float F = -1.0f, FF = -1.0f, FR = -1.0f, Split = -1.0f;
		FParse::Value(FCommandLine::Get(), TEXT("DriveTestFriction="), F);
		FParse::Value(FCommandLine::Get(), TEXT("DriveTestFrictionFront="), FF);
		FParse::Value(FCommandLine::Get(), TEXT("DriveTestFrictionRear="), FR);
		FParse::Value(FCommandLine::Get(), TEXT("DriveTestSplit="), Split);
		for (int32 i = 0; i < M->GetNumWheels(); ++i)
		{
			const float V = i < 2 ? (FF > 0.0f ? FF : F) : (FR > 0.0f ? FR : F);
			if (V > 0.0f) { M->SetWheelFrictionMultiplier(i, V); }
		}
		if (Split >= 0.0f) { M->SetDifferentialFrontRearSplit(Split); }
		// (no brake-torque override: SetWheelMaxBrakeTorque at runtime has no effect in UE 5.8)
	}

	UChaosWheeledVehicleMovementComponent* Move = Cast<UChaosWheeledVehicleMovementComponent>(Vehicle->GetVehicleMovementComponent());
	const FVector Pos = Vehicle->GetActorLocation();
	const float Yaw = Vehicle->GetActorRotation().Yaw;
	const float Kmh = Move->GetForwardSpeed() * 0.036f;
	// lateral acceleration = v * yaw rate
	const float YawRate = FMath::DegreesToRadians(Vehicle->GetMesh()->GetPhysicsAngularVelocityInDegrees().Z);
	const float LatG = FMath::Abs(Move->GetForwardSpeed() * 0.01f * YawRate) / 9.81f;
	int32 OnGround = 0;
	for (int32 i = 0; i < Move->GetNumWheels(); ++i)
	{
		OnGround += Move->GetWheelState(i).bInContact ? 1 : 0;
	}

	const bool bRunning = bManoeuvre && Elapsed >= SettleTime;
	if (bRunning && StartTime < 0.0f)
	{
		StartTime = Elapsed;
		StartPos = Pos;
		StartYaw = Yaw;
	}

	float DistM = 0.0f;
	if (bRunning)
	{
		const float T = Elapsed - StartTime;
		DistM = FVector::Dist2D(Pos, StartPos) / 100.0f;
		const float YawErr = FMath::FindDeltaAngleDegrees(Yaw, StartYaw);
		if (Mode == TEXT("brake")) { RunBrake(T, Kmh, DistM, YawErr); }
		else if (Mode == TEXT("skidpad")) { RunSkidpad(T, Kmh, Dt); LatAccelAvg = FMath::Lerp(LatAccelAvg, LatG, FMath::Min(1.0f, Dt / 1.0f)); }
		else if (Mode == TEXT("reverse"))
		{
			// keyboard-style reverse: hold brake from a standstill
			Vehicle->DoSteering(0.0f);
			Vehicle->DoBrake(1.0f);
			TopKmh = FMath::Max(TopKmh, FMath::Abs(Kmh));
			if (T >= 3.0f && T3Reverse < 0.0f) { T3Reverse = FMath::Abs(Kmh); }
		}
		else { RunAccel(T, Kmh, DistM, YawErr); }
		if (Mode == TEXT("skidpad") && T > 4.0f && LatAccelAvg > PeakLatG)
		{
			PeakLatG = LatAccelAvg;
			PeakLatSteer = Steer;
		}
	}

	Rows.Add(FString::Printf(TEXT("%.3f,%s,%.2f,%.0f,%d,%.1f,%.1f,%.1f,%.2f,%.2f,%d,%.3f,%.3f"),
		Elapsed, bRunning ? *Mode : TEXT("settle"), Kmh, Move->GetEngineRotationSpeed(),
		Move->GetCurrentGear(), Pos.X, Pos.Y, Pos.Z, Yaw, DistM, OnGround, Steer, LatG));

	if (!bManoeuvre && Elapsed >= SettleTime)
	{
		Finish(TEXT("settle only"));
	}
	else if (bRunning && Mode == TEXT("brake") && BrakeDistM >= 0.0f)
	{
		Finish(TEXT("stopped"));
	}
	else if (bRunning && Elapsed - StartTime >= ManoeuvreSeconds)
	{
		Finish(TEXT("time limit"));
	}
}

void UDriveTestSubsystem::RunAccel(float T, float Kmh, float DistM, float YawErr)
{
	// hold a straight line: proportional steering on heading error
	Steer = FMath::Clamp(YawErr * 0.05f, -1.0f, 1.0f);
	Vehicle->DoSteering(Steer);
	Vehicle->DoThrottle(1.0f);
	if (T100 < 0.0f && Kmh >= 100.0f) { T100 = T; }
	if (T200 < 0.0f && Kmh >= 200.0f) { T200 = T; }
	if (T400m < 0.0f && DistM >= 400.0f) { T400m = T; }
	TopKmh = FMath::Max(TopKmh, Kmh);
}

void UDriveTestSubsystem::RunBrake(float T, float Kmh, float DistM, float YawErr)
{
	Steer = FMath::Clamp(YawErr * 0.05f, -1.0f, 1.0f);
	Vehicle->DoSteering(Steer);
	if (!bBraking)
	{
		Vehicle->DoThrottle(1.0f);
		bBraking = Kmh >= 105.0f;
		return;
	}
	Vehicle->DoBrake(1.0f);
	if (BrakeStartDist < 0.0f && Kmh <= 100.0f)
	{
		BrakeStartDist = DistM;
	}
	if (BrakeStartDist >= 0.0f && Kmh < 0.5f)
	{
		BrakeDistM = DistM - BrakeStartDist;
	}
}

void UDriveTestSubsystem::RunSkidpad(float T, float Kmh, float DeltaTime)
{
	// PI speed hold (a pure P controller settles below the target)
	const float Err = SkidpadKmh - Kmh;
	SpeedHoldI = FMath::Clamp(SpeedHoldI + Err * 0.02f * DeltaTime, 0.0f, 1.0f);
	const float Cmd = Err * 0.15f + SpeedHoldI;
	if (Cmd >= 0.0f) { Vehicle->DoThrottle(FMath::Clamp(Cmd, 0.0f, 1.0f)); }
	else { Vehicle->DoBrake(FMath::Clamp(-Cmd * 0.3f, 0.0f, 1.0f)); }
	// wind on steering only once at speed: 0 -> full lock over ~25 s
	if (Kmh >= SkidpadKmh * 0.9f || Steer > 0.0f)
	{
		Steer = FMath::Min(1.0f, Steer + DeltaTime * 0.04f);
	}
	Vehicle->DoSteering(Steer);
}

void UDriveTestSubsystem::Finish(const TCHAR* Reason)
{
	bActive = false;
	const FString Dir = FPaths::ProjectSavedDir() / TEXT("DriveTest");
	const FString File = Dir / FString::Printf(TEXT("%s_%s_%s.csv"), *GetWorld()->GetMapName(), bManoeuvre ? *Mode : TEXT("settle"), *FDateTime::Now().ToString());
	FFileHelper::SaveStringArrayToFile(Rows, *File);

	FString Summary = FString::Printf(TEXT("DRIVETEST_RESULT mode=%s reason=\"%s\" csv=\"%s\""),
		bManoeuvre ? *Mode : TEXT("settle"), Reason, *FPaths::ConvertRelativePathToFull(File));
	if (Vehicle.IsValid())
	{
		Summary += FString::Printf(TEXT(" rest_z_cm=%.1f"), Vehicle->GetActorLocation().Z);
	}
	if (bManoeuvre && Mode == TEXT("accel"))
	{
		Summary += FString::Printf(TEXT(" t0_100=%.2f t0_200=%.2f t400m=%.2f top_kmh=%.1f"), T100, T200, T400m, TopKmh);
	}
	else if (bManoeuvre && Mode == TEXT("brake"))
	{
		Summary += FString::Printf(TEXT(" brake_100_0_m=%.1f"), BrakeDistM);
	}
	else if (bManoeuvre && Mode == TEXT("reverse"))
	{
		Summary += FString::Printf(TEXT(" kmh_at_3s=%.1f top_reverse_kmh=%.1f"), T3Reverse, TopKmh);
	}
	else if (bManoeuvre && Mode == TEXT("skidpad"))
	{
		Summary += FString::Printf(TEXT(" speed_kmh=%.0f peak_lat_g=%.3f at_steer=%.2f"), SkidpadKmh, PeakLatG, PeakLatSteer);
	}
	UE_LOG(LogDriveTest, Display, TEXT("%s"), *Summary);
	FPlatformMisc::RequestExit(false, TEXT("DriveTest"));
}
