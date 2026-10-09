// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class CambridgeRacer : ModuleRules
{
	public CambridgeRacer(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"ChaosVehicles",
			"PhysicsCore",
			"UMG",
			"Slate",
			"Json",
			"CambridgeUI"     // the UI kit and the launch menu widget (its own module: it is the loading screen)
		});

		PublicIncludePaths.AddRange(new string[] {
			"CambridgeRacer",
			"CambridgeRacer/SportsCar",
			"CambridgeRacer/OffroadCar",
			"CambridgeRacer/Impreza",
			"CambridgeRacer/Variant_OffRoad",
			"CambridgeRacer/Variant_TimeTrial",
			"CambridgeRacer/Variant_TimeTrial/UI"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { "RenderCore", "RHI", "SlateCore", "AudioMixer", "ProceduralMeshComponent", "ImageCore", "MoviePlayer" });   // frame timing (ShotTour, FPS overlay), Slate menu; MoviePlayer: the launch menu as the loading screen

		// "Luna Glass" UI (CambridgeUIStyle, module CambridgeUI): its loose fonts and brushes are staged there.

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });

		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
