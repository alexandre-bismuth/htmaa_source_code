// Engine / turbo / tyre sound for the STi from the synthesised loops (tools/mapgen/make_engine_audio.py,
// imported to /Game/Cambridge/Car/Audio by tools/unreal/import_car.sh).
//   engine   on-load and overrun loops on a geometric rpm grid. The two neighbouring loops are
//            crossfaded (in the middle of each interval only) and pitched by
//            rpm / loop rpm, so an audible loop is never shifted by more than ~12 %. All loops play
//            from BeginPlay and stay crank-locked (same firing phase), so a crossfade never
//            cancels the low orders that carry the boxer burble; silent loops whose pitch hit UE's
//            global pitch clamp are nudged back into phase before they are heard again.
//            Load: throttle, forced to overrun during gear changes and the rev-limiter cuts.
//   pops     overrun afterfire one-shots, fired at random after a lift-off at revs / on upshifts
//   turbo    a quiet spool whine with boost; blow-off "pshh" on lift-off or upshift at boost
//   tyres    squeal from body slip angle and wheelspin
// Non-spatialised (the camera always follows this car).
// tools/mapgen/render_engine_demo.py is a line-by-line Python port of TickComponent: keep them in sync.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "StiEngineAudio.generated.h"

class UAudioComponent;
class USoundWave;

UCLASS(ClassGroup = (Audio), meta = (BlueprintSpawnableComponent))
class UStiEngineAudio : public UActorComponent
{
	GENERATED_BODY()

public:
	UStiEngineAudio();
	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	UPROPERTY(EditAnywhere, Category = "Audio") float MasterVolume = 2.0f;

private:
	UAudioComponent* MakeVoice(USoundWave* Wave);
	void FirePop(float Volume);

	TArray<int32> Rpms;
	UPROPERTY(Transient) TArray<TObjectPtr<UAudioComponent>> OnVoices;
	UPROPERTY(Transient) TArray<TObjectPtr<UAudioComponent>> OffVoices;
	UPROPERTY(Transient) TArray<TObjectPtr<UAudioComponent>> PopVoices;
	UPROPERTY(Transient) TArray<TObjectPtr<USoundWave>> PopWaves;
	UPROPERTY(Transient) TObjectPtr<UAudioComponent> Whistle;
	UPROPERTY(Transient) TObjectPtr<UAudioComponent> Squeal;
	UPROPERTY(Transient) TObjectPtr<UAudioComponent> BlowOff;

	TArray<float> VoicePitch;        // pitch commanded last tick, per rpm loop
	TArray<float> PhaseErr;          // crank-phase error of each loop vs the engine, in engine cycles
	float LockRpm = 800.0f;          // rpm the loops were locked to last tick
	float MinPitch = 0.4f;           // UE's global pitch clamp (read from UAudioSettings)
	float MaxPitch = 2.0f;
	float SmoothRpm = 925.0f;
	float SmoothLoad = 1.0f;
	float SmoothSqueal = 0.0f;
	float PrevThrottle = 0.0f;
	float ShiftRpm = 0.0f;
	float LimiterClock = 0.0f;
	float CrackleEnergy = 0.0f;
	int32 LastDriveGear = 0;
	int32 NextPop = 0;
	bool bWasShifting = false;
	bool bWasCut = false;
	double LastBlowOff = -10.0;
	double LastPop = -10.0;
	bool bPaused = false;
};
