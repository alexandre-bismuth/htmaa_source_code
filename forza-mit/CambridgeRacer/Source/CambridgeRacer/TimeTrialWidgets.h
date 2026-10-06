// Race HUD leaf widgets drawn straight from UTimeTrialSubsystem state (no per-frame allocations):
//   STimeTrialRouteBar   position on the route: rail, progress fill, a tick per checkpoint (passed /
//                        next / later), lap lines, checkered finish, the ghost of the best run and the car
//   STimeTrialGuide      full-screen layer: a marker over the next checkpoint with its distance, or an
//                        arrow at the screen edge pointing to it when it is behind / far to the side
//                        (big and pulsing after a missed checkpoint)

#pragma once

#include "CoreMinimal.h"
#include "TimeTrialSubsystem.h"
#include "Widgets/SLeafWidget.h"

class UTimeTrialSubsystem;

class STimeTrialRouteBar : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(STimeTrialRouteBar) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UTimeTrialSubsystem* InOwner);
	virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(448.0, 22.0); }
	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geometry, const FSlateRect& Culling, FSlateWindowElementList& Out,
		int32 Layer, const FWidgetStyle& Style, bool bParentEnabled) const override;

private:
	TWeakObjectPtr<UTimeTrialSubsystem> Owner;
	mutable FTimeTrialRouteBar Bar;     // (filled every paint; kept to reuse its arrays)
};

class STimeTrialGuide : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(STimeTrialGuide) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs, UTimeTrialSubsystem* InOwner);
	virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(8.0, 8.0); }
	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geometry, const FSlateRect& Culling, FSlateWindowElementList& Out,
		int32 Layer, const FWidgetStyle& Style, bool bParentEnabled) const override;

private:
	TWeakObjectPtr<UTimeTrialSubsystem> Owner;
};
