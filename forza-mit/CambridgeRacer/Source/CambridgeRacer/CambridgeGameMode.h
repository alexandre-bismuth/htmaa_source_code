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
};
