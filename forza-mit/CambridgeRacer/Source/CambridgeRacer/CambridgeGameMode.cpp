#include "CambridgeGameMode.h"

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
