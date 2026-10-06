#include "RacingLineActor.h"

#include "Materials/MaterialInterface.h"
#include "ProceduralMeshComponent.h"

namespace
{
	constexpr float HalfWidth = 75.0f;       // cm (arrow width 1.5 m)
	constexpr float Lift = 4.0f;             // cm above the road surface (roads are at z = 0)
	constexpr float DashPeriod = 220.0f;     // cm between arrow tips
	constexpr float CornerKmh = 125.0f;      // "Corners Only": shown where the target speed is below this
	constexpr float ShowAhead = 25000.0f;    // cm of line shown ahead of the car
	constexpr float FadeIn = 600.0f;         // cm: the line starts just ahead of the bonnet
	constexpr int32 ChunkSegments = 48;      // line segments per mesh section (~150 m at the 3 m point spacing)

	const FLinearColor Green(0.10f, 1.00f, 0.25f), Yellow(1.00f, 0.80f, 0.05f), Red(1.00f, 0.08f, 0.04f);

	FLinearColor SpeedColour(float Ratio)
	{
		// ratio = car speed / target speed at that point
		if (Ratio < 0.92f) { return Green; }
		if (Ratio < 1.05f) { return FLinearColor::LerpUsingHSV(Green, Yellow, (Ratio - 0.92f) / 0.13f); }
		return FLinearColor::LerpUsingHSV(Yellow, Red, FMath::Clamp((Ratio - 1.05f) / 0.12f, 0.0f, 1.0f));
	}
}

ARacingLineActor::ARacingLineActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Mesh = CreateDefaultSubobject<UProceduralMeshComponent>(TEXT("Line"));
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(false);
	Mesh->bUseAsyncCooking = true;
	RootComponent = Mesh;
}

void ARacingLineActor::Build(const TArray<FVector4>& Points, bool bClosed)
{
	Line = Points;
	bLoop = bClosed;
	const int32 N = Line.Num();
	Distance.Reset();
	Chunks.Reset();
	Shown.Reset();
	Mesh->ClearAllMeshSections();
	Nearest = -1;
	UploadedNearest = -2;
	if (N < 2)
	{
		return;
	}
	float D = 0.0f;
	for (int32 i = 0; i < N; ++i)
	{
		if (i > 0) { D += FVector::Dist2D(FVector(Line[i].X, Line[i].Y, 0.0), FVector(Line[i - 1].X, Line[i - 1].Y, 0.0)); }
		Distance.Add(D);
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Cambridge/Game/M_RacingLine.M_RacingLine"));
	// sections of ChunkSegments segments; neighbours share their boundary point (same position and UV: no seam)
	const int32 Segments = bLoop ? N : N - 1;
	TArray<int32> Triangles;
	for (int32 First = 0; First < Segments; First += ChunkSegments)
	{
		const int32 Section = Chunks.Num();
		FChunk& C = Chunks.AddDefaulted_GetRef();
		C.First = First;
		C.Count = FMath::Min(ChunkSegments, Segments - First) + 1;
		Triangles.Reset();
		for (int32 k = 0; k < C.Count; ++k)
		{
			const int32 i = (First + k) % N;
			// the loop's closing point: point 0 again, at the distance round the lap (the dashes run on)
			const float Dk = First + k == N ? Distance[N - 1] + FVector::Dist2D(FVector(Line[N - 1].X, Line[N - 1].Y, 0.0), FVector(Line[0].X, Line[0].Y, 0.0)) : Distance[i];
			const FVector P(Line[i].X, Line[i].Y, Lift);
			const int32 Prev = bLoop ? (i + N - 1) % N : FMath::Max(i - 1, 0);
			const int32 Next = bLoop ? (i + 1) % N : FMath::Min(i + 1, N - 1);
			const FVector Dir = (FVector(Line[Next].X, Line[Next].Y, 0.0) - FVector(Line[Prev].X, Line[Prev].Y, 0.0)).GetSafeNormal2D();
			const FVector Side(-Dir.Y, Dir.X, 0.0);
			for (int32 s = 0; s < 2; ++s)
			{
				C.Vertices.Add(P + Side * (s == 0 ? -HalfWidth : HalfWidth) - GetActorLocation());
				C.Normals.Add(FVector::UpVector);
				C.UVs.Add(FVector2D(Dk / DashPeriod, s));
				C.Colours.Add(FLinearColor(0, 0, 0, 0));
			}
			if (k > 0)
			{
				const int32 a = 2 * (k - 1), b = 2 * k;
				// counter-clockwise seen from above (Unreal: Z up, left-handed -> this order faces up)
				Triangles.Append({ a, b, a + 1, a + 1, b, b + 1 });
			}
		}
		Mesh->CreateMeshSection_LinearColor(Section, C.Vertices, Triangles, C.Normals, C.UVs, C.Colours, TArray<FProcMeshTangent>(), false);
		Mesh->SetMeshSectionVisible(Section, false);
		if (Material)
		{
			Mesh->SetMaterial(Section, Material);
		}
	}
}

int32 ARacingLineActor::FindNearest(const FVector& P) const
{
	const int32 N = Line.Num();
	if (N == 0)
	{
		return -1;
	}
	// track forward from the last match (cheap, and never jumps to a parallel stretch of the route)
	int32 Best = Nearest;
	float BestD = TNumericLimits<float>::Max();
	const int32 From = Nearest < 0 ? 0 : -10;
	const int32 To = Nearest < 0 ? N : 60;
	for (int32 k = From; k < To; ++k)
	{
		const int32 i = Nearest < 0 ? k : (bLoop ? (Nearest + k + N) % N : FMath::Clamp(Nearest + k, 0, N - 1));
		const float Dist = FVector::DistSquared2D(P, FVector(Line[i].X, Line[i].Y, 0.0));
		if (Dist < BestD) { BestD = Dist; Best = i; }
	}
	// lost track (teleport, reset, a shortcut): search the whole line
	if (Nearest >= 0 && BestD > FMath::Square(3000.0f))
	{
		for (int32 i = 0; i < N; ++i)
		{
			const float Dist = FVector::DistSquared2D(P, FVector(Line[i].X, Line[i].Y, 0.0));
			if (Dist < BestD) { BestD = Dist; Best = i; }
		}
	}
	return Best;
}

FLinearColor ARacingLineActor::PointColour(int32 I, float SpeedKmh, bool bCornersOnly) const
{
	float Ahead = Distance[I] - Distance[Nearest];
	if (bLoop && Ahead < -FadeIn) { Ahead += Distance.Last() + 300.0f; }   // wrap round a circuit
	float Alpha = 0.0f;
	if (Ahead > 0.0f && Ahead < ShowAhead)
	{
		Alpha = FMath::Clamp(Ahead / FadeIn, 0.0f, 1.0f) * FMath::Clamp((ShowAhead - Ahead) / (ShowAhead * 0.3f), 0.0f, 1.0f) * 0.85f;
	}
	const float Ratio = FMath::Max(SpeedKmh, 0.0f) / FMath::Max(Line[I].W, 10.0f);
	if (bCornersOnly)
	{
		// keep the line where a corner (or the braking zone before it) needs attention
		const float CornerFactor = FMath::Clamp((CornerKmh - Line[I].W) / 15.0f + 1.0f, 0.0f, 1.0f);
		Alpha *= FMath::Max(CornerFactor, FMath::Clamp((Ratio - 0.88f) / 0.06f, 0.0f, 1.0f));
	}
	FLinearColor C = SpeedColour(Ratio);
	C.A = Alpha;
	return C;
}

void ARacingLineActor::UpdateFor(const FVector& CarLocation, float SpeedKmh, bool bCornersOnly)
{
	const int32 N = Line.Num();
	if (N < 2 || Chunks.Num() == 0)
	{
		return;
	}
	Nearest = FindNearest(CarLocation);
	// colours change with the car's position along the line (a point every 3 m) and its speed: skip the
	// upload while neither moved on (speed in 2 km/h steps, invisible in the colour ramp)
	const int32 SpeedBucket = FMath::RoundToInt(FMath::Max(SpeedKmh, 0.0f) * 0.5f);
	if (Nearest == UploadedNearest && SpeedBucket == UploadedSpeedBucket && bCornersOnly == bUploadedCornersOnly)
	{
		return;
	}
	UploadedNearest = Nearest;
	UploadedSpeedBucket = SpeedBucket;
	bUploadedCornersOnly = bCornersOnly;
	SpeedKmh = SpeedBucket * 2.0f;
	// the sections the visible stretch touches: from the car's point up to ShowAhead (round the lap on a circuit).
	// A point on a section boundary belongs to both sections; point 0 also closes the last section of a loop.
	Want.Reset();
	auto AddSectionsOf = [this](int32 i)
	{
		const int32 c = i / ChunkSegments;
		if (c < Chunks.Num())
		{
			Want.AddUnique(c);
		}
		if (i % ChunkSegments == 0)
		{
			if (i > 0) { Want.AddUnique(c - 1); }
			else if (bLoop) { Want.AddUnique(Chunks.Num() - 1); }
		}
	};
	for (int32 k = 0; k < N; ++k)
	{
		const int32 i = bLoop ? (Nearest + k) % N : Nearest + k;
		if (i >= N || (k > 0 && i == Nearest))
		{
			break;
		}
		float Ahead = Distance[i] - Distance[Nearest];
		if (bLoop && Ahead < 0.0f) { Ahead += Distance.Last() + 300.0f; }
		if (Ahead >= ShowAhead)
		{
			break;
		}
		AddSectionsOf(i);
	}
	for (const int32 c : Want)
	{
		FChunk& C = Chunks[c];
		for (int32 k = 0; k < C.Count; ++k)
		{
			const FLinearColor Col = PointColour((C.First + k) % N, SpeedKmh, bCornersOnly);
			C.Colours[2 * k] = Col;
			C.Colours[2 * k + 1] = Col;
		}
		Mesh->UpdateMeshSection_LinearColor(c, C.Vertices, C.Normals, C.UVs, C.Colours, TArray<FProcMeshTangent>());
		if (!Shown.Contains(c))
		{
			Mesh->SetMeshSectionVisible(c, true);
		}
	}
	for (const int32 c : Shown)
	{
		if (!Want.Contains(c))
		{
			Mesh->SetMeshSectionVisible(c, false);
		}
	}
	Swap(Shown, Want);
}
