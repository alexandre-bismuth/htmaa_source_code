#include "CambridgeGameUserSettings.h"

#include "CambridgeMenuSubsystem.h"
#include "Engine/GameInstance.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "AudioDevice.h"
#include "ComponentRecreateRenderStateContext.h"
#include "EngineUtils.h"
#include "HAL/IConsoleManager.h"
#include "Misc/ConfigCacheIni.h"
#include "PropInstancesActor.h"

namespace
{
	const float TreeCullCm[3] = { 30000.0f, 40000.0f, 70000.0f };
	const int32 MaxPixelsPerEdge[3] = { 4, 2, 1 };

	// Game-setting priority: above scalability (presets), below console (debugging still wins)
	void SetCVar(const TCHAR* Name, int32 Value)
	{
		if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(Name))
		{
			V->Set(Value, ECVF_SetByGameSetting);
		}
	}

	void SetCVar(const TCHAR* Name, float Value)
	{
		if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(Name))
		{
			V->Set(Value, ECVF_SetByGameSetting);
		}
	}

	bool IsTree(const UInstancedStaticMeshComponent* C)
	{
		return C && C->GetStaticMesh() && C->GetStaticMesh()->GetName().Contains(TEXT("tree"));
	}

	struct FPresetExtras
	{
		bool bClouds;
		int32 TreeDistance;
		int32 GeometryDetail;
	};
	const FPresetExtras PresetExtras[4] = { { false, 0, 0 }, { false, 1, 0 }, { true, 1, 1 }, { true, 2, 2 } };
}

UCambridgeGameUserSettings* UCambridgeGameUserSettings::Get()
{
	return GEngine ? Cast<UCambridgeGameUserSettings>(GEngine->GetGameUserSettings()) : nullptr;
}

void UCambridgeGameUserSettings::SetToDefaults()
{
	Super::SetToDefaults();
	bShowFPS = true;
	MasterVolume = EngineVolume = RaceSoundsVolume = 1.0f;
	ApplyPreset(2);
}

void UCambridgeGameUserSettings::ApplyPreset(int32 Level)
{
	Level = FMath::Clamp(Level, 0, 3);
	SetOverallScalabilityLevel(Level);
	// textures cost memory, not time: keep them sharp on every preset of this 24 GB machine
	SetTextureQuality(FMath::Max(Level, 2));
	// (of a 1080p frame's pixel count: see ApplyProjectSettings)
	static const float ResolutionPct[4] = { 67.0f, 83.0f, 100.0f, 100.0f };
	SetResolutionScaleValueEx(ResolutionPct[Level]);
	bVolumetricClouds = PresetExtras[Level].bClouds;
	TreeDistance = PresetExtras[Level].TreeDistance;
	GeometryDetail = PresetExtras[Level].GeometryDetail;
}

int32 UCambridgeGameUserSettings::GetPreset() const
{
	for (int32 Level = 0; Level < 4; ++Level)
	{
		const bool bGroups = GetViewDistanceQuality() == Level && GetShadowQuality() == Level && GetGlobalIlluminationQuality() == Level
			&& GetReflectionQuality() == Level && GetPostProcessingQuality() == Level && GetVisualEffectQuality() == Level
			&& GetFoliageQuality() == Level && GetShadingQuality() == Level && GetAntiAliasingQuality() == Level
			&& GetTextureQuality() == FMath::Max(Level, 2);
		const FPresetExtras& E = PresetExtras[Level];
		if (bGroups && bVolumetricClouds == E.bClouds && TreeDistance == E.TreeDistance && GeometryDetail == E.GeometryDetail)
		{
			return Level;
		}
	}
	return -1;
}

void UCambridgeGameUserSettings::ApplyNonResolutionSettings()
{
	Super::ApplyNonResolutionSettings();
	ApplyProjectSettings();
}

float UCambridgeGameUserSettings::GetResolutionScaleCapHeight() const
{
	float Norm, Value, Min, Max;
	GetResolutionScaleInformationEx(Norm, Value, Min, Max);
	return 1080.0f * Value / 100.0f;
}

float UCambridgeGameUserSettings::GetTreeCullDistanceCm() const
{
	return TreeCullCm[FMath::Clamp(TreeDistance, 0, 2)];
}

void UCambridgeGameUserSettings::ApplyTreeDistance(UInstancedStaticMeshComponent* Instances) const
{
	if (IsTree(Instances))
	{
		const float End = GetTreeCullDistanceCm();
		Instances->SetCullDistances(int32(End * 0.8f), int32(End));
	}
}

void UCambridgeGameUserSettings::ApplySound() const
{
	if (GEngine)
	{
		if (FAudioDeviceHandle Device = GEngine->GetMainAudioDevice())
		{
			Device->SetTransientPrimaryVolume(FMath::Clamp(MasterVolume, 0.0f, 1.0f));
		}
	}
}

void UCambridgeGameUserSettings::ApplyProjectSettings() const
{
	ApplySound();
	SetCVar(TEXT("r.VolumetricCloud"), bVolumetricClouds ? 1 : 0);
	// the resolution scale counts from 1080p: a bigger window (fullscreen on the 5K Studio Display is 2560x1440 without
	// high DPI) renders at most the pixels of a 1080p frame at that scale, and TSR upscales to the window. GPU time
	// follows the rendered pixels (2560x1440 at 100 %: 34-45 ms, at 1080p's pixel count: 24-33 ms, like 1080p itself)
	SetCVar(TEXT("r.ScreenPercentage.MaxResolution"), GetResolutionScaleCapHeight());
	SetCVar(TEXT("r.Nanite.MaxPixelsPerEdge"), MaxPixelsPerEdge[FMath::Clamp(GeometryDetail, 0, 2)]);
	if (!GEngine)
	{
		return;
	}
	for (const FWorldContext& Context : GEngine->GetWorldContexts())
	{
		UWorld* World = Context.World();
		if (World && World->IsGameWorld())
		{
			for (TActorIterator<APropInstancesActor> It(World); It; ++It)
			{
				ApplyTreeDistance(It->Instances);
			}
		}
	}
}

namespace
{
	// console access for testing / debugging, e.g. -ExecCmds="cr.Graphics.Preset 1,cr.Graphics.Trees 0".
	// Applied for this run only: not saved (a test must not change the player's settings), and the window
	// size / mode is left alone (ApplySettings would resize a -ResX shot-tour window to the saved size)
	void WithSettings(const TArray<FString>& Args, TFunctionRef<void(UCambridgeGameUserSettings&, int32)> Fn)
	{
		UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get();
		if (S && Args.Num() > 0)
		{
			Fn(*S, FCString::Atoi(*Args[0]));
			FGlobalComponentRecreateRenderStateContext Recreate;
			S->ApplyNonResolutionSettings();
		}
	}
	FAutoConsoleCommand PresetCmd(TEXT("cr.Graphics.Preset"), TEXT("Graphics preset 0 Low, 1 Medium, 2 High, 3 Epic"),
		FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& A) { WithSettings(A, [](UCambridgeGameUserSettings& S, int32 V) { S.ApplyPreset(V); }); }));
	FAutoConsoleCommand CloudsCmd(TEXT("cr.Graphics.Clouds"), TEXT("Volumetric clouds 0/1"),
		FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& A) { WithSettings(A, [](UCambridgeGameUserSettings& S, int32 V) { S.bVolumetricClouds = V != 0; }); }));
	FAutoConsoleCommand TreesCmd(TEXT("cr.Graphics.Trees"), TEXT("Tree draw distance 0 (300 m), 1 (400 m), 2 (700 m)"),
		FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& A) { WithSettings(A, [](UCambridgeGameUserSettings& S, int32 V) { S.TreeDistance = FMath::Clamp(V, 0, 2); }); }));
	FAutoConsoleCommand MenuCmd(TEXT("cr.Menu"), TEXT("Open / close the graphics menu"),
		FConsoleCommandWithWorldDelegate::CreateLambda([](UWorld* World)
		{
			if (UCambridgeMenuSubsystem* Menu = World && World->GetGameInstance() ? World->GetGameInstance()->GetSubsystem<UCambridgeMenuSubsystem>() : nullptr)
			{
				Menu->ToggleMenu();
			}
		}));
	FAutoConsoleCommandWithWorldAndArgs MenuTabCmd(TEXT("cr.Menu.Tab"), TEXT("Open the settings menu on a section: 0 graphics, 1 assists, 2 calibration, 3 sound, 4 controls"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UCambridgeMenuSubsystem* Menu = World && World->GetGameInstance() ? World->GetGameInstance()->GetSubsystem<UCambridgeMenuSubsystem>() : nullptr)
			{
				Menu->ShowTab(Args.Num() ? FCString::Atoi(*Args[0]) : 0);
			}
		}));
	FAutoConsoleCommand GeometryCmd(TEXT("cr.Graphics.Geometry"), TEXT("Geometry detail 0 low, 1 medium, 2 high"),
		FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& A) { WithSettings(A, [](UCambridgeGameUserSettings& S, int32 V) { S.GeometryDetail = FMath::Clamp(V, 0, 2); }); }));
}
