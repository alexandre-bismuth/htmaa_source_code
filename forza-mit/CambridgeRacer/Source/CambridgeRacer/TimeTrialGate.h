// A time-trial checkpoint, finish arch or free-roam event start, Forza-Horizon style. One procedural
// mesh (built in Configure, no collision, no assets beyond the materials of build_game_assets.py):
//   - two slim gunmetal pylons on plinths with an emissive accent (inner strip, top cap, three
//     chevrons on the approach face pointing into the road), M_GateBody
//   - the next gate only: a translucent light curtain between the pylons that fades upwards and
//     near the camera (M_GateCurtain, additive) plus thin light beams above the pylons
//   - finish: a checkered crossbar over the road and a checkered curtain
//   - event start: a dark gantry with the event name, and a start box painted on the asphalt where
//     the car waits (outline, corner brackets, chevrons sweeping forward; M_StartDecal) - no slab,
//     the car stays visibly on the road
// The actor does not tick; UTimeTrialSubsystem drives rank (next / dimmed), pulses and the pass flash.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "TimeTrialGate.generated.h"

class UMaterialInstanceDynamic;
class UProceduralMeshComponent;
class UStaticMeshComponent;
class UTextRenderComponent;

UENUM()
enum class EGateKind : uint8
{
	Checkpoint,
	Finish,
	Start,      // free-roam event marker (start gantry + start box)
};

UCLASS()
class ATimeTrialGate : public AActor
{
	GENERATED_BODY()

public:
	ATimeTrialGate();

	/** Width in cm between the pylons. Label: the event name on the start gantry. Rebuilds the mesh
	 *  only when the width or kind changed (gates are pooled and reused along the route). */
	void Configure(float WidthCm, EGateKind Kind, const FString& Label = FString());
	/** Start kind: centre of the painted start box in the gate's frame (X along the route, Y to the right; cm).
	 *  The event's grid point, in its lane; default: GridOffsetCm behind the line on the centre. Call before Configure. */
	void SetStartBox(const FVector2D& LocalCentre) { BoxCentre = LocalCentre; }
	/** Half extents (cm) of the zone around the start box where the start prompt shows. */
	static FVector2D StartZoneHalf() { return FVector2D(450.0, 300.0); }
	/** 0 = the gate to drive through now (bright accent, light curtain, beams); 1, 2 = the following gates (dimmed). */
	void SetRank(int32 Rank);
	/** Pass effect, 1 -> 0 over ~0.5 s after the car drove through: white flash of the accents and the curtain. */
	void SetPassFlash(float Alpha);
	/** Brightness multiplier (start markers breathe; the one the car is in glows brighter). */
	void SetGlowScale(float Scale);
	EGateKind GetKind() const { return Kind; }

	/** Distance (cm) behind the start line of the start box centre: where the car is put for the countdown. */
	static constexpr float GridOffsetCm = 1200.0f;

private:
	void Build(float WidthCm);
	void Apply();

	UPROPERTY() TObjectPtr<UProceduralMeshComponent> Mesh;
	UPROPERTY() TObjectPtr<UStaticMeshComponent> Beams[2];
	UPROPERTY() TObjectPtr<UTextRenderComponent> Labels[2];
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> BodyMID;
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> CurtainMID;
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> DecalMID;
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> BeamMID;

	EGateKind Kind = EGateKind::Checkpoint;
	EGateKind BuiltKind = EGateKind::Checkpoint;
	float BuiltWidth = -1.0f;
	FVector2D BoxCentre = FVector2D(-GridOffsetCm, 0.0);
	FVector2D BuiltBoxCentre = FVector2D(1e9, 1e9);
	int32 Rank = 0;
	float Glow = 1.0f;
	float Flash = 0.0f;
};
