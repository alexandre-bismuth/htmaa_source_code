// Graphics settings: the engine's scalability groups (UGameUserSettings) plus the project's own
// knobs that matter on this map (clouds, tree distance, Nanite detail), the FPS overlay, and the sound volumes.
// Saved to Saved/Config/<Platform>/GameUserSettings.ini; registered as GameUserSettingsClassName
// in DefaultEngine.ini. Edited in game through the settings menu (UCambridgeMenuSubsystem, Esc).

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameUserSettings.h"
#include "CambridgeGameUserSettings.generated.h"

class UInstancedStaticMeshComponent;

UCLASS(config = GameUserSettings, configdonotcheckdefaults)
class UCambridgeGameUserSettings : public UGameUserSettings
{
	GENERATED_BODY()

public:
	static UCambridgeGameUserSettings* Get();

	// quality presets: 0 Low, 1 Medium, 2 High (default: ~40-50 fps at 1080p on the M4 Pro, ~30-38 fps fullscreen on the
	// 5K Studio Display = 2560x1440 rendering 1080p's pixels, 2026-10-06), 3 Epic
	void ApplyPreset(int32 Level);
	/** The preset the current values match, or -1 (custom). */
	int32 GetPreset() const;

	virtual void SetToDefaults() override;
	virtual void ApplyNonResolutionSettings() override;

	/** Tree cull distance (cm) for the current setting. */
	float GetTreeCullDistanceCm() const;
	/** The resolution scale counts from 1080p: the most a frame renders (16:9 height) before TSR upscales to the window. */
	float GetResolutionScaleCapHeight() const;
	/** Applies the tree draw distance to one prop batch (called as World Partition streams them in). */
	void ApplyTreeDistance(UInstancedStaticMeshComponent* Instances) const;

	UPROPERTY(config) bool bShowFPS = true;

	// driving assists (applied to the car when it spawns; the T / G / B keys and the menu write them)
	UPROPERTY(config) int32 TractionControlMode = 1;   // 0 off, 1 sport, 2 full
	UPROPERTY(config) bool bAutomaticGearbox = true;
	UPROPERTY(config) bool bABSEnabled = true;
	UPROPERTY(config) int32 RacingLineMode = 2;        // 0 off, 1 corners only, 2 full (events)
	UPROPERTY(config) bool bShowMinimap = true;        // HUD minimap, bottom left (UMinimapSubsystem)
	UPROPERTY(config) bool bVolumetricClouds = true;
	UPROPERTY(config) int32 TreeDistance = 1;        // 0 near (300 m), 1 medium (400 m), 2 far (700 m)
	UPROPERTY(config) int32 GeometryDetail = 1;      // 0 low, 1 medium, 2 high (Nanite max pixels per edge 4 / 2 / 1)

	// sound (Options > Sound, applied at once): the whole game (the audio device), the car (engine, turbo, tyres:
	// UStiEngineAudio, up to 120 %), the race sounds (countdown, checkpoints, menus: UTimeTrialSubsystem)
	UPROPERTY(config) float MasterVolume = 1.0f;
	UPROPERTY(config) float EngineVolume = 1.0f;
	UPROPERTY(config) float RaceSoundsVolume = 1.0f;
	/** Pushes the master volume to the audio device (also when a map starts: the device may not exist before). */
	void ApplySound() const;

private:
	void ApplyProjectSettings() const;
};
