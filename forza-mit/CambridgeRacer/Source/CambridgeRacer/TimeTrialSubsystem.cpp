#include "TimeTrialSubsystem.h"

#include "CambridgeGameUserSettings.h"
#include "CambridgeLaunchSubsystem.h"
#include "CambridgeMenuSubsystem.h"
#include "CambridgeUIStyle.h"
#include "CambridgeWheelSubsystem.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Algo/BinarySearch.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "HAL/IConsoleManager.h"
#include "Framework/Application/SlateApplication.h"
#include "ImprezaSTi.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "MinimapSubsystem.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/Paths.h"
#include "RacingLineActor.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sound/SoundBase.h"
#include "Styling/CoreStyle.h"
#include "TimeTrialGate.h"
#include "TimeTrialWidgets.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "TimeTrial"

DEFINE_LOG_CATEGORY_STATIC(LogTimeTrial, Log, All);

namespace
{
	constexpr double CountdownSeconds = 3.0;
	constexpr float MarkerRadiusCm = 1600.0f;
	constexpr float HintRadiusCm = 15000.0f;     // free roam: point the way to an event start from 150 m
	constexpr double ResetHoldSeconds = 3.0;
	constexpr double HoldSeconds = 1.0;          // hold to restart / leave
	constexpr double TapSeconds = 0.4;           // shorter R press = back on track
	constexpr double PassFlashSeconds = 0.5;
	constexpr double SplitShowSeconds = 2.6;
	constexpr double CalloutSeconds = 3.0;
	constexpr float MissedPastCm = 1500.0f;      // along the line past the next gate without crossing it
	constexpr double ResultsArmSeconds = 1.5;   // results window: Enter / A ignored this long after the finish
	constexpr float StartMaxKmh = 40.0f;         // gamepad A (also the brake) only starts an event when slow
	constexpr double RoadResetToastSeconds = 2.5;

	// test: emulate long frames for the checkpoint logic (the car moves on, the gate test sees one long chord)
	TAutoConsoleVariable<int32> CVarTestHitchFrames(TEXT("cr.TT.TestHitchFrames"), 0,
		TEXT("Test: every 3 s of an event, hold the checkpoint / route tracking for N frames, then test the whole move at once (a hitch)"));
	const TCHAR* const SoundNames[] = { TEXT("ui_count"), TEXT("ui_go"), TEXT("ui_checkpoint"), TEXT("ui_checkpoint_ahead"),
		TEXT("ui_lap"), TEXT("ui_final_lap"), TEXT("ui_finish"), TEXT("ui_new_best"), TEXT("ui_wrong_way"), TEXT("ui_missed"),
		TEXT("ui_select"), TEXT("ui_confirm") };

	FString FormatTime(double T)
	{
		if (T < 0.0) { T = 0.0; }
		const int32 Minutes = int32(T / 60.0);
		return FString::Printf(TEXT("%d:%06.3f"), Minutes, T - Minutes * 60.0);
	}

	FString Signed(double V, int32 Decimals = 3)
	{
		return FString::Printf(TEXT("%s%.*f"), V <= 0.0 ? TEXT("-") : TEXT("+"), Decimals, FMath::Abs(V));
	}

	FVector ReadVec(const TSharedPtr<FJsonObject>& O)
	{
		return FVector(O->GetNumberField(TEXT("x")), O->GetNumberField(TEXT("y")), O->GetNumberField(TEXT("z")));
	}

	bool IsAnyOf(const FKey& K, std::initializer_list<FKey> Keys)
	{
		for (const FKey& X : Keys) { if (K == X) { return true; } }
		return false;
	}
}

class FTimeTrialInput : public IInputProcessor
{
public:
	explicit FTimeTrialInput(UTimeTrialSubsystem* InOwner) : Owner(InOwner) {}
	virtual void Tick(const float, FSlateApplication&, TSharedRef<ICursor>) override {}
	virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
	{
		return Owner.IsValid() && !Event.IsRepeat() && Owner->OnKeyDown(Event.GetKey());
	}
	virtual bool HandleKeyUpEvent(FSlateApplication&, const FKeyEvent& Event) override
	{
		return Owner.IsValid() && Owner->OnKeyUp(Event.GetKey());
	}
	virtual const TCHAR* GetDebugName() const override { return TEXT("TimeTrialInput"); }

private:
	TWeakObjectPtr<UTimeTrialSubsystem> Owner;
};

bool UTimeTrialSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return Super::ShouldCreateSubsystem(Outer) && !IsRunningCommandlet();
}

TStatId UTimeTrialSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UTimeTrialSubsystem, STATGROUP_Tickables);
}

void UTimeTrialSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!InWorld.IsGameWorld())
	{
		return;
	}
	LoadConfig();          // the best runs as saved now (the CDO only has what was on disk at startup)
	if (const UCambridgeGameUserSettings* Settings = UCambridgeGameUserSettings::Get())
	{
		Settings->ApplySound();      // (the master volume: the audio device exists now)
	}
	BestTimeCache.Reset();
	LoadTracks();
	LoadSounds();
	SpawnMarkers();
	const TCHAR* Cmd = FCommandLine::Get();
	const bool bAutomated = FCString::Strifind(Cmd, TEXT("-ShotTour")) || FCString::Strifind(Cmd, TEXT("-DriveTest"));
	if (FSlateApplication::IsInitialized() && !bAutomated)
	{
		Input = MakeShared<FTimeTrialInput>(this);
		FSlateApplication::Get().RegisterInputPreProcessor(Input);
	}
	FParse::Value(Cmd, TEXT("TimeTrialAuto="), AutoTrack);
	FParse::Value(Cmd, TEXT("TimeTrialAutoDelay="), AutoDelay);
	FParse::Value(Cmd, TEXT("TimeTrialAutoAfter="), AutoAfter, false);   // (no comma stop: a list of steps)
	FParse::Value(Cmd, TEXT("TimeTrialAutoAfterDelay="), AutoAfterDelay);
	bReady = true;
}

void UTimeTrialSubsystem::LoadSounds()
{
	for (const TCHAR* Name : SoundNames)
	{
		if (USoundBase* S = LoadObject<USoundBase>(nullptr, *FString::Printf(TEXT("/Game/Cambridge/Game/Audio/%s.%s"), Name, Name)))
		{
			Sounds.Add(Name, S);
		}
	}
	UE_LOG(LogTimeTrial, Display, TEXT("%d race UI sounds loaded"), Sounds.Num());
}

void UTimeTrialSubsystem::PlayUISound(FName Name, float Volume) const
{
	if (const TObjectPtr<USoundBase>* S = Sounds.Find(Name); S && *S)
	{
		const UCambridgeGameUserSettings* Settings = UCambridgeGameUserSettings::Get();
		UGameplayStatics::PlaySound2D(GetWorld(), *S, Volume * (Settings ? FMath::Clamp(Settings->RaceSoundsVolume, 0.0f, 1.0f) : 1.0f));
	}
	UE_LOG(LogTimeTrial, Verbose, TEXT("sound %s"), *Name.ToString());
}

void UTimeTrialSubsystem::ResetToLastGate()
{
	AImprezaSTi* Car = GetCar();
	if (!Car || State != ETimeTrialState::Running || !Route.IsValidIndex(RouteIndex) || bResetHold)
	{
		return;
	}
	const FTimeTrialTrack& T = Tracks[Active];
	// on the racing line (road centre) up to 15 m before the next gate, lined up with it. Only on the straight
	// run into the gate: a gate just after a corner gets the car placed past the corner apex (on the line,
	// which cuts across the junction, a point there faces diagonally into the kerb), at least 4 m before it.
	FVector At = T.StartLocation;
	FRotator Rot(0.0f, T.StartYaw, 0.0f);
	if (RouteIndex > 0 && LinePts.Num() >= 2)
	{
		const FTimeTrialGateDef& G = T.Gates[Route[RouteIndex]];
		const FVector2D GateDir(FMath::Cos(FMath::DegreesToRadians(G.Yaw)), FMath::Sin(FMath::DegreesToRadians(G.Yaw)));
		const float GateS = RouteS[RouteIndex];
		const float Floor = RouteS[RouteIndex - 1] + 100.0f;
		float S = FMath::Max(GateS - 400.0f, Floor);
		FVector2D P, D;
		for (float Back = 500.0f; Back <= 1500.0f && GateS - Back >= Floor; Back += 100.0f)
		{
			RoutePoint(GateS - Back, P, D);
			if (FVector2D::DotProduct(D, GateDir) < 0.9f)     // the line bends more than ~25 deg away: corner
			{
				break;
			}
			S = GateS - Back;
		}
		RoutePoint(S, P, D);
		At = FVector(P.X, P.Y, 0.0);
		Rot = FRotator(0.0f, G.Yaw, 0.0f);
		CarRouteS = S;
		// keep the run to the gate clear: a traffic-light pole or a bollard on the line (they stand in some
		// junctions) would stop the car again right after the 3-2-1. Sweep a car-sized box from here to just
		// past the gate (above kerb height, against what blocks the car) and slide sideways if it hits.
		{
			const FVector Right = FRotator(0.0f, G.Yaw, 0.0f).Quaternion().GetRightVector();
			const FVector Through = FVector(G.Location.X, G.Location.Y, 0.0) + Rot.Vector() * 300.0f;
			const float Room = FMath::Max(G.Width * 0.5f - 150.0f, 0.0f);
			const ECollisionChannel Channel = Car->GetMesh()->GetCollisionObjectType();
			FCollisionQueryParams Q(SCENE_QUERY_STAT(TimeTrialResetClear), false, Car);
			const FCollisionShape Box = FCollisionShape::MakeBox(FVector(220.0f, 95.0f, 40.0f));
			for (const float Side : { 0.0f, 150.0f, -150.0f, 300.0f, -300.0f, 450.0f, -450.0f })
			{
				if (FMath::Abs(Side) > Room && Side != 0.0f)
				{
					continue;
				}
				const FVector Off = Right * Side + FVector(0.0, 0.0, 110.0);
				if (!GetWorld()->SweepTestByChannel(At + Off, Through + Off, Rot.Quaternion(), Channel, Box, Q,
					FCollisionResponseParams(Car->GetMesh()->GetCollisionResponseToChannels())))
				{
					if (Side != 0.0f)
					{
						UE_LOG(LogTimeTrial, Display, TEXT("back on track: the line is blocked, %.1f m to the %s"), FMath::Abs(Side) / 100.0f, Side > 0.0f ? TEXT("right") : TEXT("left"));
					}
					At += Right * Side;
					if (!AutoTrack.IsEmpty())           // (test harness only: the autopilot keeps to that side until the gate)
					{
						AutoAimOffset = Right * Side;
						AutoAimOffsetEntry = RouteIndex;
					}
					break;
				}
			}
		}
		// drop onto whatever is there (roads are flat at z = 0 today, but bridges / ramps may come); from
		// 3 m up only, so a traffic-light arm or a canopy over the road can't catch the trace
		FHitResult Hit;
		FCollisionQueryParams Q(SCENE_QUERY_STAT(TimeTrialReset), false, Car);
		const bool bGround = GetWorld()->LineTraceSingleByChannel(Hit, At + FVector(0, 0, 300), At - FVector(0, 0, 800), ECC_Visibility, Q);
		At.Z = bGround ? Hit.ImpactPoint.Z + 60.0 : 60.0;
		UE_LOG(LogTimeTrial, Display, TEXT("back on track: %.0f m before checkpoint %d at (%.0f, %.0f, %.0f), ground %s"),
			(GateS - S) / 100.0f, RouteIndex, At.X, At.Y, At.Z, bGround && Hit.GetActor() ? *Hit.GetActor()->GetName() : TEXT("none"));
	}
	Car->SetActorTransform(FTransform(Rot, At), false, nullptr, ETeleportType::TeleportPhysics);
	Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
	Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	Car->SnapCamera();
	LastCarLocation = Car->GetActorLocation();
	// held for a 3-2-1 before it may go again; the race clock keeps running (that's the penalty)
	Car->GetChaosVehicleMovement()->SetParked(true);
	bResetHold = true;
	ResetHoldStart = Now();
	LastBeep = -1;
	bMissed = false;
	bWrongWay = false;
	WrongWayTimer = 0.0f;
	if (RacingLine) { RacingLine->ResetProgress(); }
}

// ------------------------------------------------------------------ test harness (command line only)
// -TimeTrialAuto=<id> [-TimeTrialAutoAfter=retry|next|freeroam|stay,...]: a scripted driver for headless / tour tests of
// the race flow (starts, gates, results buttons, NEXT EVENT). Not a gameplay feature: it is never active in normal play
// (Tick calls it only when AutoTrack is set) and is not being developed further.
void UTimeTrialSubsystem::Autopilot(AImprezaSTi* Car)
{
	if (State == ETimeTrialState::FreeRoam)
	{
		const int32 Index = Tracks.IndexOfByPredicate([this](const FTimeTrialTrack& T) { return T.Id == AutoTrack; });
		if (Index < 0 || Now() < AutoDelay || bAutoDone)
		{
			return;
		}
		if (!FParse::Param(FCommandLine::Get(), TEXT("TimeTrialAutoViaMarker")))
		{
			StartEvent(Index);
			return;
		}
		// the player's path: drive to the event's start marker, then "press Enter"
		if (NearMarker == Index)
		{
			UE_LOG(LogTimeTrial, Display, TEXT("autopilot reached the %s marker, confirming"), *Tracks[Index].Name);
			Car->DoBrake(1.0f);
			OnConfirm();
			return;
		}
		if (!bAutoPlaced)
		{
			// (the test driver can't route through the city: start 30 m short of the marker, lined up)
			bAutoPlaced = true;
			const FVector Back = FRotator(0.0f, Tracks[Index].StartYaw, 0.0f).Vector();
			Car->SetActorTransform(FTransform(Back.Rotation(), Tracks[Index].StartLocation - Back * 3000.0f), false, nullptr, ETeleportType::TeleportPhysics);
			Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
		}
		const FVector D = (Tracks[Index].StartLocation - Car->GetActorLocation()).GetSafeNormal2D();
		const float Angle = FMath::RadiansToDegrees(FMath::Atan2(FVector::CrossProduct(Car->GetActorForwardVector(), D).Z,
			FVector::DotProduct(Car->GetActorForwardVector().GetSafeNormal2D(), D)));
		Car->DoSteering(FMath::Clamp(Angle / 25.0f, -1.0f, 1.0f));
		const float Speed = Car->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f;
		Speed < 40.0f ? Car->DoThrottle(0.6f) : Car->DoThrottle(0.0f);
		return;
	}
	if (State == ETimeTrialState::Finished)
	{
		// (Tick brings the car to a stop on the results screen)
		// -TimeTrialAutoAfter=<step>[,<step>...]: one step per finish, retry | next | freeroam | stay, pressed
		// AutoAfterDelay s after the line (tests the results flow end to end, e.g. retry,next,next,stay).
		// The autopilot keeps driving each event that a step starts; it stops after freeroam / stay / the last step.
		if (bAutoDone || Now() - FinishedAt <= AutoAfterDelay)
		{
			return;
		}
		FString Step, Rest;
		if (!AutoAfter.Split(TEXT(","), &Step, &Rest))
		{
			Step = AutoAfter;
		}
		AutoAfter = Rest.TrimStartAndEnd();
		Step = Step.TrimStartAndEnd().ToLower();
		const int32 Choice = Step == TEXT("retry") ? 0 : Step == TEXT("next") ? 1 : Step == TEXT("freeroam") ? 2 : -1;
		bAutoDone = Choice < 0 || Choice == 2 || AutoAfter.IsEmpty();
		UE_LOG(LogTimeTrial, Display, TEXT("autopilot: after %s (%s): results step '%s' -> button %d; steps left '%s'"),
			*Tracks[Active].Id, *FormatTime(FinishTime), *Step, Choice, *AutoAfter);
		if (Choice >= 0)
		{
			ActivateResult(Choice);
		}
		return;
	}
	const FTimeTrialTrack& T = Tracks[Active];
	auto Bearing = [Car](const FVector& P)
	{
		const FVector D = (P - Car->GetActorLocation()).GetSafeNormal2D();
		return FMath::RadiansToDegrees(FMath::Atan2(FVector::CrossProduct(Car->GetActorForwardVector(), D).Z,
			FVector::DotProduct(Car->GetActorForwardVector().GetSafeNormal2D(), D)));
	};
	const FTimeTrialGateDef& Next = T.Gates[Route[RouteIndex]];
	const FTimeTrialGateDef& After = T.Gates[Route[FMath::Min(RouteIndex + 1, Route.Num() - 1)]];
	// pure pursuit on the racing line (road centre) a little ahead of the car; without a line, aim through
	// the gate along its direction. Slow for the turn that follows.
	FVector Aim = Next.Location + FRotator(0.0f, Next.Yaw, 0.0f).Vector() * 800.0f;
	if (LinePts.Num() >= 2 && State == ETimeTrialState::Running)
	{
		const float SpeedNow = FMath::Abs(Car->GetChaosVehicleMovement()->GetForwardSpeed()) * 0.036f;
		FVector2D P, D;
		RoutePoint(CarRouteS + 900.0f + 25.0f * SpeedNow, P, D);
		Aim = FVector(P.X, P.Y, Car->GetActorLocation().Z) + (AutoAimOffsetEntry == RouteIndex ? AutoAimOffset : FVector::ZeroVector);
	}
	const float Angle = Bearing(Aim);
	const float Turn = FMath::Max(FMath::Abs(FMath::FindDeltaAngleDegrees(Car->GetActorRotation().Yaw, Next.Yaw)),
		FMath::Abs(FMath::FindDeltaAngleDegrees(Next.Yaw, After.Yaw)));
	const float Dist = FVector::Dist2D(Car->GetActorLocation(), Next.Location) / 100.0f;
	// (floored: a hairpin / a gate behind the car must still mean "creep", not a negative speed = brake forever)
	const float Target = FMath::Max(FMath::Lerp(75.0f, 75.0f - 0.55f * Turn, FMath::Clamp(1.0f - (Dist - 25.0f) / 60.0f, 0.0f, 1.0f)), 18.0f);
	const float Speed = Car->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f;
	// stuck (kerb, wall): back to the last gate, like the player's reset
	AutoStuck = (State == ETimeTrialState::Running && !bResetHold && FMath::Abs(Speed) < 3.0f) ? AutoStuck + GetWorld()->GetDeltaSeconds() : 0.0f;
	if (AutoStuck > 2.0f)
	{
		AutoStuck = 0.0f;
		UE_LOG(LogTimeTrial, Display, TEXT("autopilot stuck before route entry %d at (%.0f, %.0f, %.0f) yaw %.0f, gear %d, %.0f rpm, aim %.0f deg, target %.0f km/h, %.0f m from the gate"),
			RouteIndex, Car->GetActorLocation().X, Car->GetActorLocation().Y, Car->GetActorLocation().Z, Car->GetActorRotation().Yaw,
			Car->GetChaosVehicleMovement()->GetCurrentGear(), Car->GetChaosVehicleMovement()->GetEngineRotationSpeed(), Angle, Target, Dist);
		ResetToLastGate();
		return;
	}
	Car->DoSteering(FMath::Clamp(Angle / 25.0f, -1.0f, 1.0f));
	if (State == ETimeTrialState::Countdown)
	{
		Car->DoThrottle(0.3f);
	}
	else if (Speed > Target + 6.0f)
	{
		Car->DoBrake(FMath::Clamp((Speed - Target) / 25.0f, 0.2f, 1.0f));
	}
	else
	{
		Car->DoThrottle(FMath::Clamp((Target - Speed) / 12.0f, 0.15f, 1.0f));
	}
}

void UTimeTrialSubsystem::Deinitialize()
{
	if (Input.IsValid() && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().UnregisterInputPreProcessor(Input);
	}
	Input.Reset();
	if (HUD.IsValid() && HUDViewport.IsValid())
	{
		HUDViewport->RemoveViewportWidgetContent(HUD.ToSharedRef());
	}
	HUD.Reset();
	Super::Deinitialize();
}

void UTimeTrialSubsystem::LoadTracks()
{
	const FString Map = FPackageName::GetShortName(GetWorld()->GetOutermost()->GetName()).Replace(TEXT("UEDPIE_0_"), TEXT(""));
	const FString Path = FPaths::ProjectDir() / TEXT("Tracks") / (Map + TEXT(".json"));
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogTimeTrial, Display, TEXT("no time trials for %s (%s)"), *Map, *Path);
		return;
	}
	TSharedPtr<FJsonObject> Root;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
	{
		UE_LOG(LogTimeTrial, Warning, TEXT("cannot parse %s"), *Path);
		return;
	}
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("tracks")))
	{
		const TSharedPtr<FJsonObject> O = V->AsObject();
		FTimeTrialTrack T;
		T.Id = O->GetStringField(TEXT("id"));
		T.Name = O->GetStringField(TEXT("name"));
		T.bCircuit = O->GetStringField(TEXT("type")) == TEXT("circuit");
		T.Laps = FMath::Max(1, int32(O->GetNumberField(TEXT("laps"))));
		T.LengthM = O->GetNumberField(TEXT("length_m"));
		const TSharedPtr<FJsonObject> S = O->GetObjectField(TEXT("start"));
		T.StartLocation = ReadVec(S);
		T.StartYaw = S->GetNumberField(TEXT("yaw"));
		for (const TSharedPtr<FJsonValue>& G : O->GetArrayField(TEXT("gates")))
		{
			const TSharedPtr<FJsonObject> GO = G->AsObject();
			FTimeTrialGateDef& Gate = T.Gates.Add_GetRef({ ReadVec(GO), float(GO->GetNumberField(TEXT("yaw"))), float(GO->GetNumberField(TEXT("width"))) });
			// the trigger spans the road at the gate (tools/mapgen/tracks.py): driving round a pylon still counts
			Gate.TriggerLeft = Gate.TriggerRight = Gate.Width * 0.5f;
			const TArray<TSharedPtr<FJsonValue>>* Trigger;
			if (GO->TryGetArrayField(TEXT("trigger"), Trigger) && Trigger->Num() == 2)
			{
				Gate.TriggerLeft = FMath::Max(Gate.TriggerLeft, float((*Trigger)[0]->AsNumber()));
				Gate.TriggerRight = FMath::Max(Gate.TriggerRight, float((*Trigger)[1]->AsNumber()));
			}
		}
		const TArray<TSharedPtr<FJsonValue>>* LinePtsJson;
		if (O->TryGetArrayField(TEXT("line"), LinePtsJson))
		{
			for (const TSharedPtr<FJsonValue>& P : *LinePtsJson)
			{
				const TArray<TSharedPtr<FJsonValue>>& A = P->AsArray();
				if (A.Num() >= 3) { T.Line.Add(FVector4(A[0]->AsNumber(), A[1]->AsNumber(), 0.0, A[2]->AsNumber())); }
			}
		}
		if (T.Gates.Num() >= 2)
		{
			const FVector2D D(T.StartLocation - T.Gates[0].Location);
			const FVector2D F(FMath::Cos(FMath::DegreesToRadians(T.Gates[0].Yaw)), FMath::Sin(FMath::DegreesToRadians(T.Gates[0].Yaw)));
			T.StartLocal = FVector2D(FVector2D::DotProduct(D, F), FVector2D::CrossProduct(F, D));   // UE: +Y is right of +X
			Tracks.Add(MoveTemp(T));
		}
	}
	UE_LOG(LogTimeTrial, Display, TEXT("%d time trials loaded from %s"), Tracks.Num(), *Path);
}

void UTimeTrialSubsystem::SpawnMarkers()
{
	for (ATimeTrialGate* M : Markers)
	{
		if (M) { M->Destroy(); }
	}
	Markers.Reset();
	for (const FTimeTrialTrack& T : Tracks)
	{
		FActorSpawnParameters P;
		P.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ATimeTrialGate* M = GetWorld()->SpawnActor<ATimeTrialGate>(T.Gates[0].Location, FRotator(0.0f, T.Gates[0].Yaw, 0.0f), P);
		M->SetStartBox(T.StartLocal);
		M->Configure(T.Gates[0].Width, EGateKind::Start, T.Name);
		Markers.Add(M);
	}
	MarkerGrounded.Init(false, Markers.Num());
}

bool UTimeTrialSubsystem::GroundZ(const FVector& At, float& OutZ) const
{
	FHitResult Hit;
	FCollisionQueryParams Q(SCENE_QUERY_STAT(TimeTrialGround), false, GetCar());
	if (GetWorld()->LineTraceSingleByChannel(Hit, At + FVector(0, 0, 500), At - FVector(0, 0, 500), ECC_Visibility, Q))
	{
		OutZ = float(Hit.ImpactPoint.Z);
		return true;
	}
	return false;
}

bool UTimeTrialSubsystem::IsWheelActive() const
{
	const UCambridgeWheelSubsystem* Wheel = UCambridgeWheelSubsystem::Get(this);
	return Wheel && Wheel->IsActive();
}

AImprezaSTi* UTimeTrialSubsystem::GetCar() const
{
	return Cast<AImprezaSTi>(UGameplayStatics::GetPlayerPawn(GetWorld(), 0));
}

double UTimeTrialSubsystem::Now() const
{
	return GetWorld()->GetTimeSeconds();   // stops while the pause menu is open
}

double UTimeTrialSubsystem::GetBestTime(int32 TrackIndex) const
{
	if (!Tracks.IsValidIndex(TrackIndex))
	{
		return 0.0;
	}
	if (BestTimeCache.Num() != Tracks.Num())
	{
		BestTimeCache.Init(-1.0, Tracks.Num());
	}
	double& Cached = BestTimeCache[TrackIndex];
	if (Cached < 0.0)
	{
		BestSplits(Tracks[TrackIndex], Cached);     // (0 when there is none)
	}
	return Cached;
}

TArray<double> UTimeTrialSubsystem::BestSplits(const FTimeTrialTrack& T, double& OutTotal) const
{
	TArray<double> Out;
	OutTotal = 0.0;
	if (const FString* Run = BestRuns.Find(T.Id))
	{
		FString Total, List;
		if (Run->Split(TEXT(";"), &Total, &List))
		{
			TArray<FString> Parts;
			List.ParseIntoArray(Parts, TEXT(","));
			// one split per checkpoint crossing (the race HUD's "CHECKPOINT n/N"); another count means the event was
			// regenerated with other gates since (tools/mapgen/tracks.py): that time isn't comparable, so there is no best
			const int32 Expected = T.bCircuit ? T.Gates.Num() * T.Laps : T.Gates.Num() - 1;
			if (Parts.Num() != Expected)
			{
				static TSet<FString> Reported;
				if (!Reported.Contains(T.Id))
				{
					Reported.Add(T.Id);
					UE_LOG(LogTimeTrial, Display, TEXT("best run of %s ignored: %d splits saved, the event now has %d checkpoints (it changed)"), *T.Id, Parts.Num(), Expected);
				}
				return Out;
			}
			OutTotal = FCString::Atod(*Total);
			for (const FString& S : Parts) { Out.Add(FCString::Atod(*S)); }
		}
	}
	return Out;
}

// ------------------------------------------------------------------ input

bool UTimeTrialSubsystem::IsUIBlocking() const
{
	const UGameInstance* GI = GetWorld() ? GetWorld()->GetGameInstance() : nullptr;
	const UCambridgeMenuSubsystem* Menu = GI ? GI->GetSubsystem<UCambridgeMenuSubsystem>() : nullptr;
	const UMinimapSubsystem* Map = GetWorld() ? GetWorld()->GetSubsystem<UMinimapSubsystem>() : nullptr;
	return (Menu && Menu->IsMenuOpen()) || (Map && Map->IsFullMapOpen()) || UCambridgeLaunchSubsystem::IsLaunchMenuOpen(this);
}

bool UTimeTrialSubsystem::OnKeyDown(const FKey& K)
{
	if (IsUIBlocking())
	{
		return false;
	}
	const bool bEnter = K == EKeys::Enter;
	const bool bPadA = K == EKeys::Gamepad_FaceButton_Bottom;
	// leave (hold) during an event: gamepad B is shift up while driving, so the pad uses D-pad up;
	// on the results B is "free roam" (no driving there)
	const bool bLeave = K == EKeys::BackSpace || K == EKeys::Gamepad_DPad_Up;
	const bool bBack = K == EKeys::BackSpace || K == EKeys::Gamepad_FaceButton_Right;
	const bool bReset = K == EKeys::R || K == EKeys::Gamepad_FaceButton_Top || K == EKeys::Gamepad_DPad_Down;
	const double RealNow = FPlatformTime::Seconds();
	switch (State)
	{
	case ETimeTrialState::FreeRoam:
		return (bEnter || bPadA) && OnConfirm(bPadA);
	case ETimeTrialState::Countdown:
	case ETimeTrialState::Running:
		if (bReset || bEnter)
		{
			if (RestartHeldSince < 0.0)
			{
				RestartHeldSince = RealNow;
				HoldLabel = LOCTEXT("HoldRestart", "RESTART EVENT");
			}
			return true;
		}
		if (bLeave)
		{
			if (LeaveHeldSince < 0.0)
			{
				LeaveHeldSince = RealNow;
				HoldLabel = LOCTEXT("HoldLeave", "LEAVE EVENT");
			}
			return true;
		}
		return false;
	case ETimeTrialState::Finished:
		if (IsAnyOf(K, { EKeys::Left, EKeys::Gamepad_DPad_Left, EKeys::Gamepad_LeftStick_Left, EKeys::Up, EKeys::Gamepad_DPad_Up }))
		{
			ResultsFocus = (ResultsFocus + 2) % 3;
			PlayUISound(TEXT("ui_select"), 0.8f);
			return true;
		}
		if (IsAnyOf(K, { EKeys::Right, EKeys::Gamepad_DPad_Right, EKeys::Gamepad_LeftStick_Right, EKeys::Down, EKeys::Gamepad_DPad_Down, EKeys::Tab }))
		{
			ResultsFocus = (ResultsFocus + 1) % 3;
			PlayUISound(TEXT("ui_select"), 0.8f);
			return true;
		}
		{
			// every button that leaves the results is armed ResultsArmSeconds after the line: A is the handbrake, B is
			// shift up and R is "back on track" while driving, so a press of them just after the finish must not throw
			// the results away (the key is still taken, so it doesn't shift / reset either)
			const bool bArmed = Now() - FinishedAt >= ResultsArmSeconds;
			const int32 Choice = (bEnter || bPadA) ? ResultsFocus : K == EKeys::R ? 0 : K == EKeys::N ? 1 : bBack ? 2 : -1;
			if (Choice >= 0)
			{
				if (bArmed) { ActivateResult(Choice); }
				return true;
			}
		}
		if (K == EKeys::Gamepad_FaceButton_Top) { return true; }   // Y (back on track while racing) does nothing here
		return false;
	}
	return false;
}

bool UTimeTrialSubsystem::OnKeyUp(const FKey& K)
{
	const bool bReset = K == EKeys::R || K == EKeys::Gamepad_FaceButton_Top || K == EKeys::Gamepad_DPad_Down;
	const bool bRestartKey = bReset || K == EKeys::Enter;
	const bool bBack = K == EKeys::BackSpace || K == EKeys::Gamepad_DPad_Up;
	const double RealNow = FPlatformTime::Seconds();
	bool bUsed = false;
	if (bRestartKey && RestartHeldSince >= 0.0)
	{
		// a short R press is "back on track"; holding it restarts (done in Tick)
		if (bReset && RealNow - RestartHeldSince < TapSeconds)
		{
			ResetToLastGate();
		}
		RestartHeldSince = -1.0;
		bUsed = true;
	}
	if (bBack && LeaveHeldSince >= 0.0)
	{
		LeaveHeldSince = -1.0;
		bUsed = true;
	}
	return bUsed;
}

float UTimeTrialSubsystem::GetHoldFraction() const
{
	const double Since = RestartHeldSince >= 0.0 ? RestartHeldSince : LeaveHeldSince;
	if (Since < 0.0 || !IsInEvent() || State == ETimeTrialState::Finished)
	{
		return 0.0f;
	}
	return float(FMath::Clamp((FPlatformTime::Seconds() - Since) / HoldSeconds, 0.0, 1.0));
}

bool UTimeTrialSubsystem::OnConfirm(bool bGamepadA)
{
	switch (State)
	{
	case ETimeTrialState::FreeRoam:
		if (NearMarker >= 0)
		{
			// gamepad A is also the handbrake: only start when the car is (nearly) stopped in the box
			const AImprezaSTi* Car = GetCar();
			if (bGamepadA && Car && FMath::Abs(Car->GetChaosVehicleMovement()->GetForwardSpeed()) * 0.036f > StartMaxKmh)
			{
				return false;
			}
			StartEvent(NearMarker);
			return true;
		}
		return false;
	case ETimeTrialState::Finished:
		if (Now() - FinishedAt >= ResultsArmSeconds) { ActivateResult(ResultsFocus); }
		return true;
	default:
		return false;         // during an event: restart is a hold (OnKeyDown / the wheel code in Tick)
	}
}

void UTimeTrialSubsystem::ActivateResult(int32 Choice)
{
	if (State != ETimeTrialState::Finished || !Tracks.IsValidIndex(Active))
	{
		return;
	}
	PlayUISound(TEXT("ui_confirm"));
	if (AImprezaSTi* Car = GetCar())
	{
		Car->DoBrake(0.0f);     // release the results-screen brake (Tick holds it while the results are up)
		Car->GetChaosVehicleMovement()->SetHandbrakeInput(false);
	}
	switch (Choice)
	{
	case 0: StartEvent(Active); break;
	case 1: StartEvent((Active + 1) % Tracks.Num()); break;
	default: EndEvent(); break;
	}
}

// ------------------------------------------------------------------ event flow

void UTimeTrialSubsystem::StartEvent(int32 TrackIndex)
{
	AImprezaSTi* Car = GetCar();
	if (!Car || !Tracks.IsValidIndex(TrackIndex))
	{
		return;
	}
	Active = TrackIndex;
	const FTimeTrialTrack& T = Tracks[Active];
	// onto the grid, stopped, in first gear, parked for the countdown (revving is allowed)
	Car->SetActorTransform(FTransform(FRotator(0.0f, T.StartYaw, 0.0f), T.StartLocation), false, nullptr, ETeleportType::TeleportPhysics);
	Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
	Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	Car->SnapCamera();
	UChaosWheeledVehicleMovementComponent* Move = Car->GetChaosVehicleMovement();
	Move->SetParked(true);
	if (!Car->bAutoShift)
	{
		Move->SetTargetGear(1, true);
	}
	// a start across the map (NEXT EVENT, cr.TT.Start): World Partition streams the cells around the car, which is now
	// far from where they were loaded. Until the road under the grid is in, the car would fall through: ask the engine
	// for a blocking streaming flush (done next frame by UGameEngine::Tick, outside the world tick), and hold the car on
	// the grid with the countdown not started until the ground is there (Tick). A start nearby is already loaded.
	float GridZ;
	bAwaitGround = !GroundZ(T.StartLocation, GridZ);
	if (bAwaitGround)
	{
		AwaitGroundSince = FPlatformTime::Seconds();
		GetWorld()->bRequestedBlockOnAsyncLoading = true;
		UE_LOG(LogTimeTrial, Display, TEXT("event %s: the grid isn't streamed in yet, loading before the countdown"), *T.Name);
	}
	for (ATimeTrialGate* M : Markers)
	{
		if (M) { M->SetActorHiddenInGame(true); }
	}
	State = ETimeTrialState::Countdown;
	StateStart = Now();
	// flattened gate order: start line, then each lap's gates ending on the line (circuits)
	Route.Reset();
	Route.Add(0);
	for (int32 L = 0; L < (T.bCircuit ? T.Laps : 1); ++L)
	{
		for (int32 g = 1; g < T.Gates.Num(); ++g) { Route.Add(g); }
		if (T.bCircuit) { Route.Add(0); }
	}
	RouteIndex = 0;
	Lap = 1;
	Splits.Reset();
	LapTimes.Reset();
	LastSplitShown = -100.0;
	LastPassAt = -100.0;
	LastPassEntry = -1;
	CalloutAt = -100.0;
	bNewBest = false;
	ResultsFocus = 0;
	RestartHeldSince = LeaveHeldSince = -1.0;
	LastBeep = -1;
	bWrongWay = bMissed = false;
	WrongWayTimer = 0.0f;
	PreviewUntil = -100.0;
	double BestTotal;
	GhostSplits = BestSplits(T, BestTotal);
	ClearResults();
	LastCarLocation = Car->GetActorLocation();
	bResetHold = false;
	BuildRoute();
	for (int32& E : PoolEntry) { E = -1; }
	ShowGates();
	if (RacingLine) { RacingLine->Destroy(); RacingLine = nullptr; }
	const UCambridgeGameUserSettings* Settings = UCambridgeGameUserSettings::Get();
	if (T.Line.Num() > 1 && (!Settings || Settings->RacingLineMode > 0))
	{
		RacingLine = GetWorld()->SpawnActor<ARacingLineActor>(FVector::ZeroVector, FRotator::ZeroRotator);
		RacingLine->Build(T.Line, T.bCircuit);
	}
	UE_LOG(LogTimeTrial, Display, TEXT("event %s: %d gates, %d lap(s), route %.0f m"), *T.Name, T.Gates.Num(), T.Laps, RouteS.Num() ? RouteS.Last() / 100.0f : 0.0f);
}

void UTimeTrialSubsystem::EndEvent()
{
	if (AImprezaSTi* Car = GetCar())
	{
		Car->GetChaosVehicleMovement()->SetParked(false);
	}
	for (ATimeTrialGate* G : Gates)
	{
		if (G) { G->SetActorHiddenInGame(true); }
	}
	if (RacingLine) { RacingLine->Destroy(); RacingLine = nullptr; }
	bResetHold = false;
	bAwaitGround = false;
	RestartHeldSince = LeaveHeldSince = -1.0;
	bWrongWay = bMissed = false;
	for (ATimeTrialGate* M : Markers)
	{
		if (M) { M->SetActorHiddenInGame(false); }
	}
	State = ETimeTrialState::FreeRoam;
	Active = -1;
	ClearResults();
	UE_LOG(LogTimeTrial, Display, TEXT("back to free roam"));
}

void UTimeTrialSubsystem::ShowGates()
{
	// pool of 4: the next gate (bright), the two after it (dimmed) and the one just passed (flashing)
	if (Gates.Num() < 4)
	{
		for (int32 i = Gates.Num(); i < 4; ++i)
		{
			FActorSpawnParameters P;
			P.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			ATimeTrialGate* G = GetWorld()->SpawnActor<ATimeTrialGate>(FVector::ZeroVector, FRotator::ZeroRotator, P);
			G->SetActorHiddenInGame(true);
			Gates.Add(G);
		}
	}
	const FTimeTrialTrack& T = Tracks[Active];
	const int32 Base = RouteIndex - 1;
	for (int32 p = 0; p < 4; ++p)
	{
		ATimeTrialGate* G = Gates[p];
		const int32 E = Base + ((p - Base) % 4 + 4) % 4;       // the entry in [RouteIndex - 1, RouteIndex + 2] this slot shows
		const bool bFlashing = E == LastPassEntry && PoolEntry[p] == E && Now() - LastPassAt < PassFlashSeconds;
		if (!G || !Route.IsValidIndex(E) || (E < RouteIndex && !bFlashing))
		{
			if (G) { G->SetActorHiddenInGame(true); }
			continue;
		}
		if (PoolEntry[p] != E)
		{
			const FTimeTrialGateDef& D = T.Gates[Route[E]];
			// the start / lap / finish line is a checkered arch; everything else a pair of pylons
			const bool bLine = T.bCircuit ? Route[E] == 0 : (E == 0 || E == Route.Num() - 1);
			FVector At = D.Location;
			float Z;
			if (GroundZ(At, Z)) { At.Z = Z; }      // sit on the road (gates are authored at z = 0)
			G->SetActorLocationAndRotation(At, FRotator(0.0f, D.Yaw, 0.0f));
			G->Configure(D.Width, bLine ? EGateKind::Finish : EGateKind::Checkpoint);
			PoolEntry[p] = E;
		}
		G->SetActorHiddenInGame(false);
		if (E >= RouteIndex)
		{
			G->SetRank(E - RouteIndex);
		}
	}
}

void UTimeTrialSubsystem::TickGates()
{
	// pass flash on the gate just driven through, then hide it
	if (LastPassEntry < 0 || Gates.Num() < 4)
	{
		return;
	}
	const int32 Slot = LastPassEntry % 4;
	if (PoolEntry[Slot] != LastPassEntry || !Gates[Slot])
	{
		return;
	}
	const double Age = Now() - LastPassAt;
	if (Age < PassFlashSeconds)
	{
		Gates[Slot]->SetPassFlash(1.0f - float(Age / PassFlashSeconds));
	}
	else
	{
		Gates[Slot]->SetPassFlash(0.0f);
		Gates[Slot]->SetActorHiddenInGame(true);
		PoolEntry[Slot] = -1;
		LastPassEntry = -1;
	}
}

bool UTimeTrialSubsystem::CrossedGate(const FTimeTrialGateDef& Gate, const FVector& From, const FVector& To) const
{
	// 2D segment intersection between the car's motion this frame and the gate line (across the road at the gate)
	const FVector2D Dir(FMath::Cos(FMath::DegreesToRadians(Gate.Yaw)), FMath::Sin(FMath::DegreesToRadians(Gate.Yaw)));
	const FVector2D Side(-Dir.Y, Dir.X);
	const FVector2D C(Gate.Location);
	constexpr float Forgiveness = 150.0f;            // a little past the road edge / the posts
	const float A = FVector2D::DotProduct(FVector2D(From) - C, Dir);
	const float B = FVector2D::DotProduct(FVector2D(To) - C, Dir);
	if (!(A < 0.0f && B >= 0.0f))       // must cross forwards
	{
		return false;
	}
	const float T = A / (A - B);
	const FVector2D Hit = FVector2D(From) + (FVector2D(To) - FVector2D(From)) * T;
	const float Lateral = FVector2D::DotProduct(Hit - C, Side);   // (Side = the right of the gate)
	return Lateral >= -Gate.TriggerLeft - Forgiveness && Lateral <= Gate.TriggerRight + Forgiveness;
}

void UTimeTrialSubsystem::PassGate()
{
	const FTimeTrialTrack& T = Tracks[Active];
	const double RunTime = Now() - StateStart;
	const bool bLast = RouteIndex == Route.Num() - 1;
	LastPassAt = Now();
	LastPassEntry = RouteIndex;
	bMissed = false;
	FName Sound = TEXT("ui_checkpoint");
	if (RouteIndex > 0)    // the first crossing is the start line: no split
	{
		Splits.Add(RunTime);
		LastSplitIndex = Splits.Num();
		LastSplitTime = RunTime;
		bLastSplitHasBest = GhostSplits.IsValidIndex(Splits.Num() - 1);
		LastSplitDelta = bLastSplitHasBest ? RunTime - GhostSplits[Splits.Num() - 1] : 0.0;
		LastSplitShown = Now();
		if (bLastSplitHasBest && LastSplitDelta <= 0.0) { Sound = TEXT("ui_checkpoint_ahead"); }
		if (T.bCircuit && Route[RouteIndex] == 0)     // lap line
		{
			double Previous = 0.0;
			for (double L : LapTimes) { Previous += L; }
			const double LapTime = RunTime - Previous;
			bool bFastest = LapTimes.Num() > 0;
			for (double L : LapTimes) { bFastest &= LapTime < L; }
			LapTimes.Add(LapTime);
			Lap = FMath::Min(Lap + 1, T.Laps);
			if (!bLast)
			{
				const bool bFinalLap = Lap == T.Laps;
				CalloutTitle = bFinalLap ? LOCTEXT("FinalLap", "FINAL LAP") : FText::Format(LOCTEXT("LapN", "LAP {0}/{1}"), Lap, T.Laps);
				CalloutBody = FText::FromString(FString::Printf(TEXT("Lap %d  %s%s"), LapTimes.Num(), *FormatTime(LapTime), bFastest ? TEXT("  -  fastest lap") : TEXT("")));
				bCalloutGold = bFastest;
				CalloutAt = Now();
				Sound = bFinalLap ? TEXT("ui_final_lap") : TEXT("ui_lap");
			}
		}
	}
	UE_LOG(LogTimeTrial, Display, TEXT("gate %d/%d (track gate %d) at %.3f s, %.0f km/h%s"), RouteIndex, Route.Num() - 1, Route[RouteIndex], RunTime,
		GetCar() ? GetCar()->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f : 0.0f,
		bLastSplitHasBest && RouteIndex > 0 ? *FString::Printf(TEXT(", %s vs best"), *Signed(LastSplitDelta)) : TEXT(""));
	if (bLast)
	{
		Finish();
		return;
	}
	PlayUISound(Sound);
	++RouteIndex;
	ShowGates();
}

void UTimeTrialSubsystem::FinishForTest()
{
	if (State == ETimeTrialState::Running && Tracks.IsValidIndex(Active))
	{
		UE_LOG(LogTimeTrial, Display, TEXT("test: finishing %s now (not saved)"), *Tracks[Active].Name);
		bFinishForTest = true;
		Finish();
		bFinishForTest = false;
	}
}

void UTimeTrialSubsystem::Finish()
{
	const FTimeTrialTrack& T = Tracks[Active];
	FinishTime = Now() - StateStart;
	State = ETimeTrialState::Finished;
	// keep the previous best for the results screen before it is overwritten
	PreviousBestSplits = BestSplits(T, PreviousBest);
	// compared in whole milliseconds: the best is stored with 3 decimals, so an identical run (e.g. 50.7167 s vs the
	// saved "50.717") must not count as a new best
	bNewBest = PreviousBest <= 0.0 || FMath::RoundToInt64(FinishTime * 1000.0) < FMath::RoundToInt64(PreviousBest * 1000.0);
	FinishedAt = Now();
	ResultsFocus = 0;
	bWrongWay = bMissed = false;
	RestartHeldSince = LeaveHeldSince = -1.0;
	if (bNewBest && !bFinishForTest)
	{
		TArray<FString> Parts;
		for (double S : Splits) { Parts.Add(FString::Printf(TEXT("%.3f"), S)); }
		BestRuns.Add(T.Id, FString::Printf(TEXT("%.3f;"), FinishTime) + FString::Join(Parts, TEXT(",")));
		BestTimeCache.Reset();
		SaveConfig();
		if (GConfig) { GConfig->Flush(false, GGameIni); }   // on disk now, not only at a clean exit (Config/DefaultGame.ini whitelists the section)
		// (-benchmark / -noini detach Game.ini: nothing is written in those test runs, see FEngineLoop::Init)
		UE_LOG(LogTimeTrial, Display, TEXT("best run saved to %s%s"), *GGameIni, FApp::IsBenchmarking() ? TEXT(" (NOT on disk: -benchmark)") : TEXT(""));
	}
	// the finish arch flashes (TickGates), every other gate goes
	for (int32 p = 0; p < Gates.Num(); ++p)
	{
		if (Gates[p] && PoolEntry[p] != LastPassEntry) { Gates[p]->SetActorHiddenInGame(true); PoolEntry[p] = -1; }
	}
	PlayUISound(TEXT("ui_finish"));
	if (bNewBest) { PlayUISound(TEXT("ui_new_best"), 0.8f); }
	ShowResults();
	UE_LOG(LogTimeTrial, Display, TEXT("event %s finished in %s%s"), *T.Name, *FormatTime(FinishTime), bNewBest ? TEXT(" (new best)") : TEXT(""));
}

// ------------------------------------------------------------------ route along the racing line

void UTimeTrialSubsystem::BuildRoute()
{
	const FTimeTrialTrack& T = Tracks[Active];
	LinePts.Reset();
	LineS.Reset();
	RouteS.Reset();
	for (const FVector4& P : T.Line) { LinePts.Add(FVector2D(P.X, P.Y)); }
	if (LinePts.Num() < 2)
	{
		for (const FTimeTrialGateDef& G : T.Gates) { LinePts.Add(FVector2D(G.Location)); }
	}
	if (T.bCircuit) { const FVector2D First = LinePts[0]; LinePts.Add(First); }   // (not Add(LinePts[0]): aliasing check)
	float S = 0.0f;
	for (int32 i = 0; i < LinePts.Num(); ++i)
	{
		if (i > 0) { S += FVector2D::Distance(LinePts[i - 1], LinePts[i]); }
		LineS.Add(S);
	}
	LapLength = FMath::Max(S, 1.0f);
	// each gate's distance along the line: nearest point, searched forward from the previous gate
	TArray<float> GateS;
	GateS.Add(0.0f);
	for (int32 g = 1; g < T.Gates.Num(); ++g)
	{
		const FVector2D P(T.Gates[g].Location);
		float BestD = MAX_flt, BestS = GateS.Last();
		for (int32 i = 0; i + 1 < LinePts.Num(); ++i)
		{
			if (LineS[i + 1] < GateS.Last() - 1000.0f) { continue; }
			const FVector2D A = LinePts[i], AB = LinePts[i + 1] - A;
			const double Len2 = FMath::Max(AB.SizeSquared(), 1.0);
			const double U = FMath::Clamp(FVector2D::DotProduct(P - A, AB) / Len2, 0.0, 1.0);
			const float D = FVector2D::Distance(P, A + AB * U);
			if (D < BestD) { BestD = D; BestS = LineS[i] + (LineS[i + 1] - LineS[i]) * U; }
		}
		GateS.Add(BestS);
	}
	int32 L = 0;
	for (int32 k = 0; k < Route.Num(); ++k)
	{
		if (k > 0 && T.bCircuit && Route[k] == 0)
		{
			++L;
			RouteS.Add(L * LapLength);
		}
		else
		{
			RouteS.Add(L * LapLength + GateS[Route[k]]);
		}
	}
	CarRouteS = -ATimeTrialGate::GridOffsetCm;
	CarLineDist = 0.0f;
}

void UTimeTrialSubsystem::RoutePoint(float InS, FVector2D& OutPoint, FVector2D& OutDir) const
{
	if (LinePts.Num() < 2)
	{
		OutPoint = FVector2D::ZeroVector;
		OutDir = FVector2D(1.0, 0.0);
		return;
	}
	float S = FMath::Max(InS, 0.0f);
	S = Tracks[Active].bCircuit ? FMath::Fmod(S, LapLength) : FMath::Min(S, LapLength);
	int32 i = FMath::Clamp(Algo::UpperBound(LineS, S) - 1, 0, LinePts.Num() - 2);
	const float Seg = FMath::Max(LineS[i + 1] - LineS[i], 1.0f);
	const double U = FMath::Clamp((S - LineS[i]) / Seg, 0.0f, 1.0f);
	OutPoint = LinePts[i] + (LinePts[i + 1] - LinePts[i]) * U;
	OutDir = (LinePts[i + 1] - LinePts[i]).GetSafeNormal();
}

void UTimeTrialSubsystem::UpdateRouteProgress(const FVector& Loc, const FVector& Forward, float SpeedKmh, float DeltaTime)
{
	if (LinePts.Num() < 2 || !RouteS.IsValidIndex(RouteIndex))
	{
		return;
	}
	const FTimeTrialTrack& T = Tracks[Active];
	const FVector2D P(Loc);
	// search a window around the expected position (from the last gate to a bit past the next one), so the
	// projection cannot jump to another part of the route that runs close by (out-and-back streets, laps)
	const float Next = RouteS[RouteIndex];
	const float Prev = RouteIndex > 0 ? RouteS[RouteIndex - 1] : -ATimeTrialGate::GridOffsetCm;
	const float Lo = FMath::Min(Prev, CarRouteS) - 3000.0f, Hi = Next + 8000.0f;
	double BestD2 = TNumericLimits<double>::Max();
	float BestS = CarRouteS;
	FVector2D BestDir = CarLineDir;
	const int32 NumLaps = T.bCircuit ? T.Laps : 1;
	for (int32 L = 0; L < NumLaps; ++L)
	{
		const float Off = L * LapLength;
		if (Off + LapLength < Lo || Off > Hi) { continue; }
		// only the segments inside the window (binary search for the first): ~40 per frame however long the route
		for (int32 i = FMath::Max(Algo::LowerBound(LineS, Lo - Off) - 1, 0); i + 1 < LinePts.Num(); ++i)
		{
			const float S0 = Off + LineS[i], S1 = Off + LineS[i + 1];
			if (S0 > Hi) { break; }
			if (S1 < Lo) { continue; }
			const FVector2D A = LinePts[i], AB = LinePts[i + 1] - A;
			const double Len2 = AB.SizeSquared();
			if (Len2 < 1.0) { continue; }
			const double U = FMath::Clamp(FVector2D::DotProduct(P - A, AB) / Len2, 0.0, 1.0);
			const double D2 = FVector2D::DistSquared(P, A + AB * U);
			if (D2 < BestD2)
			{
				BestD2 = D2;
				BestS = S0 + (S1 - S0) * U;
				BestDir = AB / FMath::Sqrt(Len2);
			}
		}
	}
	if (BestD2 == TNumericLimits<double>::Max())
	{
		return;
	}
	CarRouteS = BestS;
	CarLineDist = FMath::Sqrt(BestD2);
	CarLineDir = BestDir;

	// WRONG WAY: facing against the route and driving forwards for a moment (reversing is fine)
	const bool bBackwards = SpeedKmh > 8.0f && CarLineDist < 3000.0f && FVector2D::DotProduct(FVector2D(Forward).GetSafeNormal(), CarLineDir) < -0.35f;
	WrongWayTimer = bBackwards ? FMath::Min(WrongWayTimer + DeltaTime, 3.0f) : FMath::Max(WrongWayTimer - 2.0f * DeltaTime, 0.0f);
	if (!bWrongWay && WrongWayTimer > 1.2f)
	{
		bWrongWay = true;
		PlayUISound(TEXT("ui_wrong_way"));
		UE_LOG(LogTimeTrial, Display, TEXT("WRONG WAY at route %.0f m"), CarRouteS / 100.0f);
	}
	else if (bWrongWay && WrongWayTimer < 0.4f)
	{
		bWrongWay = false;
	}
	// missed checkpoint: past the next gate along the route without having crossed it
	if (!bMissed && CarRouteS > Next + MissedPastCm)
	{
		bMissed = true;
		PlayUISound(TEXT("ui_missed"));
		UE_LOG(LogTimeTrial, Display, TEXT("missed checkpoint %d (%.0f m past it, %.0f m off the line)"), RouteIndex, (CarRouteS - Next) / 100.0f, CarLineDist / 100.0f);
	}
	else if (bMissed && CarRouteS < Next - 500.0f)
	{
		bMissed = false;      // turned back before it
	}
}

float UTimeTrialSubsystem::GhostRouteS(double RaceTime) const
{
	// the best run at the same race time: linear between its splits (start on the grid at t = 0)
	double T0 = 0.0;
	float S0 = -ATimeTrialGate::GridOffsetCm;
	for (int32 k = 1; k < RouteS.Num() && GhostSplits.IsValidIndex(k - 1); ++k)
	{
		const double T1 = GhostSplits[k - 1];
		const float S1 = RouteS[k];
		if (RaceTime <= T1)
		{
			return T1 > T0 ? FMath::Lerp(S0, S1, float((RaceTime - T0) / (T1 - T0))) : S1;
		}
		T0 = T1;
		S0 = S1;
	}
	return RouteS.Num() ? RouteS.Last() : 0.0f;
}

bool UTimeTrialSubsystem::GetRouteBar(FTimeTrialRouteBar& Out) const
{
	if (!IsInEvent() || RouteS.Num() < 2 || !Tracks.IsValidIndex(Active))
	{
		return false;
	}
	const float Total = FMath::Max(RouteS.Last(), 1.0f);
	const FTimeTrialTrack& T = Tracks[Active];
	Out.Checkpoints.Reset();
	Out.LapLines.Reset();
	for (int32 k = 1; k < RouteS.Num(); ++k)
	{
		Out.Checkpoints.Add(RouteS[k] / Total);
		if (T.bCircuit && Route[k] == 0 && k < RouteS.Num() - 1) { Out.LapLines.Add(RouteS[k] / Total); }
	}
	Out.Passed = Splits.Num();
	const float Car = State == ETimeTrialState::Finished ? Total : (State == ETimeTrialState::Countdown ? 0.0f : CarRouteS);
	Out.Car = FMath::Clamp(Car / Total, 0.0f, 1.0f);
	Out.Ghost = State == ETimeTrialState::Running && GhostSplits.Num() > 0 ? FMath::Clamp(GhostRouteS(Now() - StateStart) / Total, 0.0f, 1.0f) : -1.0f;
	return true;
}

bool UTimeTrialSubsystem::GetNextGate(FVector& OutLocation, bool& bOutFinish) const
{
	if ((State != ETimeTrialState::Running && State != ETimeTrialState::Countdown) || !Route.IsValidIndex(RouteIndex) || !Tracks.IsValidIndex(Active))
	{
		return false;
	}
	OutLocation = Tracks[Active].Gates[Route[RouteIndex]].Location;
	bOutFinish = RouteIndex == Route.Num() - 1;
	return true;
}

// ------------------------------------------------------------------ tick

void UTimeTrialSubsystem::Tick(float DeltaTime)
{
	AttachHUD();
	AImprezaSTi* Car = GetCar();
	if (!Car)
	{
		return;
	}
	const FVector Loc = Car->GetActorLocation();
	const float SpeedKmh = Car->GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f;

	// the home-built wheel has no start button: both paddles together are its start - Enter in the start box and on
	// the results; during an event they work like R - a tap = back on track, hold 1 s to restart. A start button, if
	// one is ever added, does the same.
	// (a menu over the game has the wheel's buttons: the launch menu runs unpaused, so this tick still runs under it)
	if (UCambridgeWheelSubsystem* Wheel = UCambridgeWheelSubsystem::Get(this); Wheel && Wheel->IsActive() && !IsUIBlocking())
	{
		const FWheelInputState S = Wheel->GetState();
		const bool bStartEdge = Wheel->ConsumeStart();            // rising edge: catches a press shorter than a frame
		const bool bPaddles = S.bUpshift && S.bDownshift;
		const bool bPressed = bStartEdge || (bPaddles && !bBothPaddlesHeld);
		const bool bDown = S.bStart || bPaddles;
		bBothPaddlesHeld = bPaddles;
		if (State == ETimeTrialState::Countdown || State == ETimeTrialState::Running)
		{
			const double WheelNow = FPlatformTime::Seconds();
			if (bPressed && !bWheelHold && !IsUIBlocking())
			{
				bWheelHold = true;
				bWheelHoldIsStart = bStartEdge || S.bStart;
				UE_LOG(LogTimeTrial, Display, TEXT("wheel: %s down (hold to restart)"), bWheelHoldIsStart ? TEXT("start button") : TEXT("both paddles"));
				if (RestartHeldSince < 0.0)
				{
					RestartHeldSince = WheelNow;
					HoldLabel = LOCTEXT("HoldRestartWheel", "RESTART EVENT");
				}
			}
			if (bWheelHold && !bDown)
			{
				bWheelHold = false;
				if (RestartHeldSince >= 0.0)
				{
					const bool bTap = WheelNow - RestartHeldSince < TapSeconds;
					UE_LOG(LogTimeTrial, Display, TEXT("wheel: released after %.2f s -> %s"), WheelNow - RestartHeldSince,
						bTap ? TEXT("back on track") : TEXT("nothing (released before the hold)"));
					if (bTap)
					{
						ResetToLastGate();
					}
					RestartHeldSince = -1.0;
				}
			}
		}
		else if (State == ETimeTrialState::Finished)
		{
			// results: one paddle moves the focus (AImprezaSTi leaves the paddles alone while the results are up), both
			// tapped (the wheel's start) press it; armed ResultsArmSeconds after the line, like the keys
			bWheelHold = false;
			const EWheelMenuAction Action = Wheel->ConsumeMenuAction();
			if (Now() - FinishedAt >= ResultsArmSeconds && (Action == EWheelMenuAction::Up || Action == EWheelMenuAction::Down))
			{
				ResultsFocus = (ResultsFocus + (Action == EWheelMenuAction::Down ? 1 : 2)) % 3;
				PlayUISound(TEXT("ui_select"), 0.8f);
			}
			if (bStartEdge || Action == EWheelMenuAction::Go)
			{
				UE_LOG(LogTimeTrial, Display, TEXT("wheel: confirm (results)"));
				OnConfirm();
			}
		}
		else
		{
			bWheelHold = false;
			if (bPressed)
			{
				UE_LOG(LogTimeTrial, Display, TEXT("wheel: confirm (free roam)"));
				OnConfirm();
			}
		}
	}

	// held keys: restart / leave the event after a 1 s hold
	const double RealNow = FPlatformTime::Seconds();
	if (IsUIBlocking())
	{
		// the menu (also opened on focus loss) or the map swallows the key-up: a hold must not fire after it closes
		RestartHeldSince = LeaveHeldSince = -1.0;
	}
	else if (IsInEvent() && State != ETimeTrialState::Finished)
	{
		if (RestartHeldSince >= 0.0 && RealNow - RestartHeldSince >= HoldSeconds)
		{
			RestartHeldSince = -1.0;
			UE_LOG(LogTimeTrial, Display, TEXT("hold: restart"));
			StartEvent(Active);
		}
		else if (LeaveHeldSince >= 0.0 && RealNow - LeaveHeldSince >= HoldSeconds)
		{
			LeaveHeldSince = -1.0;
			UE_LOG(LogTimeTrial, Display, TEXT("hold: leave"));
			EndEvent();
		}
	}

	// test mode: -TimeTrialAuto=<track id> starts that event after 2 s and drives it (pure pursuit)
	if (!AutoTrack.IsEmpty())
	{
		Autopilot(Car);
	}
	if (ResetTestIndex >= 0)
	{
		TickResetTest(Car);
	}

	switch (State)
	{
	case ETimeTrialState::FreeRoam:
	{
		NearMarker = -1;
		HintMarker = -1;
		float Best = HintRadiusCm;
		for (int32 i = 0; i < Tracks.Num(); ++i)
		{
			const FTimeTrialTrack& Tr = Tracks[i];
			const float D = FMath::Min(FVector::Dist2D(Loc, Tr.Gates[0].Location), FVector::Dist2D(Loc, Tr.StartLocation));
			// in the start box (its lane, a car length of slack): the start prompt
			if (NearMarker < 0 && D < MarkerRadiusCm)
			{
				const FVector2D Rel(Loc - Tr.Gates[0].Location);
				const FVector2D F(FMath::Cos(FMath::DegreesToRadians(Tr.Gates[0].Yaw)), FMath::Sin(FMath::DegreesToRadians(Tr.Gates[0].Yaw)));
				const FVector2D Local(FVector2D::DotProduct(Rel, F), FVector2D::CrossProduct(F, Rel));
				const FVector2D Half = ATimeTrialGate::StartZoneHalf();
				if (FMath::Abs(Local.X - Tr.StartLocal.X) < Half.X && FMath::Abs(Local.Y - Tr.StartLocal.Y) < Half.Y)
				{
					NearMarker = i;
				}
			}
			if (D < Best)
			{
				Best = D;
				HintMarker = i;
				HintDistanceM = D / 100.0f;
			}
			// drop the start gantry + box onto the road once the car is near enough for its cell to be loaded
			float Z;
			if (D < HintRadiusCm && MarkerGrounded.IsValidIndex(i) && !MarkerGrounded[i] && Markers.IsValidIndex(i) && Markers[i] && GroundZ(Tracks[i].Gates[0].Location, Z))
			{
				MarkerGrounded[i] = true;
				FVector L = Markers[i]->GetActorLocation();
				L.Z = Z;
				Markers[i]->SetActorLocation(L);
				UE_LOG(LogTimeTrial, Display, TEXT("start marker %s on the road at z = %.1f cm"), *Tracks[i].Name, Z);
			}
		}
		// start markers near the car breathe so they catch the eye; the one you're in glows brighter
		// (the far ones sit at a steady glow: no per-frame material updates for markers nobody sees)
		for (int32 i = 0; i < Markers.Num() && i < Tracks.Num(); ++i)
		{
			if (Markers[i])
			{
				const bool bNear = FVector::Dist2D(Loc, Tracks[i].Gates[0].Location) < HintRadiusCm;
				const float Pulse = bNear ? 0.8f + 0.2f * FMath::Sin(Now() * 3.0 + i) : 1.0f;
				Markers[i]->SetGlowScale(i == NearMarker ? 1.5f : Pulse);
			}
		}
		break;
	}
	case ETimeTrialState::Countdown:
	{
		if (bAwaitGround)
		{
			const FTimeTrialTrack& T = Tracks[Active];
			float Z = 0.0f;
			const bool bLoaded = GroundZ(T.StartLocation, Z);
			const double Waited = FPlatformTime::Seconds() - AwaitGroundSince;
			if (!bLoaded && Waited < 20.0)
			{
				// held on the grid (nothing to stand on yet), the countdown not started
				Car->SetActorTransform(FTransform(FRotator(0.0f, T.StartYaw, 0.0f), T.StartLocation), false, nullptr, ETeleportType::TeleportPhysics);
				Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
				Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
				StateStart = Now();
				LastBeep = -1;
				LastCarLocation = Car->GetActorLocation();
				break;
			}
			bAwaitGround = false;
			if (bLoaded)
			{
				// on the road (the grid is authored 60 cm above z = 0: only moved if the road is elsewhere)
				FVector At = Car->GetActorLocation();
				if (FMath::Abs(At.Z - (Z + 60.0)) > 30.0)
				{
					At = FVector(T.StartLocation.X, T.StartLocation.Y, Z + 60.0);
					Car->SetActorTransform(FTransform(FRotator(0.0f, T.StartYaw, 0.0f), At), false, nullptr, ETeleportType::TeleportPhysics);
					Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
				}
			}
			UE_LOG(LogTimeTrial, Display, TEXT("event %s: grid %s after %.2f s, countdown"), *T.Name, bLoaded ? TEXT("streamed in") : TEXT("STILL NOT LOADED (timeout)"), Waited);
			StateStart = Now();
			LastBeep = -1;
			LastCarLocation = Car->GetActorLocation();
		}
		const int32 Second = int32(Now() - StateStart);
		if (Second != LastBeep && Second < 3)
		{
			LastBeep = Second;
			PlayUISound(TEXT("ui_count"));
		}
		if (Now() - StateStart >= CountdownSeconds)
		{
			Car->GetChaosVehicleMovement()->SetParked(false);
			State = ETimeTrialState::Running;
			StateStart = Now();
			PlayUISound(TEXT("ui_go"));
		}
		break;
	}
	case ETimeTrialState::Running:
		if (bResetHold)
		{
			const int32 Second = int32(Now() - ResetHoldStart);
			if (Second != LastBeep && Second < 3)
			{
				LastBeep = Second;
				PlayUISound(TEXT("ui_count"), 0.8f);
			}
			if (Now() - ResetHoldStart >= ResetHoldSeconds)
			{
				bResetHold = false;
				ResetReleased = Now();
				Car->GetChaosVehicleMovement()->SetParked(false);
				PlayUISound(TEXT("ui_go"), 0.8f);
			}
		}
		else
		{
			if (const int32 HitchFrames = CVarTestHitchFrames.GetValueOnGameThread(); HitchFrames > 0)
			{
				if (TestHitchLeft > 0)
				{
					--TestHitchLeft;
					bTestHitchHold = true;     // (LastCarLocation stays put: the next check sees the whole move)
					break;
				}
				if (Now() >= TestHitchNext)
				{
					TestHitchNext = Now() + 3.0;
					TestHitchLeft = HitchFrames;
				}
			}
			// at most a few gates per frame (a long hitch at speed can carry the car through two)
			const int32 EntryBefore = RouteIndex;
			const float RouteSBefore = CarRouteS;
			for (int32 Guard = 0; Guard < 3 && State == ETimeTrialState::Running && CrossedGate(Tracks[Active].Gates[Route[RouteIndex]], LastCarLocation, Loc); ++Guard)
			{
				PassGate();
			}
			if (State == ETimeTrialState::Running && Now() >= PreviewUntil)
			{
				UpdateRouteProgress(Loc, Car->GetActorForwardVector(), SpeedKmh, DeltaTime);
				// a hitch (or > ~500 km/h) moves the car several metres in one frame: around a corner that straight
				// chord can miss a gate just after the apex although the car drove through it. Then count it from the
				// progress along the line: passed the gate this frame, and on the line within the gate's trigger.
				// (Normal frames are < 5 m and the segment test above is exact; a shortcut never gets here: away from
				// the line the progress moves on while the car is far from it.)
				if (State == ETimeTrialState::Running && RouteIndex == EntryBefore && RouteS.IsValidIndex(RouteIndex)
					&& FVector::Dist2D(LastCarLocation, Loc) > 500.0 && RouteSBefore < RouteS[RouteIndex] && CarRouteS >= RouteS[RouteIndex]
					&& CarLineDist <= FMath::Max(Tracks[Active].Gates[Route[RouteIndex]].TriggerLeft, Tracks[Active].Gates[Route[RouteIndex]].TriggerRight) + 150.0f)
				{
					UE_LOG(LogTimeTrial, Display, TEXT("checkpoint %d passed on a long frame (%.1f m moved, %.1f m off the line)"), RouteIndex,
						FVector::Dist2D(LastCarLocation, Loc) / 100.0, CarLineDist / 100.0f);
					bMissed = false;
					PassGate();
				}
			}
		}
		break;
	case ETimeTrialState::Finished:
		// the car pulls up behind the results window (and A, the brake, is the confirm button there). Brake to
		// a stop, then the handbrake: brake held at a standstill engages reverse on the automatic gearbox
		if (FMath::Abs(SpeedKmh) > 3.0f)
		{
			Car->DoBrake(1.0f);
		}
		else
		{
			Car->DoBrake(0.0f);
			Car->GetChaosVehicleMovement()->SetHandbrakeInput(true);
		}
		break;
	default:
		break;
	}
	if (IsInEvent())
	{
		TickGates();
	}
	if (NearMarker != LastNearMarker)
	{
		LastNearMarker = NearMarker;
		NearSince = Now();         // the start dialog animates in
	}
	if (RacingLine && (State == ETimeTrialState::Running || State == ETimeTrialState::Countdown))
	{
		const UCambridgeGameUserSettings* Settings = UCambridgeGameUserSettings::Get();
		const int32 Mode = Settings ? Settings->RacingLineMode : 2;
		RacingLine->SetActorHiddenInGame(Mode == 0);      // the menu can change it mid-event
		if (Mode > 0)
		{
			RacingLine->UpdateFor(Loc, SpeedKmh, Mode == 1);
		}
	}
	if (!bTestHitchHold)
	{
		LastCarLocation = Loc;
	}
	bTestHitchHold = false;
}

// ------------------------------------------------------------------ HUD

FText UTimeTrialSubsystem::GetEventTitle() const
{
	return Tracks.IsValidIndex(Active) && State != ETimeTrialState::FreeRoam ? FText::FromString(Tracks[Active].Name.ToUpper()) : FText::GetEmpty();
}

FText UTimeTrialSubsystem::GetTimerText() const
{
	switch (State)
	{
	case ETimeTrialState::Countdown: return FText::FromString(FormatTime(0.0));
	case ETimeTrialState::Running: return FText::FromString(FormatTime(Now() - StateStart));
	case ETimeTrialState::Finished: return FText::FromString(FormatTime(FinishTime));
	default: return FText::GetEmpty();
	}
}

FText UTimeTrialSubsystem::GetSpeedText() const
{
	const AImprezaSTi* Car = GetCar();
	return Car ? FText::AsNumber(FMath::RoundToInt(FMath::Abs(Car->GetChaosVehicleMovement()->GetForwardSpeed()) * 0.036f)) : FText::GetEmpty();
}

FText UTimeTrialSubsystem::GetGearText() const
{
	const AImprezaSTi* Car = GetCar();
	if (!Car) { return FText::GetEmpty(); }
	const int32 G = Car->GetChaosVehicleMovement()->GetCurrentGear();
	return FText::FromString(G < 0 ? TEXT("R") : G == 0 ? TEXT("N") : FString::FromInt(G));
}

float UTimeTrialSubsystem::GetRpmFraction() const
{
	const AImprezaSTi* Car = GetCar();
	return Car ? FMath::Clamp(Car->GetChaosVehicleMovement()->GetEngineRotationSpeed() / 8000.0f, 0.0f, 1.0f) : 0.0f;
}

FText UTimeTrialSubsystem::GetRpmText() const
{
	const AImprezaSTi* Car = GetCar();
	return Car ? FText::FromString(FString::FromInt(FMath::RoundToInt(Car->GetChaosVehicleMovement()->GetEngineRotationSpeed() / 10.0f) * 10)) : FText::GetEmpty();
}

float UTimeTrialSubsystem::GetBoostFraction() const
{
	const AImprezaSTi* Car = GetCar();
	return Car ? FMath::Clamp(Car->GetBoost(), 0.0f, 1.0f) : 0.0f;
}

FText UTimeTrialSubsystem::GetAssistShortText() const
{
	const AImprezaSTi* Car = GetCar();
	if (!Car) { return FText::GetEmpty(); }
	static const TCHAR* TC[] = { TEXT("TC OFF"), TEXT("TC SPORT"), TEXT("TC FULL") };
	return FText::FromString(FString::Printf(TEXT("%s   %s   ABS %s"), TC[FMath::Clamp((int32)Car->TractionControl, 0, 2)],
		Car->bAutoShift ? TEXT("AUTO") : TEXT("MANUAL"), Car->bABS ? TEXT("ON") : TEXT("OFF")));
}

FText UTimeTrialSubsystem::GetLapBadgeText() const
{
	if (!Tracks.IsValidIndex(Active)) { return FText::GetEmpty(); }
	const FTimeTrialTrack& T = Tracks[Active];
	return T.bCircuit ? FText::FromString(FString::Printf(TEXT("LAP %d/%d"), Lap, T.Laps)) : LOCTEXT("Sprint", "SPRINT");
}

FText UTimeTrialSubsystem::GetGateText() const
{
	return FText::FromString(FString::Printf(TEXT("CHECKPOINT %d/%d"), Splits.Num(), FMath::Max(0, Route.Num() - 1)));
}

FText UTimeTrialSubsystem::GetBestText() const
{
	if (!Tracks.IsValidIndex(Active)) { return FText::GetEmpty(); }
	double BestTotal = GetBestTime(Active);
	// after a new best the saved run is this one: show the time to beat from before the run
	if (State == ETimeTrialState::Finished) { BestTotal = PreviousBest; }
	return FText::FromString(TEXT("BEST  ") + (BestTotal > 0.0 ? FormatTime(BestTotal) : FString(TEXT("--:--.---"))));
}

void UTimeTrialSubsystem::AttachHUD()
{
	UGameViewportClient* Viewport = GetWorld()->GetGameViewport();
	if (!Viewport || (HUD.IsValid() && HUDViewport.Get() == Viewport))
	{
		return;
	}
	namespace CUI = CambridgeUI;
	auto Bind = [this](FText (UTimeTrialSubsystem::*Getter)() const)
	{
		return TAttribute<FText>::CreateLambda([this, Getter]() { return (this->*Getter)(); });
	};
	auto ShowIf = [](TFunction<bool()> Pred)
	{
		return TAttribute<EVisibility>::CreateLambda([Pred]() { return Pred() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; });
	};
	auto Label = [](FName Style, const TAttribute<FText>& InText)
	{
		return SNew(STextBlock).TextStyle(&CUI::Text(Style)).Text(InText);
	};
	auto NearTrack = [this]() -> const FTimeTrialTrack*
	{
		return State == ETimeTrialState::FreeRoam && Tracks.IsValidIndex(NearMarker) ? &Tracks[NearMarker] : nullptr;
	};
	auto StartGo = [this]() { return State == ETimeTrialState::Running && Now() - StateStart < 1.0; };
	auto ResetGo = [this]() { return State == ETimeTrialState::Running && !bResetHold && Now() - ResetReleased < 0.8; };
	auto SplitAhead = [this]() { return bLastSplitHasBest && LastSplitDelta <= 0.0; };
	auto Racing = [this]() { return State == ETimeTrialState::Running && !bResetHold; };
	const FLinearColor Gold = CUI::Color("Race.Gold");
	const FLinearColor Ahead = CUI::Color("Race.Ahead");
	const FLinearColor Behind = CUI::Color("Race.Behind");
	const FLinearColor Amber = CUI::Color("Race.Amber");
	const FLinearColor Shadow(0.0f, 0.0f, 0.0f, 0.7f);

	// ---- race panel (top centre): event title + lap badge over glass: timer, position on the route, checkpoints, best
	TSharedRef<SWidget> RaceContent = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
		[
			Label("Timer", Bind(&UTimeTrialSubsystem::GetTimerText))
		]
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 8, 0, 0)
		[
			SNew(STimeTrialRouteBar, this)
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(2, 6, 2, 0)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.0f)[ Label("HudLabelBright", Bind(&UTimeTrialSubsystem::GetGateText)) ]
			+ SHorizontalBox::Slot().AutoWidth()[ Label("HudLabel", Bind(&UTimeTrialSubsystem::GetBestText)) ]
		];

	// ---- split pill under the race panel: the delta to the best run in big digits (or the split time on a first run)
	const FSlateFontInfo DeltaFont = CUI::DigitsFont(24);
	TSharedRef<SWidget> SplitPill = CUI::MakeAnimatedIn(
		SNew(SBorder)
		.BorderImage(CUI::Brush("glass_pill"))
		.Padding(FMargin(22, 10, 24, 10))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 10, 0)
			[
				SNew(SImage)
				.Visibility_Lambda([this]() { return bLastSplitHasBest ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
				.Image_Lambda([SplitAhead]() { return CUI::Brush(SplitAhead() ? TEXT("arrow_up") : TEXT("arrow_down")); })
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(STextBlock)
				.Font(DeltaFont)
				.ShadowOffset(FVector2D(2, 2))
				.ShadowColorAndOpacity(Shadow)
				.ColorAndOpacity_Lambda([this, SplitAhead, Ahead, Behind]()
				{
					return FSlateColor(!bLastSplitHasBest ? FLinearColor::White : SplitAhead() ? Ahead : Behind);
				})
				.Text_Lambda([this]()
				{
					return FText::FromString(bLastSplitHasBest ? Signed(LastSplitDelta) : FormatTime(LastSplitTime));
				})
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(18, 0, 0, 0)
			[
				SNew(SBox).WidthOverride(2).HeightOverride(34)
				[
					SNew(SImage).Image(FCoreStyle::Get().GetBrush("WhiteBrush")).ColorAndOpacity(FSlateColor(FLinearColor(1, 1, 1, 0.18f)))
				]
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(16, 0, 0, 0)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					Label("HudLabelBright", TAttribute<FText>::CreateLambda([this]()
					{
						return FText::Format(LOCTEXT("SplitCp", "CHECKPOINT {0}/{1}"), LastSplitIndex, FMath::Max(0, Route.Num() - 1));
					}))
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					Label("HudLabel", TAttribute<FText>::CreateLambda([this, SplitAhead]()
					{
						if (!bLastSplitHasBest) { return LOCTEXT("SplitFirst", "FIRST RUN"); }
						return SplitAhead() ? LOCTEXT("SplitAheadPill", "AHEAD OF BEST") : LOCTEXT("SplitBehindPill", "BEHIND BEST");
					}))
				]
			]
		],
		TAttribute<float>::CreateLambda([this]() { return float(Now() - LastSplitShown); }), 0.18f, 0.85f);

	// ---- callout banner: lap / final lap (gold on a fastest lap)
	TSharedRef<SWidget> Callout = CUI::MakeAnimatedIn(
		SNew(SBorder)
		.BorderImage(CUI::Brush("glass_panel"))
		.Padding(FMargin(40, 12, 40, 14))
		.HAlign(HAlign_Center)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
			[
				SNew(STextBlock)
				.Font(CUI::PixelFont(36, true))
				.ShadowOffset(FVector2D(3, 3))
				.ShadowColorAndOpacity(Shadow)
				.ColorAndOpacity_Lambda([this, Gold]() { return FSlateColor(bCalloutGold ? Gold : FLinearColor::White); })
				.Text_Lambda([this]() { return CalloutTitle; })
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 6, 0, 0)
			[
				Label("HudLabelBright", TAttribute<FText>::CreateLambda([this]() { return CalloutBody; }))
			]
		],
		TAttribute<float>::CreateLambda([this]() { return float(Now() - CalloutAt); }), 0.2f, 0.8f);

	// ---- warning banners: WRONG WAY (red, flashing) and MISSED CHECKPOINT (red, steady)
	auto Banner = [&](const FText& Title, const TAttribute<FText>& Body, bool bFlash)
	{
		TAttribute<FLinearColor> Tint = bFlash
			? TAttribute<FLinearColor>::CreateLambda([this]() { return FLinearColor(1, 1, 1, 0.55f + 0.45f * float(FMath::Abs(FMath::Sin(Now() * 5.0)))); })
			: TAttribute<FLinearColor>(FLinearColor::White);
		return SNew(SBorder)
			.BorderImage(CUI::Brush("gear_badge_red"))
			.ColorAndOpacity(Tint)
			.BorderBackgroundColor_Lambda([Tint]() { return FSlateColor(Tint.Get()); })
			.Padding(FMargin(26, 10, 30, 12))
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 16, 0)
				[
					SNew(SImage).Image(CUI::Brush("icon_warn_lg"))
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						// condensed sans, not the pixel face: Silkscreen's W reads as a U at a glance ("URONG UAY")
						SNew(STextBlock)
						.Font(CUI::CondensedFont(26))
						.ColorAndOpacity(FLinearColor::White)
						.ShadowOffset(FVector2D(2, 2))
						.ShadowColorAndOpacity(FLinearColor(0.25f, 0.0f, 0.0f, 0.8f))
						.Text(Title)
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 0)
					[
						SNew(STextBlock).TextStyle(&CUI::Text("HudLabelBright")).Text(Body)
					]
				]
			];
	};
	TSharedRef<SWidget> WrongWay = Banner(LOCTEXT("WrongWay", "WRONG WAY"), LOCTEXT("WrongWayBody", "Turn around  -  tap R / Y to get back on track"), true);
	TSharedRef<SWidget> Missed = Banner(LOCTEXT("Missed", "MISSED CHECKPOINT"),
		TAttribute<FText>::CreateLambda([this]()
		{
			return FText::Format(LOCTEXT("MissedBody", "Turn around for checkpoint {0}  -  or tap R / Y"), Splits.Num() + 1);
		}), false);

	// ---- hold-to-restart / hold-to-leave progress
	TSharedRef<SWidget> HoldPill = SNew(SBorder)
		.BorderImage(CUI::Brush("glass_pill"))
		.Padding(FMargin(20, 8, 22, 8))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 14, 0)
			[
				Label("HudHint", TAttribute<FText>::CreateLambda([this]() { return HoldLabel; }))
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				CUI::MakeSegmentBar(TAttribute<float>::CreateLambda([this]() { return GetHoldFraction(); }), 20,
					[](int32, int32) { return FName(TEXT("seg_amber")); }, FVector2D(8.0, 14.0), 2.0f)
			]
		];

	// ---- countdown: start lights, popping digit / GO!, rev hint
	TSharedRef<SWidget> Countdown = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
		[
			SNew(SBox)
			.Visibility(ShowIf([this, StartGo]() { return State == ETimeTrialState::Countdown || StartGo(); }))
			[
				CUI::MakeStartLights(
					TAttribute<int32>::CreateLambda([this]() { return State == ETimeTrialState::Countdown ? FMath::Clamp(int32(Now() - StateStart) + 1, 1, 3) : 4; }),
					TAttribute<bool>::CreateLambda([this]() { return State == ETimeTrialState::Running; }))
			]
		]
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 16, 0, 0)
		[
			SNew(SBox)
			.Visibility(ShowIf([this, StartGo, ResetGo]() { return State == ETimeTrialState::Countdown || StartGo() || ResetGo(); }))
			[
				CUI::MakeCountdownDigit(
					TAttribute<FText>::CreateLambda([this]()
					{
						return State == ETimeTrialState::Countdown ? FText::AsNumber(FMath::CeilToInt(CountdownSeconds - (Now() - StateStart))) : LOCTEXT("GoBig", "GO!");
					}),
					TAttribute<float>::CreateLambda([this, StartGo]() -> float
					{
						if (State == ETimeTrialState::Countdown)
						{
							const double E = Now() - StateStart;
							return float(E - FMath::FloorToDouble(E));
						}
						return StartGo() ? float(Now() - StateStart) : float((Now() - ResetReleased) / 0.8);
					}),
					TAttribute<bool>::CreateLambda([this]() { return State == ETimeTrialState::Running; }))
			]
		]
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 28, 0, 0)
		[
			SNew(SBox)
			.Visibility(ShowIf([this]() { return State == ETimeTrialState::Countdown; }))
			[
				CUI::MakeToast(TAttribute<FText>::CreateLambda([this]()
					{
						return bAwaitGround ? LOCTEXT("LoadingArea", "Loading the area...") : LOCTEXT("RevItUp", "Rev it up! Launch on GO");
					}), FText::GetEmpty(), TEXT("icon_info"))
			]
		];

	// ---- back on track: XP progress dialog while the car is held after R
	TSharedRef<SWidget> ResetContent = SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Top).Padding(4, 4, 16, 0)
		[
			SNew(SImage).Image(CUI::Brush("icon_reset_lg"))
		]
		+ SHorizontalBox::Slot().FillWidth(1.0f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				Label("Label", TAttribute<FText>::CreateLambda([this]() { return FText::Format(LOCTEXT("BeforeCheckpoint", "Before checkpoint {0}"), Splits.Num() + 1); }))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 6, 0, 0)
			[
				Label("BodyDim", LOCTEXT("ClockRuns", "The clock keeps running - get ready to go!"))
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Left).Padding(0, 10, 0, 0)
			[
				CUI::MakeSegmentBar(TAttribute<float>::CreateLambda([this]() { return float(FMath::Clamp((Now() - ResetHoldStart) / ResetHoldSeconds, 0.0, 1.0)); }), 26,
					[](int32, int32) { return FName(TEXT("seg_green")); }, FVector2D(9.0, 14.0), 2.0f, false)
			]
		]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Top).Padding(12, 0, 0, 0)
		[
			SNew(SBox).WidthOverride(64).HeightOverride(64)
			[
				SNew(SBorder)
				.BorderImage(CUI::Brush("gear_badge_blue"))
				.HAlign(HAlign_Center)
				.VAlign(VAlign_Center)
				.Padding(FMargin(3, 6, 0, 0))
				[
					Label("TimerSmall", TAttribute<FText>::CreateLambda([this]()
					{
						return FText::AsNumber(FMath::Max(1, FMath::CeilToInt(ResetHoldSeconds - (Now() - ResetHoldStart))));
					}))
				]
			]
		];

	// ---- start prompt: "<Event>.exe" dialog when the car is in a start box
	auto TrackInfo = [NearTrack]()
	{
		const FTimeTrialTrack* T = NearTrack();
		if (!T) { return FText::GetEmpty(); }
		// the same count as the race HUD's "CHECKPOINT n/N": every crossing after the start line, laps included
		const int32 Checkpoints = T->bCircuit ? T->Gates.Num() * T->Laps : T->Gates.Num() - 1;
		FString S = FString::Printf(TEXT("%s  ·  %.1f km"), T->bCircuit ? TEXT("Circuit") : TEXT("Sprint"), T->LengthM * T->Laps / 1000.0f);
		if (T->bCircuit) { S += FString::Printf(TEXT("  ·  %d laps"), T->Laps); }
		S += FString::Printf(TEXT("  ·  %d checkpoints"), Checkpoints);
		return FText::FromString(S);
	};
	auto TrackBest = [this, NearTrack]()
	{
		return NearTrack() ? GetBestTime(NearMarker) : 0.0;
	};
	TSharedRef<SWidget> PromptContent = SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Top).Padding(4, 8, 24, 0)
		[
			SNew(SBox).WidthOverride(104).HeightOverride(104)
			[
				SNew(SBorder).BorderImage(CUI::Brush("gear_badge_blue")).HAlign(HAlign_Center).VAlign(VAlign_Center).Padding(0)
				[
					SNew(SImage).Image(CUI::Brush("icon_flag_lg"))
				]
			]
		]
		+ SHorizontalBox::Slot().FillWidth(1.0f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 0)
			[
				Label("Heading", TAttribute<FText>::CreateLambda([NearTrack]() { const FTimeTrialTrack* T = NearTrack(); return T ? FText::FromString(T->Name) : FText::GetEmpty(); }))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 0)
			[
				Label("Body", TAttribute<FText>::CreateLambda(TrackInfo))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
				[
					SNew(SImage).Image(CUI::Brush("icon_trophy"))
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 18, 0)
				[
					Label("BodyDim", TAttribute<FText>::CreateLambda([TrackBest]()
					{
						return TrackBest() > 0.0 ? LOCTEXT("PersonalBest", "Personal best") : LOCTEXT("NoBest", "No time set yet - go!");
					}))
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					Label("DigitsInk", TAttribute<FText>::CreateLambda([TrackBest]()
					{
						const double Best = TrackBest();
						return Best > 0.0 ? FText::FromString(FormatTime(Best)) : FText::GetEmpty();
					}))
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 16, 0, 0)
			[
				CUI::MakeXPButtonFace(LOCTEXT("StartRace", "START RACE"), true, true, TEXT("icon_flag"), true)
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 12, 0, 0)
			[
				// keyboard / gamepad, or the home-built wheel's start button / both paddles
				SNew(SOverlay)
				+ SOverlay::Slot()
				[
					SNew(SHorizontalBox).Visibility(ShowIf([this]() { return !IsWheelActive(); }))
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ CUI::MakeKeyCap(LOCTEXT("KeyEnter", "ENTER"), false) ]
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 0)[ Label("Label", LOCTEXT("Or", "/")) ]
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ CUI::MakeKeyCap(FText::FromString(TEXT("pad_a")), false) ]
				]
				+ SOverlay::Slot()
				[
					SNew(SHorizontalBox).Visibility(ShowIf([this]() { return IsWheelActive(); }))
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ CUI::MakeKeyCap(LOCTEXT("KeyBothPaddles", "BOTH PADDLES"), false) ]
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 0, 0, 0)[ Label("Label", LOCTEXT("WheelTogether", "together")) ]
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(0, 10, 0, 0)
			[
				Label("Small", LOCTEXT("DriveAway", "Drive away to dismiss"))
			]
		];
	TSharedRef<SWidget> Prompt = CUI::MakeAnimatedIn(
		SNew(SBox).WidthOverride(680 + 32)
		[
			CUI::MakeXPWindow(TAttribute<FText>::CreateLambda([NearTrack]()
				{
					const FTimeTrialTrack* T = NearTrack();
					return T ? FText::FromString(T->Name + TEXT(".exe")) : FText::GetEmpty();
				}),
				PromptContent, TEXT("icon_flag"), FOnClicked(), FMargin(12, 16, 12, 12), true)
		],
		TAttribute<float>::CreateLambda([this]() { return float(Now() - NearSince); }));

	// ---- free roam toasts (bottom left): nearest event, or a welcome for the first seconds
	TSharedRef<SWidget> Toasts = SNew(SBox).WidthOverride(452)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				// free-roam reset (R / Y, or the car flipped): put back on the nearest street
				SNew(SBox)
				.Visibility(ShowIf([this]() { return State == ETimeTrialState::FreeRoam && Now() - RoadResetAt < RoadResetToastSeconds; }))
				[
					CUI::MakeAnimatedIn(
						CUI::MakeToast(LOCTEXT("BackOnRoad", "Back on the road"),
							TAttribute<FText>::CreateLambda([this]()
							{
								return RoadResetStreet.IsEmpty() ? LOCTEXT("BackOnRoadBody", "Put back on the nearest street.")
									: FText::Format(LOCTEXT("BackOnRoadStreet", "Put back on {0}."), FText::FromString(RoadResetStreet));
							}),
							TEXT("icon_reset")),
						TAttribute<float>::CreateLambda([this]() { return float(Now() - RoadResetAt); }))
				]
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SBox)
				.Visibility(ShowIf([this]() { return State == ETimeTrialState::FreeRoam && NearMarker < 0 && Tracks.IsValidIndex(HintMarker); }))
				[
					CUI::MakeToast(
						TAttribute<FText>::CreateLambda([this]() { return Tracks.IsValidIndex(HintMarker) ? FText::FromString(Tracks[HintMarker].Name) : FText::GetEmpty(); }),
						TAttribute<FText>::CreateLambda([this]()
						{
							return FText::Format(LOCTEXT("HintBody", "{0} m away - drive into the blue start box to race."), FMath::RoundToInt(HintDistanceM));
						}),
						TEXT("icon_flag"))
				]
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SBox)
				.Visibility(ShowIf([this]() { return State == ETimeTrialState::FreeRoam && NearMarker < 0 && HintMarker < 0 && Now() < 15.0; }))
				[
					CUI::MakeToast(LOCTEXT("Welcome", "Welcome to Cambridge"),
						TAttribute<FText>::CreateLambda([this]()
						{
							return IsWheelActive()
								? LOCTEXT("WelcomeBodyWheel", "Drive into a blue start box and press both paddles together to race an event.\nEsc: settings, driving assists and wheel calibration.")
								: LOCTEXT("WelcomeBody", "Drive into a blue start box to race an event.\nEsc: settings, driving assists and wheel calibration.");
						}),
						TEXT("icon_info"))
				]
			]
		];

	// ---- key hints during an event (bottom centre)
	// keyboard key + its gamepad button (Y, D-pad up = the "^" cap)
	auto Keys = [](const TCHAR* Key, const TCHAR* Pad) { return TArray<FText>{ FText::FromString(Key), FText::FromString(Pad) }; };
	auto Hold = [&Label](const TArray<FText>& KeyCaps, const FText& What)
	{
		return SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 1, 8, 0)[ Label("HudLabel", LOCTEXT("HoldWord", "HOLD")) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ CUI::MakeKeyHint(KeyCaps, What, true) ];
	};
	// (the home-built wheel: both paddles - tap: back on track, hold: restart; leaving stays on the keyboard)
	auto One = [](const TCHAR* Key) { return TArray<FText>{ FText::FromString(Key) }; };
	TSharedRef<SWidget> HintBar = SNew(SBorder)
		.BorderImage(CUI::Brush("glass_pill"))
		.Padding(FMargin(18, 9))
		[
			SNew(SOverlay)
			+ SOverlay::Slot()
			[
				SNew(SHorizontalBox).Visibility(ShowIf([this]() { return !IsWheelActive(); }))
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 28, 0)[ CUI::MakeKeyHint(Keys(TEXT("R"), TEXT("Y")), LOCTEXT("HintReset", "Back on track"), true) ]
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 28, 0)[ Hold(Keys(TEXT("R"), TEXT("Y")), LOCTEXT("HintRestart", "Restart")) ]
				+ SHorizontalBox::Slot().AutoWidth()[ Hold(Keys(TEXT("BKSP"), TEXT("^")), LOCTEXT("HintLeave", "Leave")) ]
			]
			+ SOverlay::Slot()
			[
				SNew(SHorizontalBox).Visibility(ShowIf([this]() { return IsWheelActive(); }))
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 28, 0)[ CUI::MakeKeyHint(One(TEXT("BOTH PADDLES")), LOCTEXT("WheelReset", "Back on track"), true) ]
				+ SHorizontalBox::Slot().AutoWidth().Padding(0, 0, 28, 0)[ Hold(One(TEXT("BOTH PADDLES")), LOCTEXT("WheelRestart", "Restart")) ]
				+ SHorizontalBox::Slot().AutoWidth()[ Hold(One(TEXT("BKSP")), LOCTEXT("WheelLeave", "Leave")) ]
			]
		];

	// ---- driving HUD (bottom right): dot-matrix speed, gear badge, rpm and boost blocks, assists
	TSharedRef<SWidget> DriveContent = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Top).Padding(2, 4, 0, 0)
			[
				Label("HudLabel", LOCTEXT("Kmh", "KM/H"))
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 18, 0)
			[
				SNew(SBox).HeightOverride(92).VAlign(VAlign_Center)
				[
					CUI::MakeDotReadout(Bind(&UTimeTrialSubsystem::GetSpeedText), FText::FromString(TEXT("888")))
				]
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				CUI::MakeGearBadge(Bind(&UTimeTrialSubsystem::GetGearText), TAttribute<bool>::CreateLambda([this]()
				{
					const AImprezaSTi* Car = GetCar();
					return Car && Car->GetChaosVehicleMovement()->GetCurrentGear() < 0;
				}))
			]
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)
		[
			CUI::MakeSegmentBar(TAttribute<float>::CreateLambda([this]() { return GetRpmFraction(); }), 30, &CUI::RpmSegment)
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(2, 6, 0, 0)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Label("HudLabel", LOCTEXT("Rpm", "RPM")) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10, 0, 0, 0)[ Label("HudLabelBright", Bind(&UTimeTrialSubsystem::GetRpmText)) ]
			+ SHorizontalBox::Slot().FillWidth(1.0f)[ SNullWidget::NullWidget ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 10, 0)[ Label("HudLabel", LOCTEXT("Boost", "BOOST")) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				CUI::MakeSegmentBar(TAttribute<float>::CreateLambda([this]() { return GetBoostFraction(); }), 12,
					[](int32, int32) { return FName(TEXT("seg_blue")); }, FVector2D(6.0, 14.0), 3.0f)
			]
		];
	TSharedRef<SWidget> Drive = SNew(SBox).WidthOverride(392)
		[
			CUI::MakeHudPanel(LOCTEXT("CarName", "Impreza STI"), TEXT("icon_car"), DriveContent, TAttribute<FText>(),
				Label("HudLabelBright", Bind(&UTimeTrialSubsystem::GetAssistShortText)), FMargin(18, 10, 18, 12))
		];

	HUD = SNew(SOverlay).Visibility(EVisibility::HitTestInvisible)
		// screen-edge glow when a checkpoint is passed (green ahead of the best run, amber otherwise)
		+ SOverlay::Slot()
		[
			SNew(SImage)
			.Visibility(ShowIf([this]() { return State != ETimeTrialState::FreeRoam && Now() - LastPassAt < 0.35; }))
			.Image(CUI::Brush("edge_glow"))
			.ColorAndOpacity_Lambda([this, SplitAhead, Ahead, Amber]()
			{
				const float Age = float(FMath::Clamp((Now() - LastPassAt) / 0.35, 0.0, 1.0));
				return FSlateColor((SplitAhead() ? Ahead : Amber).CopyWithNewOpacity(FMath::Square(1.0f - Age) * 0.5f));
			})
		]
		// next-checkpoint marker / guidance arrow (draws itself only while racing)
		+ SOverlay::Slot()
		[
			SNew(STimeTrialGuide, this)
		]
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Bottom).Padding(0, 0, 32, 28)
		[
			Drive
		]
		+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom).Padding(32, 0, 0, 28)
		[
			// stacked above the minimap (bottom left) when it is on
			SNew(SBox).Padding_Lambda([]() { const float H = UMinimapSubsystem::GetHudFootprint(); return FMargin(0, 0, 0, H > 0.0f ? H - 28.0f + 12.0f : 0.0f); })
			[
				Toasts
			]
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 20, 0, 0)
		[
			SNew(SVerticalBox)
			.Visibility(ShowIf([this]() { return State != ETimeTrialState::FreeRoam; }))
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
			[
				SNew(SBox).WidthOverride(480)
				[
					CUI::MakeHudPanel(Bind(&UTimeTrialSubsystem::GetEventTitle), TEXT("icon_flag"), RaceContent,
						Bind(&UTimeTrialSubsystem::GetLapBadgeText), nullptr, FMargin(16, 8, 16, 12))
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 10, 0, 0)
			[
				SNew(SBox)
				.Visibility(ShowIf([this]() { return State == ETimeTrialState::Running && Now() - LastSplitShown <= SplitShowSeconds; }))
				[
					SplitPill
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 14, 0, 0)
			[
				SNew(SBox)
				.Visibility(ShowIf([this]() { return State == ETimeTrialState::Running && Now() - CalloutAt <= CalloutSeconds; }))
				[
					Callout
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 14, 0, 0)
			[
				SNew(SBox)
				.Visibility(ShowIf([this, Racing]() { return Racing() && bWrongWay; }))
				[
					WrongWay
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 14, 0, 0)
			[
				SNew(SBox)
				.Visibility(ShowIf([this, Racing]() { return Racing() && bMissed && !bWrongWay; }))
				[
					Missed
				]
			]
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(0, 0, 0, 30)
		[
			SNew(SVerticalBox)
			.Visibility(ShowIf([this]() { return State == ETimeTrialState::Countdown || State == ETimeTrialState::Running; }))
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 0, 0, 10)
			[
				SNew(SBox)
				.Visibility(ShowIf([this]() { return GetHoldFraction() > 0.08f; }))
				[
					HoldPill
				]
			]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
			[
				HintBar
			]
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 290, 0, 0)
		[
			Countdown
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 368, 0, 0)
		[
			SNew(SBox)
			.Visibility(ShowIf([this]() { return State == ETimeTrialState::Running && bResetHold; }))
			[
				CUI::MakeAnimatedIn(
					SNew(SBox).WidthOverride(560 + 32)
					[
						CUI::MakeXPWindow(LOCTEXT("BackOnTrack", "Back on track"), ResetContent, TEXT("icon_reset"))
					],
					TAttribute<float>::CreateLambda([this]() { return float(Now() - ResetHoldStart); }))
			]
		]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 168, 0, 0)
		[
			SNew(SBox)
			.Visibility(ShowIf([NearTrack]() { return NearTrack() != nullptr; }))
			[
				Prompt
			]
		]
		+ SOverlay::Slot()
		[
			SAssignNew(ResultsHost, SBox)
			.Visibility(ShowIf([this]() { return State == ETimeTrialState::Finished; }))
		];
	Viewport->AddViewportWidgetContent(HUD.ToSharedRef(), 40);
	HUDViewport = Viewport;
	if (State == ETimeTrialState::Finished)
	{
		ShowResults();
	}
}

void UTimeTrialSubsystem::ClearResults()
{
	if (ResultsHost.IsValid())
	{
		ResultsHost->SetContent(SNullWidget::NullWidget);
	}
}

void UTimeTrialSubsystem::ShowResults()
{
	if (!ResultsHost.IsValid() || !Tracks.IsValidIndex(Active))
	{
		return;
	}
	namespace CUI = CambridgeUI;
	const FTimeTrialTrack& T = Tracks[Active];
	auto Label = [](FName Style, const FText& InText)
	{
		return SNew(STextBlock).TextStyle(&CUI::Text(Style)).Text(InText);
	};
	const FLinearColor Navy = CUI::Color("Luna.Navy");

	// NEW BEST ribbon and the delta to the previous best
	TSharedRef<SHorizontalBox> BestRow = SNew(SHorizontalBox);
	if (bNewBest)
	{
		BestRow->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 14, 0)
		[
			CUI::MakeRibbon(LOCTEXT("NewBest", "NEW BEST!"))
		];
	}
	if (PreviousBest > 0.0)
	{
		const double Delta = FinishTime - PreviousBest;
		BestRow->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 6, 0)
		[
			SNew(SImage).Image(CUI::Brush(Delta <= 0.0 ? TEXT("arrow_up") : TEXT("arrow_down")))
		];
		BestRow->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				Label(Delta <= 0.0 ? TEXT("SplitAhead") : TEXT("SplitBehind"), FText::FromString(Signed(Delta)))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(2, 2, 0, 0)
			[
				Label("BodyDim", FText::Format(LOCTEXT("VsPrevious", "vs previous best {0}"), FText::FromString(FormatTime(PreviousBest))))
			]
		];
	}
	else
	{
		BestRow->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			Label("BodyDim", LOCTEXT("FirstRun", "First time on this track"))
		];
	}
	const float Km = T.LengthM * T.Laps / 1000.0f;
	const FText Stats = FText::FromString(FString::Printf(TEXT("%.1f km  ·  avg %d km/h"), Km, FinishTime > 0.0 ? FMath::RoundToInt(Km / (FinishTime / 3600.0)) : 0));

	TSharedRef<SVerticalBox> Content = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 20, 0)
			[
				CUI::MakeTrophyBurst(150.0f)
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()[ Label("Heading", LOCTEXT("Finished", "FINISHED")) ]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 8)[ Label("ResultTime", FText::FromString(FormatTime(FinishTime))) ]
				+ SVerticalBox::Slot().AutoHeight()[ BestRow ]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 8, 0, 0)[ Label("BodyDim", Stats) ]
			]
		];

	// lap table (circuits): lap time and the delta to the same lap of the previous best run
	if (LapTimes.Num() > 1)
	{
		const int32 G = T.Gates.Num();
		auto PrevLap = [this, G](int32 K) -> double
		{
			const int32 End = (K + 1) * G - 1;
			const int32 Start = K * G - 1;
			if (!PreviousBestSplits.IsValidIndex(End) || (K > 0 && !PreviousBestSplits.IsValidIndex(Start)))
			{
				return -1.0;
			}
			return PreviousBestSplits[End] - (K > 0 ? PreviousBestSplits[Start] : 0.0);
		};
		int32 BestLap = 0;
		for (int32 i = 1; i < LapTimes.Num(); ++i) { if (LapTimes[i] < LapTimes[BestLap]) { BestLap = i; } }
		auto Row = [](const TSharedRef<SWidget>& A, const TSharedRef<SWidget>& B, const TSharedRef<SWidget>& C, const TSharedRef<SWidget>& D)
		{
			return SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(0.16f).VAlign(VAlign_Center)[ A ]
				+ SHorizontalBox::Slot().FillWidth(0.28f).VAlign(VAlign_Center)[ B ]
				+ SHorizontalBox::Slot().FillWidth(0.28f).VAlign(VAlign_Center)[ C ]
				+ SHorizontalBox::Slot().FillWidth(0.28f).VAlign(VAlign_Center).HAlign(HAlign_Right)[ D ];
		};
		auto Head = [Navy](const FText& InText)
		{
			return SNew(STextBlock).TextStyle(&CUI::Text("Value")).ColorAndOpacity(FSlateColor(Navy)).Text(InText);
		};
		TSharedRef<SVerticalBox> Table = SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().Padding(8, 2, 8, 6)
			[
				Row(Head(LOCTEXT("ColLap", "LAP")), Head(LOCTEXT("ColTime", "TIME")), Head(LOCTEXT("ColVs", "VS BEST")), SNullWidget::NullWidget)
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(4, 0, 4, 4)
			[
				SNew(SBox).HeightOverride(1)
				[
					SNew(SImage).Image(FCoreStyle::Get().GetBrush("WhiteBrush")).ColorAndOpacity(FSlateColor(CUI::Color("Luna.FaceDark")))
				]
			];
		for (int32 i = 0; i < LapTimes.Num(); ++i)
		{
			const double Prev = PrevLap(i);
			TSharedRef<SWidget> Delta = Prev > 0.0
				? StaticCastSharedRef<SWidget>(Label(LapTimes[i] - Prev <= 0.0 ? TEXT("SplitAhead") : TEXT("SplitBehind"), FText::FromString(Signed(LapTimes[i] - Prev))))
				: StaticCastSharedRef<SWidget>(Label("Value", FText::FromString(TEXT("-"))));
			TSharedRef<SWidget> Badge = i == BestLap
				? StaticCastSharedRef<SWidget>(SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)[ SNew(SImage).Image(CUI::Brush("icon_trophy")) ]
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Label("Label", LOCTEXT("BestLap", "Best lap")) ])
				: SNullWidget::NullWidget;
			Table->AddSlot().AutoHeight()
			[
				SNew(SBorder)
				.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
				.BorderBackgroundColor(i == BestLap ? FLinearColor(1.0f, 0.82f, 0.25f, 0.22f) : FLinearColor::Transparent)
				.Padding(FMargin(8, 5))
				[
					Row(Label("Label", FText::AsNumber(i + 1)), Label("Value", FText::FromString(FormatTime(LapTimes[i]))), Delta, Badge)
				]
			];
		}
		Content->AddSlot().AutoHeight().Padding(0, 16, 0, 0)
		[
			CUI::MakeXPPanel(Table, FMargin(6, 8))
		];
	}

	// RETRY / NEXT EVENT / FREE ROAM: left / right picks (focus ring), Enter / A confirms; R / N / Backspace shortcuts
	const FTimeTrialTrack& NextT = Tracks[(Active + 1) % Tracks.Num()];
	auto Focus = [this](int32 i) { return TAttribute<bool>::CreateLambda([this, i]() { return ResultsFocus == i; }); };
	auto Choice = [&](const TSharedRef<SWidget>& Button, const FText& Under)
	{
		return SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()[ Button ]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0, 6, 0, 0)[ Label("Small", Under) ];
	};
	Content->AddSlot().AutoHeight().Padding(0, 20, 0, 0)
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.0f).Padding(0, 0, 8, 0)
		[
			Choice(CUI::MakeXPButtonFace(LOCTEXT("Retry", "RETRY"), true, Focus(0), TEXT("icon_reset"), false), LOCTEXT("RetryUnder", "Same event, from the grid"))
		]
		+ SHorizontalBox::Slot().FillWidth(1.0f).Padding(4, 0)
		[
			Choice(CUI::MakeXPButtonFace(LOCTEXT("NextEvent", "NEXT EVENT"), false, Focus(1), TEXT("icon_flag"), false), FText::FromString(NextT.Name))
		]
		+ SHorizontalBox::Slot().FillWidth(1.0f).Padding(8, 0, 0, 0)
		[
			Choice(CUI::MakeXPButtonFace(LOCTEXT("FreeRoam", "FREE ROAM"), false, Focus(2), TEXT("icon_car"), false), LOCTEXT("FreeRoamUnder", "Back to the open city"))
		]
	];
	auto Key = [](const TCHAR* K) { return CUI::MakeKeyCap(FText::FromString(K), false); };
	auto ShowWheel = [this](bool bWheel)
	{
		return TAttribute<EVisibility>::CreateLambda([this, bWheel]() { return IsWheelActive() == bWheel ? EVisibility::HitTestInvisible : EVisibility::Collapsed; });
	};
	// the home-built wheel: one paddle selects, both together confirm
	Content->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0, 14, 0, 0)
	[
		SNew(SHorizontalBox).Visibility(ShowWheel(true))
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Key(TEXT("LEFT")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(4, 0, 0, 0)[ Key(TEXT("RIGHT")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 1, 22, 0)[ Label("Label", LOCTEXT("WheelResultSelect", "Paddle: select")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Key(TEXT("BOTH PADDLES")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 1, 0, 0)[ Label("Label", LOCTEXT("WheelResultConfirm", "Confirm")) ]
	];
	Content->AddSlot().AutoHeight().HAlign(HAlign_Center).Padding(0, 14, 0, 0)
	[
		SNew(SHorizontalBox).Visibility(ShowWheel(false))
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Key(TEXT("<")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(4, 0, 0, 0)[ Key(TEXT(">")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 1, 22, 0)[ Label("Label", LOCTEXT("KeySelect", "Select")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Key(TEXT("ENTER")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(4, 0, 0, 0)[ Key(TEXT("pad_a")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 1, 22, 0)[ Label("Label", LOCTEXT("KeyConfirm", "Confirm")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ Key(TEXT("R")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(4, 0, 0, 0)[ Key(TEXT("N")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(4, 0, 0, 0)[ Key(TEXT("BKSP")) ]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 1, 0, 0)[ Label("Label", LOCTEXT("KeyShortcuts", "Shortcuts")) ]
	];

	TSharedRef<SOverlay> Screen = SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SImage).Image(FCoreStyle::Get().GetBrush("WhiteBrush")).ColorAndOpacity(FSlateColor(FLinearColor(0.0f, 0.0f, 0.0f, 0.3f)))
		];
	if (bNewBest)
	{
		Screen->AddSlot()[ CUI::MakeConfetti() ];
	}
	Screen->AddSlot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 188, 0, 0)
	[
		CUI::MakeAnimatedIn(
			SNew(SBox).WidthOverride(700 + 32)
			[
				CUI::MakeXPWindow(FText::Format(LOCTEXT("ResultsTitle", "Results - {0}"), FText::FromString(T.Name)), Content,
					TEXT("icon_trophy"), FOnClicked(), FMargin(12, 16, 12, 12), true)
			],
			TAttribute<float>::CreateLambda([this]() { return float(Now() - FinishedAt); }))
	];
	ResultsHost->SetContent(Screen);
}

#undef LOCTEXT_NAMESPACE

namespace
{
	// test / debug: put the car in an event's start box (no start), e.g. for screenshots of the prompt
	FAutoConsoleCommandWithWorldAndArgs GoToStartCmd(TEXT("cr.TT.GoToStart"), TEXT("Place the car in event N's start box"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
			{
				TT->PlaceAtStart(Args.Num() ? FCString::Atoi(*Args[0]) : 0);
			}
		}));

	// test / debug: show a race HUD element (flash, lap, finallap, fastest, wrongway, missed, hold) for screenshots
	FAutoConsoleCommandWithWorldAndArgs PreviewCmd(TEXT("cr.TT.Preview"), TEXT("Show a race HUD element now: flash | lap | finallap | fastest | wrongway | missed | hold"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
			{
				TT->PreviewHUD(Args.Num() ? Args[0].ToLower() : FString(TEXT("flash")));
			}
		}));

	// test: finish the running event now (the results screen; nothing saved)
	FAutoConsoleCommandWithWorldAndArgs FinishCmd(TEXT("cr.TT.Finish"), TEXT("Test: finish the running event now (results screen, not saved)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
			{
				TT->FinishForTest();
			}
		}));

	// test / debug: press a results button (0 retry, 1 next event, 2 free roam), e.g. as a shot-tour step
	FAutoConsoleCommandWithWorldAndArgs ResultCmd(TEXT("cr.TT.Result"), TEXT("Press results button N: 0 retry, 1 next event, 2 free roam"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
			{
				TT->PressResult(Args.Num() ? FCString::Atoi(*Args[0]) : 1);
			}
		}));

	// test: free-roam reset from given spots (see UTimeTrialSubsystem::StartResetTest)
	FAutoConsoleCommandWithWorldAndArgs ResetTestCmd(TEXT("cr.Test.ResetSpots"), TEXT("Free-roam reset test: cr.Test.ResetSpots x:y:yaw:roll:manual:waypoint|... (cm, deg; manual 0 = wait for the flip check; waypoint 1 = then a GPS waypoint on the spot)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr; TT && Args.Num())
			{
				TT->StartResetTest(FString::Join(Args, TEXT("")));
			}
		}));

	// perf A/B: hide / show the free-roam start markers (gantry, beams, start box)
	FAutoConsoleCommandWithWorldAndArgs MarkersCmd(TEXT("cr.TT.Markers"), TEXT("0 hides the free-roam start markers, 1 shows them (perf A/B)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
			{
				TT->SetMarkersHidden(Args.Num() && FCString::Atoi(*Args[0]) == 0);
			}
		}));

	// test / debug: start event N now (from free roam or mid-event), e.g. a shot-tour step; with
	// -TimeTrialAuto the autopilot then drives it
	FAutoConsoleCommandWithWorldAndArgs StartCmd(TEXT("cr.TT.Start"), TEXT("Start event N (index into the map's tracks)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
			{
				TT->StartEventByIndex(Args.Num() ? FCString::Atoi(*Args[0]) : 0);
			}
		}));
}

void UTimeTrialSubsystem::PreviewHUD(const FString& What)
{
	if (State != ETimeTrialState::Running || !Tracks.IsValidIndex(Active))
	{
		return;
	}
	const FTimeTrialTrack& T = Tracks[Active];
	if (What == TEXT("flash"))
	{
		LastPassAt = LastSplitShown = Now();
		LastSplitTime = Now() - StateStart;
		bLastSplitHasBest = true;
		LastSplitDelta = -0.412;
		LastSplitIndex = FMath::Max(Splits.Num(), 1);
	}
	else if (What == TEXT("lap") || What == TEXT("finallap") || What == TEXT("fastest"))
	{
		CalloutTitle = What == TEXT("lap") ? FText::FromString(FString::Printf(TEXT("LAP 2/%d"), FMath::Max(T.Laps, 2))) : FText::FromString(TEXT("FINAL LAP"));
		CalloutBody = FText::FromString(FString::Printf(TEXT("Lap 1  %s%s"), *FormatTime(Now() - StateStart), What == TEXT("fastest") ? TEXT("  -  fastest lap") : TEXT("")));
		bCalloutGold = What == TEXT("fastest");
		CalloutAt = Now();
	}
	else if (What == TEXT("wrongway"))
	{
		bWrongWay = true;
		PreviewUntil = Now() + 3.0;
	}
	else if (What == TEXT("missed"))
	{
		bMissed = true;
		bWrongWay = false;
		PreviewUntil = Now() + 3.0;
	}
	else if (What == TEXT("hold"))
	{
		RestartHeldSince = FPlatformTime::Seconds() - 0.3;     // restarts 0.7 s later, like a real hold
		HoldLabel = NSLOCTEXT("TimeTrial", "HoldRestartPreview", "RESTART EVENT");
	}
	UE_LOG(LogTimeTrial, Display, TEXT("HUD preview: %s"), *What);
}

void UTimeTrialSubsystem::StartResetTest(const FString& Spec)
{
	ResetTestSpots.Reset();
	TArray<FString> Items;
	Spec.ParseIntoArray(Items, TEXT("|"));
	for (const FString& Item : Items)
	{
		TArray<FString> F;
		Item.ParseIntoArray(F, TEXT(":"));
		if (F.Num() >= 2)
		{
			FResetTestSpot& S = ResetTestSpots.AddDefaulted_GetRef();
			S.At = FVector2D(FCString::Atod(*F[0]), FCString::Atod(*F[1]));
			S.Yaw = F.Num() > 2 ? FCString::Atof(*F[2]) : 0.0f;
			S.Roll = F.Num() > 3 ? FCString::Atof(*F[3]) : 0.0f;
			S.bManual = F.Num() > 4 ? FCString::Atoi(*F[4]) != 0 : true;
			S.bWaypoint = F.Num() > 5 && FCString::Atoi(*F[5]) != 0;
		}
	}
	ResetTestIndex = ResetTestSpots.Num() ? 0 : -1;
	ResetTestPhase = 0;
	ResetTestNext = Now() + 3.0;      // (after the start: the car is spawned and its cell loaded)
	UE_LOG(LogTimeTrial, Display, TEXT("reset test: %d spots"), ResetTestSpots.Num());
}

void UTimeTrialSubsystem::TickResetTest(AImprezaSTi* Car)
{
	if (Now() < ResetTestNext || !ResetTestSpots.IsValidIndex(ResetTestIndex) || State != ETimeTrialState::FreeRoam)
	{
		return;
	}
	const FResetTestSpot& S = ResetTestSpots[ResetTestIndex];
	switch (ResetTestPhase)
	{
	case 0:
		Car->SetActorTransform(FTransform(FRotator(0.0f, S.Yaw, S.Roll), FVector(S.At.X, S.At.Y, 150.0)), false, nullptr, ETeleportType::TeleportPhysics);
		Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
		UE_LOG(LogTimeTrial, Display, TEXT("reset test %d: car at (%.0f, %.0f) yaw %.0f roll %.0f, %s"), ResetTestIndex, S.At.X, S.At.Y, S.Yaw, S.Roll,
			S.bManual ? TEXT("then R") : TEXT("left to the flip check"));
		ResetTestPhase = 1;
		ResetTestNext = Now() + 1.0;
		break;
	case 1:
		if (S.bManual)
		{
			Car->DoResetVehicle();
		}
		ResetTestPhase = 2;
		ResetTestNext = Now() + (S.bManual ? 3.0 : 9.0);
		break;
	case 3:
	{
		const UMinimapSubsystem* Map = UMinimapSubsystem::Get(this);
		UE_LOG(LogTimeTrial, Display, TEXT("reset test %d: GPS waypoint on the spot %s"), ResetTestIndex,
			Map && !Map->HasDestination() ? TEXT("REACHED from the street (arrived)") : TEXT("NOT reached (still navigating)"));
		if (UMinimapSubsystem* M = UMinimapSubsystem::Get(this)) { M->ClearDestination(); }
		ResetTestPhase = 0;
		ResetTestNext = Now() + 0.5;
		if (++ResetTestIndex >= ResetTestSpots.Num())
		{
			ResetTestIndex = -1;
			UE_LOG(LogTimeTrial, Display, TEXT("reset test done"));
		}
		break;
	}
	default:
	{
		const FVector L = Car->GetActorLocation();
		float Z = 0.0f;
		const bool bGround = GroundZ(L, Z);
		FVector2D Road, Dir;
		double Dist = -1.0;
		const UMinimapSubsystem* Map = UMinimapSubsystem::Get(this);
		FString Street;
		if (Map) { Map->NearestRoad(FVector2D(L), Road, Dir, Dist, &Street); }
		UE_LOG(LogTimeTrial, Display, TEXT("reset test %d: now at (%.0f, %.0f, %.0f) yaw %.0f, up %.2f, %.1f km/h, %.0f cm above the ground (%s), %.1f m from the centre of %s"),
			ResetTestIndex, L.X, L.Y, L.Z, Car->GetActorRotation().Yaw, FVector::DotProduct(Car->GetActorUpVector(), FVector::UpVector),
			Car->GetVelocity().Size() * 0.036, bGround ? L.Z - Z : -1.0, bGround ? TEXT("hit") : TEXT("NO GROUND"), Dist / 100.0, *Street);
		if (S.bWaypoint)
		{
			if (UMinimapSubsystem* M = UMinimapSubsystem::Get(this)) { M->SetDestination(S.At); }
			ResetTestPhase = 3;
			ResetTestNext = Now() + 1.5;
			break;
		}
		ResetTestPhase = 0;
		ResetTestNext = Now() + 0.5;
		if (++ResetTestIndex >= ResetTestSpots.Num())
		{
			ResetTestIndex = -1;
			UE_LOG(LogTimeTrial, Display, TEXT("reset test done"));
		}
		break;
	}
	}
}

void UTimeTrialSubsystem::NotifyRoadReset(const FString& Street)
{
	RoadResetAt = Now();
	RoadResetStreet = Street;
}

void UTimeTrialSubsystem::SetMarkersHidden(bool bHidden)
{
	for (ATimeTrialGate* M : Markers)
	{
		if (M) { M->SetActorHiddenInGame(bHidden || IsInEvent()); }
	}
}

void UTimeTrialSubsystem::PlaceAtStart(int32 TrackIndex)
{
	AImprezaSTi* Car = GetCar();
	if (!Car || !Tracks.IsValidIndex(TrackIndex) || State != ETimeTrialState::FreeRoam)
	{
		return;
	}
	const FTimeTrialTrack& T = Tracks[TrackIndex];
	Car->SetActorTransform(FTransform(FRotator(0.0f, T.StartYaw, 0.0f), T.StartLocation), false, nullptr, ETeleportType::TeleportPhysics);
	Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
	Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	Car->SnapCamera();
	// a start across the map isn't streamed in yet: load it before the car can fall through (as StartEvent does)
	float GridZ;
	if (!GroundZ(T.StartLocation, GridZ))
	{
		GetWorld()->bRequestedBlockOnAsyncLoading = true;
		UE_LOG(LogTimeTrial, Display, TEXT("go to start %s: the grid isn't streamed in yet, loading it"), *T.Name);
	}
}
