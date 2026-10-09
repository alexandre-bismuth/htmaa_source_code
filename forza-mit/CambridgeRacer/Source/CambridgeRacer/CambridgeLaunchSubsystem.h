// The game's start: the launch menu (SCambridgeLaunchScreen) and free roam from the HTMAA lectures.
//
//   startup     the menu is the loading screen (the MoviePlayer paints it while the engine starts and the map
//               loads), then the live menu is in the viewport from the first frame. The car is already at the
//               free-roam start (ACambridgeGameMode spawns it there, Tracks/<map>.json "free_roam": Amherst St in
//               front of the Media Lab, E14), parked and silent; the world keeps streaming in behind the menu
//               (never paused: a paused world requests no World Partition cells)
//   Launch Open World   close the menu and drive (the car is moved back to the start if it is elsewhere)
//   Timed Race          the event list; an event starts at once (its grid, the streaming hold, the countdown)
//   Options             the settings window over the menu (UCambridgeMenuSubsystem, not paused); Esc / Back returns
//   in game     the settings window has a Main menu button: it leaves a running event and shows this menu again
//
// Keys: arrows / W S / D-pad / stick, Enter / A, Backspace / B / Esc (back from the event list), the mouse; the
// home-built wheel: paddles up / down, both paddles tapped (its start) = go, both held (or the rim turned left past
// 50 deg) = back;
// the key hints switch to the wheel's controls while it is connected.
// Test runs (-ShotTour, -DriveTest, -TimeTrialAuto, -nullrhi, -NoLaunchMenu) skip all of it and start as before;
// -LaunchMenu forces it. Console: cr.Launch [events] [N], cr.Launch.Choose N, cr.Launch.Close, cr.Launch.LoadingPreview 1|0.

#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "Engine/World.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "CambridgeLaunchScreen.h"
#include "CambridgeLaunchSubsystem.generated.h"

UCLASS()
class UCambridgeLaunchSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** Normal play: the launch menu first and free roam from the HTMAA lectures. Test runs: off (see above).
	 *  (CambridgeUI::IsLaunchFlowEnabled: the UI module asks it before the engine is up.) */
	static bool IsLaunchFlowEnabled();
	/** The free-roam start of World's map (Tracks/<map>.json "free_roam"); false if it has none. */
	static bool GetFreeRoamStart(const UWorld* World, FTransform& Out);
	/** The launch menu is up: the car is parked and silent and takes no input (keys, gamepad, wheel). */
	static bool IsLaunchMenuOpen(const UObject* WorldContext);

	/** Shows the menu (or switches its page). Leaves a running event. */
	void Show(int32 Page = SCambridgeLaunchScreen::MainPage, int32 Select = 0);
	void Close();
	bool IsOpen() const { return Screen.IsValid(); }
	/** Esc / gamepad Menu: back from the event list (true); nothing to do on the main page (false). */
	bool Back();
	/** The settings window opened from the menu closed: the keyboard goes back to the menu. */
	void RestoreFocus();
	/** Test / console: select item N of the current page, or select and activate it. */
	void Select(int32 Index);
	void Choose(int32 Index);
	/** Test (cr.Launch.LoadingPreview): the loading-screen version over everything, for a screenshot. */
	void SetLoadingPreview(bool bShow);

private:
	void OnPostWorldInit(UWorld* World, const UWorld::InitializationValues IVS);
	void OnWorldBeginPlay();
	bool Tick(float DeltaTime);
	void TickWheel();
	void UpdateLoading();
	void OnMainChoice(int32 Choice);
	void OnEventChoice(int32 Index);
	void OnMoved();
	void LaunchOpenWorld();
	void ParkCar(bool bPark);
	void PlaySound(FName Name, float Volume = 1.0f) const;
	TArray<FLaunchEventInfo> BuildEvents() const;
	UWorld* GetGameWorld() const;
	class AImprezaSTi* GetCar() const;

	float GetLoadFraction() const { return LoadFraction; }
	FText GetLoadText() const { return LoadText; }

	TSharedPtr<SCambridgeLaunchScreen> Screen;
	TSharedPtr<SWidget> LoadingPreview;
	TWeakObjectPtr<UWorld> StartupWorld;
	FTSTicker::FDelegateHandle TickHandle;
	FDelegateHandle PostWorldInitHandle;
	bool bEnabled = false;
	bool bShownAtStartup = false;
	bool bRimArmed = false;
	double OpenedAt = 0.0;

	// map loading behind the menu (World Partition streaming + shader / asset compiles)
	float LoadFraction = 0.0f;
	FText LoadText;
	int32 MaxStreamingSeen = 0;
	bool bReadyLogged = false;
};
