// A floating landmark sign, video-game POI style (spawned at runtime by ULandmarkSubsystem, never saved in a level):
//   - an 8-bit panel (pixel icon block + Press Start 2P title + Silkscreen subtitle on dark glass, accent glow)
//   - a chunky pixel arrow under it that bounces, pointing down at the building's entrance
//   - a thin light pillar from the entrance up to the arrow
// All three are camera-facing quads with M_LandmarkSign (tools/unreal/build_landmark_assets.py) and runtime
// textures from UI/Generated/landmark_<id>_*.png (tools/ui/make_landmark_signs.py).
//
// Each tick: the sign turns to face the camera (full billboard about the arrow tip), grows with distance so it
// keeps a constant screen size from NearRefM to MaxScale x that, floats just above the roof when far and comes
// down in front of the facade when close (so a chase camera still sees it), fades out very close and very far,
// the arrow bounces, the panel bobs and the glow breathes. Hidden (no draw) when fully faded.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "LandmarkActor.generated.h"

class UMaterialInstanceDynamic;
class UProceduralMeshComponent;
class UTexture2D;

/** Layout of the generated sign art (UI/Generated/landmark_signs.json), in art pixels. */
struct FLandmarkSignLayout
{
	float MetresPerArtPx = 0.12f;
	FVector2D PanelCanvas = FVector2D(256, 64);
	float PanelTailY = 50.0f;       // first row under the panel's pointer tail
	FVector2D ArrowCanvas = FVector2D(64, 64);
	float ArrowTopY = 15.0f;
	float ArrowTipY = 49.0f;        // first row under the arrow tip
};

UCLASS(NotPlaceable, Transient)
class ALandmarkActor : public AActor
{
	GENERATED_BODY()

public:
	ALandmarkActor();

	/** Anchor = arrow tip XY (in front of the entrance, cm), RoofCm = roof height there. */
	void Setup(const FVector& Anchor, float RoofCm, const FLinearColor& Accent, const FLandmarkSignLayout& Layout,
		UTexture2D* PanelTex, UTexture2D* ArrowTex, UTexture2D* BeamTex);

	virtual void Tick(float DeltaSeconds) override;

	/** Per-landmark far fade (cm): fully visible to Full, hidden beyond Gone (default FadeFar0 / FadeFar1). */
	void SetFadeFar(float FullCm, float GoneCm) { FadeFarFullCm = FullCm; FadeFarGoneCm = GoneCm; }

	/** Current opacity (0 hidden .. 1), for tests. */
	float GetOpacity() const { return Opacity; }

	// tuning (cm unless noted)
	static constexpr float NearRefCm = 7000.0f;     // constant world size closer than this, constant screen size beyond
	static constexpr float MaxScale = 6.0f;         // stop growing at NearRef * MaxScale (420 m), then it shrinks
	static constexpr float FadeNear0 = 2200.0f, FadeNear1 = 4500.0f;
	static constexpr float FadeFar0 = 95000.0f, FadeFar1 = 130000.0f;

private:
	UProceduralMeshComponent* MakeQuadComponent(const TCHAR* Name);
	static void BuildQuad(UProceduralMeshComponent* Mesh, float Y0, float Y1, float Z0, float Z1);

	UPROPERTY() TObjectPtr<USceneComponent> Root;
	UPROPERTY() TObjectPtr<UProceduralMeshComponent> Panel;
	UPROPERTY() TObjectPtr<UProceduralMeshComponent> Arrow;
	UPROPERTY() TObjectPtr<UProceduralMeshComponent> Beam;
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> PanelMID;
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> ArrowMID;
	UPROPERTY() TObjectPtr<UMaterialInstanceDynamic> BeamMID;

	FVector Anchor = FVector::ZeroVector;
	float RoofCm = 2000.0f;
	float ArtCm = 12.0f;           // one art pixel at scale 1
	float ArrowHeightCm = 400.0f;  // arrow sprite top -> tip
	float Opacity = 1.0f;
	float FadeFarFullCm = FadeFar0;
	float FadeFarGoneCm = FadeFar1;
	float Phase = 0.0f;            // per-landmark animation offset
};
