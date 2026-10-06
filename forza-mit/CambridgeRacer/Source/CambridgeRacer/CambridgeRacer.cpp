// Copyright Epic Games, Inc. All Rights Reserved.

#include "CambridgeRacer.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"

class FCambridgeRacerModule : public FDefaultGameModuleImpl
{
public:
	virtual void StartupModule() override
	{
		// Clip capture (shot tour frame sequences, -UseFixedTimeStep -FPS=N -DeterministicAudio): the non-realtime
		// audio renderer renders FApp::GetDeltaTime() of audio per frame, read once when the audio device starts
		// (before the first tick, so it would be the 1/30 s default). Make it the fixed step so the recorded
		// audio stays in sync with the frames.
		float Fps = 0.0f;
		if (FParse::Param(FCommandLine::Get(), TEXT("DeterministicAudio")) && FParse::Value(FCommandLine::Get(), TEXT("FPS="), Fps) && Fps > 0.0f)
		{
			FApp::SetDeltaTime(1.0 / Fps);
		}
	}
};

IMPLEMENT_PRIMARY_GAME_MODULE( FCambridgeRacerModule, CambridgeRacer, "CambridgeRacer" );

DEFINE_LOG_CATEGORY(LogCambridgeRacer)
