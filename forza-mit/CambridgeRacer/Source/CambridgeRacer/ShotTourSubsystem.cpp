#include "ShotTourSubsystem.h"

#include "AudioMixerBlueprintLibrary.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "ContentStreaming.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMisc.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UnrealClient.h"
#include "WheeledVehiclePawn.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "RHI.h"
#include "WorldPartition/WorldPartitionSubsystem.h"
#include "CambridgeRacerPawn.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "TimeTrialSubsystem.h"
#if WITH_EDITOR
#include "DistanceFieldAtlas.h"
#include "ShaderCompiler.h"
#endif

DEFINE_LOG_CATEGORY_STATIC(LogShotTour, Log, All);

bool UShotTourSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	FString Path;
	return FParse::Value(FCommandLine::Get(), TEXT("ShotTour="), Path) && Super::ShouldCreateSubsystem(Outer);
}

void UShotTourSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!InWorld.IsGameWorld())
	{
		return;
	}
	FString Path, Json;
	FParse::Value(FCommandLine::Get(), TEXT("ShotTour="), Path);
	FParse::Value(FCommandLine::Get(), TEXT("ShotTourSettle="), SettleSeconds);
	if (!FFileHelper::LoadFileToString(Json, *Path))
	{
		UE_LOG(LogShotTour, Error, TEXT("SHOTTOUR_RESULT error=\"cannot read %s\""), *Path);
		FPlatformMisc::RequestExit(false, TEXT("ShotTour"));
		return;
	}
	TArray<TSharedPtr<FJsonValue>> Items;
	FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Items);
	for (const TSharedPtr<FJsonValue>& V : Items)
	{
		const TSharedPtr<FJsonObject> O = V->AsObject();
		FShot S;
		S.Name = O->GetStringField(TEXT("name"));
		const TArray<TSharedPtr<FJsonValue>>* L;
		if (O->TryGetArrayField(TEXT("loc"), L) && L->Num() == 3)
		{
			S.Loc = FVector((*L)[0]->AsNumber(), (*L)[1]->AsNumber(), (*L)[2]->AsNumber());
		}
		if (O->TryGetArrayField(TEXT("rot"), L) && L->Num() == 3)
		{
			S.Rot = FRotator((*L)[0]->AsNumber(), (*L)[1]->AsNumber(), (*L)[2]->AsNumber());
		}
		O->TryGetNumberField(TEXT("fov"), S.Fov);
		O->TryGetNumberField(TEXT("settle"), S.Settle);
		O->TryGetStringField(TEXT("exec"), S.Exec);
		bool bUI = false;
		if (O->TryGetBoolField(TEXT("ui"), bUI))
		{
			S.UI = bUI ? 1 : 0;
		}
		if (O->TryGetArrayField(TEXT("car"), L) && L->Num() == 3)
		{
			S.bCar = true;
			S.Car = FVector((*L)[0]->AsNumber(), (*L)[1]->AsNumber(), (*L)[2]->AsNumber());
		}
		O->TryGetNumberField(TEXT("drive"), S.DriveKmh);
		O->TryGetNumberField(TEXT("drive_s"), S.DriveSeconds);
		O->TryGetBoolField(TEXT("pace"), S.bPace);
		if (O->TryGetArrayField(TEXT("orbit"), L) && L->Num() == 3)
		{
			S.bOrbit = true;
			S.Orbit = FVector((*L)[0]->AsNumber(), (*L)[1]->AsNumber(), (*L)[2]->AsNumber());
		}
		if (O->TryGetArrayField(TEXT("look"), L) && L->Num() == 2)
		{
			S.Look = FVector2D((*L)[0]->AsNumber(), (*L)[1]->AsNumber());
		}
		O->TryGetStringField(TEXT("wait"), S.Wait);
		O->TryGetNumberField(TEXT("frames"), S.Frames);
		O->TryGetStringField(TEXT("seq_exec"), S.SeqExec);
		Shots.Add(S);
	}
	// force the requested window size: saved GameUserSettings (e.g. from a "scalability" console
	// command) otherwise override -ResX/-ResY and silently change what is being measured
	int32 ResX = 0, ResY = 0;
	if (FParse::Value(FCommandLine::Get(), TEXT("ResX="), ResX) && FParse::Value(FCommandLine::Get(), TEXT("ResY="), ResY))
	{
		GEngine->Exec(&InWorld, *FString::Printf(TEXT("r.SetRes %dx%dw"), ResX, ResY));
	}
	bActive = Shots.Num() > 0;
	PreTickHandle = FWorldDelegates::OnWorldPreActorTick.AddUObject(this, &UShotTourSubsystem::PreActorTick);
	UE_LOG(LogShotTour, Display, TEXT("ShotTour: %d shots from %s"), Shots.Num(), *Path);
}

void UShotTourSubsystem::Deinitialize()
{
	FWorldDelegates::OnWorldPreActorTick.Remove(PreTickHandle);
	Super::Deinitialize();
}

void UShotTourSubsystem::ExecAll(const FString& Commands)
{
	TArray<FString> Parts;
	Commands.ParseIntoArray(Parts, TEXT(";"));
	for (const FString& C : Parts)
	{
		const FString Cmd = C.TrimStartAndEnd();
		if (!Cmd.IsEmpty())
		{
			UE_LOG(LogShotTour, Display, TEXT("exec: %s"), *Cmd);
			GEngine->Exec(GetWorld(), *Cmd);
		}
	}
}

bool UShotTourSubsystem::ShowUI(const FShot& S) const
{
	return S.UI >= 0 ? S.UI > 0 : FParse::Param(FCommandLine::Get(), TEXT("ShotTourUI"));
}

void UShotTourSubsystem::PlaceCar(const FShot& S, bool bOnGround)
{
	// teleport the car to "car": [x, y, yaw]; once its cells are streamed in, onto the ground (trace) at the "drive" speed
	APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0);
	if (!Pawn || !S.bCar)
	{
		return;
	}
	FVector Loc(S.Car.X, S.Car.Y, 60.0);
	if (bOnGround)
	{
		FHitResult Hit;
		FCollisionQueryParams Q(TEXT("ShotTourGround"), false, Pawn);
		if (GetWorld()->LineTraceSingleByObjectType(Hit, FVector(Loc.X, Loc.Y, 30000.0), FVector(Loc.X, Loc.Y, -20000.0), FCollisionObjectQueryParams(ECC_WorldStatic), Q))
		{
			Loc.Z = Hit.ImpactPoint.Z + 60.0;
		}
	}
	const FRotator Rot(0.0f, S.Car.Z, 0.0f);
	Pawn->SetActorTransform(FTransform(Rot, Loc), false, nullptr, ETeleportType::TeleportPhysics);
	if (UPrimitiveComponent* Body = Cast<UPrimitiveComponent>(Pawn->GetRootComponent()))
	{
		const float StartKmh = bOnGround ? FMath::Min(S.DriveKmh, 120.0f) : 0.0f;
		Body->SetPhysicsLinearVelocity(Rot.Vector() * StartKmh / 0.036f);
		Body->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	}
	UE_LOG(LogShotTour, Display, TEXT("car placed at (%.0f, %.0f, %.0f) yaw %.1f%s"), Loc.X, Loc.Y, Loc.Z, S.Car.Z, bOnGround ? TEXT(" on the ground") : TEXT(""));
}

void UShotTourSubsystem::PlaceOrbitCamera(const FShot& S)
{
	// camera relative to the car: "orbit": [distance m, bearing from the car's heading deg, height m]
	const APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0);
	if (!Pawn || !Camera || !S.bOrbit)
	{
		return;
	}
	const FVector Target = Pawn->GetActorLocation() + FVector(0.0, 0.0, 40.0);
	const float Bearing = Pawn->GetActorRotation().Yaw + S.Orbit.Y;
	const FVector Cam = FVector(Target.X, Target.Y, Pawn->GetActorLocation().Z - 60.0 + S.Orbit.Z * 100.0)
		+ FRotator(0.0f, Bearing, 0.0f).Vector() * S.Orbit.X * 100.0;
	FRotator Rot = (Target - Cam).Rotation();
	Rot.Pitch += S.Look.X;
	Rot.Yaw += S.Look.Y;
	Camera->SetActorLocationAndRotation(Cam, Rot);
}

void UShotTourSubsystem::PreActorTick(UWorld* World, ELevelTick TickType, float DeltaSeconds)
{
	// "drive": runs before the actors tick, after every tickable (incl. the time-trial autopilot) of the last frame,
	// so these inputs win. Rev blips during a countdown, full throttle (>= 250 km/h) or cruise after it.
	if (World != GetWorld() || !bDriving || !Shots.IsValidIndex(Current))
	{
		return;
	}
	ACambridgeRacerPawn* Car = Cast<ACambridgeRacerPawn>(UGameplayStatics::GetPlayerPawn(World, 0));
	if (!Car)
	{
		return;
	}
	const UTimeTrialSubsystem* TT = World->GetSubsystem<UTimeTrialSubsystem>();
	const ETimeTrialState State = TT ? TT->GetState() : ETimeTrialState::FreeRoam;
	const float Target = Shots[Current].DriveKmh;
	if (State == ETimeTrialState::Running && Shots[Current].DriveSeconds > 0.0f)
	{
		// "drive_s": after that long the race autopilot drives on its own (brakes for the corners, follows the line)
		if (RaceGoAt < 0.0)
		{
			RaceGoAt = World->GetTimeSeconds();
		}
		if (World->GetTimeSeconds() - RaceGoAt > Shots[Current].DriveSeconds && Shots[Current].bPace && TT->GetTracks().IsValidIndex(TT->GetActiveTrack()))
		{
			// "pace": the event line's braking-guide speed (tracks.py: lateral / braking limits) at the nearest point
			const TArray<FVector4>& Line = TT->GetTracks()[TT->GetActiveTrack()].Line;
			if (Line.Num() > 1)
			{
				const FVector2D P(Car->GetActorLocation());
				const int32 From = PaceIndex < 0 ? 0 : FMath::Max(0, PaceIndex - 10);
				const int32 To = PaceIndex < 0 ? Line.Num() - 1 : FMath::Min(Line.Num() - 1, PaceIndex + 60);
				double Best = TNumericLimits<double>::Max();
				for (int32 i = From; i <= To; ++i)
				{
					const double D = FVector2D::DistSquared(P, FVector2D(Line[i].X, Line[i].Y));
					if (D < Best)
					{
						Best = D;
						PaceIndex = i;
					}
				}
				// (the guide assumes 0.75 g braking: 85 % of it, looked up ~25 m ahead, capped at 120 km/h, keeps the
				// car on the autopilot's line through the city corners)
				const float Pace = FMath::Min(float(Line[FMath::Min(PaceIndex + 8, Line.Num() - 1)].W) * 0.85f, 120.0f);
				const float V = Car->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f;
				if (V > Pace + 2.0f)
				{
					Car->DoBrake(FMath::Clamp((V - Pace) / 8.0f, 0.3f, 1.0f));
				}
				else
				{
					Car->DoThrottle(FMath::Clamp((Pace - V) / 8.0f + 0.1f, 0.0f, 1.0f));
				}
				return;
			}
		}
		if (World->GetTimeSeconds() - RaceGoAt > Shots[Current].DriveSeconds)
		{
			if (bDriving)
			{
				UE_LOG(LogShotTour, Display, TEXT("drive: autopilot takes over %.1f s after GO at %.0f km/h"), Shots[Current].DriveSeconds,
					Car->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f);
			}
			bDriving = false;
			return;
		}
	}
	if (State == ETimeTrialState::Countdown)
	{
		Car->DoThrottle(FMath::Fmod(World->GetTimeSeconds(), 1.1) < 0.45 ? 0.85f : 0.0f);
		return;
	}
	if (State == ETimeTrialState::FreeRoam)
	{
		// hold the heading and the line it started on
		const FVector P = Car->GetActorLocation() - DriveOrigin;
		const FVector Right = FRotator(0.0f, DriveYaw + 90.0f, 0.0f).Vector();
		const float Lateral = float(FVector::DotProduct(FVector(P.X, P.Y, 0.0), Right));
		const float YawErr = FMath::FindDeltaAngleDegrees(Car->GetActorRotation().Yaw, DriveYaw);
		Car->DoSteering(FMath::Clamp(YawErr / 20.0f - Lateral / 800.0f, -0.5f, 0.5f));
	}
	const float Kmh = Car->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f;
	if (Target >= 250.0f)
	{
		Car->DoThrottle(1.0f);
	}
	else if (Kmh > Target + 4.0f)
	{
		Car->DoBrake(FMath::Clamp((Kmh - Target) / 20.0f, 0.0f, 0.5f));
	}
	else
	{
		Car->DoThrottle(FMath::Clamp((Target - Kmh) / 10.0f + 0.12f, 0.0f, 1.0f));
	}
}

TStatId UShotTourSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UShotTourSubsystem, STATGROUP_Tickables);
}

bool UShotTourSubsystem::IsWorldReady() const
{
#if WITH_EDITOR
	if (GShaderCompilingManager && GShaderCompilingManager->GetNumRemainingJobs() > 0)
	{
		return false;
	}
	if (GDistanceFieldAsyncQueue && GDistanceFieldAsyncQueue->GetNumOutstandingTasks() > 0)
	{
		return false;
	}
#endif
	return IsLevelStreamingDone() && IStreamingManager::Get().GetNumWantingResources() == 0;
}

bool UShotTourSubsystem::IsLevelStreamingDone() const
{
	// World Partition: cells around the streaming sources (the player controller follows its view target,
	// so the shot camera drives streaming) must be loaded and visible
	const UWorldPartitionSubsystem* WP = GetWorld()->GetSubsystem<UWorldPartitionSubsystem>();
	return !WP || !GetWorld()->GetWorldPartition() || const_cast<UWorldPartitionSubsystem*>(WP)->IsAllStreamingCompleted();
}

void UShotTourSubsystem::LogSettings() const
{
	// what is actually in effect (startup scalability can override -ExecCmds)
	static const TCHAR* Names[] = {
		TEXT("sg.ShadowQuality"), TEXT("sg.GlobalIlluminationQuality"), TEXT("sg.ReflectionQuality"), TEXT("sg.EffectsQuality"),
		TEXT("sg.FoliageQuality"), TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectional"), TEXT("r.Lumen.TraceMeshSDFs.Allow"),
		TEXT("r.Lumen.ScreenProbeGather.DownsampleFactor"), TEXT("r.Nanite.MaxPixelsPerEdge"), TEXT("r.VolumetricCloud"),
		TEXT("r.ScreenPercentage") };
	FString Out;
	for (const TCHAR* Name : Names)
	{
		const IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(Name);
		Out += FString::Printf(TEXT(" %s=%s"), Name, V ? *V->GetString() : TEXT("?"));
	}
	const FIntPoint VP = GEngine->GameViewport && GEngine->GameViewport->Viewport ? GEngine->GameViewport->Viewport->GetSizeXY() : FIntPoint::ZeroValue;
	UE_LOG(LogShotTour, Display, TEXT("settings: viewport=%dx%d%s"), VP.X, VP.Y, *Out);
}

void UShotTourSubsystem::LogCar() const
{
	// diagnostic for the chase-cam car visibility issue
	const APlayerController* PC = UGameplayStatics::GetPlayerController(GetWorld(), 0);
	const AWheeledVehiclePawn* Car = PC ? Cast<AWheeledVehiclePawn>(PC->GetPawn()) : nullptr;
	if (!Car)
	{
		UE_LOG(LogShotTour, Display, TEXT("car: no vehicle pawn (pawn=%s)"), PC && PC->GetPawn() ? *PC->GetPawn()->GetClass()->GetName() : TEXT("none"));
		return;
	}
	const USkeletalMeshComponent* M = Car->GetMesh();
	UE_LOG(LogShotTour, Display, TEXT("car: class=%s loc=%s mesh=%s visible=%d hiddenInGame=%d materials=%d bounds=%.0f"),
		*Car->GetClass()->GetName(), *Car->GetActorLocation().ToString(),
		M && M->GetSkeletalMeshAsset() ? *M->GetSkeletalMeshAsset()->GetPathName() : TEXT("none"),
		M ? int(M->IsVisible()) : -1, int(Car->IsHidden()), M ? M->GetNumMaterials() : -1, M ? M->Bounds.SphereRadius : 0.0f);
}

void UShotTourSubsystem::BeginShot(int32 Index)
{
	// -ShotTourRecordAudio: record the main audio mix for the whole tour (Saved/BouncedWavFiles/shottour.wav),
	// unless there are frame-sequence shots (then each sequence records its own wav)
	if (Index == 0 && FParse::Param(FCommandLine::Get(), TEXT("ShotTourRecordAudio")) && !Shots.ContainsByPredicate([](const FShot& X) { return X.Frames > 0; }))
	{
		UAudioMixerBlueprintLibrary::StartRecordingOutput(GetWorld(), 600.0f, nullptr);
		bRecordingAudio = true;
	}
	Current = Index;
	PhaseTime = 0.0f;
	bCaptureRequested = false;
	FrameTimeAccum = GameMsAccum = RenderMsAccum = GpuMsAccum = 0.0;
	FrameCount = 0;
	bStreamed = false;
	bDriving = false;
	RaceGoAt = -1.0;
	PaceIndex = -1;
	SeqFrame = -1;
	SeqDropped = 0;
	FinishWait = 0.0f;

	APlayerController* PC = UGameplayStatics::GetPlayerController(GetWorld(), 0);
	const FShot& S = Shots[Index];
	if (!S.Exec.IsEmpty())
	{
		ExecAll(S.Exec);
	}
	PlaceCar(S, false);
	// "chase" shots, and UI shots without a camera of their own (the full map, the menu: "loc" [0, 0, 0]), view from
	// the car: World Partition streams around the view, so a free camera at the origin would unload the car's cells
	if (S.Name.StartsWith(TEXT("chase")) || (S.Loc.IsNearlyZero() && S.Rot.IsNearlyZero()))
	{
		PC->SetViewTarget(PC->GetPawn());
		return;
	}
	if (!Camera)
	{
		Camera = GetWorld()->SpawnActor<ACameraActor>();
		Camera->GetCameraComponent()->bConstrainAspectRatio = false;
	}
	Camera->SetActorLocationAndRotation(S.Loc, S.Rot);
	Camera->GetCameraComponent()->SetFieldOfView(S.Fov);
	PlaceOrbitCamera(S);
	PC->SetViewTarget(Camera);
}

void UShotTourSubsystem::Tick(float DeltaTime)
{
	WaitTime += DeltaTime;
	if (Current < 0)
	{
		// wait for shaders / distance fields / streaming (log progress every ~10 s)
		static float LastLog = 0.0f;
		if (!IsWorldReady() && WaitTime < 3600.0f)
		{
#if WITH_EDITOR
			if (WaitTime - LastLog > 10.0f)
			{
				LastLog = WaitTime;
				UE_LOG(LogShotTour, Display, TEXT("waiting: shaders=%d distancefields=%d streaming=%d"),
					GShaderCompilingManager ? GShaderCompilingManager->GetNumRemainingJobs() : -1,
					GDistanceFieldAsyncQueue ? GDistanceFieldAsyncQueue->GetNumOutstandingTasks() : -1,
					IStreamingManager::Get().GetNumWantingResources());
			}
#endif
			return;
		}
		const FIntPoint VP = GEngine->GameViewport && GEngine->GameViewport->Viewport ? GEngine->GameViewport->Viewport->GetSizeXY() : FIntPoint::ZeroValue;
		UE_LOG(LogShotTour, Display, TEXT("world ready after %.0f s (viewport %dx%d)"), WaitTime, VP.X, VP.Y);
		BeginShot(0);
		return;
	}

	if (!bStreamed)
	{
		// the camera just moved: wait for World Partition cells there (max 120 s), then settle
		StreamWait += DeltaTime;
		if (!IsLevelStreamingDone() && StreamWait < 120.0f)
		{
			return;
		}
		UE_LOG(LogShotTour, Display, TEXT("shot %s: streamed in %.1f s"), *Shots[Current].Name, StreamWait);
		bStreamed = true;
		StreamWait = 0.0f;
		if (Shots[Current].Name.StartsWith(TEXT("c")))
		{
			LogCar();
		}
		const FShot& S = Shots[Current];
		if (S.bCar)
		{
			PlaceCar(S, true);
		}
		PlaceOrbitCamera(S);
		if (const APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0); Pawn && S.DriveKmh > 0.0f)
		{
			DriveOrigin = Pawn->GetActorLocation();
			DriveYaw = Pawn->GetActorRotation().Yaw;
			bDriving = S.Frames <= 0;      // a clip drives from its first frame
		}
	}
	if (Shots[Current].Wait == TEXT("finished"))
	{
		// results screen: settle only once the time trial is over (max 300 s)
		const UTimeTrialSubsystem* TT = GetWorld()->GetSubsystem<UTimeTrialSubsystem>();
		if (TT && TT->GetState() != ETimeTrialState::Finished && FinishWait < 300.0f)
		{
			FinishWait += DeltaTime;
			return;
		}
	}
	PhaseTime += DeltaTime;
	// the first shot also warms up the VSM page cache, Lumen scene and Nanite streaming
	const float ShotSettle = Shots[Current].Settle > 0.0f ? Shots[Current].Settle : SettleSeconds;
	const float Settle = Current == 0 ? ShotSettle + 8.0f : ShotSettle;
	if (PhaseTime < Settle)
	{
		if (PhaseTime > Settle - ShotSettle * 0.5f)
		{
			FrameTimeAccum += FApp::GetDeltaTime();
			GameMsAccum += FPlatformTime::ToMilliseconds(GGameThreadTime);
			RenderMsAccum += FPlatformTime::ToMilliseconds(GRenderThreadTime);
			GpuMsAccum += FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles());
			++FrameCount;
		}
		return;
	}
	if (Shots[Current].Frames > 0)
	{
		// frame sequence: one screenshot per frame (fixed timestep: -benchmark -fps=N)
		const FShot& S = Shots[Current];
		const FString Dir = FPaths::ProjectSavedDir() / TEXT("Screenshots/ShotTour") / S.Name;
		if (SeqFrame < 0)
		{
			SeqFrame = 0;
			ExecAll(S.SeqExec);
			bDriving = S.DriveKmh > 0.0f;
			if (FParse::Param(FCommandLine::Get(), TEXT("ShotTourRecordAudio")))
			{
				UAudioMixerBlueprintLibrary::StartRecordingOutput(GetWorld(), 600.0f, nullptr);
				bSeqAudio = true;
			}
			UE_LOG(LogShotTour, Display, TEXT("sequence %s: %d frames at %.4f s/frame (fixed timestep %d)"), *S.Name, S.Frames, FApp::GetDeltaTime(), int(FApp::UseFixedTimeStep()));
		}
		if (SeqFrame < S.Frames)
		{
			if (FScreenshotRequest::IsScreenshotRequested())
			{
				++SeqDropped;    // the last frame's capture is still pending: it gets this frame's name instead
			}
			FScreenshotRequest::RequestScreenshot(Dir / FString::Printf(TEXT("f%04d.png"), SeqFrame), ShowUI(S), false);
			++SeqFrame;
			PhaseTime = Settle;     // hold the phase until the sequence is done
			return;
		}
		if (!bCaptureRequested)
		{
			bCaptureRequested = true;
			bDriving = false;
			if (bSeqAudio)
			{
				UAudioMixerBlueprintLibrary::StopRecordingOutput(GetWorld(), EAudioRecordingExportType::WavFile, S.Name, FString(), nullptr);
				bSeqAudio = false;
			}
			Summary.Add(FString::Printf(TEXT("{\"name\":\"%s\",\"frames\":%d,\"dropped\":%d,\"dt\":%.5f}"), *S.Name, S.Frames, SeqDropped, FApp::GetDeltaTime()));
			UE_LOG(LogShotTour, Display, TEXT("sequence %s: %d frames, %d pending captures overwritten"), *S.Name, S.Frames, SeqDropped);
		}
	}
	if (!bCaptureRequested)
	{
		// -ShotTourProfile: dump a per-pass GPU timing tree into the log for this shot
		if (FParse::Param(FCommandLine::Get(), TEXT("ShotTourProfile")))
		{
			UE_LOG(LogShotTour, Display, TEXT("PROFILEGPU_BEGIN %s"), *Shots[Current].Name);
			GEngine->Exec(GetWorld(), TEXT("ProfileGPU"));
		}
		const FString Dir = FPaths::ProjectSavedDir() / TEXT("Screenshots/ShotTour");
		FScreenshotRequest::RequestScreenshot(Dir / (Shots[Current].Name + TEXT(".png")), ShowUI(Shots[Current]), false);
		bCaptureRequested = true;
		const double N = FMath::Max(FrameCount, 1);
		const double Ms = 1000.0 * FrameTimeAccum / N, Game = GameMsAccum / N, Render = RenderMsAccum / N, Gpu = GpuMsAccum / N;
		const FIntPoint VP = GEngine->GameViewport && GEngine->GameViewport->Viewport ? GEngine->GameViewport->Viewport->GetSizeXY() : FIntPoint::ZeroValue;
		Summary.Add(FString::Printf(TEXT("{\"name\":\"%s\",\"frame_ms\":%.2f,\"fps\":%.1f,\"game_ms\":%.2f,\"render_ms\":%.2f,\"gpu_ms\":%.2f,\"viewport\":\"%dx%d\"}"),
			*Shots[Current].Name, Ms, Ms > 0 ? 1000.0 / Ms : 0.0, Game, Render, Gpu, VP.X, VP.Y));
		UE_LOG(LogShotTour, Display, TEXT("shot %s: %.2f ms/frame (game %.2f, render %.2f, gpu %.2f)"), *Shots[Current].Name, Ms, Game, Render, Gpu);
		if (Current == 0)
		{
			LogSettings();
		}
		return;
	}
	// one more second so the screenshot is written before moving on
	if (PhaseTime < Settle + 1.0f)
	{
		return;
	}
	if (Current + 1 < Shots.Num())
	{
		BeginShot(Current + 1);
	}
	else
	{
		Finish();
	}
}

void UShotTourSubsystem::Finish()
{
	if (bRecordingAudio)
	{
		UAudioMixerBlueprintLibrary::StopRecordingOutput(GetWorld(), EAudioRecordingExportType::WavFile, TEXT("shottour"), FString(), nullptr);
	}
	bActive = false;
	const FString Dir = FPaths::ProjectSavedDir() / TEXT("Screenshots/ShotTour");
	FFileHelper::SaveStringToFile(TEXT("[") + FString::Join(Summary, TEXT(",\n")) + TEXT("]"), *(Dir / TEXT("summary.json")));
	UE_LOG(LogShotTour, Display, TEXT("SHOTTOUR_RESULT shots=%d dir=\"%s\""), Summary.Num(), *FPaths::ConvertRelativePathToFull(Dir));
	FPlatformMisc::RequestExit(false, TEXT("ShotTour"));
}
