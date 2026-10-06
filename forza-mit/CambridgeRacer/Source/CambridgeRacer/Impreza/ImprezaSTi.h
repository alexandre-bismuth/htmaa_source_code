// 2002 Subaru Impreza WRX STi, JDM GDB-B "bugeye" (GDBB4EH, Sep 2001 - Sep 2002), standard car.
//
// Physics comes from published specs wherever Chaos has a matching parameter
// (sources: Subaru JP catalogue ucar.subaru.jp cat_id=4502486, Subaru press releases
// 2000-10-24 / 2001-09-10, legacypic.uk GDBB4EH + TY856WB1AA). Driver assists that the
// real car did NOT have (traction control, auto-shift) are optional game assists.
//
// Visual mesh is a placeholder (template sports car) until an STi model is sourced;
// the centre of mass is derived from the mesh's wheel bones so the 61:39 split holds anyway.

#pragma once

#include "CoreMinimal.h"
#include "CambridgeRacerPawn.h"
#include "ImprezaSTi.generated.h"

class UInputAction;
class UStaticMeshComponent;
class UInputMappingContext;

UENUM(BlueprintType)
enum class ETractionControlMode : uint8
{
	Off,
	Sport,   // allows a little wheelspin
	Full,
};

UCLASS()
class AImprezaSTi : public ACambridgeRacerPawn
{
	GENERATED_BODY()

public:
	AImprezaSTi();

	virtual void Tick(float Delta) override;
	virtual void SetupPlayerInputComponent(UInputComponent* InputComponent) override;
	virtual void PawnClientRestart() override;
	virtual void BeginPlay() override;

	// --- driver assists (all toggleable in game) ---
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Assists")
	ETractionControlMode TractionControl = ETractionControlMode::Sport;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Assists")
	bool bAutoShift = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Assists")
	bool bABS = true;

	/** JDM cars were limited to 180 km/h (JAMA agreement). Off by default. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Assists")
	bool bSpeedLimiter180 = false;

	UFUNCTION(BlueprintCallable, Category = "Assists") void CycleTractionControl();
	UFUNCTION(BlueprintCallable, Category = "Assists") void SetTractionControl(ETractionControlMode Mode);
	UFUNCTION(BlueprintCallable, Category = "Assists") void SetAutoShift(bool bEnabled);
	UFUNCTION(BlueprintCallable, Category = "Assists") void SetABS(bool bEnabled);
	UFUNCTION(BlueprintCallable, Category = "Gearbox") void ShiftUp();
	UFUNCTION(BlueprintCallable, Category = "Gearbox") void ShiftDown();

	/** Turbo boost state 0..1 (for HUD / sound) */
	UFUNCTION(BlueprintPure, Category = "Engine") float GetBoost() const { return Boost; }

protected:
	virtual float FilterThrottle(float DriverInput, float Delta) override;

	/** EJ207 peak torque, N*m (373 @ 4000 rpm) */
	static constexpr float PeakTorque = 373.0f;

	/** Share of torque available before the IHI VF30 spools (transient only). */
	UPROPERTY(EditAnywhere, Category = "Engine") float OffBoostTorqueFraction = 0.55f;
	/** Spool time constant at low / high rpm, seconds */
	UPROPERTY(EditAnywhere, Category = "Engine") float SpoolTimeLowRPM = 1.1f;
	UPROPERTY(EditAnywhere, Category = "Engine") float SpoolTimeHighRPM = 0.35f;
	UPROPERTY(EditAnywhere, Category = "Engine") float BoostDecayTime = 0.15f;

	/** Chaos has no clutch (engine rpm is tied to the wheels). Below this rpm in 1st/reverse we
	 *  model a slipping clutch: the wheels get the torque the engine makes at the slip rpm. */
	UPROPERTY(EditAnywhere, Category = "Engine") float ClutchSlipRPM = 4000.0f;

	/** Drive-wheel slip ratio allowed before traction control cuts throttle */
	UPROPERTY(EditAnywhere, Category = "Assists") float TCSlipSport = 0.18f;
	UPROPERTY(EditAnywhere, Category = "Assists") float TCSlipFull = 0.08f;

private:
	void UpdateEngine(float Delta);
	int32 GearForShift() const;
	void RequestGear(int32 From, int32 To);
	double LastManualShiftTime = -100.0;
	void EnsureAssistInput();
	void ToggleAutoShiftInput() { SetAutoShift(!bAutoShift); }
	void ToggleABSInput() { SetABS(!bABS); }

	float Boost = 0.0f;
	float AppliedMaxTorque = PeakTorque;
	float TCCut = 0.0f;
	float LastFilteredThrottle = 0.0f;

	// visible car (placeholder template sports car until the STi model exists)
	UPROPERTY(VisibleAnywhere, Category = "Audio") TObjectPtr<class UStiEngineAudio> EngineAudio;
	UPROPERTY(VisibleAnywhere, Category = "Visual") TObjectPtr<UStaticMeshComponent> BodyMesh;
	UPROPERTY(VisibleAnywhere, Category = "Visual") TObjectPtr<UStaticMeshComponent> GlassMesh;
	UPROPERTY(VisibleAnywhere, Category = "Visual") TObjectPtr<UStaticMeshComponent> WheelMeshes[4];
	UPROPERTY(VisibleAnywhere, Category = "Visual") TObjectPtr<UStaticMeshComponent> CaliperMeshes[4];
	/** Wheel centres at rest in mesh space (template bones + the STi offsets). */
	FVector WheelRestPositions[4];
	bool bLoggedSuspension = false;
	void UpdateWheelVisuals();

	// home-built wheel: input override and force feedback (CambridgeWheelSubsystem)
	void ApplyWheelInput(class UCambridgeWheelSubsystem& Wheel);
	float ComputeForceFeedback(const class UCambridgeWheelSubsystem& Wheel, float Delta);
	float LastRimDeg = 0.0f;
	float PrevRimDeg = 0.0f;
	float LastSuspension[2] = { 0.0f, 0.0f };
	double LastWheelLog = 0.0;

	UPROPERTY(Transient) TObjectPtr<UInputMappingContext> AssistMapping;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ShiftUpAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ShiftDownAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> CycleTCAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ToggleAutoShiftAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ToggleABSAction;
};
