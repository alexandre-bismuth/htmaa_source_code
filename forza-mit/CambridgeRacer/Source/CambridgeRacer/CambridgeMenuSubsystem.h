// In-game graphics settings menu and FPS overlay (Slate, no assets).
//
//   Esc / gamepad Menu    open or close the menu (the game pauses while it is open; also opens when the
//                         game loses focus). Backspace / gamepad B close it too
//   Up / Down             select a setting        Left / Right   change it (applied immediately)
//   Tab / LB RB           section (Graphics, Driving Assists, Calibration, Controls)
//   mouse                 the < > buttons
//   wheel                 paddles select, rim turned past 50 deg changes, start = next section
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
	/** Opens the menu (if needed) on a section: 0 graphics, 1 assists, 2 calibration, 3 controls. */
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
	FDelegateHandle ActivationHandle;

	// smoothed timings (ms)
	double FrameMs = 0.0;
	double GpuMs = 0.0;
};
