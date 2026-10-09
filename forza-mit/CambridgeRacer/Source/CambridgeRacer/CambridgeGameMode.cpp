#include "CambridgeGameMode.h"

#include "CambridgeLaunchSubsystem.h"
#include "CambridgeRacer.h"
#include "GameFramework/Controller.h"
#include "ImprezaSTi.h"
#include "UObject/ConstructorHelpers.h"

ACambridgeGameMode::ACambridgeGameMode()
{
	static ConstructorHelpers::FClassFinder<APlayerController> TemplateController(
		TEXT("/Game/VehicleTemplate/Blueprints/BP_VehicleAdvPlayerController"));
	if (TemplateController.Succeeded())
	{
		PlayerControllerClass = TemplateController.Class;
	}
	DefaultPawnClass = AImprezaSTi::StaticClass();
}

APawn* ACambridgeGameMode::SpawnDefaultPawnFor_Implementation(AController* NewPlayer, AActor* StartSpot)
{
	FTransform Start;
	if (UCambridgeLaunchSubsystem::IsLaunchFlowEnabled() && UCambridgeLaunchSubsystem::GetFreeRoamStart(GetWorld(), Start))
	{
		UE_LOG(LogCambridgeRacer, Display, TEXT("free roam start: %s yaw %.0f (HTMAA lectures)"), *Start.GetLocation().ToString(), Start.Rotator().Yaw);
		if (NewPlayer)
		{
			NewPlayer->SetControlRotation(Start.Rotator());
		}
		return SpawnDefaultPawnAtTransform(NewPlayer, Start);
	}
	return Super::SpawnDefaultPawnFor_Implementation(NewPlayer, StartSpot);
}
