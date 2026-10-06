// Editor-side helpers called from the headless Python level build (tools/unreal/build_level.py).

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "CambridgeWorldTools.generated.h"

class UPhysicsAsset;

UCLASS()
class UCambridgeWorldTools : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Sets the World Partition runtime grids of a World Partition map: the main grid gets CellSize /
	 * LoadingRange (cm), each HLOD grid keeps the engine's scheme (x2, x4, ... of the main grid).
	 * The runtime hash isn't reachable from Python (plain UPROPERTYs), hence this helper.
	 * Returns a description of the resulting grids, or an error string.
	 */
	UFUNCTION(BlueprintCallable, Category = "Cambridge|Editor")
	static FString ConfigureStreaming(UWorld* World, int32 CellSizeCm, int32 LoadingRangeCm);

	/**
	 * Editor: replaces a static mesh's simple collision with one upright capsule (trunk / pole) of the
	 * given radius and height (mesh units, cm), standing on the mesh origin, and makes the mesh use
	 * simple collision for everything. Returns false if the mesh has no body setup.
	 */
	UFUNCTION(BlueprintCallable, Category = "Cambridge|Editor")
	static bool SetTrunkCollision(UStaticMesh* Mesh, float RadiusCm, float HeightCm);

	/**
	 * Editor: replaces the collision of a physics asset's root body with boxes (centres / full sizes in
	 * cm, mesh space) and marks it dirty. Returns a description of the previous and new geometry.
	 * Used for the STi, whose physics asset is the template sports car's (a wider car).
	 */
	UFUNCTION(BlueprintCallable, Category = "Cambridge|Editor")
	static FString SetChassisBoxes(UPhysicsAsset* PhysicsAsset, const TArray<FVector>& Centres, const TArray<FVector>& Sizes);

	/** Describes the World Partition runtime grids (name, cell size, loading range) of a map. */
	UFUNCTION(BlueprintCallable, Category = "Cambridge|Editor")
	static FString DescribeStreaming(UWorld* World);
};
