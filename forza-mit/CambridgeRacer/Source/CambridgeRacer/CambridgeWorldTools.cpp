#include "CambridgeWorldTools.h"

#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "PhysicsEngine/BodySetup.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "GameFramework/WorldSettings.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/RuntimeHashSet/RuntimePartition.h"
#include "WorldPartition/RuntimeHashSet/WorldPartitionRuntimeHashSet.h"

namespace
{
	// the partition fields are private UPROPERTYs: go through reflection
	int64 GetInt(const UObject* O, FName Name)
	{
		const FNumericProperty* P = O ? FindFProperty<FNumericProperty>(O->GetClass(), Name) : nullptr;
		return P ? P->GetSignedIntPropertyValue(P->ContainerPtrToValuePtr<void>(O)) : -1;
	}

	void SetInt(UObject* O, FName Name, int64 Value)
	{
		if (FNumericProperty* P = O ? FindFProperty<FNumericProperty>(O->GetClass(), Name) : nullptr)
		{
			O->Modify();
			P->SetIntPropertyValue(P->ContainerPtrToValuePtr<void>(O), Value);
		}
	}

	TArray<FRuntimePartitionDesc>* GetPartitions(UWorld* World, FString& Error)
	{
		UWorldPartition* WP = World ? World->GetWorldPartition() : nullptr;
		UWorldPartitionRuntimeHashSet* Hash = WP ? Cast<UWorldPartitionRuntimeHashSet>(WP->RuntimeHash) : nullptr;
		if (!Hash)
		{
			Error = WP ? TEXT("error: runtime hash is not a WorldPartitionRuntimeHashSet") : TEXT("error: not a World Partition map");
			return nullptr;
		}
		const FArrayProperty* P = FindFProperty<FArrayProperty>(Hash->GetClass(), TEXT("RuntimePartitions"));
		if (!P)
		{
			Error = TEXT("error: RuntimePartitions property not found");
			return nullptr;
		}
		Hash->Modify();
		return P->ContainerPtrToValuePtr<TArray<FRuntimePartitionDesc>>(Hash);
	}

	FString Describe(const UObject* Layer)
	{
		return FString::Printf(TEXT("%s(cell=%lld, range=%lld)"), Layer ? *Layer->GetClass()->GetName() : TEXT("null"),
			GetInt(Layer, TEXT("CellSize")), GetInt(Layer, TEXT("LoadingRange")));
	}
}

FString UCambridgeWorldTools::ConfigureStreaming(UWorld* World, int32 CellSizeCm, int32 LoadingRangeCm)
{
	FString Error;
	TArray<FRuntimePartitionDesc>* Partitions = GetPartitions(World, Error);
	if (!Partitions)
	{
		return Error;
	}
	for (FRuntimePartitionDesc& Desc : *Partitions)
	{
		SetInt(Desc.MainLayer, TEXT("CellSize"), CellSizeCm);
		SetInt(Desc.MainLayer, TEXT("LoadingRange"), LoadingRangeCm);
		for (int32 i = 0; i < Desc.HLODSetups.Num(); ++i)
		{
			SetInt(Desc.HLODSetups[i].PartitionLayer, TEXT("CellSize"), int64(CellSizeCm) * (2 << i));
			SetInt(Desc.HLODSetups[i].PartitionLayer, TEXT("LoadingRange"), int64(LoadingRangeCm) * (2 << i));
		}
	}
	World->GetWorldSettings()->MarkPackageDirty();
	return DescribeStreaming(World);
}

FString UCambridgeWorldTools::DescribeStreaming(UWorld* World)
{
	FString Error;
	TArray<FRuntimePartitionDesc>* Partitions = GetPartitions(World, Error);
	if (!Partitions)
	{
		return Error;
	}
	TArray<FString> Out;
	for (const FRuntimePartitionDesc& Desc : *Partitions)
	{
		FString S = Desc.Name.ToString() + TEXT(": ") + Describe(Desc.MainLayer);
		for (const FRuntimePartitionHLODSetup& H : Desc.HLODSetups)
		{
			S += TEXT(" | ") + H.Name.ToString() + TEXT(": ") + Describe(H.PartitionLayer);
		}
		Out.Add(S);
	}
	return FString::Join(Out, TEXT("; "));
}

bool UCambridgeWorldTools::SetTrunkCollision(UStaticMesh* Mesh, float RadiusCm, float HeightCm)
{
	UBodySetup* Body = Mesh ? Mesh->GetBodySetup() : nullptr;
	if (!Body)
	{
		return false;
	}
	Body->Modify();
	Body->RemoveSimpleCollision();
	FKSphylElem Trunk(RadiusCm, FMath::Max(HeightCm - 2.0f * RadiusCm, 0.0f));
	Trunk.Center = FVector(0.0, 0.0, HeightCm * 0.5);
	Body->AggGeom.SphylElems.Add(Trunk);
	Body->CollisionTraceFlag = CTF_UseSimpleAsComplex;
	Body->InvalidatePhysicsData();
	Body->CreatePhysicsMeshes();
	Mesh->MarkPackageDirty();
	return true;
}

FString UCambridgeWorldTools::SetChassisBoxes(UPhysicsAsset* PhysicsAsset, const TArray<FVector>& Centres, const TArray<FVector>& Sizes)
{
	if (!PhysicsAsset || PhysicsAsset->SkeletalBodySetups.Num() == 0 || Centres.Num() != Sizes.Num())
	{
		return TEXT("error: no physics asset / bodies, or mismatched arrays");
	}
	// the chassis body: the one that isn't on a wheel bone (the template also has wheel spheres)
	USkeletalBodySetup* Body = nullptr;
	FString All;
	for (USkeletalBodySetup* B : PhysicsAsset->SkeletalBodySetups)
	{
		All += B->BoneName.ToString() + TEXT(" ");
		if (B && !B->BoneName.ToString().Contains(TEXT("Wheel")))
		{
			Body = B;
		}
	}
	if (!Body)
	{
		return TEXT("error: no chassis body among: ") + All;
	}
	FString Out = FString::Printf(TEXT("bodies=%d [%s] chassis=%s before: boxes=%d convex=%d sphyls=%d spheres=%d"), PhysicsAsset->SkeletalBodySetups.Num(), *All,
		*Body->BoneName.ToString(), Body->AggGeom.BoxElems.Num(), Body->AggGeom.ConvexElems.Num(), Body->AggGeom.SphylElems.Num(), Body->AggGeom.SphereElems.Num());
	for (const FKBoxElem& B : Body->AggGeom.BoxElems)
	{
		Out += FString::Printf(TEXT(" [box c=%s %.0fx%.0fx%.0f]"), *B.Center.ToString(), B.X, B.Y, B.Z);
	}
	PhysicsAsset->Modify();
	Body->Modify();
	Body->RemoveSimpleCollision();
	for (int32 i = 0; i < Centres.Num(); ++i)
	{
		FKBoxElem Box(Sizes[i].X, Sizes[i].Y, Sizes[i].Z);
		Box.Center = Centres[i];
		Body->AggGeom.BoxElems.Add(Box);
	}
	Body->InvalidatePhysicsData();
	Body->CreatePhysicsMeshes();
	PhysicsAsset->MarkPackageDirty();
	return Out + FString::Printf(TEXT(" -> %d boxes"), Centres.Num());
}
