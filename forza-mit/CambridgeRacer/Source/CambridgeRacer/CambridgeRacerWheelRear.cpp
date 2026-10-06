// Copyright Epic Games, Inc. All Rights Reserved.

#include "CambridgeRacerWheelRear.h"
#include "UObject/ConstructorHelpers.h"

UCambridgeRacerWheelRear::UCambridgeRacerWheelRear()
{
	AxleType = EAxleType::Rear;
	bAffectedByHandbrake = true;
	bAffectedByEngine = true;
}