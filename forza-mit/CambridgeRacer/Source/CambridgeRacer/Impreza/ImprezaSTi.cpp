#include "ImprezaSTi.h"

#include "ChaosWheeledVehicleMovementComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "CambridgeGameUserSettings.h"
#include "CambridgeLaunchSubsystem.h"
#include "TimeTrialSubsystem.h"
#include "CambridgeWheelSubsystem.h"
#include "Misc/CommandLine.h"
#include "ChaosVehicleWheel.h"
#include "StiEngineAudio.h"
#include "ImprezaSTiWheels.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "UObject/ConstructorHelpers.h"

namespace
{
	// placeholder visuals + template input actions
	const TCHAR* MeshPath = TEXT("/Game/Vehicles/SportsCar/SKM_SportsCar.SKM_SportsCar");
	const TCHAR* AnimPath = TEXT("/Game/Vehicles/SportsCar/ABP_SportsCar");
	const FName WheelBones[4] = { TEXT("Phys_Wheel_FL"), TEXT("Phys_Wheel_FR"), TEXT("Phys_Wheel_BL"), TEXT("Phys_Wheel_BR") };

	// The template skeleton's wheel bones sit at x = 135 / -129.2, y = +-90 (264.2 cm wheelbase, 180 cm
	// track). The GDB STi: 2525 mm wheelbase, 1485 / 1490 mm track. Physics wheels are moved onto the
	// real geometry (same axle midpoint, x = 2.9) with AdditionalOffset; the visible wheels follow.
	const FVector WheelOffsets[4] = {
		FVector(-5.85, 15.75, 0.0), FVector(-5.85, -15.75, 0.0), FVector(5.85, 15.5, 0.0), FVector(5.85, -15.5, 0.0) };

	// Synthetic full-boost torque curve (N*m vs rpm) anchored to the factory figures
	// 373 N*m @ 4000 and 206 kW @ 6400 (=> 307 N*m). No stock GDB-B dyno sheet is public.
	const FVector2f TorqueCurveNm[] = {
		{0, 110}, {1000, 130}, {2000, 190}, {2500, 250}, {3000, 320}, {3500, 360}, {4000, 373},
		{4500, 370}, {5000, 360}, {5500, 345}, {6000, 327}, {6400, 307}, {7000, 280},
		{7500, 258}, {8000, 235},
	};

	// Height of the centre of gravity above the ground (m). Regression estimate 0.54 m for a
	// 1430 kg car, lowered slightly for the boxer engine.
	constexpr float CGHeightCm = 52.0f;
	// Front axle share of the weight (GDB axle weights 880/580 kg, owner scale 61.2 %)
	constexpr float FrontWeightShare = 0.61f;

	FVector RefPoseComponentLocation(const FReferenceSkeleton& Ref, FName Bone)
	{
		int32 Index = Ref.FindBoneIndex(Bone);
		FTransform T = FTransform::Identity;
		while (Index != INDEX_NONE)
		{
			T = T * Ref.GetRefBonePose()[Index];
			Index = Ref.GetParentIndex(Index);
		}
		return T.GetLocation();
	}
}

AImprezaSTi::AImprezaSTi()
{
	static ConstructorHelpers::FObjectFinder<USkeletalMesh> MeshAsset(MeshPath);
	static ConstructorHelpers::FClassFinder<UAnimInstance> AnimClass(AnimPath);
	static ConstructorHelpers::FObjectFinder<UInputAction> IASteering(TEXT("/Game/VehicleTemplate/Input/Actions/IA_Steering"));
	static ConstructorHelpers::FObjectFinder<UInputAction> IAThrottle(TEXT("/Game/VehicleTemplate/Input/Actions/IA_Throttle"));
	static ConstructorHelpers::FObjectFinder<UInputAction> IABrake(TEXT("/Game/VehicleTemplate/Input/Actions/IA_Brake"));
	static ConstructorHelpers::FObjectFinder<UInputAction> IAHandbrake(TEXT("/Game/VehicleTemplate/Input/Actions/IA_Handbrake"));
	static ConstructorHelpers::FObjectFinder<UInputAction> IALook(TEXT("/Game/VehicleTemplate/Input/Actions/IA_LookAround"));
	static ConstructorHelpers::FObjectFinder<UInputAction> IACamera(TEXT("/Game/VehicleTemplate/Input/Actions/IA_ToggleCamera"));
	static ConstructorHelpers::FObjectFinder<UInputAction> IAReset(TEXT("/Game/VehicleTemplate/Input/Actions/IA_Reset"));
	SteeringAction = IASteering.Object;
	ThrottleAction = IAThrottle.Object;
	BrakeAction = IABrake.Object;
	HandbrakeAction = IAHandbrake.Object;
	LookAroundAction = IALook.Object;
	ToggleCameraAction = IACamera.Object;
	ResetVehicleAction = IAReset.Object;

	GetMesh()->SetSkeletalMesh(MeshAsset.Object);
	GetMesh()->SetAnimInstanceClass(AnimClass.Class);
	EngineAudio = CreateDefaultSubobject<UStiEngineAudio>(TEXT("EngineAudio"));

	// SKM_SportsCar is only the physics skeleton: the visible car is static meshes on top of it.
	// Preferred: the procedural GDB STi in its rally livery (tools/mapgen/make_sti.py, import_car.sh);
	// fallback: the template sports car's body / glass / wheels.
	auto Find = [](const TCHAR* Path) { ConstructorHelpers::FObjectFinderOptional<UStaticMesh> F(Path); return F.Get(); };
	auto Visual = [this](FName Name, UStaticMesh* Asset, USceneComponent* Parent)
	{
		UStaticMeshComponent* C = CreateDefaultSubobject<UStaticMeshComponent>(Name);
		C->SetupAttachment(Parent);
		C->SetStaticMesh(Asset);
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetGenerateOverlapEvents(false);
		return C;
	};
	auto StiPart = [&Find](const TCHAR* Part)
	{
		return Find(*FString::Printf(TEXT("/Game/Cambridge/Car/sti_%s/sti_%s/StaticMeshes/sti_%s.sti_%s"), Part, Part, Part, Part));
	};
	const TCHAR* WheelNames[4] = { TEXT("Wheel_FL"), TEXT("Wheel_FR"), TEXT("Wheel_BL"), TEXT("Wheel_BR") };
	if (UStaticMesh* Paint = StiPart(TEXT("paint")))
	{
		BodyMesh = Visual(TEXT("Body_Paint"), Paint, GetMesh());
		for (const TCHAR* Part : { TEXT("glass"), TEXT("black"), TEXT("lens"), TEXT("red"), TEXT("chrome"), TEXT("mesh"),
			TEXT("amber"), TEXT("interior"), TEXT("under"), TEXT("badge"), TEXT("driver_suit"), TEXT("driver_helmet"),
			TEXT("driver_visor"), TEXT("plate") })
		{
			if (UStaticMesh* M = StiPart(Part))
			{
				Visual(*FString::Printf(TEXT("Body_%s"), Part), M, BodyMesh);
			}
		}
		UStaticMesh* Tire = StiPart(TEXT("tire"));
		UStaticMesh* Rim = StiPart(TEXT("rim"));
		UStaticMesh* Brake = StiPart(TEXT("brake"));
		UStaticMesh* Caliper = StiPart(TEXT("caliper"));
		for (int32 i = 0; i < 4; ++i)
		{
			// posed every tick in UpdateWheelVisuals (steer, spin, suspension); rim + disc ride on the tyre,
			// the caliper only steers (it's on the knuckle, it doesn't spin)
			WheelMeshes[i] = Visual(WheelNames[i], Tire, GetMesh());
			Visual(*FString::Printf(TEXT("%s_Rim"), WheelNames[i]), Rim, WheelMeshes[i]);
			Visual(*FString::Printf(TEXT("%s_Brake"), WheelNames[i]), Brake, WheelMeshes[i]);
			if (Caliper)
			{
				CaliperMeshes[i] = Visual(*FString::Printf(TEXT("%s_Caliper"), WheelNames[i]), Caliper, GetMesh());
			}
		}
	}
	else
	{
		BodyMesh = Visual(TEXT("Chassis"), Find(TEXT("/Game/Vehicles/SportsCar/SM_SportsCar")), GetMesh());
		GlassMesh = Visual(TEXT("Chassis_Glass"), Find(TEXT("/Game/Vehicles/SportsCar/SM_SportsCar_Glass")), GetMesh());
		UStaticMesh* Wheel = Find(TEXT("/Game/Vehicles/SportsCar/SM_SportsCar_Wheel"));
		for (int32 i = 0; i < 4; ++i)
		{
			WheelMeshes[i] = Visual(WheelNames[i], Wheel, GetMesh());
		}
	}

	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();

	// --- chassis ---
	Move->Mass = 1430.0f + 75.0f;         // kerb weight + driver
	Move->ChassisWidth = 173.0f;          // body width 1730 mm
	Move->ChassisHeight = 122.0f;         // so width*height = 2.11 m^2 frontal area (0.85 * 1.73 * 1.435)
	Move->DragCoefficient = 0.33f;
	Move->DownforceCoefficient = 0.3f;    // playability: some aero grip at speed (the real car made ~none)

	// centre of mass from the mesh's wheel bones: 61 % on the front axle, 52 cm above ground
	if (MeshAsset.Object)
	{
		const FReferenceSkeleton& Ref = MeshAsset.Object->GetRefSkeleton();
		FVector Wheel[4];
		for (int32 i = 0; i < 4; ++i)
		{
			Wheel[i] = RefPoseComponentLocation(Ref, WheelBones[i]) + WheelOffsets[i];
			WheelRestPositions[i] = Wheel[i];
		}
		const FVector Front = (Wheel[0] + Wheel[1]) * 0.5f;
		const FVector Rear = (Wheel[2] + Wheel[3]) * 0.5f;
		const float GroundZ = (Front.Z + Rear.Z) * 0.5f - 31.7f;
		Move->bEnableCenterOfMassOverride = true;
		Move->CenterOfMassOverride = FVector(
			FMath::Lerp(Rear.X, Front.X, FrontWeightShare), 0.0f, GroundZ + CGHeightCm);
	}

	// --- wheels ---
	Move->bLegacyWheelFrictionPosition = true;
	Move->WheelSetups.SetNum(4);
	for (int32 i = 0; i < 4; ++i)
	{
		Move->WheelSetups[i].WheelClass = i < 2 ? UImprezaSTiWheelFront::StaticClass() : UImprezaSTiWheelRear::StaticClass();
		Move->WheelSetups[i].BoneName = WheelBones[i];
		Move->WheelSetups[i].AdditionalOffset = WheelOffsets[i];
	}

	// --- engine: EJ207 2.0 L flat-4 turbo, 280 PS @ 6400, 373 N*m @ 4000, 8000 rpm cut ---
	FRichCurve* Curve = Move->EngineSetup.TorqueCurve.GetRichCurve();
	Curve->Reset();
	for (const FVector2f& P : TorqueCurveNm)
	{
		Curve->AddKey(P.X, P.Y);
	}
	Move->EngineSetup.MaxTorque = PeakTorque;
	Move->EngineSetup.MaxRPM = 8000.0f;
	Move->EngineSetup.EngineIdleRPM = 925.0f;    // round-3 playtest: 800 sounded lumpy ("cranky")
	// Chaos applies engine braking as rpm * EngineBrakeEffect N*m of BRAKE torque on every driven
	// wheel. The template's 0.2 gives ~1 g on lift-off at 6000 rpm; 0.02 gives a realistic ~0.1 g.
	Move->EngineSetup.EngineBrakeEffect = 0.02f;
	Move->EngineSetup.EngineRevUpMOI = 2.0f;
	Move->EngineSetup.EngineRevDownRate = 600.0f;

	// --- gearbox: TY856 6-speed, JDM ratios, 3.900 final drive ---
	Move->TransmissionSetup.bUseAutomaticGears = bAutoShift;
	Move->TransmissionSetup.bUseAutoReverse = true;
	Move->TransmissionSetup.FinalRatio = 3.9f;
	Move->TransmissionSetup.ForwardGearRatios = { 3.636f, 2.375f, 1.761f, 1.346f, 1.062f, 0.842f };
	Move->TransmissionSetup.ReverseGearRatios = { 3.545f };
	Move->TransmissionSetup.ChangeUpRPM = 7400.0f;   // auto-shift: keep it on boost
	Move->TransmissionSetup.ChangeDownRPM = 3800.0f;
	Move->TransmissionSetup.GearChangeTime = 0.25f;
	Move->TransmissionSetup.TransmissionEfficiency = 0.85f;  // AWD driveline losses

	// --- AWD: standard GDB-B = viscous-LSD centre diff, 50:50 base split ---
	Move->DifferentialSetup.DifferentialType = EVehicleDifferential::AllWheelDrive;
	Move->DifferentialSetup.FrontRearSplit = 0.5f;

	// --- steering: 15:1 rack. Speed-sensitive curve (x = mph) makes keyboard/gamepad drivable;
	// it should be flattened to 1.0 for the force-feedback wheel. ---
	Move->SteeringSetup.SteeringType = ESteeringType::Ackermann;
	Move->SteeringSetup.AngleRatio = 0.7f;
	FRichCurve* Steer = Move->SteeringSetup.SteeringCurve.GetRichCurve();
	Steer->Reset();
	Steer->AddKey(0.0f, 1.0f);
	Steer->AddKey(25.0f, 0.88f);
	Steer->AddKey(50.0f, 0.7f);
	Steer->AddKey(90.0f, 0.5f);
	Steer->AddKey(150.0f, 0.38f);
}

void AImprezaSTi::Tick(float Delta)
{
	// the home-built wheel (when connected) overrides the analog axes before the base pawn applies them
	UCambridgeWheelSubsystem* Wheel = IsLocallyControlled() ? UCambridgeWheelSubsystem::Get(this) : nullptr;
	// (behind the launch menu the wheel drives the menu, not the parked car, and pushes no force)
	const bool bMenu = Wheel && Wheel->IsActive() && UCambridgeLaunchSubsystem::IsLaunchMenuOpen(this);
	if (bMenu)
	{
		Wheel->SetForceFeedback(0.0f);
	}
	const bool bWheel = Wheel && Wheel->IsActive() && !bMenu;
	// keyboard / gamepad: holding brake at a standstill reverses. Real pedals: the brake only brakes,
	// reverse is a downshift past neutral
	GetChaosVehicleMovement()->bReverseAsBrake = !bWheel;
	if (bWheel)
	{
		ApplyWheelInput(*Wheel);
	}
	Super::Tick(Delta);
	UpdateEngine(Delta);
	UpdateWheelVisuals();
	if (bWheel)
	{
		Wheel->SetForceFeedback(ComputeForceFeedback(*Wheel, Delta));
		static const bool bLog = FParse::Param(FCommandLine::Get(), TEXT("WheelLog"));
		if (bLog && GetWorld()->GetTimeSeconds() - LastWheelLog > 1.0)
		{
			LastWheelLog = GetWorld()->GetTimeSeconds();
			UE_LOG(LogTemp, Display, TEXT("STI_WHEEL speed=%.0f km/h gear=%d auto=%d rpm=%.0f"),
				GetChaosVehicleMovement()->GetForwardSpeed() * 0.036f, GetChaosVehicleMovement()->GetCurrentGear(), bAutoShift ? 1 : 0,
				GetChaosVehicleMovement()->GetEngineRotationSpeed());
		}
	}

	// (assists, gear, boost and speed are on the Slate HUD: UTimeTrialSubsystem)
}

float AImprezaSTi::FilterThrottle(float DriverInput, float Delta)
{
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	float Out = DriverInput;

	if (TractionControl != ETractionControlMode::Off && Move->Wheels.Num() == 4 && Delta > 0.0f)
	{
		// drive slip ratio (wheel surface speed vs ground speed) of the worst driven wheel
		const float Ground = FMath::Abs(Move->GetForwardSpeed());
		float WorstSlip = 0.0f;
		for (UChaosVehicleWheel* W : Move->Wheels)
		{
			if (W && !W->IsInAir())
			{
				const float Surface = FMath::Abs(W->GetWheelAngularVelocity()) * W->GetWheelRadius();
				WorstSlip = FMath::Max(WorstSlip, (Surface - Ground) / FMath::Max(Ground, 300.0f));
			}
		}
		const float Allowed = TractionControl == ETractionControlMode::Full ? TCSlipFull : TCSlipSport;
		const float TargetCut = FMath::Clamp((WorstSlip - Allowed) / Allowed, 0.0f, 1.0f);
		// cut fast, restore slower, like a real ECU throttle/ignition cut
		TCCut = FMath::FInterpTo(TCCut, TargetCut, Delta, TargetCut > TCCut ? 25.0f : 6.0f);
		Out *= 1.0f - 0.9f * TCCut;
	}

	if (bSpeedLimiter180 && Move->GetForwardSpeed() * 0.036f >= 180.0f)
	{
		Out = 0.0f;
	}

	LastFilteredThrottle = Out;
	return Out;
}

void AImprezaSTi::UpdateWheelVisuals()
{
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	if (!Move || !Move->PhysicsVehicleOutput())
	{
		return;
	}
	for (int32 i = 0; i < 4 && i < Move->Wheels.Num(); ++i)
	{
		const UChaosVehicleWheel* W = Move->Wheels[i];
		if (!W || !WheelMeshes[i])
		{
			continue;
		}
		// suspension offset: + = wheel pushed up into the arch (cm)
		const float Suspension = W->GetSuspensionOffset();
		const float Spin = FMath::Fmod(W->GetRotationAngle(), 360.0f);
		const bool bRight = i % 2 == 1;
		// the wheel meshes are modelled for the left side (outer face toward -Y in Unreal). Right side: the
		// tyre (+ rim and disc riding on it) is turned 180 deg about Z rather than mirrored, so the sidewall
		// lettering reads correctly (the spin sign flips with the axle); the caliper is a mirror image
		// (Y scale -1), which keeps it on the trailing side on both sides
		const FVector Location = WheelRestPositions[i] + FVector(0.0, 0.0, Suspension);
		const FVector Scale(1.0, bRight ? -1.0 : 1.0, 1.0);
		WheelMeshes[i]->SetRelativeTransform(bRight
			? FTransform(FRotator(-Spin, W->GetSteerAngle() + 180.0f, 0.0f), Location)
			: FTransform(FRotator(Spin, W->GetSteerAngle(), 0.0f), Location));
		if (CaliperMeshes[i])
		{
			CaliperMeshes[i]->SetRelativeTransform(FTransform(FRotator(0.0f, W->GetSteerAngle(), 0.0f), Location, Scale));
		}
		if (!bLoggedSuspension && i == 3)
		{
			bLoggedSuspension = true;
			UE_LOG(LogTemp, Display, TEXT("STI_WHEELS rest=%s suspension=%.2f radius=%.1f actorZ=%.1f"),
				*WheelRestPositions[i].ToString(), Suspension, W->GetWheelRadius(), GetActorLocation().Z);
		}
	}
}

void AImprezaSTi::UpdateEngine(float Delta)
{
	if (Delta <= 0.0f)
	{
		return;
	}
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	const float RPM = Move->GetEngineRotationSpeed();
	const FRichCurve* Curve = Move->EngineSetup.TorqueCurve.GetRichCurveConst();

	// clutch slip at launch: engine held near ClutchSlipRPM (by how far the throttle is open).
	// In reverse on keyboard / gamepad the brake input drives the car (Chaos bReverseAsBrake), so it
	// counts as the throttle here; otherwise reverse never boosts or slips the clutch and crawls.
	float EngineRPM = RPM;
	float ClutchScale = 1.0f;
	const int32 Gear = Move->GetCurrentGear();
	const float DriveThrottle = (Gear < 0 && Move->bReverseAsBrake) ? FMath::Max(LastFilteredThrottle, Move->GetBrakeInput()) : LastFilteredThrottle;
	if ((Gear == 1 || Gear == -1) && RPM < ClutchSlipRPM && DriveThrottle > 0.05f)
	{
		EngineRPM = FMath::Lerp(RPM, ClutchSlipRPM, DriveThrottle);
		ClutchScale = Curve->Eval(EngineRPM) / FMath::Max(Curve->Eval(RPM), 1.0f);
	}

	// turbo spool, driven by the engine's own rpm
	const float Target = DriveThrottle;
	const float Tau = Target > Boost
		? FMath::GetMappedRangeValueClamped(FVector2f(2000.0f, 4500.0f), FVector2f(SpoolTimeLowRPM, SpoolTimeHighRPM), EngineRPM)
		: BoostDecayTime;
	Boost += (Target - Boost) * (1.0f - FMath::Exp(-Delta / Tau));

	// The torque curve is the steady-state full-boost curve; boost only adds the transient lag.
	// reverse limiter: Chaos doesn't rev-limit reverse (a real car tops out ~60 km/h in reverse);
	// fade the torque out between 40 and 45 km/h backwards
	const float ReverseKmh = Gear < 0 ? FMath::Max(0.0f, -Move->GetForwardSpeed() * 0.036f) : 0.0f;
	const float ReverseLimit = FMath::Clamp((45.0f - ReverseKmh) / 5.0f, 0.0f, 1.0f);
	const float NewMaxTorque = PeakTorque * ClutchScale * ReverseLimit * (OffBoostTorqueFraction + (1.0f - OffBoostTorqueFraction) * Boost);
	if (FMath::Abs(NewMaxTorque - AppliedMaxTorque) > 2.0f)
	{
		AppliedMaxTorque = NewMaxTorque;
		Move->SetMaxEngineTorque(NewMaxTorque);
	}
}

void AImprezaSTi::CycleTractionControl()
{
	SetTractionControl((ETractionControlMode)(((int32)TractionControl + 1) % 3));
}

void AImprezaSTi::SetTractionControl(ETractionControlMode Mode)
{
	TractionControl = Mode;
	TCCut = 0.0f;
	if (UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
	{
		S->TractionControlMode = (int32)Mode;
	}
}

void AImprezaSTi::SetAutoShift(bool bEnabled)
{
	bAutoShift = bEnabled;
	GetChaosVehicleMovement()->SetUseAutomaticGears(bEnabled);
	if (UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
	{
		S->bAutomaticGearbox = bEnabled;
	}
}

void AImprezaSTi::SetABS(bool bEnabled)
{
	bABS = bEnabled;
	for (int32 i = 0; i < GetChaosVehicleMovement()->GetNumWheels(); ++i)
	{
		GetChaosVehicleMovement()->SetABSEnabled(i, bEnabled);
	}
	if (UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
	{
		S->bABSEnabled = bEnabled;
	}
}

void AImprezaSTi::BeginPlay()
{
	Super::BeginPlay();
	// the driving assists are player settings (menu: Driving Assists), not per-car defaults
	if (const UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
	{
		SetTractionControl((ETractionControlMode)FMath::Clamp(S->TractionControlMode, 0, 2));
		SetAutoShift(S->bAutomaticGearbox);
		SetABS(S->bABSEnabled);
	}
}

int32 AImprezaSTi::GearForShift() const
{
	// Chaos reports gear 0 (neutral) for GearChangeTime during every shift: a second quick press must count
	// from the gear being selected, not from 0 (3rd, down, down went 3 -> 2 -> reverse)
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	const int32 Current = Move->GetCurrentGear();
	if (Current != 0)
	{
		return Current;
	}
	const bool bRecentManualShift = GetWorld()->GetTimeSeconds() - LastManualShiftTime < Move->TransmissionSetup.GearChangeTime + 0.2f;
	if (bRecentManualShift || !Move->PhysicsVehicleOutput())
	{
		return Move->GetTargetGear();          // the one we asked for
	}
	return Move->PhysicsVehicleOutput()->TargetGear;   // the automatic gearbox's (the game-thread copy is stale)
}

void AImprezaSTi::RequestGear(int32 From, int32 To)
{
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	// SetTargetGear ignores a gear equal to its game-thread copy, which the automatic gearbox leaves stale
	// (auto drove to 3rd, the copy still says 2nd: "down to 2nd" did nothing). Resync it first.
	if (To == Move->GetTargetGear() && To != From)
	{
		Move->SetTargetGear(From, true);
	}
	Move->SetTargetGear(To, false);
	LastManualShiftTime = GetWorld()->GetTimeSeconds();
}

void AImprezaSTi::ShiftUp()
{
	const int32 From = GearForShift();
	SetAutoShift(false);    // touching a shifter (key or paddle) takes over the gearbox
	RequestGear(From, FMath::Min(From + 1, 6));
}

void AImprezaSTi::ShiftDown()
{
	const int32 From = GearForShift();
	SetAutoShift(false);
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	// reverse only from (nearly) standing: past neutral at speed it stays in neutral
	const int32 Lowest = Move->GetForwardSpeed() * 0.036f > 8.0f ? 0 : -1;
	RequestGear(From, FMath::Max(From - 1, Lowest));
}

void AImprezaSTi::SetEngineSoundMuted(bool bMuted)
{
	if (EngineAudio)
	{
		EngineAudio->SetMuted(bMuted);
	}
}

void AImprezaSTi::ApplyWheelInput(UCambridgeWheelSubsystem& Wheel)
{
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	const FWheelInputState S = Wheel.GetState();
	// rim angle -> steering input, linear over half the lock-to-lock range. Chaos scales the input by
	// the speed-sensitive steering curve (made for keyboards); dividing it back out keeps the rim 1:1
	// with the road wheels, as on a real car
	const float Half = FMath::Max(Wheel.RotationRangeDeg * 0.5f, 45.0f);
	const float SpeedMph = FMath::Abs(Move->GetForwardSpeedMPH());
	const float Curve = FMath::Max(Move->SteeringSetup.SteeringCurve.GetRichCurveConst()->Eval(SpeedMph), 0.05f);
	Move->SetSteeringInput(FMath::Clamp(S.SteerDeg / Half / Curve, -1.0f, 1.0f));
	// two independent pedals: left-foot braking works
	DriverThrottle = S.Throttle;
	Move->SetBrakeInput(S.Brake);
	// (the results window: the paddles pick its buttons, UTimeTrialSubsystem takes them)
	const UTimeTrialSubsystem* TT = GetWorld() ? GetWorld()->GetSubsystem<UTimeTrialSubsystem>() : nullptr;
	if (!TT || TT->GetState() != ETimeTrialState::Finished)
	{
		if (Wheel.ConsumeUpshift())
		{
			ShiftUp();
		}
		if (Wheel.ConsumeDownshift())
		{
			ShiftDown();
		}
	}
	LastRimDeg = S.SteerDeg;
}

float AImprezaSTi::ComputeForceFeedback(const UCambridgeWheelSubsystem& Wheel, float Delta)
{
	// Self-aligning torque from a bicycle model of the front axle: it builds with slip angle up to the
	// tyres' peak (~6 deg) and then fades, so the rim goes light when the front washes out (understeer).
	// Plus low-speed "parking" weight, rim damping, and kerb / bump kicks from the front suspension.
	UChaosWheeledVehicleMovementComponent* Move = GetChaosVehicleMovement();
	const FTransform& X = GetActorTransform();
	const FVector V = X.InverseTransformVectorNoScale(GetVelocity()) / 100.0;     // m/s, x fwd, y right
	const FVector W = X.InverseTransformVectorNoScale(GetMesh()->GetPhysicsAngularVelocityInRadians());
	const double YawRate = W.Z;                                                  // rad/s, + = turning right
	const double FrontArm = (WheelRestPositions[0].X - Move->CenterOfMassOverride.X) / 100.0;   // CG -> front axle, m
	bool bFrontContact = false;
	double SteerRad = 0.0, BumpL = 0.0, BumpR = 0.0;
	for (int32 i = 0; i < 2 && i < Move->Wheels.Num(); ++i)
	{
		SteerRad += 0.5 * FMath::DegreesToRadians(Move->Wheels[i]->GetSteerAngle());
		bFrontContact |= Move->GetWheelState(i).bInContact;
		const float Susp = Move->Wheels[i]->GetSuspensionOffset();
		(i == 0 ? BumpL : BumpR) = (Susp - LastSuspension[i]) / FMath::Max(Delta, 1e-3f);
		LastSuspension[i] = Susp;
	}
	const double Fwd = FMath::Max(V.X, 0.5);
	const double Slip = SteerRad - FMath::Atan2(V.Y + YawRate * FrontArm, Fwd);      // front slip angle
	const double Peak = FMath::DegreesToRadians(6.0);
	const double S = Slip / Peak;
	const double Align = S * FMath::Exp(0.5 * (1.0 - S * S));                       // 1 at the peak, then falls off
	const double SpeedFade = FMath::Clamp(V.X / 6.0, 0.0, 1.0);
	const double RimNorm = LastRimDeg / FMath::Max(Wheel.RotationRangeDeg * 0.5f, 45.0f);
	const double RimRate = (LastRimDeg - PrevRimDeg) / FMath::Max(Delta, 1e-3f);
	PrevRimDeg = LastRimDeg;

	double T = 0.0;
	if (bFrontContact)
	{
		T -= 0.75 * Align * SpeedFade;                      // aligning torque
		T -= 0.30 * RimNorm * (1.0 - SpeedFade);            // standing / parking weight
		T += FMath::Clamp(0.0025 * (BumpR - BumpL), -0.35, 0.35);   // one-sided kerb strikes twist the rim
	}
	T -= 0.06 * RimRate / 360.0;                            // damping (the motor driver adds its own)
	return FMath::Clamp(float(T), -1.0f, 1.0f);
}

void AImprezaSTi::EnsureAssistInput()
{
	if (AssistMapping)
	{
		return;
	}
	// Code-defined actions/mapping for the extra controls, so they need no editor assets.
	auto MakeAction = [this](const TCHAR* Name) { return NewObject<UInputAction>(this, Name); };
	ShiftUpAction = MakeAction(TEXT("IA_ShiftUp"));
	ShiftDownAction = MakeAction(TEXT("IA_ShiftDown"));
	CycleTCAction = MakeAction(TEXT("IA_CycleTC"));
	ToggleAutoShiftAction = MakeAction(TEXT("IA_ToggleAutoShift"));
	ToggleABSAction = MakeAction(TEXT("IA_ToggleABS"));

	AssistMapping = NewObject<UInputMappingContext>(this, TEXT("IMC_ImprezaAssists"));
	AssistMapping->MapKey(ShiftUpAction, EKeys::E);
	AssistMapping->MapKey(ShiftUpAction, EKeys::Gamepad_FaceButton_Right);      // Forza: B shift up, X shift down
	                                                                             // (scheme: ACambridgeRacerPlayerController)
	AssistMapping->MapKey(ShiftDownAction, EKeys::Q);
	AssistMapping->MapKey(ShiftDownAction, EKeys::Gamepad_FaceButton_Left);
	AssistMapping->MapKey(CycleTCAction, EKeys::T);
	AssistMapping->MapKey(ToggleAutoShiftAction, EKeys::G);
	AssistMapping->MapKey(ToggleABSAction, EKeys::B);
}

void AImprezaSTi::PawnClientRestart()
{
	Super::PawnClientRestart();
	EnsureAssistInput();
	if (APlayerController* PC = Cast<APlayerController>(GetController()))
	{
		if (UEnhancedInputLocalPlayerSubsystem* Sub = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer()))
		{
			Sub->AddMappingContext(AssistMapping, 1);
		}
	}
}

void AImprezaSTi::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);
	EnsureAssistInput();
	if (UEnhancedInputComponent* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent))
	{
		EIC->BindAction(ShiftUpAction, ETriggerEvent::Started, this, &AImprezaSTi::ShiftUp);
		EIC->BindAction(ShiftDownAction, ETriggerEvent::Started, this, &AImprezaSTi::ShiftDown);
		EIC->BindAction(CycleTCAction, ETriggerEvent::Started, this, &AImprezaSTi::CycleTractionControl);
		EIC->BindAction(ToggleAutoShiftAction, ETriggerEvent::Started, this, &AImprezaSTi::ToggleAutoShiftInput);
		EIC->BindAction(ToggleABSAction, ETriggerEvent::Started, this, &AImprezaSTi::ToggleABSInput);
	}
}
