// The launch menu ("Forza @ MIT"), the first screen of the game. Hero layout (tools/ui/make_launch_mockups.py,
// design D): the title and three Luna buttons (Launch Open World / Timed Race / Options) over a blurred shot of the
// car, Neil (HTMAA's instructor, as a Mii carrying the driver's helmet) standing on the right, and a glass bar with
// the keys and the map loading. Timed Race swaps the buttons for the list of events.
//
// One widget, two uses:
//   loading   painted by the MoviePlayer's Slate loading thread while the engine starts and the map loads
//             (UCambridgeLaunchSubsystem sets it up): no input, nothing that touches the world or a UObject;
//             the buttons are dimmed and the bar runs a marquee
//   live      in the game viewport from the first frame: keyboard, gamepad, mouse (the wheel through
//             UCambridgeLaunchSubsystem), the event list, the World Partition streaming progress
//
// Brushes: launch_bg and neil_mii (tools/ui/make_launch_assets.py) plus the Luna set (CambridgeUIStyle).
// The loading screen is set up by this module (CambridgeUI, loading phase PreLoadingScreen) so the engine plays it
// as soon as it creates the game window; the game module (UCambridgeLaunchSubsystem) puts up the live one.

#pragma once

#include "CoreMinimal.h"
#include "Styling/SlateTypes.h"
#include "Widgets/SCompoundWidget.h"

class SWidgetSwitcher;

namespace CambridgeUI
{
	/** Normal play: the launch menu first (also as the loading screen) and free roam from the HTMAA lectures.
	 *  Command line only (it is asked before the engine is up): off in test runs (-ShotTour, -DriveTest,
	 *  -TimeTrialAuto, -nullrhi, -NoLaunchMenu, commandlets); -LaunchMenu forces it on. */
	CAMBRIDGEUI_API bool IsLaunchFlowEnabled();
	/** This module set the launch menu up as the engine's loading screen (at startup). */
	CAMBRIDGEUI_API bool IsLaunchLoadingScreenSetUp();
}

/** One row of the Timed Race list. */
struct FLaunchEventInfo
{
	FText Name;
	FText Short;    // right-hand side of the row: "3.2 KM   2:41.183"
	FText Detail;   // the description panel under the list
};

class CAMBRIDGEUI_API SCambridgeLaunchScreen : public SCompoundWidget
{
public:
	DECLARE_DELEGATE_OneParam(FOnLaunchChoice, int32);

	SLATE_BEGIN_ARGS(SCambridgeLaunchScreen) : _bLive(false) {}
		SLATE_ARGUMENT(bool, bLive)
		SLATE_ARGUMENT(TArray<FLaunchEventInfo>, Events)
		/** live: 0..1, how much of the map around the car is in */
		SLATE_ATTRIBUTE(float, LoadFraction)
		SLATE_ATTRIBUTE(FText, LoadText)
		/** live: the home-built wheel is connected, the key hints show its controls */
		SLATE_ATTRIBUTE(bool, bWheel)
		/** main page: 0 open world, 1 timed race (the list opens here; for the sound), 2 options */
		SLATE_EVENT(FOnLaunchChoice, OnMainChoice)
		/** event list: index into Events */
		SLATE_EVENT(FOnLaunchChoice, OnEventChoice)
		/** the selection moved (a click sound) */
		SLATE_EVENT(FSimpleDelegate, OnMoved)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	static constexpr int32 MainPage = 0;
	static constexpr int32 EventPage = 1;

	void ShowPage(int32 NewPage, int32 Select = 0);
	int32 GetPage() const { return Page; }
	void Select(int32 Index);
	void Move(int32 Delta);
	void Activate();
	/** The event list goes back to the main page (true); the main page has nowhere to go back to (false). */
	bool Back();

	virtual bool SupportsKeyboardFocus() const override { return bLive; }
	virtual FReply OnKeyDown(const FGeometry& Geometry, const FKeyEvent& Event) override;

private:
	TSharedRef<SWidget> MakeButton(int32 Index, const FText& Label, FName Icon, const FText& Right, bool bRow);
	TSharedRef<SWidget> MakeTitle() const;
	TSharedRef<SWidget> MakeBottomBar();
	int32 NumItems() const;
	FText GetDescription() const;
	float GetButtonsOpacity() const;

	bool bLive = false;
	TArray<FLaunchEventInfo> Events;
	TAttribute<float> LoadFraction;
	TAttribute<FText> LoadText;
	TAttribute<bool> bWheel;
	FOnLaunchChoice OnMainChoice;
	FOnLaunchChoice OnEventChoice;
	FSimpleDelegate OnMoved;
	TSharedPtr<SWidgetSwitcher> Pages;
	int32 Page = MainPage;
	int32 Selected = 0;
	double ShownAt = 0.0;

	FTextBlockStyle TitleStyle, AtStyle, SubtitleStyle, ButtonStyle, RowStyle, RowRightStyle, HeadingStyle, DescStyle, LoadStyle;
};
