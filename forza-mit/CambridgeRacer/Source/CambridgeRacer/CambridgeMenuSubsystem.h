// In-game graphics settings menu and FPS overlay (Slate, no assets).
//
//   Esc / gamepad Menu    open or close the menu (the game pauses while it is open; also opens when the
//                         game loses focus). Backspace / gamepad B close it too. Opened from the launch menu's
//                         Options it doesn't pause and Back returns there; in game it has a Main menu button
//   Up / Down             select a setting        Left / Right   change it (applied immediately)
//   Tab / LB RB           section (Graphics, Driving Assists, Calibration, Sound, Controls)
//   mouse                 the < > buttons
//   wheel                 paddles select, rim turned past 50 deg changes, both paddles tapped (its start) = next
//                         section, both held close;
//                         the key hints show these while the wheel is connected
//
// Settings live in UCambridgeGameUserSettings and are saved when the menu closes.
// The overlay shows FPS, frame time and GPU time; off in -ShotTour / -DriveTest runs.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "CambridgeMenuSubsystem.generated.h"

class FCambridgeMenuInput;
class SWidget;

UCLASS()
class UCambridgeMenuSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	void ToggleMenu();
	/** The settings window's Main menu button: close it and show the launch menu (UCambridgeLaunchSubsystem). */
	void GoToMainMenu();
	/** Opens the menu (if needed) on a section: 0 graphics, 1 assists, 2 calibration, 3 sound, 4 controls. */
	void ShowTab(int32 Tab);
	bool IsMenuOpen() const { return MenuWidget.IsValid(); }
	/** Called every frame by the input processor: FPS smoothing and keeping the overlay attached. */
	void Tick(float DeltaTime);

	FText GetFPSText() const;
	FText GetFPSNumberText() const;     // FPS readout chip
	FText GetFPSDetailText() const;
	FText GetTrayText() const;          // menu taskbar tray: FPS + clock

private:
	void OpenMenu();
	void CloseMenu();
	void SetOverlayVisible(bool bVisible);
	void TickWheelNavigation();
	void OnApplicationActivationChanged(bool bActive);

	TSharedPtr<FCambridgeMenuInput> Input;
	TSharedPtr<SWidget> MenuWidget;
	TSharedPtr<SWidget> OverlayWidget;
	TWeakObjectPtr<class UGameViewportClient> OverlayViewport;
	bool bEnabled = true;
	bool bRimArmed = false;
	bool bOpenedFromLaunch = false;   // Options of the launch menu: not paused, Back returns to it
	FDelegateHandle ActivationHandle;

	// smoothed timings (ms)
	double FrameMs = 0.0;
	double GpuMs = 0.0;
};
