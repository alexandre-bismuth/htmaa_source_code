// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "CambridgeRacerPawn.h"
#include "CambridgeRacerSportsCar.generated.h"

/**
 *  Sports car wheeled vehicle implementation
 */
UCLASS(abstract)
class ACambridgeRacerSportsCar : public ACambridgeRacerPawn
{
	GENERATED_BODY()
	
public:

	ACambridgeRacerSportsCar();
};
