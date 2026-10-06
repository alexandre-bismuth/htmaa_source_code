#include "PropInstancesActor.h"

#include "CambridgeGameUserSettings.h"
#include "Components/InstancedStaticMeshComponent.h"

APropInstancesActor::APropInstancesActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Instances = CreateDefaultSubobject<UInstancedStaticMeshComponent>(TEXT("Instances"));
	Instances->SetMobility(EComponentMobility::Static);
	RootComponent = Instances;
}

void APropInstancesActor::BeginPlay()
{
	Super::BeginPlay();
	if (const UCambridgeGameUserSettings* Settings = UCambridgeGameUserSettings::Get())
	{
		Settings->ApplyTreeDistance(Instances);
	}
}
