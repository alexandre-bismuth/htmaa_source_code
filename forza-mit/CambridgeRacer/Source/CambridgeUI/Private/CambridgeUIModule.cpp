// CambridgeUI module (loading phase PreLoadingScreen): sets the launch menu up as the engine's loading screen. The
// engine then plays it (the MoviePlayer, Slate loading thread) from the moment it creates the game window until it
// is initialised and the map is in; UCambridgeLaunchSubsystem (game module) puts the live menu in the viewport.

#include "CambridgeLaunchScreen.h"
#include "CambridgeUIStyle.h"
#include "CoreGlobals.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/PlatformTime.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"
#include "MoviePlayer.h"

DEFINE_LOG_CATEGORY_STATIC(LogCambridgeUI, Log, All);

namespace
{
	bool GLaunchLoadingScreenSetUp = false;
}

bool CambridgeUI::IsLaunchFlowEnabled()
{
	const TCHAR* Cmd = FCommandLine::Get();
	if (IsRunningCommandlet() || !FApp::CanEverRender() || FParse::Param(Cmd, TEXT("nullrhi")) || FParse::Param(Cmd, TEXT("NoLaunchMenu")))
	{
		return false;
	}
	if (FParse::Param(Cmd, TEXT("LaunchMenu")))
	{
		return true;
	}
	// automated runs keep the old start (the car on Mass Ave, driving at once)
	return !FCString::Strifind(Cmd, TEXT("-ShotTour")) && !FCString::Strifind(Cmd, TEXT("-DriveTest")) && !FCString::Strifind(Cmd, TEXT("-TimeTrialAuto"));
}

bool CambridgeUI::IsLaunchLoadingScreenSetUp()
{
	return GLaunchLoadingScreenSetUp;
}

class FCambridgeUIModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		if (!CambridgeUI::IsLaunchFlowEnabled() || !FSlateApplication::IsInitialized() || !IsMoviePlayerEnabled() || !GetMoviePlayer())
		{
			return;
		}
		FCambridgeUIStyle::Initialize();
		// auto-complete: the end of FEngineLoop::Init waits for the loading screen WITHOUT ticking the engine, so a
		// screen that waited for a key would stall the world; the live menu takes over in the viewport instead
		FLoadingScreenAttributes Attributes;
		Attributes.bAutoCompleteWhenLoadingCompletes = true;
		Attributes.bWaitForManualStop = false;
		Attributes.bMoviesAreSkippable = false;
		Attributes.MinimumLoadingScreenDisplayTime = -1.0f;
		Attributes.WidgetLoadingScreen = SNew(SCambridgeLaunchScreen).bLive(false);
		GetMoviePlayer()->SetupLoadingScreen(Attributes);
		GLaunchLoadingScreenSetUp = true;
		UE_LOG(LogCambridgeUI, Display, TEXT("launch: loading screen set up %.1f s after start"), FPlatformTime::Seconds() - GStartTime);
		// (only the first playback is ours: later ones are the engine's streaming pauses, the last frame + a throbber)
		StartedHandle = GetMoviePlayer()->OnMoviePlaybackStarted().AddLambda([this]()
		{
			UE_LOG(LogCambridgeUI, Display, TEXT("launch: loading screen up %.1f s after start"), FPlatformTime::Seconds() - GStartTime);
			GetMoviePlayer()->OnMoviePlaybackStarted().Remove(StartedHandle);
		});
		FinishedHandle = GetMoviePlayer()->OnMoviePlaybackFinished().AddLambda([this]()
		{
			UE_LOG(LogCambridgeUI, Display, TEXT("launch: loading screen done %.1f s after start"), FPlatformTime::Seconds() - GStartTime);
			GetMoviePlayer()->OnMoviePlaybackFinished().Remove(FinishedHandle);
		});
	}

	virtual void ShutdownModule() override
	{
		if (GetMoviePlayer())
		{
			GetMoviePlayer()->OnMoviePlaybackStarted().Remove(StartedHandle);
			GetMoviePlayer()->OnMoviePlaybackFinished().Remove(FinishedHandle);
		}
	}

private:
	FDelegateHandle StartedHandle;
	FDelegateHandle FinishedHandle;
};

IMPLEMENT_MODULE(FCambridgeUIModule, CambridgeUI)
