#include "LandmarkActor.h"

#include "Camera/PlayerCameraManager.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "HAL/IConsoleManager.h"
#include "ProceduralMeshComponent.h"

namespace
{
	constexpr float LmGapArtPx = 3.0f;             // between the arrow's highest bounce and the panel's tail
	constexpr float LmBounce = 0.28f;              // arrow hop, fraction of the arrow height
	constexpr float LmBouncePeriod = 0.95f;        // s
	constexpr float LmBeamWidthCm = 170.0f;
	constexpr float LmPanelBrightness = 1.15f;
	constexpr float LmArrowBrightness = 1.6f;
	constexpr float LmBeamBrightness = 1.4f;

	// showcase shots (e.g. the aerial in docs/figures): keep constant screen size and stay visible this many times farther
	float GLmShowcaseScale = 1.0f;
	FAutoConsoleVariableRef CVarLmShowcaseScale(TEXT("cr.Landmark.ShowcaseScale"), GLmShowcaseScale,
		TEXT("Landmark signs keep their screen size and fade out this many times farther away (1 = game, e.g. 3 for an aerial screenshot)"));
	float GLmShowcaseSize = 1.0f;
	FAutoConsoleVariableRef CVarLmShowcaseSize(TEXT("cr.Landmark.ShowcaseSize"), GLmShowcaseSize,
		TEXT("Landmark sign size multiplier (1 = game; for screenshots only)"));

	float LmSmooth(float A, float B, float X)
	{
		return A < B ? FMath::SmoothStep(A, B, X) : 1.0f - FMath::SmoothStep(B, A, X);
	}
}

ALandmarkActor::ALandmarkActor()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;      // after the camera moved this frame
	SetCanBeDamaged(false);
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Panel = MakeQuadComponent(TEXT("Panel"));
	Arrow = MakeQuadComponent(TEXT("Arrow"));
	Beam = MakeQuadComponent(TEXT("Beam"));
	Beam->SetUsingAbsoluteLocation(true);
	Beam->SetUsingAbsoluteRotation(true);
	Beam->SetUsingAbsoluteScale(true);
	Beam->SetTranslucentSortPriority(-1);
	Panel->SetTranslucentSortPriority(1);
	Arrow->SetTranslucentSortPriority(1);
}

UProceduralMeshComponent* ALandmarkActor::MakeQuadComponent(const TCHAR* Name)
{
	UProceduralMeshComponent* C = CreateDefaultSubobject<UProceduralMeshComponent>(Name);
	C->SetupAttachment(RootComponent);
	C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	C->SetGenerateOverlapEvents(false);
	C->SetCastShadow(false);
	C->bAffectDistanceFieldLighting = false;
	C->bVisibleInRayTracing = false;
	C->bVisibleInReflectionCaptures = false;
	C->bReceivesDecals = false;
	C->SetCanEverAffectNavigation(false);
	return C;
}

void ALandmarkActor::BuildQuad(UProceduralMeshComponent* Mesh, float Y0, float Y1, float Z0, float Z1)
{
	// a quad in the local YZ plane facing +X (the actor's X points at the camera, so local +Y is screen LEFT);
	// UV (0,0) = top left as seen from the camera
	const TArray<FVector> V = { FVector(0, Y1, Z0), FVector(0, Y0, Z0), FVector(0, Y0, Z1), FVector(0, Y1, Z1) };
	const TArray<int32> T = { 0, 2, 1, 0, 3, 2 };
	const TArray<FVector> N = { FVector::ForwardVector, FVector::ForwardVector, FVector::ForwardVector, FVector::ForwardVector };
	const TArray<FVector2D> UV = { FVector2D(0, 1), FVector2D(1, 1), FVector2D(1, 0), FVector2D(0, 0) };
	const TArray<FLinearColor> C = { FLinearColor::White, FLinearColor::White, FLinearColor::White, FLinearColor::White };
	const TArray<FProcMeshTangent> Tan = { FProcMeshTangent(0, 1, 0), FProcMeshTangent(0, 1, 0), FProcMeshTangent(0, 1, 0), FProcMeshTangent(0, 1, 0) };
	Mesh->CreateMeshSection_LinearColor(0, V, T, N, UV, C, Tan, false);
}

void ALandmarkActor::Setup(const FVector& InAnchor, float InRoofCm, const FLinearColor& Accent, const FLandmarkSignLayout& L,
	UTexture2D* PanelTex, UTexture2D* ArrowTex, UTexture2D* BeamTex)
{
	Anchor = InAnchor;
	RoofCm = InRoofCm;
	ArtCm = L.MetresPerArtPx * 100.0f;
	Phase = float(GetTypeHash(GetName()) % 1000u) * 0.0137f;

	// arrow: its tip row at the actor origin; panel: its tail above the arrow's highest hop
	const float AW = L.ArrowCanvas.X * ArtCm, AH = L.ArrowCanvas.Y * ArtCm;
	const float ATop = L.ArrowTipY * ArtCm;
	BuildQuad(Arrow, -AW * 0.5f, AW * 0.5f, ATop - AH, ATop);
	ArrowHeightCm = (L.ArrowTipY - L.ArrowTopY) * ArtCm;
	const float PanelBase = ArrowHeightCm * (1.0f + LmBounce) + LmGapArtPx * ArtCm;
	const float PW = L.PanelCanvas.X * ArtCm, PH = L.PanelCanvas.Y * ArtCm;
	const float PTop = PanelBase + L.PanelTailY * ArtCm;
	BuildQuad(Panel, -PW * 0.5f, PW * 0.5f, PTop - PH, PTop);
	BuildQuad(Beam, -LmBeamWidthCm * 0.5f, LmBeamWidthCm * 0.5f, 0.0f, 100.0f);

	UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Cambridge/Landmarks/M_LandmarkSign.M_LandmarkSign"));
	auto Make = [this, Base](UProceduralMeshComponent* Mesh, UTexture2D* Tex, float Brightness) -> UMaterialInstanceDynamic*
	{
		if (!Base || !Tex)
		{
			Mesh->SetVisibility(false);
			return nullptr;
		}
		UMaterialInstanceDynamic* MID = UMaterialInstanceDynamic::Create(Base, this);
		MID->SetTextureParameterValue(TEXT("Tex"), Tex);
		MID->SetScalarParameterValue(TEXT("Brightness"), Brightness);
		Mesh->SetMaterial(0, MID);
		return MID;
	};
	PanelMID = Make(Panel, PanelTex, LmPanelBrightness);
	ArrowMID = Make(Arrow, ArrowTex, LmArrowBrightness);
	BeamMID = Make(Beam, BeamTex, LmBeamBrightness);
	if (BeamMID)
	{
		BeamMID->SetScalarParameterValue(TEXT("Ghost"), 0.18f);     // the pillar only faintly through buildings
	}
	if (!Base)
	{
		UE_LOG(LogTemp, Warning, TEXT("landmarks: no /Game/Cambridge/Landmarks/M_LandmarkSign (run tools/unreal/build_landmark_assets.sh)"));
	}
	SetActorLocation(FVector(Anchor.X, Anchor.Y, RoofCm));
}

void ALandmarkActor::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
	if (!PC || !PC->PlayerCameraManager)
	{
		return;
	}
	const FVector Cam = PC->PlayerCameraManager->GetCameraLocation();
	const FQuat CamQ = PC->PlayerCameraManager->GetCameraRotation().Quaternion();
	const float Horiz = float(FVector2D::Distance(FVector2D(Cam), FVector2D(Anchor)));

	// float just above the roof when far; come down in front of the facade when close
	const float FarZ = RoofCm + 300.0f;
	const float NearZ = FMath::Clamp(RoofCm * 0.55f, 900.0f, FarZ);
	const float TipZ = FMath::Lerp(FarZ, NearZ, LmSmooth(16000.0f, 6000.0f, Horiz));
	const FVector Tip(Anchor.X, Anchor.Y, TipZ);
	const FVector ToCam = Cam - Tip;
	const float Dist = float(ToCam.Size());

	const float Showcase = FMath::Max(GLmShowcaseScale, 0.1f);
	Opacity = LmSmooth(FadeNear0, FadeNear1, Dist) * LmSmooth(FadeFarGoneCm * Showcase, FadeFarFullCm * Showcase, Dist);
	const bool bHidden = Opacity < 0.01f;
	if (IsHidden() != bHidden)
	{
		SetActorHiddenInGame(bHidden);
	}
	if (bHidden)
	{
		return;
	}

	// full billboard about the arrow tip; constant screen size beyond NearRef
	const float Scale = FMath::Clamp(Dist / NearRefCm, 1.0f, MaxScale * Showcase) * FMath::Max(GLmShowcaseSize, 0.1f);
	const FRotator Rot = FRotationMatrix::MakeFromXZ(ToCam.GetSafeNormal(), CamQ.GetUpVector()).Rotator();
	SetActorLocationAndRotation(Tip, Rot);
	SetActorScale3D(FVector(Scale));

	const float T = GetWorld()->GetTimeSeconds() + Phase;
	const float Hop = FMath::Abs(FMath::Sin(T * UE_PI / LmBouncePeriod));
	Arrow->SetRelativeLocation(FVector(0.0f, 0.0f, ArrowHeightCm * LmBounce * Hop));
	Panel->SetRelativeLocation(FVector(0.0f, 0.0f, ArtCm * 0.8f * FMath::Sin(T * 1.6f)));

	if (PanelMID)
	{
		PanelMID->SetScalarParameterValue(TEXT("Opacity"), Opacity);
		PanelMID->SetScalarParameterValue(TEXT("Brightness"), LmPanelBrightness * (1.0f + 0.05f * FMath::Sin(T * 2.2f)));
	}
	if (ArrowMID)
	{
		ArrowMID->SetScalarParameterValue(TEXT("Opacity"), Opacity);
		ArrowMID->SetScalarParameterValue(TEXT("Brightness"), LmArrowBrightness * (1.0f + 0.18f * (1.0f - Hop)));
	}

	// light pillar from the entrance up to the arrow (vertical, turns to the camera about Z)
	const float BeamAlpha = Opacity * LmSmooth(2500.0f, 6000.0f, Horiz);
	Beam->SetVisibility(BeamAlpha > 0.01f && BeamMID != nullptr);
	if (BeamMID && BeamAlpha > 0.01f)
	{
		const FVector Flat(Cam.X - Anchor.X, Cam.Y - Anchor.Y, 0.0);
		Beam->SetWorldLocationAndRotation(FVector(Anchor.X, Anchor.Y, 0.0), FRotator(0.0, Flat.Rotation().Yaw, 0.0));
		Beam->SetWorldScale3D(FVector(1.0, FMath::Sqrt(Scale), FMath::Max(1.0f, TipZ) / 100.0f));
		BeamMID->SetScalarParameterValue(TEXT("Opacity"), BeamAlpha);
	}
}
