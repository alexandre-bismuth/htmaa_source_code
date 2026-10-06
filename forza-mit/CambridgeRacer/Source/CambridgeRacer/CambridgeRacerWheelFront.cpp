// Copyright Epic Games, Inc. All Rights Reserved.

#include "CambridgeRacerWheelFront.h"
#include "UObject/ConstructorHelpers.h"

UCambridgeRacerWheelFront::UCambridgeRacerWheelFront()
{
	AxleType = EAxleType::Front;
	bAffectedBySteering = true;
	MaxSteerAngle = 40.f;
}