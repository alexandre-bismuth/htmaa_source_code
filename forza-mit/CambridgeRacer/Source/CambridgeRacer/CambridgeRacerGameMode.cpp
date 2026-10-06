// Copyright Epic Games, Inc. All Rights Reserved.

#include "CambridgeRacerGameMode.h"
#include "CambridgeRacerPlayerController.h"

ACambridgeRacerGameMode::ACambridgeRacerGameMode()
{
	PlayerControllerClass = ACambridgeRacerPlayerController::StaticClass();
}
