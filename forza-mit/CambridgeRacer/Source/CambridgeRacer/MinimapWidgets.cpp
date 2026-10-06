#include "MinimapWidgets.h"

#include "CambridgeUIStyle.h"
#include "Fonts/FontMeasure.h"
#include "LandmarkSubsystem.h"
#include "Framework/Application/SlateApplication.h"
#include "MinimapSubsystem.h"
#include "Rendering/DrawElements.h"
#include "Rendering/SlateRenderer.h"
#include "Styling/CoreStyle.h"
#include "Textures/SlateShaderResource.h"
#include "TimeTrialSubsystem.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBackgroundBlur.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "Minimap"

DEFINE_LOG_CATEGORY_STATIC(LogMapLabels, Log, All);

namespace
{
	// Luna Glass map colours
	const FLinearColor MmGpsFill = FLinearColor(FColor(0x5c, 0xb8, 0xff));
	const FLinearColor MmGpsEdge = FLinearColor(FColor(0x0a, 0x24, 0x6a));
	const FLinearColor MmEventFill = FLinearColor(FColor(0xff, 0xb0, 0x00));
	const FLinearColor MmEventEdge = FLinearColor(FColor(0x3a, 0x22, 0x00));
	const FLinearColor MmGateNext = FLinearColor(FColor(0xff, 0xb0, 0x00));
	const FLinearColor MmGateFinish = FLinearColor(FColor(0x3d, 0xdc, 0x5a));
	const FLinearColor MmPinTint = FLinearColor(FColor(0xa5, 0x65, 0xff));
	const FLinearColor MmBackground = FLinearColor(FColor(0x0b, 0x0d, 0x11));

	double MmCross(const FVector2D& A, const FVector2D& B) { return A.X * B.Y - A.Y * B.X; }

	/** Rounded rectangle polygon (convex), clockwise in screen space. */
	void MmRoundedRect(TArray<FVector2D>& Out, const FVector2D& Size, double Radius, int32 Segs = 5)
	{
		Out.Reset();
		const double R = FMath::Min(Radius, FMath::Min(Size.X, Size.Y) * 0.5);
		const FVector2D Centers[4] = { FVector2D(Size.X - R, R), FVector2D(Size.X - R, Size.Y - R), FVector2D(R, Size.Y - R), FVector2D(R, R) };
		for (int32 c = 0; c < 4; ++c)
		{
			const double Start = -UE_HALF_PI + c * UE_HALF_PI;
			for (int32 i = 0; i <= Segs; ++i)
			{
				const double A = Start + UE_HALF_PI * i / Segs;
				Out.Add(Centers[c] + FVector2D(FMath::Cos(A), FMath::Sin(A)) * R);
			}
		}
	}

	/** Largest t so that From + Dir * t stays inside [Margin, Size - Margin]. */
	double MmRayToRect(const FVector2D& From, const FVector2D& Dir, const FVector2D& Size, double Margin)
	{
		double T = TNumericLimits<double>::Max();
		if (Dir.X > 1e-6) { T = FMath::Min(T, (Size.X - Margin - From.X) / Dir.X); }
		if (Dir.X < -1e-6) { T = FMath::Min(T, (Margin - From.X) / Dir.X); }
		if (Dir.Y > 1e-6) { T = FMath::Min(T, (Size.Y - Margin - From.Y) / Dir.Y); }
		if (Dir.Y < -1e-6) { T = FMath::Min(T, (Margin - From.Y) / Dir.Y); }
		return FMath::Max(0.0, T);
	}

	bool MmInsideRect(const FVector2D& P, const FVector2D& Size, double Margin)
	{
		return P.X >= Margin && P.Y >= Margin && P.X <= Size.X - Margin && P.Y <= Size.Y - Margin;
	}

	FString MmFormatTime(double T)
	{
		const int32 Minutes = int32(T / 60.0);
		return FString::Printf(TEXT("%d:%06.3f"), Minutes, T - Minutes * 60.0);
	}

	FString MmFormatDistance(double Cm)
	{
		const double M = Cm / 100.0;
		return M >= 1000.0 ? FString::Printf(TEXT("%.1f km"), M / 1000.0) : FString::Printf(TEXT("%d m"), FMath::RoundToInt(M / 10.0) * 10);
	}

	FVector2D MmMeasure(const FString& Text, const FSlateFontInfo& Font)
	{
		if (!FSlateApplication::IsInitialized())
		{
			return FVector2D(Text.Len() * 8.0, 14.0);
		}
		return FVector2D(FSlateApplication::Get().GetRenderer()->GetFontMeasureService()->Measure(Text, Font));
	}

	// full map fonts
	const FSlateFontInfo& MmStreetLabelFont(uint8 Kind)
	{
		static const FSlateFontInfo Street = []() { FSlateFontInfo F = CambridgeUI::CondensedFont(10.0f); F.OutlineSettings.OutlineSize = 2; F.OutlineSettings.OutlineColor = FLinearColor(0.0f, 0.0f, 0.0f, 0.85f); return F; }();
		static const FSlateFontInfo Area = []() { FSlateFontInfo F = CambridgeUI::PixelFont(12.0f, true); F.OutlineSettings.OutlineSize = 2; F.OutlineSettings.OutlineColor = FLinearColor(0.0f, 0.0f, 0.0f, 0.7f); F.LetterSpacing = 120; return F; }();
		static const FSlateFontInfo Water = []() { FSlateFontInfo F = CambridgeUI::BodyFont(11.0f); F.OutlineSettings.OutlineSize = 1; F.OutlineSettings.OutlineColor = FLinearColor(0.0f, 0.02f, 0.08f, 0.8f); F.LetterSpacing = 160; return F; }();
		return Kind == 0 ? Street : (Kind == 1 ? Area : Water);
	}
	const FSlateFontInfo& MmEventNameFont() { static const FSlateFontInfo F = CambridgeUI::PixelFont(12.0f, true); return F; }
	const FSlateFontInfo& MmEventTimeFont() { static const FSlateFontInfo F = CambridgeUI::DigitsFont(6.0f); return F; }

	constexpr double MmHiddenLabel = -1.0e9;     // EventLabelTL.X of a name with no room at this zoom
}

// ------------------------------------------------------------------ painter

void FMmPainter::DrawLayers(const UMinimapSubsystem& Map, const FMmXform& X, const TArray<FVector2D>& Frame, const FGeometry& Geo,
	FSlateWindowElementList& Out, int32 Layer) const
{
	if (!FSlateApplication::IsInitialized() || Frame.Num() < 3)
	{
		return;
	}
	const FSlateRenderTransform& RT = Geo.GetAccumulatedRenderTransform();
	for (const FMinimapLayer& L : Map.GetLayers())
	{
		// the layer's rectangle in widget space (rotated quad); clip the frame polygon to it (both convex)
		const FVector2D Q[4] = { X.ToLocal(L.Min), X.ToLocal(FVector2D(L.Max.X, L.Min.Y)), X.ToLocal(L.Max), X.ToLocal(FVector2D(L.Min.X, L.Max.Y)) };
		const double Sign = MmCross(Q[1] - Q[0], Q[2] - Q[1]) >= 0.0 ? 1.0 : -1.0;
		ClipA = Frame;
		for (int32 e = 0; e < 4 && ClipA.Num() >= 3; ++e)
		{
			const FVector2D P0 = Q[e];
			const FVector2D E = Q[(e + 1) % 4] - P0;
			auto Side = [&](const FVector2D& P) { return Sign * MmCross(E, P - P0); };
			ClipB.Reset();
			const int32 N = ClipA.Num();
			for (int32 i = 0; i < N; ++i)
			{
				const FVector2D& Cur = ClipA[i];
				const FVector2D& Prev = ClipA[(i + N - 1) % N];
				const double SC = Side(Cur), SP = Side(Prev);
				if ((SC >= 0.0) != (SP >= 0.0))
				{
					ClipB.Add(Prev + (Cur - Prev) * (SP / (SP - SC)));
				}
				if (SC >= 0.0)
				{
					ClipB.Add(Cur);
				}
			}
			Swap(ClipA, ClipB);
		}
		if (ClipA.Num() < 3)
		{
			continue;
		}
		const FSlateResourceHandle Handle = FSlateApplication::Get().GetRenderer()->GetResourceHandle(L.Brush);
		if (!Handle.IsValid())
		{
			continue;
		}
		FVector2f UV0(0.0f, 0.0f), UVS(1.0f, 1.0f);
		if (const FSlateShaderResourceProxy* Proxy = Handle.GetResourceProxy())
		{
			UV0 = Proxy->StartUV;
			UVS = Proxy->SizeUV;
		}
		const FVector2D Span = L.Max - L.Min;
		Verts.Reset();
		Indices.Reset();
		for (const FVector2D& P : ClipA)
		{
			const FVector2D W = X.ToWorld(P);
			const FVector2f UV(FMath::Clamp(float((W.X - L.Min.X) / Span.X), 0.0f, 1.0f), FMath::Clamp(float((W.Y - L.Min.Y) / Span.Y), 0.0f, 1.0f));
			Verts.Add(FSlateVertex::Make<ESlateVertexRounding::Disabled>(RT, FVector2f(P), UV0 + UV * UVS, FColor::White));
		}
		for (int32 i = 1; i + 1 < ClipA.Num(); ++i)
		{
			Indices.Add(0);
			Indices.Add(SlateIndex(i));
			Indices.Add(SlateIndex(i + 1));
		}
		FSlateDrawElement::MakeCustomVerts(Out, Layer, Handle, Verts, Indices, nullptr, 0, 0);
	}
}

void FMmPainter::DrawPolyline(const TArray<FVector2D>& World, int32 First, const FVector2D* Prefix, bool bClosed, const FMmXform& X,
	const FGeometry& Geo, FSlateWindowElementList& Out, int32 Layer, const FLinearColor& Fill, float Width, const FLinearColor& Edge, float EdgeWidth) const
{
	LinePts.Reset();
	if (Prefix)
	{
		LinePts.Add(X.ToLocal(*Prefix));
	}
	for (int32 i = FMath::Max(0, First); i < World.Num(); ++i)
	{
		LinePts.Add(X.ToLocal(World[i]));
	}
	if (bClosed && World.Num() > 1)
	{
		LinePts.Add(X.ToLocal(World[0]));
	}
	if (LinePts.Num() < 2)
	{
		return;
	}
	const FPaintGeometry PG = Geo.ToPaintGeometry();
	if (EdgeWidth > 0.0f)
	{
		FSlateDrawElement::MakeLines(Out, Layer, PG, LinePts, ESlateDrawEffect::None, Edge, true, EdgeWidth);
	}
	FSlateDrawElement::MakeLines(Out, Layer + 1, PG, LinePts, ESlateDrawEffect::None, Fill, true, Width);
}

void FMmPainter::DrawIcon(const FSlateBrush* Brush, const FVector2D& Center, const FVector2D& Size, const FGeometry& Geo,
	FSlateWindowElementList& Out, int32 Layer, const FLinearColor& Tint, float AngleRad)
{
	if (!Brush)
	{
		return;
	}
	const FPaintGeometry PG = Geo.ToPaintGeometry(FVector2f(Size), FSlateLayoutTransform(FVector2f(Center - Size * 0.5)));
	if (AngleRad != 0.0f)
	{
		FSlateDrawElement::MakeRotatedBox(Out, Layer, PG, Brush, ESlateDrawEffect::None, AngleRad, TOptional<FVector2f>(), FSlateDrawElement::RelativeToElement, Tint);
	}
	else
	{
		FSlateDrawElement::MakeBox(Out, Layer, PG, Brush, ESlateDrawEffect::None, Tint);
	}
}

void FMmPainter::DrawText(const FString& Text, const FVector2D& TopLeft, const FSlateFontInfo& Font, const FGeometry& Geo,
	FSlateWindowElementList& Out, int32 Layer, const FLinearColor& Color, bool bShadow)
{
	const FVector2f Size(600.0f, 60.0f);
	if (bShadow)
	{
		FSlateDrawElement::MakeText(Out, Layer, Geo.ToPaintGeometry(Size, FSlateLayoutTransform(FVector2f(TopLeft + FVector2D(1.0, 1.0)))), Text, Font,
			ESlateDrawEffect::None, FLinearColor(0.0f, 0.0f, 0.0f, 0.85f * Color.A));
	}
	FSlateDrawElement::MakeText(Out, Layer, Geo.ToPaintGeometry(Size, FSlateLayoutTransform(FVector2f(TopLeft))), Text, Font, ESlateDrawEffect::None, Color);
}

// ------------------------------------------------------------------ HUD minimap

void SMinimapView::Construct(const FArguments& InArgs)
{
	Map = InArgs._Map;
	Size = InArgs._Size;
	SetClipping(EWidgetClipping::ClipToBounds);
	SetCanTick(false);
}

int32 SMinimapView::OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	FSlateWindowElementList& Out, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const
{
	UMinimapSubsystem* M = Map.Get();
	if (!M || !M->HasMap())
	{
		return LayerId;
	}
	const FVector2D S = AllottedGeometry.GetLocalSize();
	if (!S.Equals(FrameSize, 0.01))
	{
		FrameSize = S;
		MmRoundedRect(Frame, S, 7.0);
	}
	FVector2D Car;
	float Yaw = 0.0f, Kmh = 0.0f;
	if (!M->GetCarPose(Car, Yaw, Kmh))
	{
		return LayerId;
	}

	// zoom out with speed, ease the heading (the map turns, the arrow stays up)
	const double Now = FPlatformTime::Seconds();
	const double Dt = FMath::Clamp(Now - LastPaint, 0.0, 0.1);
	LastPaint = Now;
	const double Target = FMath::Lerp(110.0, 260.0, FMath::Clamp(Kmh / 140.0, 0.0, 1.0));
	HalfHeightM += (Target - HalfHeightM) * FMath::Min(1.0, Dt * 1.5);
	SmoothYaw += FMath::FindDeltaAngleDegrees(SmoothYaw, double(Yaw)) * FMath::Min(1.0, Dt * 14.0);
	SmoothYaw = FRotator::NormalizeAxis(SmoothYaw);

	FMmXform X;
	X.Center = Car;
	X.Origin = FVector2D(S.X * 0.5, S.Y * 0.6);
	X.Scale = (S.Y * 0.5) / (HalfHeightM * 100.0);
	X.SetAngle(-FMath::DegreesToRadians(SmoothYaw + 90.0));   // car forward -> screen up

	const FGeometry& G = AllottedGeometry;
	FSlateDrawElement::MakeBox(Out, LayerId, G.ToPaintGeometry(), FCoreStyle::Get().GetBrush("WhiteBrush"), ESlateDrawEffect::None, MmBackground.CopyWithNewOpacity(0.6f));
	Painter.DrawLayers(*M, X, Frame, G, Out, LayerId + 1);

	UTimeTrialSubsystem* TT = M->GetTimeTrial();
	const int32 Active = TT ? TT->GetActiveTrack() : -1;
	if (Active >= 0 && TT->GetTracks().IsValidIndex(Active))
	{
		// event: its route (the racing line) and the next gates
		const FTimeTrialTrack& T = TT->GetTracks()[Active];
		Painter.DrawPolyline(M->GetEventLine(Active), 0, nullptr, T.bCircuit, X, G, Out, LayerId + 2, MmEventFill, 3.5f, MmEventEdge, 6.5f);
		TT->GetUpcomingGates(GateScratch, 2);
		const int32 Left = TT->GetGatesLeft();
		for (int32 k = GateScratch.Num() - 1; k >= 0; --k)
		{
			const bool bFinish = k == Left - 1;
			const FLinearColor Tint = bFinish ? MmGateFinish : (k == 0 ? MmGateNext : FLinearColor::White);
			const double Px = k == 0 ? 16.0 : 12.0;
			FMmPainter::DrawIcon(M->GetIcon("minimap_gate"), X.ToLocal(FVector2D(T.Gates[GateScratch[k]].Location)), FVector2D(Px), G, Out, LayerId + 4, Tint);
		}
	}
	else if (TT)
	{
		// free roam: every event start
		for (const FTimeTrialTrack& T : TT->GetTracks())
		{
			if (T.Gates.Num() > 0)
			{
				FMmPainter::DrawIcon(M->GetIcon("minimap_event"), X.ToLocal(FVector2D(T.Gates[0].Location)), FVector2D(24.0), G, Out, LayerId + 4);
			}
		}
	}

	if (M->IsRouteActive())
	{
		const FVector2D Proj = M->GetRouteProjection();
		Painter.DrawPolyline(M->GetRoute(), M->GetRouteSegment() + 1, &Proj, false, X, G, Out, LayerId + 5, MmGpsFill, 4.5f, MmGpsEdge, 8.0f);
	}
	LandmarkMap::PaintMinimap(*M, X, S, G, Out, LayerId + 6);     // landmark tags (clamped to the edge when off the map)
	if (M->HasDestination() && Active < 0)
	{
		const FVector2D D = X.ToLocal(M->GetDestination());
		const double Margin = 18.0;
		if (MmInsideRect(D, S, Margin))
		{
			FMmPainter::DrawIcon(M->GetIcon("minimap_pin"), D - FVector2D(0.0, 12.0), FVector2D(20.0, 26.0), G, Out, LayerId + 7);
		}
		else
		{
			// off the map: an arrow on the edge pointing at it, with the pin just inside
			const FVector2D Dir = D - X.Origin;
			const FVector2D N = Dir.GetSafeNormal();
			const FVector2D P = X.Origin + Dir * MmRayToRect(X.Origin, Dir, S, 10.0);
			const float Angle = float(FMath::Atan2(N.Y, N.X) + UE_HALF_PI);
			FMmPainter::DrawIcon(M->GetIcon("minimap_edge"), P, FVector2D(16.0), G, Out, LayerId + 7, MmPinTint, Angle);
			FMmPainter::DrawIcon(M->GetIcon("minimap_pin"), P - N * 20.0 - FVector2D(0.0, 8.0), FVector2D(14.0, 18.0), G, Out, LayerId + 7);
		}
	}

	FMmPainter::DrawIcon(M->GetIcon("minimap_player"), X.Origin, FVector2D(28.0), G, Out, LayerId + 8);

	// compass: N on the frame edge, towards north
	const FVector2D North(X.Sin, -X.Cos);          // R * (0, -1)
	const FVector2D Mid = S * 0.5;
	FMmPainter::DrawIcon(M->GetIcon("minimap_north"), Mid + North * MmRayToRect(Mid, North, S, 14.0), FVector2D(22.0), G, Out, LayerId + 9);
	return LayerId + 10;
}

// ------------------------------------------------------------------ full map

void SFullMapView::Construct(const FArguments& InArgs)
{
	Map = InArgs._Map;
	Center = InArgs._Center;
	Zoom = InArgs._Zoom > 0.0f ? InArgs._Zoom : 1.0f;
	SetClipping(EWidgetClipping::ClipToBounds);
	SetCanTick(false);
}

FMmXform SFullMapView::MakeXform(const FVector2D& LocalSize) const
{
	FMmXform X;
	X.Center = Center;
	X.Origin = LocalSize * 0.5;
	X.Scale = Zoom / 100.0;
	return X;
}

void SFullMapView::ClampCenter()
{
	if (const UMinimapSubsystem* M = Map.Get())
	{
		const FBox2D B = M->GetMapBounds();
		if (B.bIsValid)
		{
			Center.X = FMath::Clamp(Center.X, B.Min.X, B.Max.X);
			Center.Y = FMath::Clamp(Center.Y, B.Min.Y, B.Max.Y);
		}
	}
}

void SFullMapView::PanLocal(const FVector2D& Delta)
{
	Center -= Delta / (Zoom / 100.0);
	ClampCenter();
}

void SFullMapView::ZoomBy(float Factor, const FVector2D* AtLocal)
{
	const FVector2D At = AtLocal ? *AtLocal : LastSize * 0.5;
	const FVector2D Before = MakeXform(LastSize).ToWorld(At);
	float MinZoom = 0.15f;
	if (const UMinimapSubsystem* M = Map.Get())
	{
		const FVector2D Ext = M->GetMapBounds().GetSize() / 100.0;
		if (Ext.X > 0.0 && Ext.Y > 0.0)
		{
			MinZoom = FMath::Max(0.1f, float(FMath::Min(LastSize.X / Ext.X, LastSize.Y / Ext.Y)) * 0.9f);
		}
	}
	Zoom = FMath::Clamp(Zoom * Factor, MinZoom, 4.0f);
	Center += Before - MakeXform(LastSize).ToWorld(At);
	ClampCenter();
}

void SFullMapView::SetView(const FVector2D& InCenter, float InZoom)
{
	Center = InCenter;
	if (InZoom > 0.0f)
	{
		Zoom = FMath::Clamp(InZoom, 0.1f, 4.0f);
	}
	CenterCursor();
	ClampCenter();
}

bool SFullMapView::IsInside(const FVector2D& Screen) const
{
	return GetTickSpaceGeometry().IsUnderLocation(Screen);
}

FVector2D SFullMapView::ScreenToLocal(const FVector2D& Screen) const
{
	return FVector2D(GetTickSpaceGeometry().AbsoluteToLocal(Screen));
}

FVector2D SFullMapView::GetCursorWorld() const
{
	return MakeXform(LastSize).ToWorld(bCursorFollowsCenter ? LastSize * 0.5 : Cursor);
}

void SFullMapView::Confirm()
{
	UMinimapSubsystem* M = Map.Get();
	if (!M)
	{
		return;
	}
	if (Hovered >= 0)
	{
		M->NavigateToEvent(Hovered);
	}
	else if (HoveredLandmark >= 0 && LandmarkMap::Navigate(*M, HoveredLandmark))
	{
	}
	else
	{
		M->SetDestination(GetCursorWorld());
	}
}

FText SFullMapView::GetCursorTitle() const
{
	const UMinimapSubsystem* M = Map.Get();
	UTimeTrialSubsystem* TT = M ? M->GetTimeTrial() : nullptr;
	if (TT && TT->GetTracks().IsValidIndex(Hovered))
	{
		return FText::FromString(TT->GetTracks()[Hovered].Name);
	}
	if (M && Hovered < 0 && HoveredLandmark >= 0)
	{
		return LandmarkMap::CursorTitle(*M, HoveredLandmark);
	}
	const FString Street = M ? M->StreetNear(GetCursorWorld(), 4000.0) : FString();
	return Street.IsEmpty() ? LOCTEXT("CursorNoStreet", "Off the street map") : FText::FromString(Street);
}

FText SFullMapView::GetCursorBody() const
{
	const UMinimapSubsystem* M = Map.Get();
	if (!M)
	{
		return FText::GetEmpty();
	}
	UTimeTrialSubsystem* TT = M->GetTimeTrial();
	if (TT && TT->GetTracks().IsValidIndex(Hovered))
	{
		const FTimeTrialTrack& T = TT->GetTracks()[Hovered];
		FString S = FString::Printf(TEXT("%s  ·  %.1f km"), T.bCircuit ? TEXT("Circuit") : TEXT("Sprint"), T.LengthM * T.Laps / 1000.0f);
		if (T.bCircuit) { S += FString::Printf(TEXT("  ·  %d laps"), T.Laps); }
		const double Best = TT->GetBestTime(Hovered);
		S += Best > 0.0 ? TEXT("\nPersonal best ") + MmFormatTime(Best) : FString(TEXT("\nNo time set yet"));
		S += TEXT("\nEnter / A: navigate to the start");
		return FText::FromString(S);
	}
	if (Hovered < 0 && HoveredLandmark >= 0)
	{
		return LandmarkMap::CursorBody(*M, HoveredLandmark);
	}
	FVector2D Car;
	float Yaw, Kmh;
	FString S;
	if (M->GetCarPose(Car, Yaw, Kmh))
	{
		S = MmFormatDistance(FVector2D::Distance(Car, GetCursorWorld())) + TEXT(" from your car\n");
	}
	S += TEXT("Enter / A / click: set a GPS waypoint here");
	if (M->HasDestination())
	{
		S += TEXT("\nBackspace / B / right click: clear the waypoint");
	}
	return FText::FromString(S);
}

FName SFullMapView::GetCursorIcon() const
{
	return Hovered >= 0 || HoveredLandmark >= 0 ? FName(TEXT("icon_flag")) : FName(TEXT("icon_info"));
}

/**
 * Greedy label placement for the full map, by priority: the hovered event's name > landmark tags > the other event
 * names > street / area / water names. Each event name (name + best time block) tries below, above, right and left of
 * its badge and takes the first spot that is on screen and clear of every badge / tag icon and of the labels already
 * placed (then the first clear spot partly off screen); with no room at this zoom the name is hidden and the badge
 * stays (the hovered event always shows its name). Street names keep their own importance order and are dropped on
 * any collision. Runs from OnPaint only when LayoutKey changes (pan, zoom, size, hover, label text). Positions are
 * in widget space, so nothing depends on the map's extent.
 */
void SFullMapView::LayoutLabels(const UMinimapSubsystem& M, const FMmXform& X, const FVector2D& S) const
{
	++LayoutBuilds;
	const int32 NumEvents = EventPos.Num();
	const FBox2D Screen(FVector2D(4.0, 4.0), S - FVector2D(4.0, 4.0));
	TArray<FBox2D, TInlineAllocator<32>> Icons;
	TArray<int32, TInlineAllocator<32>> IconOwner;           // event index, or -1 for landmark icons
	TArray<FBox2D, TInlineAllocator<64>> Taken;              // label blocks placed so far
	auto Clear = [&](const FBox2D& B, int32 Owner)
	{
		for (int32 k = 0; k < Icons.Num(); ++k)
		{
			if (IconOwner[k] != Owner && Icons[k].Intersect(B)) { return false; }
		}
		for (const FBox2D& T : Taken)
		{
			if (T.Intersect(B)) { return false; }
		}
		return true;
	};
	auto Inside = [&Screen](const FBox2D& B) { return Screen.IsInside(B.Min) && Screen.IsInside(B.Max); };

	for (int32 i = 0; i < NumEvents; ++i)
	{
		const double Px = (i == LayoutKey.HoveredEvent ? 48.0 : 40.0) * 0.5;
		Icons.Add(FBox2D(EventPos[i] - FVector2D(Px), EventPos[i] + FVector2D(Px)));
		IconOwner.Add(i);
	}
	// landmark tags: placed here once per view by the landmark code's own rule (LandmarkMap::PlaceTags), then drawn from
	// LandmarkTags by LandmarkMap::PaintFullMap; the event names below keep clear of exactly those rects
	TArray<FBox2D, TInlineAllocator<16>> TagBlocks;
	LandmarkMap::PlaceTags(M, X, LayoutKey.HoveredLandmark, EventPos, LandmarkTags);
	for (const FMmLandmarkTag& Tag : LandmarkTags)
	{
		if (Tag.bShown)
		{
			Icons.Add(Tag.Icon);
			IconOwner.Add(-1);
			TagBlocks.Add(Tag.Block);
		}
	}

	TArray<int32, TInlineAllocator<16>> Side;     // (log) 0 below, 1 above, 2 right, 3 left, -1 hidden
	Side.Init(-1, NumEvents);
	EventLabelTL.Init(FVector2D(MmHiddenLabel), NumEvents);
	EventLabelSize.SetNum(NumEvents);
	auto PlaceEvent = [&](int32 i, bool bAlways)
	{
		const FVector2D P = EventPos[i];
		const double Half = (i == LayoutKey.HoveredEvent ? 48.0 : 40.0) * 0.5;
		const FVector2D Sz(FMath::Max(EventNameSize[i].X, EventTimeSize[i].X), EventNameSize[i].Y + 2.0 + EventTimeSize[i].Y);
		EventLabelSize[i] = Sz;
		const FVector2D Candidates[] = {
			FVector2D(P.X - Sz.X * 0.5, P.Y + Half + 2.0),             // below (the default)
			FVector2D(P.X - Sz.X * 0.5, P.Y - Half - 2.0 - Sz.Y),      // above
			FVector2D(P.X + Half + 4.0, P.Y - Sz.Y * 0.5),             // right
			FVector2D(P.X - Half - 4.0 - Sz.X, P.Y - Sz.Y * 0.5) };    // left
		const FVector2D Pad(3.0, 2.0);
		for (int32 Pass = 0; Pass < 2; ++Pass)
		{
			for (const FVector2D& C : Candidates)
			{
				const FBox2D B(C - Pad, C + Sz + Pad);
				if ((Pass == 1 || Inside(B)) && Clear(B, i))
				{
					EventLabelTL[i] = C;
					Side[i] = int32(&C - Candidates);
					Taken.Add(B);
					return;
				}
			}
		}
		if (bAlways)
		{
			EventLabelTL[i] = Candidates[0];
			Side[i] = 0;
			Taken.Add(FBox2D(Candidates[0] - Pad, Candidates[0] + Sz + Pad));
		}
	};
	if (EventPos.IsValidIndex(LayoutKey.HoveredEvent))
	{
		PlaceEvent(LayoutKey.HoveredEvent, true);
	}
	Taken.Append(TagBlocks);
	for (int32 i = 0; i < NumEvents; ++i)
	{
		if (i != LayoutKey.HoveredEvent)
		{
			PlaceEvent(i, false);
		}
	}

	// street / area / water names: constant screen size, in the JSON's importance order, dropped on any collision
	StreetShown.Reset();
	StreetPos.Reset();
	const FSlateRect View(-80.0f, -40.0f, S.X + 80.0f, S.Y + 40.0f);
	const TArray<FMinimapLabel>& Labels = M.GetLabels();
	for (int32 k = 0; k < Labels.Num(); ++k)
	{
		const FMinimapLabel& Lb = Labels[k];
		if (Lb.Kind == 0 && ((Lb.Priority == 0 && Zoom < 0.55f) || (Lb.Priority > 0 && Zoom < 1.1f)))
		{
			continue;
		}
		if (Lb.Kind == 1 && Zoom > 2.2f)
		{
			continue;
		}
		const FVector2D P = X.ToLocal(Lb.Pos);
		if (!View.ContainsPoint(FVector2f(P)))
		{
			continue;
		}
		if (Lb.Size.X < 0.0)
		{
			Lb.Size = MmMeasure(Lb.Text, MmStreetLabelFont(Lb.Kind));     // (area names are upper case since the load)
		}
		const double Rad = FMath::DegreesToRadians(double(Lb.AngleDeg));
		const double C = FMath::Abs(FMath::Cos(Rad)), Sn = FMath::Abs(FMath::Sin(Rad));
		const FVector2D Half(C * Lb.Size.X * 0.5 + Sn * Lb.Size.Y * 0.5 + 3.0, Sn * Lb.Size.X * 0.5 + C * Lb.Size.Y * 0.5 + 2.0);
		const FBox2D Box(P - Half, P + Half);
		if (!Clear(Box, -2))
		{
			continue;
		}
		Taken.Add(Box);
		StreetShown.Add(k);
		StreetPos.Add(P);
	}
	if (LayoutBuilds <= 60)    // (verification: one rebuild per view change, not per paint)
	{
		static const TCHAR* SideNames[] = { TEXT("below"), TEXT("above"), TEXT("right"), TEXT("left") };
		FString Ev;
		for (int32 i = 0; i < NumEvents; ++i)
		{
			Ev += FString::Printf(TEXT(" %d:%s"), i, Side[i] >= 0 ? SideNames[Side[i]] : TEXT("hidden"));
		}
		UE_LOG(LogMapLabels, Display, TEXT("label layout #%d after %d paints: zoom %.2f, view %.0fx%.0f, hovered event %d landmark %d, tags %d, names%s, street labels %d"),
			LayoutBuilds, PaintCount, Zoom, S.X, S.Y, LayoutKey.HoveredEvent, LayoutKey.HoveredLandmark, TagBlocks.Num(), *Ev, StreetShown.Num());
	}
}

int32 SFullMapView::OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	FSlateWindowElementList& Out, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const
{
	namespace CUI = CambridgeUI;
	UMinimapSubsystem* M = Map.Get();
	const FGeometry& G = AllottedGeometry;
	const FVector2D S = G.GetLocalSize();
	FSlateDrawElement::MakeBox(Out, LayerId, G.ToPaintGeometry(), FCoreStyle::Get().GetBrush("WhiteBrush"), ESlateDrawEffect::None, MmBackground);
	if (!M || !M->HasMap())
	{
		return LayerId + 1;
	}
	LastSize = S;
	++PaintCount;
	if (bCursorFollowsCenter)
	{
		Cursor = S * 0.5;
	}
	const FMmXform X = MakeXform(S);
	Frame.Reset();
	Frame.Add(FVector2D(0, 0));
	Frame.Add(FVector2D(S.X, 0));
	Frame.Add(S);
	Frame.Add(FVector2D(0, S.Y));
	Painter.DrawLayers(*M, X, Frame, G, Out, LayerId + 1);

	// ---- event badges in local space (events sharing a start spot are fanned out sideways) and the hovered one
	UTimeTrialSubsystem* TT = M->GetTimeTrial();
	const int32 Active = TT ? TT->GetActiveTrack() : -1;
	Hovered = -1;
	EventPos.Reset();
	if (TT)
	{
		const TArray<FTimeTrialTrack>& Tracks = TT->GetTracks();
		for (int32 i = 0; i < Tracks.Num(); ++i)
		{
			const FVector2D W = Tracks[i].Gates.Num() ? FVector2D(Tracks[i].Gates[0].Location) : FVector2D(Tracks[i].StartLocation);
			int32 Same = 0;
			for (int32 j = 0; j < i; ++j)
			{
				const FVector2D Wj = Tracks[j].Gates.Num() ? FVector2D(Tracks[j].Gates[0].Location) : FVector2D(Tracks[j].StartLocation);
				Same += FVector2D::Distance(W, Wj) < 2500.0 ? 1 : 0;
			}
			EventPos.Add(X.ToLocal(W) + FVector2D(Same * 150.0, 0.0));
		}
		if (EventPos.IsValidIndex(PendingFocus))
		{
			Cursor = EventPos[PendingFocus];
			bCursorFollowsCenter = false;
		}
		PendingFocus = -1;
		double BestD = 32.0;
		for (int32 i = 0; i < EventPos.Num(); ++i)
		{
			const double D = FVector2D::Distance(EventPos[i], Cursor);
			if (D < BestD) { BestD = D; Hovered = i; }
		}
	}

	// ---- label layout: rebuilt only when the view, the hovered tag or a label's text changes
	{
		FLabelLayoutKey Key;
		Key.Size = S;
		Key.Center = Center;
		Key.Zoom = Zoom;
		Key.HoveredEvent = Hovered;
		Key.HoveredLandmark = Hovered < 0 ? LandmarkMap::HitTest(*M, X, Cursor) : -1;
		Key.NumEvents = EventPos.Num();
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(M);
		Key.NumLandmarks = L ? L->GetLandmarks().Num() : 0;
		// best times change the "BEST m:ss.sss" lines (strings and sizes cached per event)
		if (EventBestCache.Num() != EventPos.Num())
		{
			EventBestCache.Init(-2.0, EventPos.Num());
			EventTimeText.SetNum(EventPos.Num());
			EventTimeSize.SetNum(EventPos.Num());
			EventNameSize.Init(FVector2D(-1.0), EventPos.Num());
		}
		uint32 Hash = 0;
		for (int32 i = 0; i < EventPos.Num(); ++i)
		{
			const double Best = TT->GetBestTime(i);
			if (Best != EventBestCache[i])
			{
				EventBestCache[i] = Best;
				EventTimeText[i] = Best > 0.0 ? TEXT("BEST ") + MmFormatTime(Best) : FString(TEXT("NO TIME"));
				EventTimeSize[i] = MmMeasure(EventTimeText[i], MmEventTimeFont());
			}
			if (EventNameSize[i].X < 0.0)
			{
				EventNameSize[i] = MmMeasure(TT->GetTracks()[i].Name, MmEventNameFont());
			}
			Hash = HashCombineFast(Hash, GetTypeHash(Best));
		}
		Key.TextHash = Hash;
		if (!(Key == LayoutKey))
		{
			LayoutKey = Key;
			LayoutLabels(*M, X, S);
		}
		HoveredLandmark = LayoutKey.HoveredLandmark;
	}

	// ---- street / area / water names (placed by LayoutLabels, below everything else)
	{
		const TArray<FMinimapLabel>& Labels = M->GetLabels();
		for (int32 k = 0; k < StreetShown.Num(); ++k)
		{
			if (!Labels.IsValidIndex(StreetShown[k]))
			{
				continue;
			}
			const FMinimapLabel& Lb = Labels[StreetShown[k]];
			const FVector2D P = StreetPos[k];
			const FLinearColor Color = Lb.Kind == 2 ? FLinearColor(FColor(0x8c, 0xc0, 0xff)) : Lb.Kind == 1 ? FLinearColor(1.0f, 1.0f, 1.0f, 0.55f)
				: (Lb.Priority == 0 ? FLinearColor(FColor(0xe6, 0xe8, 0xec)) : FLinearColor(FColor(0x9e, 0xa3, 0xad)));
			const FPaintGeometry PG = G.ToPaintGeometry(FVector2f(Lb.Size), FSlateLayoutTransform(FVector2f(P - Lb.Size * 0.5)),
				FSlateRenderTransform(FQuat2D(float(FMath::DegreesToRadians(double(Lb.AngleDeg))))), FVector2f(0.5f, 0.5f));
			FSlateDrawElement::MakeText(Out, LayerId + 2, PG, Lb.Text, MmStreetLabelFont(Lb.Kind), ESlateDrawEffect::None, Color);
		}
	}

	// ---- the hovered (or running) event's route, then the GPS route
	const int32 RouteEvent = Active >= 0 ? Active : Hovered;
	if (RouteEvent >= 0 && TT->GetTracks().IsValidIndex(RouteEvent))
	{
		const float A = RouteEvent == Active ? 1.0f : 0.75f;
		Painter.DrawPolyline(M->GetEventLine(RouteEvent), 0, nullptr, TT->GetTracks()[RouteEvent].bCircuit, X, G, Out, LayerId + 3,
			MmEventFill.CopyWithNewOpacity(A), 4.0f, MmEventEdge.CopyWithNewOpacity(A), 7.0f);
	}
	if (M->IsRouteActive())
	{
		const FVector2D Proj = M->GetRouteProjection();
		Painter.DrawPolyline(M->GetRoute(), M->GetRouteSegment() + 1, &Proj, false, X, G, Out, LayerId + 5, MmGpsFill, 5.0f, MmGpsEdge, 9.0f);
	}

	// ---- events: badge (always), name + best time where LayoutLabels found room (the hovered one grows)
	if (TT)
	{
		const TArray<FTimeTrialTrack>& Tracks = TT->GetTracks();
		for (int32 i = 0; i < Tracks.Num() && i < EventPos.Num(); ++i)
		{
			const FVector2D P = EventPos[i];
			const bool bHover = i == Hovered;
			const double Px = bHover ? 48.0 : 40.0;
			if (bHover)
			{
				FMmPainter::DrawIcon(M->GetIcon("minimap_dot"), P, FVector2D(62.0), G, Out, LayerId + 7, CUI::Color("Luna.Focus").CopyWithNewOpacity(0.45f));
			}
			FMmPainter::DrawIcon(M->GetIcon("minimap_event_lg"), P, FVector2D(Px), G, Out, LayerId + 8);
			if (!EventLabelTL.IsValidIndex(i) || EventLabelTL[i].X < MmHiddenLabel * 0.5)
			{
				continue;
			}
			const FVector2D TL = EventLabelTL[i];
			const double W = EventLabelSize[i].X;
			FMmPainter::DrawText(Tracks[i].Name, FVector2D(TL.X + (W - EventNameSize[i].X) * 0.5, TL.Y), MmEventNameFont(), G, Out, LayerId + 8, FLinearColor::White);
			FMmPainter::DrawText(EventTimeText[i], FVector2D(TL.X + (W - EventTimeSize[i].X) * 0.5, TL.Y + EventNameSize[i].Y + 2.0), MmEventTimeFont(), G, Out,
				LayerId + 8, EventBestCache[i] > 0.0 ? CUI::Color("Race.Gold") : CUI::Color("Glass.TextDim"));
		}
	}

	// ---- landmark tags (name + subtitle; hover card / Enter sets a GPS waypoint when no event is under the cursor)
	LandmarkMap::PaintFullMap(*M, LandmarkTags, HoveredLandmark, G, Out, LayerId + 7);

	// ---- waypoint and player
	if (M->HasDestination())
	{
		FMmPainter::DrawIcon(M->GetIcon("minimap_pin"), X.ToLocal(M->GetDestination()) - FVector2D(0.0, 16.0), FVector2D(26.0, 34.0), G, Out, LayerId + 9);
	}
	FVector2D Car;
	float Yaw = 0.0f, Kmh = 0.0f;
	if (M->GetCarPose(Car, Yaw, Kmh))
	{
		FMmPainter::DrawIcon(M->GetIcon("minimap_player"), X.ToLocal(Car), FVector2D(30.0), G, Out, LayerId + 9, FLinearColor::White,
			FMath::DegreesToRadians(Yaw + 90.0f));
	}

	// ---- cursor crosshair (hidden while it sits on an event: the badge grows instead)
	if (Hovered < 0 && HoveredLandmark < 0)
	{
		FMmPainter::DrawIcon(M->GetIcon("map_cursor"), Cursor, FVector2D(44.0), G, Out, LayerId + 10);
	}

	// ---- scale bar (bottom right)
	{
		static const double Steps[] = { 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0 };
		double Metres = Steps[0];
		for (double St : Steps) { if (St * Zoom <= 170.0) { Metres = St; } }
		const double Len = Metres * Zoom;
		const FVector2D A(S.X - 24.0 - Len, S.Y - 22.0), B(S.X - 24.0, S.Y - 22.0);
		ScaleBar.Reset();
		ScaleBar.Append({ A - FVector2D(0, 6), A, B, B - FVector2D(0, 6) });
		FSlateDrawElement::MakeLines(Out, LayerId + 10, G.ToPaintGeometry(), ScaleBar, ESlateDrawEffect::None, FLinearColor(0, 0, 0, 0.8f), true, 4.0f);
		FSlateDrawElement::MakeLines(Out, LayerId + 11, G.ToPaintGeometry(), ScaleBar, ESlateDrawEffect::None, FLinearColor::White, true, 2.0f);
		static const FSlateFontInfo ScaleFont = CambridgeUI::PixelFont(12.0f, true);
		if (Metres != ScaleMetres)
		{
			ScaleMetres = Metres;
			ScaleLabel = Metres >= 1000.0 ? FString::Printf(TEXT("%.0f KM"), Metres / 1000.0) : FString::Printf(TEXT("%.0f M"), Metres);
			ScaleLabelSize = MmMeasure(ScaleLabel, ScaleFont);
		}
		FMmPainter::DrawText(ScaleLabel, FVector2D((A.X + B.X) * 0.5 - ScaleLabelSize.X * 0.5, A.Y - 8.0 - ScaleLabelSize.Y), ScaleFont, G, Out, LayerId + 11, FLinearColor::White);
	}
	return LayerId + 12;
}

// ------------------------------------------------------------------ composite widgets

namespace MinimapUI
{
	TSharedRef<SWidget> MakeHudPanel(UMinimapSubsystem* InMap)
	{
		namespace CUI = CambridgeUI;
		TWeakObjectPtr<UMinimapSubsystem> W(InMap);
		const FSlateBrush* MapIcon = InMap->GetIcon("minimap_icon");
		TSharedRef<SWidget> Header = SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 7, 0)
			[
				SNew(SImage).Image(MapIcon)
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center).Padding(0, 1, 0, 0)
			[
				SNew(STextBlock).TextStyle(&CUI::Text("Title")).OverflowPolicy(ETextOverflowPolicy::Ellipsis)
				.Text_Lambda([W]() { return W.IsValid() ? W->GetStreetText() : FText::GetEmpty(); })
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 0, 4, 0)
			[
				SNew(STextBlock).TextStyle(&CUI::Text("HudLabelBright"))
				.Text_Lambda([W]() { return W.IsValid() ? W->GetDistanceText() : FText::GetEmpty(); })
			];
		TSharedRef<SWidget> Instruction = SNew(SBorder)
			.BorderImage(CUI::Brush("glass_pill"))
			.Padding(FMargin(8, 3, 12, 3))
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
				[
					SNew(SImage).Image_Lambda([W]() { return W.IsValid() ? W->GetInstructionIcon() : nullptr; })
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(STextBlock).TextStyle(&CUI::Text("HudLabelBright"))
					.Text_Lambda([W]() { return W.IsValid() ? W->GetInstructionText() : FText::GetEmpty(); })
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10, 0, 0, 0)
				[
					SNew(STextBlock).TextStyle(&CUI::Text("HudLabel"))
					.Text_Lambda([W]() { return W.IsValid() ? W->GetInstructionDistanceText() : FText::GetEmpty(); })
				]
			];
		return SNew(SBox)
			.WidthOverride(HudWidth)
			.Visibility_Lambda([W]() { return W.IsValid() && W->IsMinimapVisible() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SBorder)
					.BorderImage(CUI::Brush("xp_titlebar"))
					.Padding(FMargin(7, 3, 5, 3))
					[
						SNew(SBox).HeightOverride(24)[ Header ]
					]
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SBorder)
					.BorderImage(CUI::Brush("glass_panel_bottom"))
					.Padding(FMargin(8))
					[
						SNew(SOverlay)
						+ SOverlay::Slot()
						[
							SNew(SBox).WidthOverride(HudMapW).HeightOverride(HudMapH)
							[
								SNew(SMinimapView).Map(W).Size(FVector2D(HudMapW, HudMapH))
							]
						]
						+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 6, 0, 0)
						[
							SNew(SBox)
							.Visibility_Lambda([W]() { return W.IsValid() && W->HasInstruction() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
							[
								Instruction
							]
						]
					]
				]
			];
	}

	TSharedRef<SWidget> MakeFullMapScreen(UMinimapSubsystem* InMap, TSharedPtr<SFullMapView>& OutView, const FVector2D& Center, float Zoom)
	{
		namespace CUI = CambridgeUI;
		TWeakObjectPtr<UMinimapSubsystem> W(InMap);
		SAssignNew(OutView, SFullMapView).Map(W).Center(Center).Zoom(Zoom);
		TWeakPtr<SFullMapView> WeakView = OutView;

		auto Swatch = [](const FLinearColor& Fill, const FLinearColor& Edge)
		{
			return SNew(SBox).WidthOverride(26).HeightOverride(9)
				[
					SNew(SBorder).BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush")).BorderBackgroundColor(Edge).Padding(FMargin(0, 2))
					[
						SNew(SImage).Image(FCoreStyle::Get().GetBrush("WhiteBrush")).ColorAndOpacity(Fill)
					]
				];
		};
		auto LegendRow = [](const TSharedRef<SWidget>& Icon, const FText& Label)
		{
			return SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(SBox).WidthOverride(30).HAlign(HAlign_Center)[ Icon ]
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(8, 0, 0, 0)
				[
					SNew(STextBlock).TextStyle(&CUI::Text("HudLabelBright")).Text(Label)
				];
		};
		auto IconBox = [](const FSlateBrush* B, float Sz)
		{
			return SNew(SBox).WidthOverride(Sz).HeightOverride(Sz)[ SNew(SImage).Image(B) ];
		};
		TSharedRef<SWidget> Legend = CUI::MakeGlassPanel(
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 6)
			[
				SNew(STextBlock).TextStyle(&CUI::Text("HudLabel")).Text(LOCTEXT("Legend", "LEGEND"))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 2)[ LegendRow(IconBox(InMap->GetIcon("minimap_player"), 22), LOCTEXT("LegendYou", "Your car")) ]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 2)[ LegendRow(IconBox(InMap->GetIcon("minimap_event"), 22), LOCTEXT("LegendEvent", "Event start")) ]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 2)[ LegendRow(IconBox(InMap->GetIcon("landmark_htmaa"), 22), LOCTEXT("LegendLandmark", "Landmark")) ]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 2)[ LegendRow(SNew(SBox).WidthOverride(17).HeightOverride(22)[ SNew(SImage).Image(InMap->GetIcon("minimap_pin")) ], LOCTEXT("LegendPin", "GPS waypoint")) ]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4)[ LegendRow(Swatch(MmGpsFill, MmGpsEdge), LOCTEXT("LegendGps", "GPS route")) ]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4)[ LegendRow(Swatch(MmEventFill, MmEventEdge), LOCTEXT("LegendRoute", "Event route")) ],
			FMargin(14, 10, 16, 10));

		TSharedRef<SWidget> CardHeader = SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
			[
				SNew(SImage).Image_Lambda([WeakView]() { TSharedPtr<SFullMapView> V = WeakView.Pin(); return CUI::Brush(V.IsValid() ? V->GetCursorIcon() : FName(TEXT("icon_info"))); })
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
			[
				SNew(STextBlock).TextStyle(&CUI::Text("ToastTitle"))
				.Text_Lambda([WeakView]() { TSharedPtr<SFullMapView> V = WeakView.Pin(); return V.IsValid() ? V->GetCursorTitle() : FText::GetEmpty(); })
			];
		TSharedRef<SWidget> Card = SNew(SBox).WidthOverride(400)
			[
				CUI::MakeToastCustom(CardHeader, TAttribute<FText>::CreateLambda([WeakView]()
				{
					TSharedPtr<SFullMapView> V = WeakView.Pin();
					return V.IsValid() ? V->GetCursorBody() : FText::GetEmpty();
				}), CUI::ETail::None, 370.0f)
			];

		auto Keys = [](std::initializer_list<const TCHAR*> List)
		{
			TArray<FText> Out;
			for (const TCHAR* K : List) { Out.Add(FText::FromString(K)); }
			return Out;
		};
		TSharedRef<SWidget> Footer = SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 18, 0)[ CUI::MakeKeyHint(Keys({ TEXT("W"), TEXT("A"), TEXT("S"), TEXT("D") }), LOCTEXT("HintPan", "Pan"), false) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 18, 0)[ CUI::MakeKeyHint(Keys({ TEXT("Q"), TEXT("E") }), LOCTEXT("HintZoom", "Zoom"), false) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 18, 0)[ CUI::MakeKeyHint(Keys({ TEXT("ENTER"), TEXT("pad_a") }), LOCTEXT("HintSet", "Waypoint / navigate"), false) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 18, 0)[ CUI::MakeKeyHint(Keys({ TEXT("BKSP"), TEXT("pad_b") }), LOCTEXT("HintClear", "Clear"), false) ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ CUI::MakeKeyHint(Keys({ TEXT("M") }), LOCTEXT("HintClose", "Close"), false) ]
			+ SHorizontalBox::Slot().FillWidth(1.0f)[ SNullWidget::NullWidget ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(12, 0, 4, 0)
			[
				SNew(STextBlock).TextStyle(&CUI::Text("Value"))
				.Text_Lambda([W]()
				{
					if (!W.IsValid() || !W->HasDestination()) { return LOCTEXT("NoGps", "GPS: no waypoint"); }
					return FText::Format(LOCTEXT("GpsStatus", "GPS: {0}"), W->GetDistanceText());
				})
			];

		TSharedRef<SWidget> MapArea = SNew(SBorder)
			.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
			.BorderBackgroundColor(CUI::Color("Luna.ContentBorder"))
			.Padding(FMargin(1))
			[
				SNew(SOverlay)
				+ SOverlay::Slot()[ OutView.ToSharedRef() ]
				+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Top).Padding(12)
				[
					SNew(SBox).Visibility(EVisibility::HitTestInvisible)[ Legend ]
				]
				+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom).Padding(12)
				[
					SNew(SBox).Visibility(EVisibility::HitTestInvisible)[ Card ]
				]
			];
		TSharedRef<SWidget> Content = SNew(SVerticalBox)
			+ SVerticalBox::Slot().FillHeight(1.0f)[ MapArea ]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 12, 0, 2)[ Footer ];

		auto Close = FOnClicked::CreateLambda([W]()
		{
			if (W.IsValid()) { W->CloseFullMap(); }
			return FReply::Handled();
		});
		return SNew(SOverlay)
			+ SOverlay::Slot()
			[
				SNew(SBackgroundBlur)
				.BlurStrength(6.0f)
				.Padding(0)
				[
					SNew(SImage).Image(FCoreStyle::Get().GetBrush("WhiteBrush")).ColorAndOpacity(FSlateColor(FLinearColor(0.0f, 0.0f, 0.0f, 0.45f)))
				]
			]
			+ SOverlay::Slot().Padding(FMargin(56, 30, 56, 34))
			[
				CUI::MakeXPWindow(LOCTEXT("MapTitle", "Map - GPS"), Content, TEXT("icon_flag"), Close, FMargin(10, 10, 10, 10))
			];
	}
}

#undef LOCTEXT_NAMESPACE
