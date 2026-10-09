#include "CambridgeLaunchSubsystem.h"

#include "CambridgeMenuSubsystem.h"
#include "CambridgeRacer.h"
#include "CambridgeUIStyle.h"
#include "CambridgeWheelSubsystem.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LevelStreaming.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "ImprezaSTi.h"
#include "Kismet/GameplayStatics.h"
#include "CoreGlobals.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "MoviePlayer.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ShaderCompiler.h"
#include "TimeTrialSubsystem.h"
#include "WorldPartition/WorldPartitionSubsystem.h"
#if WITH_EDITOR
#include "AssetCompilingManager.h"
#endif

#define LOCTEXT_NAMESPACE "CambridgeLaunch"

namespace
{
	double LaunchSinceStart()
	{
		return FPlatformTime::Seconds() - GStartTime;
	}

	FString LaunchFormatTime(double T)
	{
		const int32 Minutes = int32(T / 60.0);
		return FString::Printf(TEXT("%d:%06.3f"), Minutes, T - Minutes * 60.0);
	}

	UCambridgeLaunchSubsystem* LaunchFromWorld(UWorld* World)
	{
		UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
		return GI ? GI->GetSubsystem<UCambridgeLaunchSubsystem>() : nullptr;
	}

	FAutoConsoleCommandWithWorldAndArgs CmdLaunch(TEXT("cr.Launch"),
		TEXT("Show the launch menu: cr.Launch [events] [N] (the Timed Race list, item N selected)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UCambridgeLaunchSubsystem* L = LaunchFromWorld(World))
			{
				const bool bEvents = Args.Num() > 0 && Args[0] == TEXT("events");
				const int32 N = Args.Num() > (bEvents ? 1 : 0) ? FCString::Atoi(*Args[bEvents ? 1 : 0]) : 0;
				L->Show(bEvents ? SCambridgeLaunchScreen::EventPage : SCambridgeLaunchScreen::MainPage, N);
			}
		}));
	FAutoConsoleCommandWithWorldAndArgs CmdLaunchChoose(TEXT("cr.Launch.Choose"),
		TEXT("Launch menu: select item N of the current page and press it (main page: 0 open world, 1 timed race, 2 options)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UCambridgeLaunchSubsystem* L = LaunchFromWorld(World); L && Args.Num() > 0)
			{
				L->Choose(FCString::Atoi(*Args[0]));
			}
		}));
	FAutoConsoleCommandWithWorldAndArgs CmdLaunchLoading(TEXT("cr.Launch.LoadingPreview"),
		TEXT("Test: show (1) / hide (0) the loading-screen version of the launch menu over everything"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UCambridgeLaunchSubsystem* L = LaunchFromWorld(World))
			{
				L->SetLoadingPreview(Args.Num() == 0 || Args[0] != TEXT("0"));
			}
		}));
	FAutoConsoleCommandWithWorldAndArgs CmdLaunchClose(TEXT("cr.Launch.Close"), TEXT("Close the launch menu"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
		{
			if (UCambridgeLaunchSubsystem* L = LaunchFromWorld(World)) { L->Close(); }
		}));
}

// ------------------------------------------------------------------ static helpers

bool UCambridgeLaunchSubsystem::IsLaunchFlowEnabled()
{
	return CambridgeUI::IsLaunchFlowEnabled();
}

bool UCambridgeLaunchSubsystem::GetFreeRoamStart(const UWorld* World, FTransform& Out)
{
	if (!World)
	{
		return false;
	}
	const FString Map = FPackageName::GetShortName(World->GetOutermost()->GetName()).Replace(TEXT("UEDPIE_0_"), TEXT(""));
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectDir() / TEXT("Tracks") / (Map + TEXT(".json")))))
	{
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	const TSharedPtr<FJsonObject>* Free = nullptr;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid() || !Root->TryGetObjectField(TEXT("free_roam"), Free))
	{
		return false;
	}
	const TSharedPtr<FJsonObject>& F = *Free;
	Out = FTransform(FRotator(0.0, F->GetNumberField(TEXT("yaw")), 0.0),
		FVector(F->GetNumberField(TEXT("x")), F->GetNumberField(TEXT("y")), F->GetNumberField(TEXT("z"))));
	return true;
}

bool UCambridgeLaunchSubsystem::IsLaunchMenuOpen(const UObject* WorldContext)
{
	const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull) : nullptr;
	const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
	const UCambridgeLaunchSubsystem* L = GI ? GI->GetSubsystem<UCambridgeLaunchSubsystem>() : nullptr;
	return L && L->IsOpen();
}

// ------------------------------------------------------------------ lifetime

bool UCambridgeLaunchSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return !IsRunningCommandlet() && Super::ShouldCreateSubsystem(Outer);
}

void UCambridgeLaunchSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	bEnabled = IsLaunchFlowEnabled() && FSlateApplication::IsInitialized();
	if (!bEnabled)
	{
		return;
	}
	FCambridgeUIStyle::Initialize();
	// the menu is the loading screen: CambridgeUI (loading phase PreLoadingScreen) set it up so the engine plays it from
	// the moment the game window appears. If that module didn't (the loading screen disabled at its startup), from
	// here it still covers the map load
	if (!CambridgeUI::IsLaunchLoadingScreenSetUp() && IsMoviePlayerEnabled() && GetMoviePlayer() && !GetMoviePlayer()->IsMovieCurrentlyPlaying())
	{
		FLoadingScreenAttributes Attributes;
		Attributes.bAutoCompleteWhenLoadingCompletes = true;
		Attributes.bWaitForManualStop = false;
		Attributes.bMoviesAreSkippable = false;
		Attributes.MinimumLoadingScreenDisplayTime = -1.0f;
		Attributes.WidgetLoadingScreen = SNew(SCambridgeLaunchScreen).bLive(false);
		GetMoviePlayer()->SetupLoadingScreen(Attributes);
	}
	PostWorldInitHandle = FWorldDelegates::OnPostWorldInitialization.AddUObject(this, &UCambridgeLaunchSubsystem::OnPostWorldInit);
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this, &UCambridgeLaunchSubsystem::Tick));
	LoadText = LOCTEXT("LoadingStart", "LOADING CAMBRIDGE");
	UE_LOG(LogCambridgeRacer, Display, TEXT("launch: menu first, free roam from the HTMAA lectures (%.1f s after start)"), LaunchSinceStart());
}

void UCambridgeLaunchSubsystem::Deinitialize()
{
	FWorldDelegates::OnPostWorldInitialization.Remove(PostWorldInitHandle);
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	SetLoadingPreview(false);
	if (Screen.IsValid())
	{
		if (UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr)
		{
			Viewport->RemoveViewportWidgetContent(Screen.ToSharedRef());
		}
		Screen.Reset();
	}
	Super::Deinitialize();
}

void UCambridgeLaunchSubsystem::OnPostWorldInit(UWorld* World, const UWorld::InitializationValues)
{
	if (!bShownAtStartup && World && World->IsGameWorld())
	{
		StartupWorld = World;
		World->OnWorldBeginPlay.AddUObject(this, &UCambridgeLaunchSubsystem::OnWorldBeginPlay);
	}
}

void UCambridgeLaunchSubsystem::OnWorldBeginPlay()
{
	// (inside the map load: the menu is in the viewport before its first frame, so the world never shows first)
	if (bShownAtStartup)
	{
		return;
	}
	bShownAtStartup = true;
	if (AImprezaSTi* Car = GetCar())
	{
		// (RestartPlayer aimed the controller like the PlayerStart; the camera behind the car instead)
		if (APlayerController* PC = Cast<APlayerController>(Car->GetController()))
		{
			PC->SetControlRotation(Car->GetActorRotation());
		}
		Car->SnapCamera();
	}
	Show();
	UE_LOG(LogCambridgeRacer, Display, TEXT("launch: menu in the viewport %.1f s after start"), LaunchSinceStart());
}

// ------------------------------------------------------------------ show / close

UWorld* UCambridgeLaunchSubsystem::GetGameWorld() const
{
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	UWorld* World = Viewport ? Viewport->GetWorld() : nullptr;
	return World ? World : StartupWorld.Get();
}

AImprezaSTi* UCambridgeLaunchSubsystem::GetCar() const
{
	UWorld* World = GetGameWorld();
	return World ? Cast<AImprezaSTi>(UGameplayStatics::GetPlayerPawn(World, 0)) : nullptr;
}

TArray<FLaunchEventInfo> UCambridgeLaunchSubsystem::BuildEvents() const
{
	TArray<FLaunchEventInfo> Out;
	UWorld* World = GetGameWorld();
	const UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr;
	if (!TT)
	{
		return Out;
	}
	const TArray<FTimeTrialTrack>& Tracks = TT->GetTracks();
	for (int32 i = 0; i < Tracks.Num(); ++i)
	{
		const FTimeTrialTrack& T = Tracks[i];
		const double Best = TT->GetBestTime(i);
		const FString Km = FString::Printf(TEXT("%.1f KM"), T.LengthM * (T.bCircuit ? T.Laps : 1) / 1000.0f);
		FLaunchEventInfo E;
		E.Name = FText::FromString(T.Name);
		E.Short = FText::FromString(Best > 0.0 ? FString::Printf(TEXT("%s   %s"), *Km, *LaunchFormatTime(Best)) : Km);
		const FString Kind = T.bCircuit ? FString::Printf(TEXT("Circuit, %d lap%s"), T.Laps, T.Laps > 1 ? TEXT("s") : TEXT("")) : FString(TEXT("Sprint"));
		E.Detail = FText::FromString(FString::Printf(TEXT("%s  ·  %.1f km  ·  %s"), *Kind, T.LengthM * (T.bCircuit ? T.Laps : 1) / 1000.0f,
			Best > 0.0 ? *FString::Printf(TEXT("best %s"), *LaunchFormatTime(Best)) : TEXT("no best time yet")));
		Out.Add(E);
	}
	return Out;
}

void UCambridgeLaunchSubsystem::Show(int32 Page, int32 Select)
{
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (!Viewport)
	{
		return;
	}
	if (Screen.IsValid())
	{
		Screen->ShowPage(Page, Select);
		return;
	}
	// the main menu replaces a running event (the settings window's Main menu button)
	UWorld* World = GetGameWorld();
	if (UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
	{
		TT->LeaveEvent();
	}
	Screen = SNew(SCambridgeLaunchScreen)
		.bLive(true)
		.Events(BuildEvents())
		.LoadFraction_UObject(this, &UCambridgeLaunchSubsystem::GetLoadFraction)
		.LoadText_UObject(this, &UCambridgeLaunchSubsystem::GetLoadText)
		.bWheel_Lambda([this]()
		{
			const UCambridgeWheelSubsystem* Wheel = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr;
			return Wheel && Wheel->IsActive();
		})
		.OnMainChoice_UObject(this, &UCambridgeLaunchSubsystem::OnMainChoice)
		.OnEventChoice_UObject(this, &UCambridgeLaunchSubsystem::OnEventChoice)
		.OnMoved_UObject(this, &UCambridgeLaunchSubsystem::OnMoved);
	Screen->ShowPage(Page, Select);
	// over the HUD (40-50) and the full map (90), under the settings window (100: Options opens on top of it)
	Viewport->AddViewportWidgetContent(Screen.ToSharedRef(), 95);
	OpenedAt = FPlatformTime::Seconds();
	bRimArmed = false;
	RestoreFocus();
	ParkCar(true);
	UpdateLoading();
}

void UCambridgeLaunchSubsystem::Close()
{
	if (!Screen.IsValid())
	{
		return;
	}
	if (UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr)
	{
		Viewport->RemoveViewportWidgetContent(Screen.ToSharedRef());
	}
	Screen.Reset();
	if (APlayerController* PC = GetGameInstance() ? GetGameInstance()->GetFirstLocalPlayerController() : nullptr)
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->SetShowMouseCursor(false);
	}
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().SetAllUserFocusToGameViewport();
	}
	ParkCar(false);
}

void UCambridgeLaunchSubsystem::RestoreFocus()
{
	if (!Screen.IsValid())
	{
		return;
	}
	if (APlayerController* PC = GetGameInstance() ? GetGameInstance()->GetFirstLocalPlayerController() : nullptr)
	{
		FInputModeUIOnly Mode;
		Mode.SetWidgetToFocus(Screen);
		Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		PC->SetInputMode(Mode);
		PC->SetShowMouseCursor(true);
	}
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().SetAllUserFocus(Screen, EFocusCause::SetDirectly);
	}
}

void UCambridgeLaunchSubsystem::SetLoadingPreview(bool bShow)
{
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (!Viewport)
	{
		return;
	}
	if (LoadingPreview.IsValid())
	{
		Viewport->RemoveViewportWidgetContent(LoadingPreview.ToSharedRef());
		LoadingPreview.Reset();
	}
	if (bShow)
	{
		LoadingPreview = SNew(SCambridgeLaunchScreen).bLive(false);
		Viewport->AddViewportWidgetContent(LoadingPreview.ToSharedRef(), 99);
	}
}

bool UCambridgeLaunchSubsystem::Back()
{
	const bool bBack = Screen.IsValid() && Screen->Back();
	if (bBack)
	{
		UE_LOG(LogCambridgeRacer, Display, TEXT("launch: back to the main page"));
	}
	return bBack;
}

void UCambridgeLaunchSubsystem::Select(int32 Index)
{
	if (Screen.IsValid()) { Screen->Select(Index); }
}

void UCambridgeLaunchSubsystem::Choose(int32 Index)
{
	if (Screen.IsValid())
	{
		Screen->Select(Index);
		Screen->Activate();
	}
}

void UCambridgeLaunchSubsystem::ParkCar(bool bPark)
{
	AImprezaSTi* Car = GetCar();
	if (!Car)
	{
		return;
	}
	UChaosWheeledVehicleMovementComponent* Move = Car->GetChaosVehicleMovement();
	if (bPark)
	{
		// hands off, handbrake on, stopped: the car waits silently behind the menu
		Car->DoThrottle(0.0f);
		Car->DoBrake(0.0f);
		Car->DoSteering(0.0f);
		Car->DoHandbrakeStop();
		Move->SetParked(true);
		Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	}
	else
	{
		Move->SetParked(false);
	}
	Car->SetEngineSoundMuted(bPark);
}

// ------------------------------------------------------------------ choices

void UCambridgeLaunchSubsystem::PlaySound(FName Name, float Volume) const
{
	UWorld* World = GetGameWorld();
	if (const UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr)
	{
		TT->PlayUISound(Name, Volume);
	}
}

void UCambridgeLaunchSubsystem::OnMoved()
{
	PlaySound(TEXT("ui_select"), 0.8f);
}

void UCambridgeLaunchSubsystem::OnMainChoice(int32 Choice)
{
	static const TCHAR* const Names[] = { TEXT("open world"), TEXT("timed race list"), TEXT("options") };
	UE_LOG(LogCambridgeRacer, Display, TEXT("launch: choice %s"), Names[FMath::Clamp(Choice, 0, 2)]);
	PlaySound(TEXT("ui_confirm"));
	switch (Choice)
	{
	case 0:
		LaunchOpenWorld();
		break;
	case 2:
		if (UCambridgeMenuSubsystem* Menu = GetGameInstance()->GetSubsystem<UCambridgeMenuSubsystem>())
		{
			Menu->ShowTab(0);      // over the launch menu, not paused (the map keeps loading)
		}
		break;
	default:
		break;                     // 1: the widget opened the event list
	}
}

void UCambridgeLaunchSubsystem::OnEventChoice(int32 Index)
{
	UWorld* World = GetGameWorld();
	UTimeTrialSubsystem* TT = World ? World->GetSubsystem<UTimeTrialSubsystem>() : nullptr;
	if (!TT || !TT->GetTracks().IsValidIndex(Index))
	{
		return;
	}
	UE_LOG(LogCambridgeRacer, Display, TEXT("launch: timed race %s"), *TT->GetTracks()[Index].Name);
	Close();
	TT->StartEventByIndex(Index);    // its grid (with the streaming hold for a far start), parked for the countdown
}

void UCambridgeLaunchSubsystem::LaunchOpenWorld()
{
	UWorld* World = GetGameWorld();
	AImprezaSTi* Car = GetCar();
	FTransform Start;
	if (World && Car && GetFreeRoamStart(World, Start) && FVector::Dist2D(Car->GetActorLocation(), Start.GetLocation()) > 3000.0)
	{
		// back from somewhere else (the main menu mid-game): to the lectures, loading the street first if it is out
		Car->SetActorTransform(Start, false, nullptr, ETeleportType::TeleportPhysics);
		Car->GetMesh()->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Car->GetMesh()->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
		Car->SnapCamera();
		FHitResult Hit;
		const FVector At = Start.GetLocation();
		FCollisionQueryParams Query(SCENE_QUERY_STAT(LaunchGround), false, Car);
		if (!World->LineTraceSingleByChannel(Hit, At + FVector(0, 0, 500), At - FVector(0, 0, 500), ECC_Visibility, Query))
		{
			World->bRequestedBlockOnAsyncLoading = true;
		}
	}
	UE_LOG(LogCambridgeRacer, Display, TEXT("launch: open world from the HTMAA lectures (%.1f s after the menu opened, map %s)"),
		FPlatformTime::Seconds() - OpenedAt, *LoadText.ToString());
	Close();
}

// ------------------------------------------------------------------ per frame (runs while the game is paused too)

bool UCambridgeLaunchSubsystem::Tick(float)
{
	if (Screen.IsValid())
	{
		UpdateLoading();
		TickWheel();
	}
	return true;
}

void UCambridgeLaunchSubsystem::TickWheel()
{
	UCambridgeMenuSubsystem* Menu = GetGameInstance()->GetSubsystem<UCambridgeMenuSubsystem>();
	UCambridgeWheelSubsystem* Wheel = GetGameInstance()->GetSubsystem<UCambridgeWheelSubsystem>();
	if (!Wheel || !Wheel->IsActive() || (Menu && Menu->IsMenuOpen()))
	{
		bRimArmed = false;
		return;       // (the settings window, when open over the menu, has the wheel)
	}
	// paddles: left up, right down; both tapped = go (the wheel's start), both held = back (from the event list)
	switch (Wheel->ConsumeMenuAction())
	{
	case EWheelMenuAction::Up: Screen->Move(-1); break;
	case EWheelMenuAction::Down: Screen->Move(+1); break;
	case EWheelMenuAction::Go: Screen->Activate(); break;
	case EWheelMenuAction::Back: Back(); break;
	default: break;
	}
	if (!Screen.IsValid())
	{
		return;      // (Go closed the menu)
	}
	const float Rim = Wheel->GetState().SteerDeg;
	if (!bRimArmed)
	{
		bRimArmed = FMath::Abs(Rim) < 25.0f;
	}
	else if (Rim < -50.0f)
	{
		bRimArmed = false;
		Back();       // (the rim turned left: back from the event list)
	}
}

void UCambridgeLaunchSubsystem::UpdateLoading()
{
	UWorld* World = GetGameWorld();
	if (!World)
	{
		return;
	}
	// World Partition cells (streaming levels) wanted around the car vs those already in; then the shaders and
	// meshes the editor binary still compiles for them (uncooked content)
	int32 Wanted = 0, In = 0;
	for (const ULevelStreaming* Level : World->GetStreamingLevels())
	{
		if (Level && Level->ShouldBeLoaded())
		{
			++Wanted;
			In += Level->IsLevelVisible() ? 1 : 0;
		}
	}
	MaxStreamingSeen = FMath::Max(MaxStreamingSeen, Wanted);
	UWorldPartitionSubsystem* WP = World->GetSubsystem<UWorldPartitionSubsystem>();
	const bool bStreamed = !WP || WP->IsAllStreamingCompleted();
	int32 Compiling = GShaderCompilingManager ? GShaderCompilingManager->GetNumRemainingJobs() : 0;
#if WITH_EDITOR
	Compiling += FAssetCompilingManager::Get().GetNumRemainingAssets();
#endif
	const float Streamed = bStreamed ? 1.0f : MaxStreamingSeen > 0 ? float(In) / float(MaxStreamingSeen) : 0.0f;
	// (shown as one bar: streaming is most of the wait; the compiles fill the last 10 %)
	const float Fraction = bStreamed && Compiling > 0 ? 0.9f : Streamed * (Compiling > 0 ? 0.9f : 1.0f);
	LoadFraction = FMath::Max(LoadFraction, Fraction);
	if (!bStreamed)
	{
		LoadText = FText::Format(LOCTEXT("Loading", "LOADING CAMBRIDGE  {0}%"), FText::AsNumber(FMath::RoundToInt(LoadFraction * 100.0f)));
	}
	else if (Compiling > 0)
	{
		LoadText = FText::Format(LOCTEXT("Preparing", "PREPARING SHADERS  {0}"), FText::AsNumber(Compiling));
	}
	else
	{
		LoadFraction = 1.0f;
		LoadText = LOCTEXT("Ready", "CAMBRIDGE IS READY");
		if (!bReadyLogged)
		{
			bReadyLogged = true;
			UE_LOG(LogCambridgeRacer, Display, TEXT("launch: map ready behind the menu %.1f s after start (%d cells)"), LaunchSinceStart(), MaxStreamingSeen);
		}
	}
}

#undef LOCTEXT_NAMESPACE
