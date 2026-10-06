// Landmarks: GTA-style points of interest (the Architecture Shop at the Met Warehouse, HTMAA Lectures at E14).
//
// Data (no level content, nothing to rebuild in the editor):
//   <Project>/Tracks/<map>_landmarks.json          where (tools/minimap/landmarks.py: city address points + 3D models)
//   <Project>/UI/Generated/landmark_<id>_*.png      sign art + landmark_signs.json layout (tools/ui/make_landmark_signs.py)
//   <Project>/UI/Generated/landmark_<icon>[_lg].png map tags (tools/minimap/make_map.py --icons-only)
//   /Game/Cambridge/Landmarks/M_LandmarkSign        sign material (tools/unreal/build_landmark_assets.sh)
//
// At BeginPlay this spawns one ALandmarkActor (floating 8-bit sign + bouncing arrow + light pillar) per landmark.
// The minimap and the full map draw the tags through LandmarkMap::Paint* (called from MinimapWidgets.cpp); on the
// full map, Enter / A / click on a tag sets a GPS waypoint to it. Stopping next to a landmark shows a toast.
//
// Console (tests / screenshots):
//   cr.Landmark.GoTo <id|index> [metres]   put the car on the road ~that far away, heading towards it (50/150/300)
//   cr.Landmark.Navigate <id|index>        GPS waypoint to it
//   cr.Landmark.Toast <id|index>           show its arrival toast now
//   cr.Landmark.Signs 0|1                  hide / show the floating signs (perf A/B)

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "LandmarkSubsystem.generated.h"

class ALandmarkActor;
class FSlateWindowElementList;
class SWidget;
class UMinimapSubsystem;
class UTexture2D;
struct FGeometry;
struct FMmLandmarkTag;
struct FMmXform;

struct FLandmarkView
{
	FVector Location = FVector::ZeroVector;   // on the road (cm)
	float Yaw = 0.0f;
	float DistanceM = 0.0f;
};

struct FLandmarkDef
{
	FString Id;
	FString Label;          // "ARCHITECTURE SHOP"
	FString Subtitle;       // "MET WAREHOUSE"
	FString Address;        // "134 Massachusetts Ave / 95 Vassar St"
	FString Building;
	FName Icon;             // map tag brush (minimap icons), "<Icon>_lg" on the full map
	FName IconLg;           // "<Icon>_lg" (made once at load, not per paint)
	FLinearColor Accent = FLinearColor::White;
	FVector Entrance = FVector::ZeroVector;   // on the facade (cm)
	FVector Anchor = FVector::ZeroVector;     // arrow tip XY, in front of the entrance (cm); also the GPS target
	float RoofCm = 2000.0f;
	FVector2D FadeFarM = FVector2D::ZeroVector;   // "fade_far_m": sign fully visible to X, gone at Y (m); 0 = defaults
	TArray<FLandmarkView> Views;
};

UCLASS()
class ULandmarkSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static ULandmarkSubsystem* Get(const UObject* WorldContext);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bReady; }

	const TArray<FLandmarkDef>& GetLandmarks() const { return Landmarks; }
	/** Index by id ("htmaa") or by number ("1"); -1 if none. */
	int32 Find(const FString& IdOrIndex) const;

	void NavigateTo(int32 Index);
	void GoTo(int32 Index, float Metres);
	void ShowToast(int32 Index);
	void SetSignsVisible(bool bVisible);

private:
	void Load(const FString& MapName);
	void SpawnSigns();
	UTexture2D* LoadTexture(const FString& Path);
	void AttachToastHost();

	bool bReady = false;
	TArray<FLandmarkDef> Landmarks;
	UPROPERTY(Transient) TArray<TObjectPtr<ALandmarkActor>> Signs;
	UPROPERTY(Transient) TArray<TObjectPtr<UTexture2D>> Textures;

	// arrival toast
	TArray<float> StoppedFor;          // per landmark: seconds the car has been stopped close by
	TArray<bool> Armed;                // re-armed once the car drove away
	int32 ToastIndex = -1;
	double ToastAt = -100.0;
	TSharedPtr<SWidget> ToastHost;
	TWeakObjectPtr<class UGameViewportClient> ToastViewport;
};

/** Landmark tags on the HUD minimap and the full map (called from MinimapWidgets.cpp's paint code). */
namespace LandmarkMap
{
	/** HUD minimap: a tag per landmark; off-map ones clamp to the frame edge with an accent arrow, like the GPS pin. */
	void PaintMinimap(const UMinimapSubsystem& Map, const FMmXform& X, const FVector2D& Size, const FGeometry& Geo,
		FSlateWindowElementList& Out, int32 Layer);
	/** Full map: the landmark whose tag is under the cursor (within 30 px of its anchor), -1 if none. */
	int32 HitTest(const UMinimapSubsystem& Map, const FMmXform& X, const FVector2D& Cursor);
	/** Full map: where each tag and its name + subtitle pill go (beside the tag, least covering of the event badges
	 *  and the names under them; EventBadges = the badges' widget positions). The ONE placement rule: SFullMapView's
	 *  label layout calls it (and keeps the event names clear of the result), PaintFullMap only draws the result. */
	void PlaceTags(const UMinimapSubsystem& Map, const FMmXform& X, int32 Hovered, const TArray<FVector2D>& EventBadges,
		TArray<FMmLandmarkTag>& Out);
	/** Full map: draws the tags placed by PlaceTags (Hovered: the one under the cursor, -1 if none). */
	void PaintFullMap(const UMinimapSubsystem& Map, const TArray<FMmLandmarkTag>& Tags, int32 Hovered, const FGeometry& Geo,
		FSlateWindowElementList& Out, int32 Layer);
	/** Hover card of the full map for landmark Index. */
	FText CursorTitle(const UMinimapSubsystem& Map, int32 Index);
	FText CursorBody(const UMinimapSubsystem& Map, int32 Index);
	/** Enter / A / click on a hovered tag: GPS waypoint to it. False if there is no such landmark. */
	bool Navigate(UMinimapSubsystem& Map, int32 Index);
}
