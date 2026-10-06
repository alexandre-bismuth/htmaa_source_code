#include "TimeTrialWidgets.h"

#include "CambridgeUIStyle.h"
#include "Camera/PlayerCameraManager.h"
#include "Engine/World.h"
#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"
#include "TimeTrialSubsystem.h"

namespace
{
	const FLinearColor TtAmber = FLinearColor(FColor(0xff, 0xb0, 0x00));
	const FLinearColor TtGreen = FLinearColor(FColor(0x3d, 0xdc, 0x5a));
	const FLinearColor TtRed = FLinearColor(FColor(0xff, 0x4f, 0x3f));
	const FLinearColor TtBlue = FLinearColor(FColor(0x3d, 0x95, 0xff));

	void TtBox(FSlateWindowElementList& Out, int32 Layer, const FGeometry& G, const FVector2D& Pos, const FVector2D& Size, const FSlateBrush* Brush, const FLinearColor& Tint)
	{
		FSlateDrawElement::MakeBox(Out, Layer, G.ToPaintGeometry(FVector2f(Size), FSlateLayoutTransform(FVector2f(Pos))), Brush, ESlateDrawEffect::None, Tint);
	}

	void TtText(FSlateWindowElementList& Out, int32 Layer, const FGeometry& G, const FString& Text, const FSlateFontInfo& Font, const FVector2D& Centre, const FLinearColor& Tint)
	{
		const FVector2D Size = FSlateApplication::Get().GetRenderer()->GetFontMeasureService()->Measure(Text, Font);
		const FVector2D Pos = Centre - Size * 0.5;
		// 1 px drop shadow for legibility over the city
		FSlateDrawElement::MakeText(Out, Layer, G.ToPaintGeometry(FVector2f(Size), FSlateLayoutTransform(FVector2f(Pos + FVector2D(1.5, 1.5)))), Text, Font, ESlateDrawEffect::None, FLinearColor(0, 0, 0, 0.7f * Tint.A));
		FSlateDrawElement::MakeText(Out, Layer + 1, G.ToPaintGeometry(FVector2f(Size), FSlateLayoutTransform(FVector2f(Pos))), Text, Font, ESlateDrawEffect::None, Tint);
	}
}

// ------------------------------------------------------------------ route bar

void STimeTrialRouteBar::Construct(const FArguments&, UTimeTrialSubsystem* InOwner)
{
	Owner = InOwner;
}

int32 STimeTrialRouteBar::OnPaint(const FPaintArgs&, const FGeometry& G, const FSlateRect&, FSlateWindowElementList& Out, int32 Layer, const FWidgetStyle&, bool) const
{
	FTimeTrialRouteBar& B = Bar;
	if (!Owner.IsValid() || !Owner->GetRouteBar(B))
	{
		return Layer;
	}
	namespace CUI = CambridgeUI;
	const FSlateBrush* White = FCoreStyle::Get().GetBrush("WhiteBrush");
	const FVector2D S = G.GetLocalSize();
	const double Pad = 8.0;                       // room for the car dot at both ends
	const double W = S.X - 2.0 * Pad;
	const double Y = S.Y * 0.5;
	auto X = [&](float F) { return Pad + W * FMath::Clamp(F, 0.0f, 1.0f); };

	// rail + progress
	TtBox(Out, Layer, G, FVector2D(Pad, Y - 2.5), FVector2D(W, 5.0), White, FLinearColor(1, 1, 1, 0.14f));
	TtBox(Out, Layer + 1, G, FVector2D(Pad, Y - 2.5), FVector2D(X(B.Car) - Pad, 5.0), White, TtBlue.CopyWithNewOpacity(0.95f));
	// lap lines, checkpoint ticks (the last one is the checkered finish)
	for (float F : B.LapLines)
	{
		TtBox(Out, Layer + 2, G, FVector2D(X(F) - 1.5, Y - 9.0), FVector2D(3.0, 18.0), White, FLinearColor(1, 1, 1, 0.75f));
	}
	for (int32 i = 0; i + 1 < B.Checkpoints.Num(); ++i)
	{
		const bool bPassed = i < B.Passed;
		const bool bNext = i == B.Passed;
		const FLinearColor C = bNext ? TtAmber : FLinearColor(1, 1, 1, bPassed ? 0.9f : 0.35f);
		const double H = bNext ? 14.0 : 9.0;
		TtBox(Out, Layer + 2, G, FVector2D(X(B.Checkpoints[i]) - 1.0, Y - H * 0.5), FVector2D(2.0, H), White, C);
	}
	if (B.Checkpoints.Num() > 0)
	{
		TtBox(Out, Layer + 2, G, FVector2D(X(1.0f) - 5.0, Y - 8.0), FVector2D(10.0, 16.0), CUI::Brush("flag_strip"), FLinearColor::White);
	}
	// ghost of the best run, then the car on top
	if (B.Ghost >= 0.0f)
	{
		TtBox(Out, Layer + 3, G, FVector2D(X(B.Ghost) - 7.0, Y - 7.0), FVector2D(14.0, 14.0), CUI::Brush("route_ghost"), FLinearColor::White);
	}
	TtBox(Out, Layer + 4, G, FVector2D(X(B.Car) - 8.0, Y - 8.0), FVector2D(16.0, 16.0), CUI::Brush("route_car"), FLinearColor::White);
	return Layer + 4;
}

// ------------------------------------------------------------------ next-checkpoint marker / guidance arrow

void STimeTrialGuide::Construct(const FArguments&, UTimeTrialSubsystem* InOwner)
{
	Owner = InOwner;
	SetVisibility(EVisibility::HitTestInvisible);
}

int32 STimeTrialGuide::OnPaint(const FPaintArgs&, const FGeometry& G, const FSlateRect&, FSlateWindowElementList& Out, int32 Layer, const FWidgetStyle&, bool) const
{
	UTimeTrialSubsystem* TT = Owner.Get();
	FVector Gate;
	bool bFinish = false;
	if (!TT || TT->GetState() != ETimeTrialState::Running || TT->IsResetHolding() || TT->IsWrongWay() || !TT->GetNextGate(Gate, bFinish))
	{
		return Layer;
	}
	UWorld* World = TT->GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC || !PC->PlayerCameraManager || !PC->GetPawn())
	{
		return Layer;
	}
	namespace CUI = CambridgeUI;
	const bool bMissed = TT->IsCheckpointMissed();
	const double T = World->GetRealTimeSeconds();
	const FVector Target = Gate + FVector(0.0, 0.0, 380.0);
	const float DistM = FVector::Dist2D(PC->GetPawn()->GetActorLocation(), Gate) / 100.0f;
	const FString DistText = FString::Printf(TEXT("%d M"), FMath::RoundToInt(DistM));
	const FLinearColor Col = bMissed ? TtRed : (bFinish ? TtGreen : TtAmber);
	const FVector2D L = G.GetLocalSize();
	int32 VX = 0, VY = 0;
	PC->GetViewportSize(VX, VY);
	if (VX <= 0 || VY <= 0)
	{
		return Layer;
	}
	FVector2D Screen;
	const bool bProjected = PC->ProjectWorldLocationToScreen(Target, Screen, true);
	const FVector2D P = Screen * (L.X / double(VX));
	const double Margin = 60.0;
	const bool bInside = bProjected && P.X > Margin && P.X < L.X - Margin && P.Y > Margin && P.Y < L.Y - Margin;
	const FSlateFontInfo Font = CUI::CondensedFont(13);

	if (bInside)
	{
		// marker over the gate (hidden close up: the gate itself is obvious then)
		const float Alpha = bMissed ? 1.0f : FMath::Clamp((DistM - 30.0f) / 40.0f, 0.0f, 1.0f);
		if (Alpha <= 0.0f)
		{
			return Layer;
		}
		const double Sz = bMissed ? 40.0 : 30.0;
		TtBox(Out, Layer, G, P - FVector2D(Sz * 0.5, Sz), FVector2D(Sz, Sz), CUI::Brush("cp_marker"), Col.CopyWithNewOpacity(Alpha));
		TtText(Out, Layer + 1, G, DistText, Font, P - FVector2D(0.0, Sz + 12.0), FLinearColor(1, 1, 1, Alpha));
		return Layer + 2;
	}
	// behind / far to the side: an arrow on an ellipse around the screen centre, pointing at it
	const FVector CamLoc = PC->PlayerCameraManager->GetCameraLocation();
	const float CamYaw = PC->PlayerCameraManager->GetCameraRotation().Yaw;
	const float Bearing = FMath::FindDeltaAngleDegrees(CamYaw, float((Target - CamLoc).Rotation().Yaw));
	if (!bMissed && FMath::Abs(Bearing) < 65.0f)
	{
		return Layer;          // ahead, just round a corner: the racing line and the minimap already show it
	}
	const double Rad = FMath::DegreesToRadians(Bearing);
	const FVector2D C(L.X * 0.5, L.Y * 0.56);
	const FVector2D R(L.X * 0.30, L.Y * 0.26);
	const FVector2D At = C + FVector2D(FMath::Sin(Rad) * R.X, -FMath::Cos(Rad) * R.Y);
	const double Pulse = bMissed ? 1.0 + 0.12 * FMath::Sin(T * 9.0) : 1.0;
	const double Sz = (bMissed ? 72.0 : 52.0) * Pulse;
	FSlateDrawElement::MakeRotatedBox(Out, Layer, G.ToPaintGeometry(FVector2f(Sz, Sz), FSlateLayoutTransform(FVector2f(At - FVector2D(Sz * 0.5)))),
		CUI::Brush("guide_arrow"), ESlateDrawEffect::None, float(Rad), TOptional<FVector2f>(), FSlateDrawElement::RelativeToElement, Col);
	TtText(Out, Layer + 1, G, DistText, Font, At + FVector2D(0.0, Sz * 0.5 + 12.0), FLinearColor::White);
	return Layer + 2;
}
