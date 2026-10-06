#include "ImprezaSTiWheels.h"

// Shared by both axles: 225/45ZR17 Bridgestone Potenza RE040 on 17x7.5 alloys.
//   radius   = (17 * 25.4 / 2) + 0.45 * 225 = 317 mm unloaded
//   mass     ~ 21 kg wheel + tyre
// Suspension: MacPherson struts. Chaos SpringRate is effectively N/cm (it is scaled by MToCm
// and applied to a cm displacement), so owner-measured 35 / 30 N/mm springs -> 350 / 300.
// Grip values (FrictionForceMultiplier, CorneringStiffness) are tuned against the skidpad
// test in DriveTestSubsystem, not taken from a datasheet.
static void SetupCommon(UChaosVehicleWheel* W)
{
	W->WheelRadius = 31.7f;
	W->WheelWidth = 22.5f;
	W->WheelMass = 21.0f;

	W->bABSEnabled = true;               // the real car had ABS with EBD
	W->bTractionControlEnabled = false;  // no TCS on the real car; our assist lives in AImprezaSTi

	W->SuspensionMaxRaise = 8.0f;
	W->SuspensionMaxDrop = 8.0f;
	W->SuspensionDampingRatio = 0.45f;
	W->SpringPreload = 50.0f;
	W->WheelLoadRatio = 0.5f;
}

UImprezaSTiWheelFront::UImprezaSTiWheelFront()
{
	SetupCommon(this);
	AxleType = EAxleType::Front;
	bAffectedBySteering = true;
	bAffectedByHandbrake = false;
	MaxSteerAngle = 38.0f;               // real car ~33 deg (mean at full lock); more lock for playability

	SpringRate = 350.0f;
	RollbarScaling = 0.30f;

	// 4-pot Brembo, 325 mm ventilated disc; ~62 % front bias.
	// Chaos tyres give more grip under braking than in cornering (one friction value for both),
	// so the brakes are sized to make a straight-line stop torque-limited at ~1.05 g, which gives
	// the real car's ~37 m from 100 km/h. Combined braking + cornering still hits the grip limit (ABS).
	MaxBrakeTorque = 2000.0f;            // bigger than stock for playability (stock sizing was 1400)

	// tuned: skidpad 0.86 g @ 50 km/h, 0.94 g @ 80 km/h (front-limited, mild understeer)
	FrictionForceMultiplier = 2.45f;
	CorneringStiffness = 1000.0f;
}

UImprezaSTiWheelRear::UImprezaSTiWheelRear()
{
	SetupCommon(this);
	AxleType = EAxleType::Rear;
	bAffectedBySteering = false;
	MaxSteerAngle = 0.0f;
	bAffectedByHandbrake = true;

	SpringRate = 300.0f;
	RollbarScaling = 0.20f;

	// 2-pot Brembo, 315 mm ventilated disc (see front wheel note on brake sizing)
	MaxBrakeTorque = 1200.0f;            // stock sizing was 850
	MaxHandBrakeTorque = 3000.0f;        // stronger than stock: handbrake turns are part of the fun

	FrictionForceMultiplier = 2.1f;
	CorneringStiffness = 1000.0f;
}
