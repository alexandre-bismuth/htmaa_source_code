// Minimap (HUD, bottom left), full-screen map and GPS navigation, Forza Horizon style.
//
// Data (regenerate with `cd tools/mapgen && uv run ../minimap/make_map.py <map>`):
//   <Project>/UI/Generated/minimap_<map>.json         layer bounds (UE cm), label anchors, icon sizes
//   <Project>/UI/Generated/minimap_<map>_{wide,detail}.png, minimap_*.png   map layers + icons (gitignored)
//   <Project>/Tracks/<map>_roads.json                 road graph for routing (committed)
// Events come from UTimeTrialSubsystem (start markers, gates, racing line, best times).
//
// Controls
//   M / gamepad View (Special Left)         open / close the full map (pauses the game, like the Esc menu)
//   in the map: WASD / arrows / left stick / d-pad / mouse drag   pan
//               Q-E / PageUp-PageDown / triggers / mouse wheel   zoom
//               Enter / A / left click        set a GPS waypoint at the cursor, or navigate to the event under it
//               Backspace / B / right click   clear the waypoint          M / Esc / B-less View   close
//
// GPS: A* on the road graph from the car's projection on the nearest street to the destination's; recomputed
// every 2 s and as soon as the car is > 25 m off the route; cleared on arrival (< 25 m, or in the event's start
// box, or - for a waypoint off the streets: in a building, a park, across the river - < 25 m from the route's
// last road point) with a short "arrived" note on the minimap. Suspended during events (the event route is
// shown instead). One-way streets are not modelled (the graph has none: tools/minimap/make_map.py).
// Nearest-street queries (the street chip every frame, the map cursor card, routing, the free-roam reset's
// snap to the road) go through a uniform grid over the road segments, so they cost a few cells, not the map.
//
// Console (tests / screenshots):
//   cr.Map.Toggle [0|1]          close / open the full map           cr.Map.SetWaypoint X Y   (UE cm)
//   cr.Map.NavigateToEvent N     GPS to event N's start              cr.Map.Clear
//   cr.Map.View X Y [PxPerM]     centre the full map (and its cursor) cr.Map.CursorToEvent N (hover card)
//   cr.Map.Minimap 0|1           HUD minimap off / on (the menu's Driving Assists > Minimap setting)

#pragma once

#include "CoreMinimal.h"
#include "Styling/SlateBrush.h"
#include "Subsystems/WorldSubsystem.h"
#include "MinimapSubsystem.generated.h"

class FMinimapInput;
class SFullMapView;
class SWidget;
class UTexture2D;
class UTimeTrialSubsystem;

/** One map texture and the world rectangle it covers (UE cm, Min = top-left = west / north). */
struct FMinimapLayer
{
	FSlateBrush Brush;
	FVector2D Min = FVector2D::ZeroVector;
	FVector2D Max = FVector2D::ZeroVector;
	float MetresPerPixel = 1.0f;
};

/** Street / area name drawn on the full map (north-up), at a constant screen size. */
struct FMinimapLabel
{
	FString Text;
	FVector2D Pos = FVector2D::ZeroVector;     // UE cm
	float AngleDeg = 0.0f;                      // screen angle, clockwise from +x, within -90..90
	uint8 Kind = 0;                             // 0 street, 1 area, 2 water
	uint8 Priority = 0;                         // 0 inside the play area, 1 backdrop
	mutable FVector2D Size = FVector2D(-1.0);   // measured on first use (Slate units)
};

/** A turn along the GPS route. */
struct FMinimapManeuver
{
	double Along = 0.0;     // cm from the route start
	int32 Turn = 0;         // -1 left, 0 straight on, +1 right
	int32 Street = -1;
};

UCLASS()
class UMinimapSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UMinimapSubsystem* Get(const UObject* WorldContext);
	/** Height the HUD minimap takes at the bottom left (Slate units, from the bottom edge incl. its margin), 0 when hidden. */
	static float GetHudFootprint();

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override { return bReady; }

	// ---- map data
	bool HasMap() const { return Layers.Num() > 0; }
	const TArray<FMinimapLayer>& GetLayers() const { return Layers; }
	const TArray<FMinimapLabel>& GetLabels() const { return Labels; }
	/** World rectangle of the whole map (cm). */
	FBox2D GetMapBounds() const { return MapBounds; }
	const FSlateBrush* GetIcon(FName Name) const;
	const TArray<FString>& GetStreetNames() const { return StreetNames; }

	// ---- car
	bool GetCarPose(FVector2D& OutLoc, float& OutYawDeg, float& OutSpeedKmh) const;
	/** Street the car is on ("" when away from the street network). */
	FText GetStreetText() const;

	// ---- events (UTimeTrialSubsystem)
	UTimeTrialSubsystem* GetTimeTrial() const;
	bool IsInEvent() const;
	/** An event's route (its racing line) as 2D world points (cached). */
	const TArray<FVector2D>& GetEventLine(int32 TrackIndex) const;

	// ---- GPS
	void SetDestination(const FVector2D& World, int32 EventIndex = -1);
	void NavigateToEvent(int32 EventIndex);
	void ClearDestination();
	/** Waypoint with a name for the GPS card / "arrived" note (landmarks, ULandmarkSubsystem). */
	void SetNamedDestination(const FVector2D& World, const FString& Name);
	bool HasDestination() const { return bHasDestination; }
	FVector2D GetDestination() const { return Destination; }
	int32 GetDestinationEvent() const { return DestinationEvent; }
	/** True when a route should be drawn (destination set, not in an event). */
	bool IsRouteActive() const { return bHasDestination && Route.Num() >= 2 && !IsInEvent(); }
	const TArray<FVector2D>& GetRoute() const { return Route; }
	/** Index of the route segment the car is on and the car's projection on it. */
	int32 GetRouteSegment() const { return RouteSeg; }
	FVector2D GetRouteProjection() const { return RouteProj; }
	FText GetDistanceText() const;            // "1.2 KM" to the destination
	bool HasInstruction() const;              // GPS instruction or a recent "arrived" note
	FText GetInstructionText() const;         // "Turn left onto Vassar St"
	FText GetInstructionDistanceText() const; // "120 m"
	const FSlateBrush* GetInstructionIcon() const;
	/** Nearest street name to a world point (within MaxCm), "" if none. */
	FString StreetNear(const FVector2D& World, double MaxCm) const;
	/** Nearest point on the drivable street network (the GPS graph: the main connected network inside the
	 *  playable area), the street's direction there (unit; its sign is arbitrary), the distance (cm) and the
	 *  street name ("" if unnamed). False without a road graph. Used by the free-roam reset (snap to the road). */
	bool NearestRoad(const FVector2D& World, FVector2D& OutPoint, FVector2D& OutDir, double& OutDistCm, FString* OutStreet = nullptr) const;

	// ---- full map
	void ToggleFullMap();
	void OpenFullMap();
	void CloseFullMap();
	bool IsFullMapOpen() const { return FullMapWidget.IsValid(); }
	TSharedPtr<SFullMapView> GetFullMapView() const { return FullMapView; }
	/** Console / tests: centre the full map on a world point (cm) with the cursor there, optional zoom (px per m). */
	void SetFullMapView(const FVector2D& Center, float PxPerM);

	/** HUD visibility (setting + full map closed). */
	bool IsMinimapVisible() const;

private:
	friend class FMinimapInput;

	void LoadMap(const FString& MapName);
	void LoadGraph(const FString& MapName);
	UTexture2D* LoadTexture(const FString& Path, bool bMips);
	void AttachHUD();
	void DetachHUD();

	// routing
	/** Nearest point of the road graph to P (within MaxCm when given). Grid search: a few cells around P. */
	bool Project(const FVector2D& P, int32& OutEdge, double& OutAlong, FVector2D& OutPoint, double& OutDist, FVector2D* OutDir = nullptr,
		double MaxCm = TNumericLimits<double>::Max()) const;
	void BuildRoadGrid();
	FVector2D EdgePointAt(int32 Edge, double Along) const;
	FVector2D RoutePointAt(double Along) const;
	bool ComputeRoute(const FVector2D& From, const FVector2D& Forward);
	void AppendEdgePart(int32 Edge, double From, double To);
	void AddRoutePoint(const FVector2D& P, int32 Street);
	void UpdateProgress(const FVector2D& Car);
	void Arrive();
	FString DestinationName() const;

	bool bReady = false;

	// map
	TArray<FMinimapLayer> Layers;
	TArray<FMinimapLabel> Labels;
	FBox2D MapBounds = FBox2D(ForceInit);
	TMap<FName, FSlateBrush> Icons;
	UPROPERTY(Transient) TArray<TObjectPtr<UTexture2D>> Textures;
	int64 TextureBytes = 0;             // GPU memory of the map textures and icons (BGRA8 + mips; no CPU copy is kept)

	// road graph
	TArray<FVector2D> Nodes;
	struct FEdge { int32 A = 0, B = 0, Street = -1, First = 0, Num = 0; double Length = 0.0; };
	TArray<FEdge> Edges;
	TArray<FVector2D> EdgePts;          // all edges' polylines, A -> B
	TArray<double> EdgeCum;             // distance along the edge at each point
	TArray<TArray<int32>> NodeEdges;
	TArray<FString> StreetNames;
	// spatial index: segment i runs EdgePts[i] -> EdgePts[i + 1] (both on edge PtEdge[i]); the segments touching
	// grid cell c are GridSegs[GridStart[c] .. GridStart[c + 1])
	TArray<int32> PtEdge;               // edge of each EdgePts entry (-1: a dropped edge's points)
	FVector2D GridMin = FVector2D::ZeroVector;
	double GridCellCm = 5000.0;
	int32 GridW = 0, GridH = 0;
	TArray<int32> GridStart;
	TArray<int32> GridSegs;

	// GPS state
	bool bHasDestination = false;
	FVector2D Destination = FVector2D::ZeroVector;
	int32 DestinationEvent = -1;
	FString DestinationLabel;           // SetNamedDestination
	TArray<FVector2D> Route;
	TArray<int32> RouteStreets;         // street of the segment ending at each point
	TArray<double> RouteCum;
	TArray<FMinimapManeuver> Maneuvers;
	int32 RouteSeg = 0;
	FVector2D RouteProj = FVector2D::ZeroVector;
	double RouteAlong = 0.0;
	double OffRouteCm = 0.0;
	double SinceRoute = 0.0;
	bool bRouteFailed = false;          // no road route (no graph / unreachable): a straight line, retried every 2 s only
	FVector2D RoadEnd = FVector2D::ZeroVector;   // last point of the route on the streets
	bool bArriveAtRoadEnd = false;      // the destination is off the streets: arriving at RoadEnd counts
	double ArrivedAt = -100.0;
	FString ArrivedName;
	int32 CarStreet = -1;
	mutable int32 StreetTextFor = -2;     // GetStreetText cache (the HUD asks every frame)
	mutable FText StreetText;
	mutable TMap<int32, TArray<FVector2D>> EventLines;

	// UI
	TSharedPtr<FMinimapInput> Input;
	TSharedPtr<SWidget> HUD;
	TWeakObjectPtr<class UGameViewportClient> HUDViewport;
	TSharedPtr<SWidget> FullMapWidget;
	TSharedPtr<SFullMapView> FullMapView;
	bool bPausedByMap = false;
	float SavedZoom = 1.0f;
};
