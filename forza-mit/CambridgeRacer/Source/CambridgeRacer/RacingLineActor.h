// The racing line drawn on the road during an event, Forza-style: flat chevron arrow tips along the
// route (M_RacingLine draws them), each coloured by comparing the car's speed with the target speed
// at that point (precomputed by tools/mapgen/tracks.py from curvature and braking distance):
//   green  carry this speed / accelerate     yellow  ease off     red  brake
// Modes (Driving Assists menu): Full, Corners Only (hidden on straights that need no lift), Off.
// Only the next ~250 m are shown, fading in just ahead of the car and out in the distance.
// The line is cut into mesh sections of ChunkSegments segments: an update recolours and uploads only the few
// sections around the car (and hides the ones it left), so its cost doesn't grow with the route's length.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RacingLineActor.generated.h"

class UProceduralMeshComponent;

UCLASS()
class ARacingLineActor : public AActor
{
	GENERATED_BODY()

public:
	ARacingLineActor();

	/** Points: X, Y (cm, world), Z unused, W = target speed (km/h). */
	void Build(const TArray<FVector4>& Points, bool bClosed);
	/** Recolours the line ahead of the car. SpeedKmh = the car's current forward speed. */
	void UpdateFor(const FVector& CarLocation, float SpeedKmh, bool bCornersOnly);
	/** Forget the car's progress (after a restart or a teleport). */
	void ResetProgress() { Nearest = -1; UploadedNearest = -2; }

private:
	int32 FindNearest(const FVector& P) const;

	/** Colour (alpha = visibility) of line point I for the car at Nearest. */
	FLinearColor PointColour(int32 I, float SpeedKmh, bool bCornersOnly) const;

	UPROPERTY() TObjectPtr<UProceduralMeshComponent> Mesh;
	TArray<FVector4> Line;
	TArray<float> Distance;       // cumulative distance (cm) along the line
	struct FChunk                 // one mesh section: line points First .. First + Count - 1 (the last one wraps to 0 on a loop)
	{
		int32 First = 0;
		int32 Count = 0;
		TArray<FVector> Vertices;
		TArray<FVector> Normals;
		TArray<FVector2D> UVs;
		TArray<FLinearColor> Colours;
	};
	TArray<FChunk> Chunks;
	TArray<int32> Shown;          // sections visible after the last update
	TArray<int32> Want;           // (scratch)
	bool bLoop = false;
	int32 Nearest = -1;
	// last uploaded state: the vertex colours are only re-uploaded when one of these changes
	int32 UploadedNearest = -2;
	int32 UploadedSpeedBucket = -1;
	bool bUploadedCornersOnly = false;
};
