#include "TimeTrialGate.h"

#include "Components/StaticMeshComponent.h"
#include "Components/TextRenderComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "ProceduralMeshComponent.h"
#include "UObject/ConstructorHelpers.h"

namespace
{
	// sizes in cm (local frame: X along the route, Y across, Z up; the actor sits on the road at the line)
	constexpr float PylonHalf = 24.0f;        // square shaft (reads at 100 m)
	constexpr float PylonTop = 520.0f;
	constexpr float PylonOut = 25.0f;         // pylon centre outside the gate width
	constexpr float CurtainTop = 400.0f;
	constexpr float BeamHeight = 3000.0f;
	constexpr float BoxHalfLength = 300.0f;   // start box (a car is 445 x 180)
	constexpr float BoxHalfWidth = 160.0f;

	enum ESection { Body = 0, Curtain = 1, Decal = 2 };

	const FLinearColor Dark(0, 0, 0, 0), Accent(1, 0, 0, 0), Checker(0, 1, 0, 0);

	FLinearColor AccentColour(EGateKind Kind, int32 Rank)
	{
		if (Kind == EGateKind::Start) { return FLinearColor(0.3f, 1.6f, 6.0f); }        // Subaru blue
		if (Rank > 0) { return FLinearColor(0.45f, 0.42f, 0.36f) * (Rank == 1 ? 1.0f : 0.5f); }   // dimmed
		return Kind == EGateKind::Finish ? FLinearColor(0.5f, 5.0f, 1.0f) : FLinearColor(6.0f, 2.8f, 0.12f);   // green / amber
	}

	/** Procedural mesh buffers with a box / quad helper (UV0 in metres of the face plane, for the checker). */
	struct FGateMesh
	{
		TArray<FVector> V;
		TArray<int32> T;
		TArray<FVector> N;
		TArray<FVector2D> UV0, UV1;
		TArray<FLinearColor> C;
		TArray<FProcMeshTangent> Tan;

		void Quad(const FVector (&P)[4], const FVector& Normal, const FVector2D (&A)[4], const FVector2D (&B)[4], const FLinearColor& Col, const FVector& TangentX)
		{
			const int32 Base = V.Num();
			for (int32 i = 0; i < 4; ++i)
			{
				V.Add(P[i]);
				N.Add(Normal);
				UV0.Add(A[i]);
				UV1.Add(B[i]);
				C.Add(Col);
				Tan.Add(FProcMeshTangent(TangentX, false));
			}
			// front faces: (b - a) x (c - a) points AGAINST the normal (UE's left-handed winding; verified in game:
			// the other way round the one-sided boxes render inside out and the start box decal is culled)
			const bool bFlip = FVector::DotProduct(FVector::CrossProduct(P[1] - P[0], P[2] - P[0]), Normal) > 0.0;
			const int32 Order[6] = { 0, 1, 2, 0, 2, 3 };
			for (int32 k = 0; k < 6; k += 3)
			{
				T.Add(Base + Order[k]);
				T.Add(Base + (bFlip ? Order[k + 2] : Order[k + 1]));
				T.Add(Base + (bFlip ? Order[k + 1] : Order[k + 2]));
			}
		}

		void Box(const FVector& Centre, const FVector& Half, const FLinearColor& Col, const FQuat& Rot = FQuat::Identity)
		{
			const FVector Axis[3] = { FVector::ForwardVector, FVector::RightVector, FVector::UpVector };
			for (int32 i = 0; i < 3; ++i)
			{
				for (int32 s = -1; s <= 1; s += 2)
				{
					if (i == 2 && s < 0) { continue; }      // never seen from below
					const int32 iu = (i + 1) % 3, iv = (i + 2) % 3;
					const FVector Nrm = Rot.RotateVector(Axis[i] * s);
					FVector P[4];
					FVector2D A[4];
					const float Su[4] = { -1, 1, 1, -1 }, Sv[4] = { -1, -1, 1, 1 };
					for (int32 k = 0; k < 4; ++k)
					{
						const FVector L = Axis[i] * (s * Half[i]) + Axis[iu] * (Su[k] * Half[iu]) + Axis[iv] * (Sv[k] * Half[iv]);
						P[k] = Centre + Rot.RotateVector(L);
						// metres in the face plane: horizontal axis first so the checker reads across the road
						const FVector W = Centre + L;
						A[k] = i == 0 ? FVector2D(W.Y, W.Z) / 100.0 : i == 1 ? FVector2D(W.X, W.Z) / 100.0 : FVector2D(W.X, W.Y) / 100.0;
					}
					Quad(P, Nrm, A, A, Col, Rot.RotateVector(Axis[iu]));
				}
			}
		}

		void Commit(UProceduralMeshComponent* Mesh, int32 Section) const
		{
			const TArray<FVector2D> None;
			Mesh->CreateMeshSection_LinearColor(Section, V, T, N, UV0, UV1, None, None, C, Tan, false, false);
		}
	};
}

ATimeTrialGate::ATimeTrialGate()
{
	PrimaryActorTick.bCanEverTick = false;
	static ConstructorHelpers::FObjectFinder<UStaticMesh> Cylinder(TEXT("/Engine/BasicShapes/Cylinder.Cylinder"));
	Mesh = CreateDefaultSubobject<UProceduralMeshComponent>(TEXT("Gate"));
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(false);
	Mesh->SetGenerateOverlapEvents(false);
	Mesh->bUseAsyncCooking = true;
	RootComponent = Mesh;
	for (int32 i = 0; i < 2; ++i)
	{
		Beams[i] = CreateDefaultSubobject<UStaticMeshComponent>(*FString::Printf(TEXT("Beam%d"), i));
		Beams[i]->SetupAttachment(Mesh);
		Beams[i]->SetStaticMesh(Cylinder.Object);
		Beams[i]->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Beams[i]->SetCastShadow(false);
		Beams[i]->SetGenerateOverlapEvents(false);
		Labels[i] = CreateDefaultSubobject<UTextRenderComponent>(*FString::Printf(TEXT("Label%d"), i));
		Labels[i]->SetupAttachment(Mesh);
		Labels[i]->SetHorizontalAlignment(EHTA_Center);
		Labels[i]->SetVerticalAlignment(EVRTA_TextCenter);
		Labels[i]->SetTextRenderColor(FColor(225, 238, 255));
		Labels[i]->SetCastShadow(false);
		Labels[i]->SetVisibility(false);
	}
}

void ATimeTrialGate::Configure(float WidthCm, EGateKind InKind, const FString& Label)
{
	Kind = InKind;
	if (!BodyMID)
	{
		auto Make = [this](const TCHAR* Path) -> UMaterialInstanceDynamic*
		{
			UMaterialInterface* M = LoadObject<UMaterialInterface>(nullptr, Path);
			return M ? UMaterialInstanceDynamic::Create(M, this) : nullptr;
		};
		BodyMID = Make(TEXT("/Game/Cambridge/Game/M_GateBody.M_GateBody"));
		CurtainMID = Make(TEXT("/Game/Cambridge/Game/M_GateCurtain.M_GateCurtain"));
		DecalMID = Make(TEXT("/Game/Cambridge/Game/M_StartDecal.M_StartDecal"));
		BeamMID = Make(TEXT("/Game/Cambridge/Game/M_GateBeam.M_GateBeam"));
		for (UStaticMeshComponent* B : Beams) { B->SetMaterial(0, BeamMID); }
		if (DecalMID)
		{
			DecalMID->SetScalarParameterValue(TEXT("HalfLength"), BoxHalfLength / 100.0f);
			DecalMID->SetScalarParameterValue(TEXT("HalfWidth"), BoxHalfWidth / 100.0f);
		}
	}
	if (BuiltWidth != WidthCm || BuiltKind != Kind || (Kind == EGateKind::Start && BuiltBoxCentre != BoxCentre))
	{
		Build(WidthCm);
	}
	const float Half = WidthCm * 0.5f;
	for (int32 i = 0; i < 2; ++i)
	{
		const float Y = (i == 0 ? -1.0f : 1.0f) * (Half + PylonOut);
		Beams[i]->SetRelativeLocation(FVector(0.0, Y, PylonTop + BeamHeight * 0.5));
		Beams[i]->SetRelativeScale3D(FVector(0.16, 0.16, BeamHeight / 100.0));
		// event name on both faces of the start gantry, sized to fit between the pylons
		const bool bLabel = Kind == EGateKind::Start && !Label.IsEmpty();
		Labels[i]->SetVisibility(bLabel);
		if (bLabel)
		{
			const float Size = FMath::Clamp((WidthCm + 2.0f * PylonOut) * 0.8f / (0.62f * FMath::Max(Label.Len(), 1)), 30.0f, 62.0f);
			Labels[i]->SetWorldSize(Size);
			Labels[i]->SetText(FText::FromString(Label.ToUpper()));
			Labels[i]->SetRelativeLocation(FVector(i == 0 ? -16.0 : 16.0, 0.0, 470.0));
			Labels[i]->SetRelativeRotation(FRotator(0.0f, i == 0 ? 180.0f : 0.0f, 0.0f));
		}
	}
	Rank = 0;
	Flash = 0.0f;
	Glow = 1.0f;
	Apply();
}

void ATimeTrialGate::Build(float WidthCm)
{
	BuiltWidth = WidthCm;
	BuiltKind = Kind;
	BuiltBoxCentre = BoxCentre;
	Mesh->ClearAllMeshSections();
	const float Half = WidthCm * 0.5f;
	const float Span = Half + PylonOut;           // pylon centres
	const float Inner = Span - PylonHalf;         // pylon inner faces

	// ---- body: pylons (+ crossbar for the start gantry and the finish arch)
	FGateMesh B;
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		const float Y = Side * Span;
		const float In = -Side;                   // towards the road centre
		B.Box(FVector(0, Y, 10), FVector(34, 34, 10), Dark);                                           // plinth
		B.Box(FVector(0, Y, 20 + (PylonTop - 20) * 0.5f), FVector(PylonHalf, PylonHalf, (PylonTop - 20) * 0.5f), Dark);
		B.Box(FVector(0, Y, PylonTop + 4), FVector(PylonHalf + 3, PylonHalf + 3, 4), Accent);          // glowing cap
		B.Box(FVector(0, Y + In * (PylonHalf + 1.2f), 270), FVector(4, 1.2f, 230), Accent);            // inner strip
		// three chevrons on the approach face, pointing into the road
		for (int32 k = 0; k < 3; ++k)
		{
			const float Z = 250.0f + 58.0f * k;
			const float Ang = FMath::DegreesToRadians(45.0f) * In;
			B.Box(FVector(-PylonHalf - 1.5f, Y, Z + 7.0f), FVector(1.5f, 10.5f, 2.8f), Accent, FQuat(FVector::ForwardVector, -Ang));
			B.Box(FVector(-PylonHalf - 1.5f, Y, Z - 7.0f), FVector(1.5f, 10.5f, 2.8f), Accent, FQuat(FVector::ForwardVector, Ang));
		}
	}
	if (Kind == EGateKind::Finish)
	{
		// checkered arch: 2 rows of 0.5 m squares on both faces, accent strip underneath
		B.Box(FVector(0, 0, 450), FVector(14, Span, 56), Dark);
		B.Box(FVector(-15.2f, 0, 450), FVector(1.2f, Inner, 50), Checker);
		B.Box(FVector(15.2f, 0, 450), FVector(1.2f, Inner, 50), Checker);
		B.Box(FVector(0, 0, 391), FVector(6, Inner, 2.5f), Accent);
	}
	else if (Kind == EGateKind::Start)
	{
		B.Box(FVector(0, 0, 470), FVector(14, Span, 38), Dark);
		B.Box(FVector(0, 0, 429), FVector(6, Inner, 2.5f), Accent);
		B.Box(FVector(0, 0, 510), FVector(6, Inner, 2.0f), Accent);
	}
	B.Commit(Mesh, Body);
	Mesh->SetMaterial(Body, BodyMID);

	// ---- light curtain between the pylons' inner faces (next gate only)
	FGateMesh Cu;
	{
		const FVector P[4] = { FVector(0, -Inner, 0), FVector(0, Inner, 0), FVector(0, Inner, CurtainTop), FVector(0, -Inner, CurtainTop) };
		const FVector2D A[4] = { FVector2D(0, 0), FVector2D(1, 0), FVector2D(1, 1), FVector2D(0, 1) };
		const FVector2D M[4] = { FVector2D(-Inner / 100.0, 0), FVector2D(Inner / 100.0, 0), FVector2D(Inner / 100.0, CurtainTop / 100.0), FVector2D(-Inner / 100.0, CurtainTop / 100.0) };
		Cu.Quad(P, FVector::BackwardVector, A, M, FLinearColor::White, FVector::RightVector);
	}
	Cu.Commit(Mesh, Curtain);
	Mesh->SetMaterial(Curtain, CurtainMID);

	// ---- start box on the asphalt where the car waits (+ chevrons up to the line), 3 cm above the road
	if (Kind == EGateKind::Start)
	{
		FGateMesh D;
		// around the box centre (the grid point, in its lane), chevrons running on towards the line
		const float Bx = float(BoxCentre.X), By = float(BoxCentre.Y);
		const float X0 = Bx - BoxHalfLength - 40.0f, X1 = Bx + BoxHalfLength + 470.0f, Y1 = BoxHalfWidth + 20.0f;
		const FVector P[4] = { FVector(X0, By - Y1, 3), FVector(X1, By - Y1, 3), FVector(X1, By + Y1, 3), FVector(X0, By + Y1, 3) };
		FVector2D A[4];
		for (int32 k = 0; k < 4; ++k) { A[k] = FVector2D((P[k].X - Bx) / 100.0, (P[k].Y - By) / 100.0); }
		D.Quad(P, FVector::UpVector, A, A, FLinearColor::White, FVector::ForwardVector);
		D.Commit(Mesh, Decal);
		Mesh->SetMaterial(Decal, DecalMID);
	}
}

void ATimeTrialGate::SetRank(int32 InRank)
{
	Rank = InRank;
	Apply();
}

void ATimeTrialGate::SetPassFlash(float Alpha)
{
	Flash = FMath::Clamp(Alpha, 0.0f, 1.0f);
	Apply();
}

void ATimeTrialGate::SetGlowScale(float Scale)
{
	if (Scale == Glow)
	{
		return;     // (no MID parameter churn for markers that aren't pulsing)
	}
	Glow = Scale;
	Apply();
}

void ATimeTrialGate::Apply()
{
	const bool bLead = Rank == 0 || Kind == EGateKind::Start;
	const FLinearColor Base = AccentColour(Kind, Rank) * Glow;
	const FLinearColor AccentNow = FMath::Lerp(Base, FLinearColor(9.0f, 9.0f, 9.0f), Flash * Flash);
	if (BodyMID)
	{
		BodyMID->SetVectorParameterValue(TEXT("Color"), AccentNow);
		BodyMID->SetScalarParameterValue(TEXT("CheckerGlow"), Kind == EGateKind::Finish ? (bLead ? 0.45f : 0.12f) + Flash * 2.0f : 0.0f);
	}
	const bool bCurtain = (bLead && Kind != EGateKind::Start) || Flash > 0.0f;
	Mesh->SetMeshSectionVisible(Curtain, bCurtain);
	if (CurtainMID && bCurtain)
	{
		const FLinearColor CurtainColour = Kind == EGateKind::Finish ? FLinearColor(0.35f, 0.85f, 0.45f) : FLinearColor(0.9f, 0.42f, 0.03f);
		CurtainMID->SetVectorParameterValue(TEXT("Color"), CurtainColour);
		CurtainMID->SetScalarParameterValue(TEXT("Checker"), Kind == EGateKind::Finish ? 1.0f : 0.0f);
		CurtainMID->SetScalarParameterValue(TEXT("Intensity"), 1.0f - Flash);
		CurtainMID->SetScalarParameterValue(TEXT("Flash"), Flash * 1.6f);
	}
	if (DecalMID)
	{
		DecalMID->SetVectorParameterValue(TEXT("Color"), FLinearColor(0.3f, 1.15f, 3.6f) * Glow);
	}
	if (BeamMID)
	{
		BeamMID->SetVectorParameterValue(TEXT("Color"), Base * (Kind == EGateKind::Start ? 0.35f : 0.3f));
	}
	for (UStaticMeshComponent* Beam : Beams)
	{
		Beam->SetVisibility(bLead && Flash <= 0.0f);
	}
}
