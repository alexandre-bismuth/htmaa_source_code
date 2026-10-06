// Wheel setups for the 2002 Subaru Impreza WRX STi (GDB-B). See ImprezaSTi.h for sources.

#pragma once

#include "CoreMinimal.h"
#include "ChaosVehicleWheel.h"
#include "ImprezaSTiWheels.generated.h"

UCLASS()
class UImprezaSTiWheelFront : public UChaosVehicleWheel
{
	GENERATED_BODY()

public:
	UImprezaSTiWheelFront();
};

UCLASS()
class UImprezaSTiWheelRear : public UChaosVehicleWheel
{
	GENERATED_BODY()

public:
	UImprezaSTiWheelRear();
};
