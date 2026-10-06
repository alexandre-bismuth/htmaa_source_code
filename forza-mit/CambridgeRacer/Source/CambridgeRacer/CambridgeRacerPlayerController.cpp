// Copyright Epic Games, Inc. All Rights Reserved.


#include "CambridgeRacerPlayerController.h"
#include "CambridgeRacerPawn.h"
#include "CambridgeRacerUI.h"
#include "EnhancedInputSubsystems.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Blueprint/UserWidget.h"
#include "CambridgeRacer.h"
#include "Kismet/GameplayStatics.h"
#include "GameFramework/PlayerStart.h"
#include "Widgets/Input/SVirtualJoystick.h"

namespace
{
	/**
	 * forza-MIT control scheme (Forza Horizon gamepad layout), applied to a transient copy of each template context.
	 * The template's IMC_Vehicle_Default is not edited (Content/ is restored from the engine template on a fresh
	 * clone). It maps gamepad X to the throttle (X is shift down), A to the brake, LB to the handbrake, View to the
	 * camera (View opens the full map), and Menu / Backspace to the vehicle reset (Menu opens the settings,
	 * Backspace is "leave / back"). Result, one role per button while driving:
	 *   RT throttle, LT brake / reverse, left stick steer, right stick look, A handbrake, B shift up, X shift down
	 *   (both in AImprezaSTi's assist context), Y reset (free roam; in an event the time trial takes Y: tap = back
	 *   on track, hold = restart), RB camera, View full map, Menu settings, D-pad down = back on track /
	 *   hold restart, D-pad up hold = leave the event (UTimeTrialSubsystem).
	 *   Keyboard: W/S or Up/Down throttle / brake, A/D steer, Space handbrake, E/Q shift, Tab camera, R reset
	 *   (back on track in an event), Backspace leave / back, M map, Esc settings.
	 */
	UInputMappingContext* ApplyControlScheme(UInputMappingContext* Source, UObject* Outer)
	{
		if (!Source)
		{
			return nullptr;
		}
		UInputMappingContext* Ctx = DuplicateObject<UInputMappingContext>(Source, Outer,
			MakeUniqueObjectName(Outer, UInputMappingContext::StaticClass(), FName(*(Source->GetName() + TEXT("_Cambridge")))));
		TMap<FString, const UInputAction*> Actions;
		for (const FEnhancedActionKeyMapping& M : Ctx->GetMappings())
		{
			if (M.Action)
			{
				Actions.Add(M.Action->GetName(), M.Action);
			}
		}
		auto Move = [&](const TCHAR* Action, const FKey& From, const FKey& To)
		{
			const UInputAction* A = Actions.FindRef(Action);
			if (!A)
			{
				return;
			}
			if (From.IsValid())
			{
				Ctx->UnmapKey(A, From);
			}
			if (To.IsValid() && !Ctx->GetMappings().ContainsByPredicate([A, &To](const FEnhancedActionKeyMapping& M) { return M.Action == A && M.Key == To; }))
			{
				Ctx->MapKey(A, To);
			}
		};
		Move(TEXT("IA_Throttle"), EKeys::Gamepad_FaceButton_Left, EKeys::Invalid);           // X = shift down
		Move(TEXT("IA_Brake"), EKeys::Gamepad_FaceButton_Bottom, EKeys::Invalid);            // LT brakes; A is the handbrake
		Move(TEXT("IA_Handbrake"), EKeys::Gamepad_LeftShoulder, EKeys::Gamepad_FaceButton_Bottom);
		Move(TEXT("IA_ToggleCamera"), EKeys::Gamepad_Special_Left, EKeys::Gamepad_RightShoulder);   // View = full map
		Move(TEXT("IA_Reset"), EKeys::Gamepad_Special_Right, EKeys::Gamepad_FaceButton_Top);       // Menu = settings
		Move(TEXT("IA_Reset"), EKeys::BackSpace, EKeys::R);                                          // Backspace = leave / back
		// log the gamepad result once (verification: every gamepad key has one action)
		TMap<FKey, TArray<FString>> PadKeys;
		for (const FEnhancedActionKeyMapping& M : Ctx->GetMappings())
		{
			if (M.Action && M.Key.IsGamepadKey())
			{
				PadKeys.FindOrAdd(M.Key).Add(M.Action->GetName());
			}
		}
		FString Line;
		for (const TPair<FKey, TArray<FString>>& P : PadKeys)
		{
			Line += FString::Printf(TEXT(" %s=%s"), *P.Key.ToString(), *FString::Join(P.Value, TEXT("+")));
		}
		UE_LOG(LogCambridgeRacer, Display, TEXT("control scheme %s:%s"), *Source->GetName(), *Line);
		return Ctx;
	}
}

void ACambridgeRacerPlayerController::BeginPlay()
{
	Super::BeginPlay();
	
	// ensure we're attached to the vehicle pawn so that World Partition streaming works correctly
	bAttachToPawn = true;
}

void ACambridgeRacerPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();
	
	// only add IMCs for local player controllers
	if (IsLocalPlayerController())
	{
		// Add Input Mapping Contexts
		if (UEnhancedInputLocalPlayerSubsystem* Subsystem = ULocalPlayer::GetSubsystem<UEnhancedInputLocalPlayerSubsystem>(GetLocalPlayer()))
		{
			if (SchemeContexts.Num() == 0)      // (built once; SetupInputComponent can run again)
			{
				for (UInputMappingContext* CurrentContext : DefaultMappingContexts)
				{
					if (UInputMappingContext* Scheme = ApplyControlScheme(CurrentContext, this))
					{
						SchemeContexts.Add(Scheme);
					}
				}
			}
			for (UInputMappingContext* Scheme : SchemeContexts)
			{
				Subsystem->AddMappingContext(Scheme, 0);
			}

			// only add these IMCs if we're not using mobile touch input
			if (!ShouldUseTouchControls())
			{
				for (UInputMappingContext* CurrentContext : MobileExcludedMappingContexts)
				{
					Subsystem->AddMappingContext(CurrentContext, 0);
				}
			}

			if (bUseSteeringWheelControls)
			{
				Subsystem->AddMappingContext(SteeringWheelInputMappingContext, 0);
			}
		}
	}

	// only spawn UI on local player controllers
	if (IsLocalPlayerController())
	{
		if (ShouldUseTouchControls())
		{
			// spawn the mobile controls widget
			MobileControlsWidget = CreateWidget<UUserWidget>(this, MobileControlsWidgetClass);

			if (MobileControlsWidget)
			{
				// add the controls to the player screen
				MobileControlsWidget->AddToPlayerScreen(0);

			} else {

				UE_LOG(LogCambridgeRacer, Error, TEXT("Could not spawn mobile controls widget."));

			}
		}
		

		// the template's MPH widget is replaced by the Slate driving HUD (UTimeTrialSubsystem)
		VehicleUI = bUseTemplateHUD ? CreateWidget<UCambridgeRacerUI>(this, VehicleUIClass) : nullptr;

		if (VehicleUI)
		{
			VehicleUI->AddToPlayerScreen(0);

		} else if (bUseTemplateHUD) {

			UE_LOG(LogCambridgeRacer, Error, TEXT("Could not spawn vehicle UI widget."));

		}
	}
}

void ACambridgeRacerPlayerController::Tick(float Delta)
{
	Super::Tick(Delta);

	if (IsValid(VehiclePawn) && IsValid(VehicleUI))
	{
		VehicleUI->UpdateSpeed(VehiclePawn->GetChaosVehicleMovement()->GetForwardSpeed());
		VehicleUI->UpdateGear(VehiclePawn->GetChaosVehicleMovement()->GetCurrentGear());
	}
}

void ACambridgeRacerPlayerController::OnPossess(APawn* InPawn)
{
	Super::OnPossess(InPawn);

	// get a pointer to the controlled pawn
	VehiclePawn = CastChecked<ACambridgeRacerPawn>(InPawn);

	// subscribe to the pawn's OnDestroyed delegate
	VehiclePawn->OnDestroyed.AddDynamic(this, &ACambridgeRacerPlayerController::OnPawnDestroyed);
}

void ACambridgeRacerPlayerController::OnPawnDestroyed(AActor* DestroyedPawn)
{
	// find the player start
	TArray<AActor*> ActorList;
	UGameplayStatics::GetAllActorsOfClass(GetWorld(), APlayerStart::StaticClass(), ActorList);

	if (ActorList.Num() > 0)
	{
		// spawn a vehicle at the player start
		const FTransform SpawnTransform = ActorList[0]->GetActorTransform();

		if (ACambridgeRacerPawn* RespawnedVehicle = GetWorld()->SpawnActor<ACambridgeRacerPawn>(DestroyedPawn ? DestroyedPawn->GetClass() : VehiclePawnClass.Get(), SpawnTransform))
		{
			// possess the vehicle
			Possess(RespawnedVehicle);
		}
	}
}

bool ACambridgeRacerPlayerController::ShouldUseTouchControls() const
{
	// are we on a mobile platform? Should we force touch?
	return SVirtualJoystick::ShouldDisplayTouchInterface() || bForceTouchControls;
}
