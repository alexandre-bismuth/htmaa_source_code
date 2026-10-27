#include "CambridgeGameUserSettings.h"

#include "CambridgeMenuSubsystem.h"
#include "Engine/GameInstance.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "AudioDevice.h"
#include "ComponentRecreateRenderStateContext.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/SkyLight.h"
#include "EngineUtils.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"
#include "HAL/IConsoleManager.h"
#include "Misc/CommandLine.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/Parse.h"
#include "PropInstancesActor.h"
#include "UnrealClient.h"

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
		int32 TreeDistance;
		int32 GeometryDetail;
	};
	const FPresetExtras PresetExtras[4] = { { 0, 0 }, { 1, 0 }, { 1, 1 }, { 2, 2 } };
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
		if (bGroups && TreeDistance == E.TreeDistance && GeometryDetail == E.GeometryDetail)
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
	// the resolution scale counts from 1080p: a bigger window (fullscreen on the 5K Studio Display is 2560x1440 without
	// high DPI) renders at most the pixels of a 1080p frame at that scale, and TSR upscales to the window. GPU time
	// follows the rendered pixels (2560x1440 at 100 %: 34-45 ms, at 1080p's pixel count: 24-33 ms, like 1080p itself)
	SetCVar(TEXT("r.ScreenPercentage.MaxResolution"), GetResolutionScaleCapHeight());
	SetCVar(TEXT("r.Nanite.MaxPixelsPerEdge"), MaxPixelsPerEdge[FMath::Clamp(GeometryDetail, 0, 2)]);
	ApplyDynamicResolution();
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

void UCambridgeGameUserSettings::ApplyDynamicResolution() const
{
	// dynamic resolution: the GPU budget is the frame-rate target (60, or the frame-rate limit below it). Heavy views
	// (tree-lined parks, Harvard Sq) hold it at a slightly lower resolution instead of dropping to ~45 fps (2026-10-26,
	// 1080p High: Cambridge Common 23 -> 16.7 ms). Its upper bound is the resolution scale's share of a 1080p frame's
	// pixels, like r.ScreenPercentage.MaxResolution (which dynamic resolution overrides), from the window's real size:
	// in windowed fullscreen that is the screen's, not the saved resolution. Re-applied when the window resizes
	FIntPoint Window = GetScreenResolution();
	if (GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport && GEngine->GameViewport->Viewport->GetSizeXY().Y > 0)
	{
		Window = GEngine->GameViewport->Viewport->GetSizeXY();
	}
	const float ScalePct = GetResolutionScaleCapHeight() / 1080.0f * 100.0f;
	const float PixelRatio = Window.X * Window.Y > 0 ? FMath::Sqrt(1920.0f * 1080.0f / (float(Window.X) * float(Window.Y))) : 1.0f;
	const float MaxPct = ScalePct * FMath::Min(PixelRatio, 1.0f);
	const float TargetFps = GetFrameRateLimit() > 0.0f ? FMath::Min(GetFrameRateLimit(), 60.0f) : 60.0f;
	// (off in shot tours, which measure the full-resolution cost; "r.DynamicRes.OperationMode 2" in a shot's exec forces it)
	FString Tour;
	static const bool bShotTour = FParse::Value(FCommandLine::Get(), TEXT("ShotTour="), Tour);
	SetCVar(TEXT("r.DynamicRes.OperationMode"), bDynamicResolution && !bShotTour ? 2 : 0);
	SetCVar(TEXT("r.DynamicRes.FrameTimeBudget"), 1000.0f / TargetFps);
	SetCVar(TEXT("r.DynamicRes.MaxScreenPercentage"), FMath::Clamp(MaxPct, 30.0f, 100.0f));
	SetCVar(TEXT("r.DynamicRes.MinScreenPercentage"), FMath::Clamp(MaxPct * 0.7f, 25.0f, 100.0f));
	static bool bHooked = false;
	if (!bHooked)
	{
		bHooked = true;
		FViewport::ViewportResizedEvent.AddLambda([](FViewport*, uint32)
		{
			if (const UCambridgeGameUserSettings* S = Get())
			{
				S->ApplyDynamicResolution();
			}
		});
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
	FAutoConsoleCommand DynResCmd(TEXT("cr.Graphics.DynRes"), TEXT("Dynamic resolution 0/1"),
		FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& A) { WithSettings(A, [](UCambridgeGameUserSettings& S, int32 V) { S.bDynamicResolution = V != 0; }); }));

	// lighting tuning (this run only): sky dome brightness (MPC_Sky, tools/unreal/build_sky.py), sky light and sun intensity
	FAutoConsoleCommandWithWorldAndArgs SkyCmd(TEXT("cr.Graphics.Sky"), TEXT("Lighting tuning: <dome brightness> [sky light intensity] [sun intensity]"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (!World || Args.Num() == 0)
			{
				return;
			}
			if (UMaterialParameterCollection* MPC = LoadObject<UMaterialParameterCollection>(nullptr, TEXT("/Game/Cambridge/Sky/MPC_Sky.MPC_Sky")))
			{
				UKismetMaterialLibrary::SetScalarParameterValue(World, MPC, TEXT("Intensity"), FCString::Atof(*Args[0]));
			}
			for (TActorIterator<ASkyLight> It(World); It; ++It)
			{
				USkyLightComponent* Sky = It->GetLightComponent();
				if (Args.Num() > 1)
				{
					Sky->SetIntensity(FCString::Atof(*Args[1]));
				}
				Sky->RecaptureSky();
			}
			for (TActorIterator<ADirectionalLight> It(World); It; ++It)
			{
				if (Args.Num() > 2)
				{
					It->GetLightComponent()->SetIntensity(FCString::Atof(*Args[2]));
				}
				UE_LOG(LogTemp, Display, TEXT("cr.Graphics.Sky: sun intensity %.2f"), It->GetLightComponent()->Intensity);
			}
		}));
	// look tuning (this run only): any FPostProcessSettings field of the level's post-process volumes, by name, e.g.
	// "cr.Graphics.Post ColorSaturation (X=1,Y=1,Z=1,W=1)" or "cr.Graphics.Post AutoExposureBias 1.1"
	FAutoConsoleCommandWithWorldAndArgs PostCmd(TEXT("cr.Graphics.Post"), TEXT("Look tuning: <post-process setting> <value>"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (!World || Args.Num() < 2)
			{
				UE_LOG(LogTemp, Display, TEXT("usage: cr.Graphics.Post <post-process setting> <value>"));
				return;
			}
			const UScriptStruct* Struct = FPostProcessSettings::StaticStruct();
			FProperty* Prop = Struct->FindPropertyByName(*Args[0]);
			FBoolProperty* Override = Prop ? CastField<FBoolProperty>(Struct->FindPropertyByName(*(TEXT("bOverride_") + Args[0]))) : nullptr;
			TArray<FString> Value(Args);
			Value.RemoveAt(0);
			for (TActorIterator<APostProcessVolume> It(World); Prop && It; ++It)
			{
				Prop->ImportText_Direct(*FString::Join(Value, TEXT(" ")), Prop->ContainerPtrToValuePtr<void>(&It->Settings), nullptr, PPF_None);
				if (Override)
				{
					Override->SetPropertyValue_InContainer(&It->Settings, true);
				}
			}
			UE_LOG(LogTemp, Display, TEXT("cr.Graphics.Post %s: %s"), *Args[0], Prop ? TEXT("set") : TEXT("unknown setting"));
		}));
}
