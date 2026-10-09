// Free-roam game mode for the Cambridge maps: the Impreza STi with the template's
// player controller blueprint (input mapping contexts + speed/gear HUD).

#pragma once

#include "CoreMinimal.h"
#include "CambridgeRacerGameMode.h"
#include "CambridgeGameMode.generated.h"

UCLASS()
class ACambridgeGameMode : public ACambridgeRacerGameMode
{
	GENERATED_BODY()

public:
	ACambridgeGameMode();

protected:
	/** Normal play (UCambridgeLaunchSubsystem::IsLaunchFlowEnabled): the car starts at the HTMAA lectures (the map's
	 *  "free_roam" start), so the map loads around it behind the launch menu. Test runs: the PlayerStart (Mass Ave). */
	virtual APawn* SpawnDefaultPawnFor_Implementation(AController* NewPlayer, AActor* StartSpot) override;
};
