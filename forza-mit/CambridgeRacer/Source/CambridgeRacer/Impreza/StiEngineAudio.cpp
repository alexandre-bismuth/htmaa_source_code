#include "StiEngineAudio.h"

#include "CambridgeGameUserSettings.h"

#include "ChaosVehicleWheel.h"
#include "ChaosWheeledVehicleMovementComponent.h"
#include "Components/AudioComponent.h"
#include "Engine/World.h"
#include "ImprezaSTi.h"
#include "Sound/AudioSettings.h"
#include "Sound/SoundWave.h"

// Every constant and step below is mirrored in tools/mapgen/render_engine_demo.py.
namespace
{
	// must match RPMS in tools/mapgen/make_engine_audio.py (geometric, ratio ~1.25)
	const int32 LoopRpms[] = { 800, 1000, 1250, 1550, 1950, 2450, 3050, 3800, 4750, 5950, 7400 };
	constexpr int32 NumPopWaves = 5;          // pop_1 .. pop_5
	constexpr int32 NumPopVoices = 2;
	constexpr float XFadeStart = 0.2f;        // crossfade only across the middle of each rpm interval
	constexpr float XFadeEnd = 0.8f;
	constexpr float XFadeShape = 1.5f;        // cos/sin^1.5: the loops' low orders add coherently (crank-locked),
	                                          // the upper ones don't: halfway between equal-power and linear
	constexpr float LoadCurve = 0.75f;        // on/off gains: Load^0.75 / (1-Load)^0.75 (partly coherent pair)
	constexpr float RelockGain = 0.15f;       // silent loops: pitch nudge per cycle of phase error
	constexpr float LaunchRpm = 4000.0f;      // AImprezaSTi::ClutchSlipRPM (clutch slip at launch)
	constexpr float LimiterRpm = 7900.0f;     // Chaos MaxRPM is 8000
	constexpr float LimiterHz = 14.0f;        // fuel-cut bounce rate
	constexpr float ShiftRpmFall = 4000.0f;   // rpm/s the engine falls with the clutch in
	constexpr float PopVolume = 0.40f;
	constexpr float WhistleVolume = 0.0093f;   // whistle + blow-off: -4.2 dB = "25 % quieter" to the ear (round 3)
	constexpr float BlowOffVolume = 0.124f;
	// The on-load loops' 1.2-2.6 kHz band (where the whistle sits) grows ~14 dB from 4750 to 7400 rpm: at a fixed level
	// the whistle was ~0 dB under it at 3000-4000 rpm but -13 dB at 5950 and -21 dB at 7400 (inaudible on boost, where
	// the game is mostly driven). Its level rises with rpm above 4750 (x WhistleRpmGainMax at 7400) so it stays ~10 dB
	// under the engine there: a quiet whine, unchanged below 4750 rpm.
	constexpr float WhistleRpmFrom = 4750.0f;
	constexpr float WhistleRpmTo = 7400.0f;
	constexpr float WhistleRpmGainMax = 3.1f;

	USoundWave* LoadWave(const FString& Name)
	{
		return LoadObject<USoundWave>(nullptr, *FString::Printf(TEXT("/Game/Cambridge/Car/Audio/%s.%s"), *Name, *Name));
	}

	float WrapCycles(float X) { return X - FMath::RoundToFloat(X); }
}

UStiEngineAudio::UStiEngineAudio()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bTickEvenWhenPaused = true;    // to pause the voices
}

UAudioComponent* UStiEngineAudio::MakeVoice(USoundWave* Wave)
{
	if (!Wave)
	{
		return nullptr;
	}
	UAudioComponent* A = NewObject<UAudioComponent>(GetOwner());
	A->bAutoActivate = false;
	A->bAutoDestroy = false;
	A->bAllowSpatialization = false;
	A->SetSound(Wave);
	A->RegisterComponent();
	return A;
}

void UStiEngineAudio::BeginPlay()
{
	Super::BeginPlay();
	// UE clamps every pitch to Project Settings > Audio > Global Min/Max Pitch Scale (default 0.4..2.0).
	// DefaultEngine.ini sets 0.08..12 so the loops (800..7400 rpm, engine 720..8000) are never clamped
	// and stay crank-locked; with a narrower range the relock below takes over.
	const UAudioSettings* AudioSettings = GetDefault<UAudioSettings>();
	MinPitch = FMath::Max(AudioSettings->GlobalMinPitchScale, 0.0001f);
	MaxPitch = FMath::Max(AudioSettings->GlobalMaxPitchScale, MinPitch);
	for (int32 Rpm : LoopRpms)
	{
		USoundWave* OnWave = LoadWave(FString::Printf(TEXT("engine_on_%d"), Rpm));
		USoundWave* OffWave = LoadWave(FString::Printf(TEXT("engine_off_%d"), Rpm));
		if (!OnWave || !OffWave)
		{
			continue;
		}
		// Silent loops must keep playing (the default, Restart, would restart them from sample 0
		// when they become audible again and break the crank lock between loops).
		OnWave->VirtualizationMode = EVirtualizationMode::PlayWhenSilent;
		OffWave->VirtualizationMode = EVirtualizationMode::PlayWhenSilent;
		Rpms.Add(Rpm);
		OnVoices.Add(MakeVoice(OnWave));
		OffVoices.Add(MakeVoice(OffWave));
	}
	// all loops start in the same tick at sample 0 (= the same crank angle) and run forever
	for (int32 i = 0; i < Rpms.Num(); ++i)
	{
		const float Pitch = FMath::Clamp(SmoothRpm / Rpms[i], MinPitch, MaxPitch);
		VoicePitch.Add(Pitch);
		PhaseErr.Add(0.0f);
		for (UAudioComponent* A : { OnVoices[i].Get(), OffVoices[i].Get() })
		{
			A->SetVolumeMultiplier(0.0f);
			A->SetPitchMultiplier(Pitch);
			A->Play();
		}
	}
	LockRpm = SmoothRpm;
	for (int32 i = 1; i <= NumPopWaves; ++i)
	{
		if (USoundWave* W = LoadWave(FString::Printf(TEXT("pop_%d"), i)))
		{
			PopWaves.Add(W);
		}
	}
	for (int32 i = 0; PopWaves.Num() > 0 && i < NumPopVoices; ++i)
	{
		PopVoices.Add(MakeVoice(PopWaves[0]));
	}
	Whistle = MakeVoice(LoadWave(TEXT("turbo_whistle")));
	Squeal = MakeVoice(LoadWave(TEXT("tyre_squeal")));
	BlowOff = MakeVoice(LoadWave(TEXT("blowoff")));
	for (UAudioComponent* A : { Whistle.Get(), Squeal.Get() })
	{
		if (A) { A->SetVolumeMultiplier(0.0f); A->Play(); }
	}
	SetComponentTickEnabled(Rpms.Num() >= 2);
}

void UStiEngineAudio::FirePop(float Volume)
{
	if (PopVoices.Num() == 0)
	{
		return;
	}
	UAudioComponent* A = PopVoices[NextPop++ % PopVoices.Num()];
	A->SetSound(PopWaves[FMath::RandRange(0, PopWaves.Num() - 1)]);
	A->SetVolumeMultiplier(Gain * PopVolume * Volume * FMath::FRandRange(0.55f, 1.0f));
	A->SetPitchMultiplier(FMath::FRandRange(0.85f, 1.15f));
	A->Play();
	LastPop = GetWorld()->GetTimeSeconds();
}

void UStiEngineAudio::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	const AImprezaSTi* Car = Cast<AImprezaSTi>(GetOwner());
	UChaosWheeledVehicleMovementComponent* Move = Car ? Car->GetChaosVehicleMovement() : nullptr;
	if (!Move || !Move->PhysicsVehicleOutput())
	{
		return;
	}
	// pause menu (and the launch menu: muted): freeze all voices
	const bool bNowPaused = GetWorld()->IsPaused() || bMuted;
	if (bNowPaused != bPaused)
	{
		bPaused = bNowPaused;
		for (UAudioComponent* A : OnVoices) { A->SetPaused(bPaused); }
		for (UAudioComponent* A : OffVoices) { A->SetPaused(bPaused); }
		for (UAudioComponent* A : PopVoices) { A->SetPaused(bPaused); }
		for (UAudioComponent* A : { Whistle.Get(), Squeal.Get(), BlowOff.Get() }) { if (A) { A->SetPaused(bPaused); } }
	}
	const UCambridgeGameUserSettings* Settings = UCambridgeGameUserSettings::Get();
	Gain = MasterVolume * (Settings ? FMath::Clamp(Settings->EngineVolume, 0.0f, 1.2f) : 1.0f);
	if (bPaused || DeltaTime <= 0.0f)
	{
		return;
	}
	const double Now = GetWorld()->GetTimeSeconds();
	const int32 Gear = Move->GetCurrentGear();
	const int32 TargetGear = Move->GetTargetGear();
	// the pedal that drives the car. Keyboard / gamepad reverse (Chaos bReverseAsBrake): the brake key drives and the raw
	// throttle stays 0, so reverse used to play the overrun loops (quiet, dark, popping) under a full-boost whistle
	// (AImprezaSTi::UpdateEngine spools the turbo from the brake key there). Same rule as UpdateEngine.
	float Throttle = Move->GetThrottleInput();
	if (Gear < 0 && Move->bReverseAsBrake)
	{
		Throttle = FMath::Max(Throttle, Move->GetBrakeInput());
	}
	Throttle = FMath::Clamp(Throttle, 0.0f, 1.0f);
	const float Boost = Car->GetBoost();

	// --- crank lock: integrate each loop's phase error over the last tick (pitch it actually played at)
	for (int32 i = 0; i < Rpms.Num(); ++i)
	{
		PhaseErr[i] = WrapCycles(PhaseErr[i] + (VoicePitch[i] * Rpms[i] - LockRpm) / 120.0f * DeltaTime);
	}

	// --- engine rpm as heard
	float Rpm = Move->GetEngineRotationSpeed();
	// launch: Chaos ties the engine to the wheels; the car slips the clutch up to LaunchRpm in 1st/reverse
	if ((Gear == 1 || Gear == -1) && Rpm < LaunchRpm && Throttle > 0.05f)
	{
		Rpm = FMath::Lerp(Rpm, LaunchRpm, Throttle);
	}
	// gear change: Chaos sits in neutral (gear 0) for GearChangeTime; the engine falls with the clutch in
	const bool bShifting = Gear == 0 && TargetGear != 0;
	if (bShifting && !bWasShifting && TargetGear > LastDriveGear && LastDriveGear >= 1)
	{
		// upshift: the turbo dumps its charge, sometimes a pop
		if (BlowOff && Boost > 0.45f && Now - LastBlowOff > 0.5)
		{
			LastBlowOff = Now;
			BlowOff->SetVolumeMultiplier(Gain * BlowOffVolume * Boost);
			BlowOff->SetPitchMultiplier(FMath::FRandRange(0.92f, 1.08f));
			BlowOff->Play();
		}
		CrackleEnergy = FMath::Max(CrackleEnergy, 0.35f);
	}
	ShiftRpm = bShifting ? FMath::Max(ShiftRpm - ShiftRpmFall * DeltaTime, float(Rpms[0])) : Rpm;
	if (bShifting)
	{
		Rpm = FMath::Min(Rpm, ShiftRpm);
	}
	bWasShifting = bShifting;
	if (Gear != 0)
	{
		LastDriveGear = Gear;
	}
	// rev limiter: fuel-cut bounce
	const bool bLimiter = Rpm >= LimiterRpm && Throttle > 0.5f;
	LimiterClock = bLimiter ? LimiterClock + DeltaTime : 0.0f;
	const bool bCut = bLimiter && FMath::Frac(LimiterClock * LimiterHz) < 0.5f;
	if (bCut)
	{
		Rpm -= 250.0f;
		if (!bWasCut && FMath::FRand() < 0.25f && Now - LastPop > 0.07)
		{
			FirePop(0.7f);
		}
	}
	bWasCut = bCut;
	Rpm = FMath::Clamp(Rpm, float(Rpms[0]) * 0.9f, 8000.0f);
	SmoothRpm = FMath::FInterpTo(SmoothRpm, Rpm, DeltaTime, 25.0f);

	// --- load: near idle the engine holds itself up (on load); overrun when lifting / shifting / cutting
	const float IdleOn = 1.0f - FMath::Clamp((SmoothRpm - 1100.0f) / 600.0f, 0.0f, 1.0f);
	const float TargetLoad = (bShifting || bCut) ? IdleOn : FMath::Max(Throttle, IdleOn);
	SmoothLoad = FMath::FInterpTo(SmoothLoad, TargetLoad, DeltaTime, (bShifting || bLimiter) ? 60.0f : 12.0f);

	// --- engine loops
	int32 Lo = 0;
	while (Lo + 1 < Rpms.Num() - 1 && Rpms[Lo + 1] <= SmoothRpm) { ++Lo; }
	const float T = FMath::Clamp((SmoothRpm - Rpms[Lo]) / float(Rpms[Lo + 1] - Rpms[Lo]), 0.0f, 1.0f);
	const float U = FMath::Clamp((T - XFadeStart) / (XFadeEnd - XFadeStart), 0.0f, 1.0f);
	// Max(0, .) before Pow: in single precision Cos(UE_HALF_PI) is -4.4e-8 and Pow(-4.4e-8, 1.5) is NaN. UE's mixer
	// clamps a NaN volume to MAX_VOLUME (4.0, after the platform headroom), so the lower loop pair (on AND off) blared at
	// 4x the loudest normal voice whenever SmoothRpm sat in the top 20 % of an rpm interval (U = 1): +12 dB bursts that
	// hit 0 dBFS and clipped, the in-game "saturation". The double-precision Python port (cos(pi/2) = +6e-17) never saw it.
	const float WeightLo = FMath::Pow(FMath::Max(FMath::Cos(U * UE_HALF_PI), 0.0f), XFadeShape);
	const float WeightHi = FMath::Pow(FMath::Max(FMath::Sin(U * UE_HALF_PI), 0.0f), XFadeShape);
	const float LoadClamped = FMath::Clamp(SmoothLoad, 0.0f, 1.0f);
	const float OnGain = FMath::Pow(LoadClamped, LoadCurve);
	const float OffGain = FMath::Pow(1.0f - LoadClamped, LoadCurve);
	for (int32 i = 0; i < Rpms.Num(); ++i)
	{
		const float Weight = i == Lo ? WeightLo : (i == Lo + 1 ? WeightHi : 0.0f);
		float Pitch = SmoothRpm / Rpms[i];
		if (Weight <= 0.0f)
		{
			Pitch *= 1.0f - RelockGain * PhaseErr[i];
		}
		Pitch = FMath::Clamp(Pitch, MinPitch, MaxPitch);
		VoicePitch[i] = Pitch;
		OnVoices[i]->SetVolumeMultiplier(Gain * Weight * OnGain);
		OffVoices[i]->SetVolumeMultiplier(Gain * Weight * OffGain);
		OnVoices[i]->SetPitchMultiplier(Pitch);
		OffVoices[i]->SetPitchMultiplier(Pitch);
	}
	LockRpm = SmoothRpm;

	// --- overrun pops: a burst after lifting off at revs, then the odd one while coasting
	if (PrevThrottle > 0.5f && Throttle < 0.2f && SmoothRpm > 3000.0f)
	{
		CrackleEnergy = 1.0f;
	}
	CrackleEnergy *= FMath::Exp(-DeltaTime / 0.8f);
	if (SmoothLoad < 0.2f && SmoothRpm > 2400.0f)
	{
		const float RpmFactor = FMath::Clamp((SmoothRpm - 2400.0f) / 3000.0f, 0.2f, 1.0f);
		const float Rate = (0.3f + 6.0f * CrackleEnergy) * RpmFactor;     // pops per second
		if (FMath::FRand() < Rate * DeltaTime && Now - LastPop > 0.07)
		{
			FirePop(0.5f + 0.5f * RpmFactor);
		}
	}

	// --- turbo: quiet spool whine; blow-off when lifting at boost
	if (Whistle)
	{
		const float RpmX = FMath::Clamp((SmoothRpm - WhistleRpmFrom) / (WhistleRpmTo - WhistleRpmFrom), 0.0f, 1.0f);
		const float WhistleRpmGain = 1.0f + (WhistleRpmGainMax - 1.0f) * RpmX * RpmX;
		Whistle->SetVolumeMultiplier(Gain * WhistleVolume * WhistleRpmGain * Boost * Boost * (0.3f + 0.7f * Throttle));
		Whistle->SetPitchMultiplier(0.75f + 0.45f * Boost + 0.1f * SmoothRpm / 8000.0f);
	}
	if (BlowOff && PrevThrottle > 0.6f && Throttle < 0.2f && Boost > 0.45f && Now - LastBlowOff > 0.8)
	{
		LastBlowOff = Now;
		BlowOff->SetVolumeMultiplier(Gain * BlowOffVolume * Boost);
		BlowOff->SetPitchMultiplier(FMath::FRandRange(0.92f, 1.08f));
		BlowOff->Play();
	}
	PrevThrottle = Throttle;

	// --- tyres: body slip angle (sliding) and wheelspin
	if (Squeal)
	{
		const FVector V = Car->GetActorTransform().InverseTransformVectorNoScale(Car->GetVelocity()) / 100.0;   // m/s
		const float Speed = FMath::Abs(V.X);
		const float SlipDeg = Speed > 2.0 ? FMath::Abs(FMath::RadiansToDegrees(FMath::Atan2(V.Y, FMath::Abs(V.X)))) : 0.0f;
		float Spin = 0.0f;
		for (int32 i = 0; i < Move->Wheels.Num(); ++i)
		{
			const UChaosVehicleWheel* W = Move->Wheels[i];
			if (W && Move->GetWheelState(i).bInContact)
			{
				const float WheelSpeed = FMath::Abs(FMath::DegreesToRadians(W->GetRotationAngularVelocity())) * W->GetWheelRadius() / 100.0f;
				Spin = FMath::Max(Spin, FMath::Abs(WheelSpeed - Speed) / FMath::Max(Speed, 3.0f));
			}
		}
		const float Target = FMath::Clamp((SlipDeg - 5.0f) / 12.0f, 0.0f, 1.0f) * FMath::Clamp(Speed / 6.0f, 0.0f, 1.0f)
			+ FMath::Clamp((Spin - 0.25f) / 0.6f, 0.0f, 1.0f);
		SmoothSqueal = FMath::FInterpTo(SmoothSqueal, FMath::Clamp(Target, 0.0f, 1.0f), DeltaTime, 10.0f);
		Squeal->SetVolumeMultiplier(Gain * 0.42f * SmoothSqueal);   // same level as before (0.35 x 2.4)
		Squeal->SetPitchMultiplier(0.9f + 0.25f * SmoothSqueal);
	}
}
