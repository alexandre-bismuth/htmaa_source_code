// Slate widgets of the minimap / full map (UMinimapSubsystem). Both map views are leaf widgets that paint the map
// textures as custom verts (a convex frame polygon clipped to each layer's projected rectangle, so the UVs never
// leave the texture), then routes as lines and icons as boxes. No per-frame allocations beyond Slate's own.

#pragma once

#include "CoreMinimal.h"
#include "Rendering/RenderingCommon.h"
#include "Widgets/SLeafWidget.h"

class UMinimapSubsystem;

/** World (UE cm) <-> widget-local transform: Local = Origin + R(Angle) * (World - Center) * Scale. */
struct FMmXform
{
	FVector2D Center = FVector2D::ZeroVector;
	FVector2D Origin = FVector2D::ZeroVector;
	double Scale = 0.01;      // local units per cm
	double Cos = 1.0, Sin = 0.0;

	void SetAngle(double Radians) { Cos = FMath::Cos(Radians); Sin = FMath::Sin(Radians); }
	FVector2D ToLocal(const FVector2D& W) const
	{
		const FVector2D D = (W - Center) * Scale;
		return Origin + FVector2D(Cos * D.X - Sin * D.Y, Sin * D.X + Cos * D.Y);
	}
	FVector2D ToWorld(const FVector2D& L) const
	{
		const FVector2D D = (L - Origin) / Scale;
		return Center + FVector2D(Cos * D.X + Sin * D.Y, -Sin * D.X + Cos * D.Y);
	}
};

/** A landmark tag on the full map, as LandmarkMap::PlaceTags placed it (widget space). */
struct FMmLandmarkTag
{
	bool bShown = false;                         // false: no icon for it (nothing drawn, nothing reserved)
	FVector2D Center = FVector2D::ZeroVector;    // the tag icon's centre (the landmark's anchor)
	double IconPx = 40.0;                        // icon size (larger when hovered)
	FBox2D Icon = FBox2D(ForceInit);
	FBox2D Block = FBox2D(ForceInit);            // name + subtitle pill
	FVector2D NameSize = FVector2D::ZeroVector, SubSize = FVector2D::ZeroVector;
};

/** Shared painting state / helpers for both views. */
class FMmPainter
{
public:
	void DrawLayers(const UMinimapSubsystem& Map, const FMmXform& X, const TArray<FVector2D>& Frame, const FGeometry& Geo,
		FSlateWindowElementList& Out, int32 Layer) const;
	void DrawPolyline(const TArray<FVector2D>& World, int32 First, const FVector2D* Prefix, bool bClosed, const FMmXform& X, const FGeometry& Geo,
		FSlateWindowElementList& Out, int32 Layer, const FLinearColor& Fill, float Width, const FLinearColor& Edge, float EdgeWidth) const;
	static void DrawIcon(const FSlateBrush* Brush, const FVector2D& Center, const FVector2D& Size, const FGeometry& Geo,
		FSlateWindowElementList& Out, int32 Layer, const FLinearColor& Tint = FLinearColor::White, float AngleRad = 0.0f);
	static void DrawText(const FString& Text, const FVector2D& TopLeft, const FSlateFontInfo& Font, const FGeometry& Geo,
		FSlateWindowElementList& Out, int32 Layer, const FLinearColor& Color, bool bShadow = true);

private:
	mutable TArray<FVector2D> ClipA, ClipB;
	mutable TArray<FSlateVertex> Verts;
	mutable TArray<SlateIndex> Indices;
	mutable TArray<FVector2D> LinePts;
};

/** HUD minimap: heading-up, zoom widens with speed, player arrow fixed near the centre. */
class SMinimapView : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SMinimapView) {}
		SLATE_ARGUMENT(TWeakObjectPtr<UMinimapSubsystem>, Map)
		SLATE_ARGUMENT(FVector2D, Size)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual FVector2D ComputeDesiredSize(float) const override { return Size; }
	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
		FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;

private:
	TWeakObjectPtr<UMinimapSubsystem> Map;
	FVector2D Size = FVector2D(320, 240);
	FMmPainter Painter;
	mutable TArray<FVector2D> Frame;
	mutable FVector2D FrameSize = FVector2D::ZeroVector;
	mutable double HalfHeightM = 120.0;   // smoothed visible half height (m)
	mutable double SmoothYaw = 0.0;
	mutable double LastPaint = 0.0;
	mutable TArray<int32> GateScratch;
};

/** Full-screen map: north-up, pan / zoom, cursor, event icons, labels, waypoint. */
class SFullMapView : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SFullMapView) {}
		SLATE_ARGUMENT(TWeakObjectPtr<UMinimapSubsystem>, Map)
		SLATE_ARGUMENT(FVector2D, Center)
		SLATE_ARGUMENT(float, Zoom)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(800, 600); }
	virtual bool SupportsKeyboardFocus() const override { return true; }
	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
		FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;

	// input (from UMinimapSubsystem's input processor)
	void PanLocal(const FVector2D& Delta);                    // drag the map by Delta local units
	void ZoomBy(float Factor, const FVector2D* AtLocal = nullptr);
	void SetCursorLocal(const FVector2D& L) { Cursor = L; bCursorFollowsCenter = false; }
	void CenterCursor() { bCursorFollowsCenter = true; }
	/** Put the cursor on event N's badge at the next paint (console / tests: shows its hover card). */
	void FocusEvent(int32 N) { PendingFocus = N; }
	void SetView(const FVector2D& InCenter, float InZoom);
	bool IsInside(const FVector2D& Screen) const;
	FVector2D ScreenToLocal(const FVector2D& Screen) const;
	/** Enter / A / click: navigate to the hovered event or drop a waypoint at the cursor. */
	void Confirm();

	float GetZoom() const { return Zoom; }
	FVector2D GetCursorWorld() const;
	int32 GetHoveredEvent() const { return Hovered; }
	FText GetCursorTitle() const;
	FText GetCursorBody() const;
	FName GetCursorIcon() const;

private:
	FMmXform MakeXform(const FVector2D& LocalSize) const;
	void ClampCenter();
	/** Greedy label placement (see the .cpp); rebuilt only when the view, the hovered tag or a label's text changes. */
	void LayoutLabels(const UMinimapSubsystem& M, const FMmXform& X, const FVector2D& S) const;

	TWeakObjectPtr<UMinimapSubsystem> Map;
	FMmPainter Painter;
	FVector2D Center = FVector2D::ZeroVector;    // world cm at the widget centre
	float Zoom = 1.0f;                            // local units per metre
	mutable FVector2D Cursor = FVector2D::ZeroVector;
	mutable FVector2D LastSize = FVector2D(800, 600);
	mutable bool bCursorFollowsCenter = true;
	mutable int32 Hovered = -1;
	mutable int32 HoveredLandmark = -1;     // ULandmarkSubsystem index under the cursor (when no event is)
	mutable int32 PendingFocus = -1;
	mutable TArray<FVector2D> Frame;
	mutable TArray<FVector2D> EventPos;     // event badges in local space (paint), used for hover

	// label layout cache: placed once per view (pan / zoom / size), hover target and label text, never per paint
	struct FLabelLayoutKey
	{
		FVector2D Size = FVector2D(-1.0), Center = FVector2D::ZeroVector;
		float Zoom = -1.0f;
		int32 HoveredEvent = -2, HoveredLandmark = -2, NumEvents = -1, NumLandmarks = -1;
		uint32 TextHash = 0;
		bool operator==(const FLabelLayoutKey& O) const
		{
			return Size == O.Size && Center == O.Center && Zoom == O.Zoom && HoveredEvent == O.HoveredEvent && HoveredLandmark == O.HoveredLandmark
				&& NumEvents == O.NumEvents && NumLandmarks == O.NumLandmarks && TextHash == O.TextHash;
		}
	};
	mutable FLabelLayoutKey LayoutKey;
	mutable int32 LayoutBuilds = 0;          // (stat: how often the layout was rebuilt ...
	mutable int32 PaintCount = 0;            //  ... over how many paints)
	mutable TArray<FString> EventTimeText;   // "BEST 1:23.456" / "NO TIME" per event
	mutable TArray<double> EventBestCache;   // the best times the strings above were made from
	mutable TArray<FVector2D> EventLabelTL;  // top-left of the name + time block; X < -1e8 = hidden (icon only)
	mutable TArray<FVector2D> EventLabelSize;
	mutable TArray<FVector2D> EventNameSize, EventTimeSize;
	mutable TArray<int32> StreetShown;       // indices into UMinimapSubsystem::GetLabels(), placed this view
	mutable TArray<FVector2D> StreetPos;
	mutable TArray<FMmLandmarkTag> LandmarkTags;   // landmark tags placed this view (LandmarkMap::PlaceTags), drawn by PaintFullMap
	mutable TArray<FVector2D> ScaleBar;      // (scratch: no per-paint allocation)
	mutable double ScaleMetres = -1.0;       // scale bar label cache
	mutable FString ScaleLabel;
	mutable FVector2D ScaleLabelSize = FVector2D::ZeroVector;
};

namespace MinimapUI
{
	/** Bottom-left HUD panel: Luna title chip (street, GPS distance) over glass with the map and the GPS hint. */
	TSharedRef<SWidget> MakeHudPanel(UMinimapSubsystem* Map);
	/** Full-screen map: blurred game, XP window with the map, legend, cursor card and key hints. */
	TSharedRef<SWidget> MakeFullMapScreen(UMinimapSubsystem* Map, TSharedPtr<SFullMapView>& OutView, const FVector2D& Center, float Zoom);

	constexpr float HudWidth = 336.0f;
	constexpr float HudMapW = 320.0f;
	constexpr float HudMapH = 240.0f;
	constexpr float HudHeight = 30.0f + 240.0f + 16.0f;   // title chip + map + glass padding
	constexpr float HudMarginLeft = 32.0f;
	constexpr float HudMarginBottom = 28.0f;
}
