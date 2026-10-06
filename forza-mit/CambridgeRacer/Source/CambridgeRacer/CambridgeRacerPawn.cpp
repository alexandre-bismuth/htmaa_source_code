// Copyright Epic Games, Inc. All Rights Reserved.

#include "CambridgeRacerPawn.h"
#include "CambridgeRacerWheelFront.h"
#include "CambridgeRacerWheelRear.h"
#include "Components/SkeletalMeshComponent.h"
#include "GameFramework/SpringArmComponent.h"
#include "Camera/CameraComponent.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "InputActionValue.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "CambridgeRacer.h"
#include "Camera/PlayerCameraManager.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "MinimapSubsystem.h"
#include "TimeTrialSubsystem.h"
#include "TimerManager.h"

#define LOCTEXT_NAMESPACE "VehiclePawn"

ACambridgeRacerPawn::ACambridgeRacerPawn()
{
	// construct the front camera boom
	FrontSpringArm = CreateDefaultSubobject<USpringArmComponent>(TEXT("Front Spring Arm"));
	FrontSpringArm->SetupAttachment(GetMesh());
	FrontSpringArm->TargetArmLength = 0.0f;
	FrontSpringArm->bDoCollisionTest = false;
	FrontSpringArm->bEnableCameraRotationLag = true;
	FrontSpringArm->CameraRotationLagSpeed = 15.0f;
	FrontSpringArm->SetRelativeLocation(FVector(30.0f, 0.0f, 120.0f));

	FrontCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("Front Camera"));
	FrontCamera->SetupAttachment(FrontSpringArm);
	FrontCamera->bAutoActivate = false;

	// construct the back camera boom
	BackSpringArm = CreateDefaultSubobject<USpringArmComponent>(TEXT("Back Spring Arm"));
	BackSpringArm->SetupAttachment(GetMesh());
	BackSpringArm->TargetArmLength = 650.0f;
	BackSpringArm->SocketOffset.Z = 150.0f;
	BackSpringArm->bDoCollisionTest = false;
	BackSpringArm->bInheritPitch = false;
	BackSpringArm->bInheritRoll = false;
	BackSpringArm->bEnableCameraRotationLag = true;
	BackSpringArm->CameraRotationLagSpeed = 2.0f;
	BackSpringArm->CameraLagMaxDistance = 50.0f;

	BackCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("Back Camera"));
	BackCamera->SetupAttachment(BackSpringArm);

	// Configure the car mesh
	GetMesh()->SetSimulatePhysics(true);
	GetMesh()->SetCollisionProfileName(FName("Vehicle"));

	// get the Chaos Wheeled movement component
	ChaosVehicleMovement = CastChecked<UChaosWheeledVehicleMovementComponent>(GetVehicleMovement());

}

void ACambridgeRacerPawn::SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent)
{
	Super::SetupPlayerInputComponent(PlayerInputComponent);

	if (UEnhancedInputComponent* EnhancedInputComponent = Cast<UEnhancedInputComponent>(PlayerInputComponent))
	{
		// steering 
		EnhancedInputComponent->BindAction(SteeringAction, ETriggerEvent::Triggered, this, &ACambridgeRacerPawn::Steering);
		EnhancedInputComponent->BindAction(SteeringAction, ETriggerEvent::Completed, this, &ACambridgeRacerPawn::Steering);

		// throttle 
		EnhancedInputComponent->BindAction(ThrottleAction, ETriggerEvent::Triggered, this, &ACambridgeRacerPawn::Throttle);
		EnhancedInputComponent->BindAction(ThrottleAction, ETriggerEvent::Completed, this, &ACambridgeRacerPawn::Throttle);

		// break 
		EnhancedInputComponent->BindAction(BrakeAction, ETriggerEvent::Triggered, this, &ACambridgeRacerPawn::Brake);
		EnhancedInputComponent->BindAction(BrakeAction, ETriggerEvent::Started, this, &ACambridgeRacerPawn::StartBrake);
		EnhancedInputComponent->BindAction(BrakeAction, ETriggerEvent::Completed, this, &ACambridgeRacerPawn::StopBrake);
		// IA_Brake (a template asset) has Pressed / Released triggers, so the events above only carry the value
		// at the press: gamepad LT braked at ~50 % however hard it was squeezed. Tick follows the live axis.
		EnhancedInputComponent->BindActionValue(BrakeAction);

		// handbrake 
		EnhancedInputComponent->BindAction(HandbrakeAction, ETriggerEvent::Started, this, &ACambridgeRacerPawn::StartHandbrake);
		EnhancedInputComponent->BindAction(HandbrakeAction, ETriggerEvent::Completed, this, &ACambridgeRacerPawn::StopHandbrake);

		// look around 
		EnhancedInputComponent->BindAction(LookAroundAction, ETriggerEvent::Triggered, this, &ACambridgeRacerPawn::LookAround);

		// toggle camera 
		EnhancedInputComponent->BindAction(ToggleCameraAction, ETriggerEvent::Triggered, this, &ACambridgeRacerPawn::ToggleCamera);

		// reset the vehicle 
		EnhancedInputComponent->BindAction(ResetVehicleAction, ETriggerEvent::Triggered, this, &ACambridgeRacerPawn::ResetVehicle);
	}
	else
	{
		UE_LOG(LogCambridgeRacer, Error, TEXT("'%s' Failed to find an Enhanced Input component! This template is built to use the Enhanced Input system. If you intend to use the legacy system, then you will need to update this C++ file."), *GetNameSafe(this));
	}
}

void ACambridgeRacerPawn::BeginPlay()
{
	Super::BeginPlay();

	// set up the flipped check timer
	GetWorld()->GetTimerManager().SetTimer(FlipCheckTimer, this, &ACambridgeRacerPawn::FlippedCheck, FlipCheckTime, true);
}

void ACambridgeRacerPawn::EndPlay(EEndPlayReason::Type EndPlayReason)
{
	// clear the flipped check timer
	GetWorld()->GetTimerManager().ClearTimer(FlipCheckTimer);

	Super::EndPlay(EndPlayReason);
}

void ACambridgeRacerPawn::Tick(float Delta)
{
	Super::Tick(Delta);

	// analog brake (gamepad LT): the live axis while it is pressed, then 0 once on release. Inputs that don't
	// come from the brake key (wheel pedals, the time trials' autopilot and results hold) are left alone.
	if (const UEnhancedInputComponent* EIC = BrakeAction ? Cast<UEnhancedInputComponent>(InputComponent) : nullptr)
	{
		const float BrakeAxis = FMath::Clamp(EIC->GetBoundActionValue(BrakeAction).Get<float>(), 0.0f, 1.0f);
		if (BrakeAxis > 0.0f || bBrakeAxisHeld)
		{
			ChaosVehicleMovement->SetBrakeInput(BrakeAxis);
			bBrakeAxisHeld = BrakeAxis > 0.0f;
		}
	}

	// assists (e.g. traction control) depend on wheel state, so re-filter the throttle every frame
	ChaosVehicleMovement->SetThrottleInput(FilterThrottle(DriverThrottle, Delta));

	// add some angular damping if the vehicle is in midair
	bool bMovingOnGround = ChaosVehicleMovement->IsMovingOnGround();
	const float Damping = bMovingOnGround ? 0.0f : 3.0f;
	if (GetMesh()->GetAngularDamping() != Damping)     // (setting it every frame dirties the physics body)
	{
		GetMesh()->SetAngularDamping(Damping);
	}

	// SnapCamera: the rotation lag comes back once the arms have caught up with the teleport
	if (CameraSnapTicks > 0 && --CameraSnapTicks == 0)
	{
		BackSpringArm->bEnableCameraRotationLag = bBackArmLag;
		FrontSpringArm->bEnableCameraRotationLag = bFrontArmLag;
	}

	// realign the camera yaw to face front
	float CameraYaw = BackSpringArm->GetRelativeRotation().Yaw;
	CameraYaw = FMath::FInterpTo(CameraYaw, 0.0f, Delta, 1.0f);

	BackSpringArm->SetRelativeRotation(FRotator(0.0f, CameraYaw, 0.0f));
}

void ACambridgeRacerPawn::Steering(const FInputActionValue& Value)
{
	// route the input
	DoSteering(Value.Get<float>());
}

void ACambridgeRacerPawn::Throttle(const FInputActionValue& Value)
{
	// route the input
	DoThrottle(Value.Get<float>());
}

void ACambridgeRacerPawn::Brake(const FInputActionValue& Value)
{
	// route the input
	DoBrake(Value.Get<float>());
}

void ACambridgeRacerPawn::StartBrake(const FInputActionValue& Value)
{
	// route the input
	DoBrakeStart();
}

void ACambridgeRacerPawn::StopBrake(const FInputActionValue& Value)
{
	// route the input
	DoBrakeStop();
}

void ACambridgeRacerPawn::StartHandbrake(const FInputActionValue& Value)
{
	// route the input
	DoHandbrakeStart();
}

void ACambridgeRacerPawn::StopHandbrake(const FInputActionValue& Value)
{
	// route the input
	DoHandbrakeStop();
}

void ACambridgeRacerPawn::LookAround(const FInputActionValue& Value)
{
	// route the input
	DoLookAround(Value.Get<float>());
}

void ACambridgeRacerPawn::ToggleCamera(const FInputActionValue& Value)
{
	// route the input
	DoToggleCamera();
}

void ACambridgeRacerPawn::ResetVehicle(const FInputActionValue& Value)
{
	// route the input
	DoResetVehicle();
}

void ACambridgeRacerPawn::DoSteering(float SteeringValue)
{
	// add the input
	ChaosVehicleMovement->SetSteeringInput(SteeringValue);
}

void ACambridgeRacerPawn::DoThrottle(float ThrottleValue)
{
	// add the input (through the assists filter; Tick keeps re-applying it)
	DriverThrottle = ThrottleValue;
	ChaosVehicleMovement->SetThrottleInput(FilterThrottle(DriverThrottle, 0.0f));

	// reset the brake input
	ChaosVehicleMovement->SetBrakeInput(0.0f);
}

void ACambridgeRacerPawn::DoBrake(float BrakeValue)
{
	// add the input
	ChaosVehicleMovement->SetBrakeInput(BrakeValue);

	// reset the throttle input
	DriverThrottle = 0.0f;
	ChaosVehicleMovement->SetThrottleInput(0.0f);
}

void ACambridgeRacerPawn::DoBrakeStart()
{
	// call the Blueprint hook for the brake lights
	BrakeLights(true);
}

void ACambridgeRacerPawn::DoBrakeStop()
{
	// call the Blueprint hook for the brake lights
	BrakeLights(false);

	// reset brake input to zero
	ChaosVehicleMovement->SetBrakeInput(0.0f);
}

void ACambridgeRacerPawn::DoHandbrakeStart()
{
	// add the input
	ChaosVehicleMovement->SetHandbrakeInput(true);

	// call the Blueprint hook for the break lights
	BrakeLights(true);
}

void ACambridgeRacerPawn::DoHandbrakeStop()
{
	// add the input
	ChaosVehicleMovement->SetHandbrakeInput(false);

	// call the Blueprint hook for the break lights
	BrakeLights(false);
}

void ACambridgeRacerPawn::DoLookAround(float YawDelta)
{
	// rotate the spring arm
	BackSpringArm->AddLocalRotation(FRotator(0.0f, YawDelta, 0.0f));
}

void ACambridgeRacerPawn::DoToggleCamera()
{
	// toggle the active camera flag
	bFrontCameraActive = !bFrontCameraActive;

	FrontCamera->SetActive(bFrontCameraActive);
	BackCamera->SetActive(!bFrontCameraActive);
}

void ACambridgeRacerPawn::SnapCamera()
{
	// (the arms tick after the pawn: with the lag off for their next update they jump to the new heading)
	if (CameraSnapTicks == 0)
	{
		bBackArmLag = BackSpringArm->bEnableCameraRotationLag;
		bFrontArmLag = FrontSpringArm->bEnableCameraRotationLag;
	}
	BackSpringArm->SetRelativeRotation(FRotator::ZeroRotator);     // (and no look-around offset)
	BackSpringArm->bEnableCameraRotationLag = false;
	FrontSpringArm->bEnableCameraRotationLag = false;
	CameraSnapTicks = 2;
}

bool ACambridgeRacerPawn::FindRoadResetSpot(FTransform& OutSpot, FString& OutStreet, bool& bOutGround) const
{
	bOutGround = false;
	const UMinimapSubsystem* Map = UMinimapSubsystem::Get(this);
	UWorld* World = GetWorld();
	FVector2D Road, Dir;
	double Dist;
	if (!Map || !World || !Map->NearestRoad(FVector2D(GetActorLocation()), Road, Dir, Dist, &OutStreet))
	{
		return false;
	}
	// along the street, the way the car points (its nose, even on its roof; its motion if it stands on its nose)
	FVector2D Heading(GetActorForwardVector());
	if (Heading.SizeSquared() < 0.04)
	{
		Heading = FVector2D(GetVelocity());
	}
	if (FVector2D::DotProduct(Heading, Dir) < 0.0)
	{
		Dir = -Dir;
	}
	const FVector2D Right(-Dir.Y, Dir.X);       // (UE: +Y is right of +X)
	const FRotator Rot(0.0f, float(FMath::RadiansToDegrees(FMath::Atan2(Dir.Y, Dir.X))), 0.0f);
	// candidate spots (along, right of the centreline; cm): the right-hand lane first (2 m right: inside the lane of a
	// two-way street, still on a narrow one-way one), then nearer the centre / further out, then a car length or two
	// along the street. The first spot clear of poles, hydrants, trees, parked props and walls wins.
	static const FVector2D Spots[] = { FVector2D(0, 200), FVector2D(0, 120), FVector2D(0, 300), FVector2D(0, 0), FVector2D(600, 200), FVector2D(-600, 200),
		FVector2D(600, 0), FVector2D(-600, 0), FVector2D(1200, 200), FVector2D(-1200, 200), FVector2D(0, -200) };
	const ECollisionChannel Channel = GetMesh()->GetCollisionObjectType();
	const FCollisionResponseParams Response(GetMesh()->GetCollisionResponseToChannels());
	FCollisionQueryParams Q(SCENE_QUERY_STAT(CarRoadReset), false, this);
	const FCollisionShape Box = FCollisionShape::MakeBox(FVector(240.0f, 105.0f, 45.0f));
	FVector First = FVector::ZeroVector;
	bool bFirstGround = false;
	for (int32 k = 0; k < UE_ARRAY_COUNT(Spots); ++k)
	{
		const FVector2D P = Road + Dir * Spots[k].X + Right * Spots[k].Y;
		// onto the road surface (roads are at z = 0; traced from 3 m up so a traffic-light arm or a canopy can't catch it)
		FHitResult Hit;
		const bool bGround = World->LineTraceSingleByChannel(Hit, FVector(P.X, P.Y, 300.0), FVector(P.X, P.Y, -800.0), ECC_Visibility, Q);
		const FVector At(P.X, P.Y, (bGround ? Hit.ImpactPoint.Z : 0.0) + 60.0);
		if (k == 0)
		{
			First = At;
			bFirstGround = bGround;
		}
		// a car-sized box from 65 cm up (above the kerbs) to 1.55 m
		if (!World->OverlapBlockingTestByChannel(At + FVector(0.0, 0.0, 50.0), Rot.Quaternion(), Channel, Box, Q, Response))
		{
			OutSpot = FTransform(Rot, At);
			bOutGround = bGround;
			return true;
		}
	}
	OutSpot = FTransform(Rot, First);     // all blocked (a crowded junction): the lane anyway
	bOutGround = bFirstGround;
	return true;
}

void ACambridgeRacerPawn::DoResetVehicle()
{
	UWorld* World = GetWorld();
	UTimeTrialSubsystem* TT = World && IsPlayerControlled() ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr;
	// during an event the time trial owns resets (it takes R / Y itself: tap = back on track). What gets here then is
	// the flip check: back before the next checkpoint like a tap of R, or upright in place on the grid
	if (TT && TT->IsInEvent() && TT->GetState() != ETimeTrialState::Finished)
	{
		if (TT->GetState() == ETimeTrialState::Running)
		{
			TT->ResetToLastGate();
			return;
		}
	}
	else
	{
		// free roam (and the results screen): back on the nearest street, in its lane, facing the way the car pointed
		FTransform Spot;
		FString Street;
		bool bGround = false;
		if (FindRoadResetSpot(Spot, Street, bGround))
		{
			const FVector From = GetActorLocation();
			SetActorTransform(Spot, false, nullptr, ETeleportType::TeleportPhysics);
			if (!bGround && World)
			{
				// the street's cell isn't streamed in (only if the car was far from any street): load it before the car
				// can fall through (a blocking flush next frame, UGameEngine::Tick)
				World->bRequestedBlockOnAsyncLoading = true;
			}
			GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
			GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
			SnapCamera();
			if (const APlayerController* PC = Cast<APlayerController>(GetController()); PC && PC->PlayerCameraManager)
			{
				PC->PlayerCameraManager->StartCameraFade(1.0f, 0.0f, 0.45f, FLinearColor::Black, false, false);   // a short fade in
			}
			if (TT)
			{
				TT->NotifyRoadReset(Street);
			}
			UE_LOG(LogCambridgeRacer, Display, TEXT("reset: back on the road (%s) at (%.0f, %.0f, %.0f) yaw %.0f, %.1f m from (%.0f, %.0f, %.0f)%s"),
				Street.IsEmpty() ? TEXT("unnamed street") : *Street, Spot.GetLocation().X, Spot.GetLocation().Y, Spot.GetLocation().Z,
				Spot.Rotator().Yaw, FVector::Dist(From, Spot.GetLocation()) / 100.0, From.X, From.Y, From.Z,
				bGround ? TEXT("") : TEXT(", its cell not loaded yet: streaming it in"));
			return;
		}
	}

	// no road graph (or on the grid in a countdown): upright, slightly above where it is
	FVector ResetLocation = GetActorLocation() + FVector(0.0f, 0.0f, 50.0f);

	// reset to our yaw. Ignore pitch and roll
	FRotator ResetRotation = GetActorRotation();
	ResetRotation.Pitch = 0.0f;
	ResetRotation.Roll = 0.0f;

	// teleport the actor to the reset spot and reset physics
	SetActorTransform(FTransform(ResetRotation, ResetLocation, FVector::OneVector), false, nullptr, ETeleportType::TeleportPhysics);

	GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
}

void ACambridgeRacerPawn::FlippedCheck()
{
	// below the world (the ground under it was not loaded): back on the road now
	if (GetActorLocation().Z < -5000.0)
	{
		UE_LOG(LogCambridgeRacer, Display, TEXT("flip check: the car is %.0f m below the street, resetting"), -GetActorLocation().Z / 100.0);
		bPreviousFlipCheck = false;
		DoResetVehicle();
		return;
	}

	// check the difference in angle between the mesh's up vector and world up: upside down, or lying on its side
	// (it can't drive off from there either) at a crawl
	const float UpDot = FVector::DotProduct(FVector::UpVector, GetMesh()->GetUpVector());
	const bool bOnItsSide = UpDot < 0.3f && GetVelocity().Size() < 300.0f;

	if (UpDot < FlipCheckMinDot || bOnItsSide)
	{
		// is this the second time we've checked that the vehicle is still flipped?
		if (bPreviousFlipCheck)
		{
			// reset the vehicle to upright
			DoResetVehicle();
		}
		
		// set the flipped check flag so the next check resets the car
		bPreviousFlipCheck = true;

	} else {

		// we're upright. reset the flipped check flag
		bPreviousFlipCheck = false;
	}
}

#undef LOCTEXT_NAMESPACE