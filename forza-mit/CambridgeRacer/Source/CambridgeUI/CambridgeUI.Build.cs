using UnrealBuildTool;

// The game's Slate UI kit ("Luna Glass": CambridgeUIStyle) and the launch menu widget. Loaded in the PreLoadingScreen
// phase (CambridgeRacer.uproject) so the launch menu can be the engine's loading screen from the moment the game
// window appears; nothing here uses UObjects. The game module (CambridgeRacer) depends on it.
public class CambridgeUI : ModuleRules
{
	public CambridgeUI(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "SlateCore", "Slate", "InputCore" });   // (CoreUObject: Slate fonts and brushes reference UObjects)
		PrivateDependencyModuleNames.AddRange(new string[] { "MoviePlayer", "ApplicationCore" });

		// loose fonts and brushes read from <Project>/UI at runtime (brushes: tools/ui/make_ui_assets.py and
		// make_launch_assets.py, gitignored); stage both folders in packaged builds
		RuntimeDependencies.Add("$(ProjectDir)/UI/Fonts/...", StagedFileType.UFS);
		RuntimeDependencies.Add("$(ProjectDir)/UI/Generated/...", StagedFileType.UFS);
	}
}
