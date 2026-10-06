// A batch of identical props (one mesh type within one map tile) drawn as instances.
// Built by tools/unreal/build_level.py: one actor per (prop mesh, 256 m tile), so World Partition
// still streams props by cell, while thousands of trees / lamps become a few dozen draw batches.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "PropInstancesActor.generated.h"

class UInstancedStaticMeshComponent;

UCLASS()
class APropInstancesActor : public AActor
{
	GENERATED_BODY()

public:
	APropInstancesActor();

	/** Applies the player's tree draw distance (graphics settings) as the batch streams in. */
	virtual void BeginPlay() override;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Props")
	TObjectPtr<UInstancedStaticMeshComponent> Instances;
};
