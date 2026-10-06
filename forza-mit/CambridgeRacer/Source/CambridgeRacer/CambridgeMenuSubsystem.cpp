#include "CambridgeMenuSubsystem.h"

#include "CambridgeGameUserSettings.h"
#include "CambridgeUIStyle.h"
#include "ImprezaSTi.h"
#include "CambridgeWheelSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "MinimapSubsystem.h"
#include "ComponentRecreateRenderStateContext.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "RHI.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBackgroundBlur.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SGridPanel.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "CambridgeMenu"

namespace
{
	/** One menu line: label, list of named options, and how to read / write the current one. */
	struct FSettingRow
	{
		FText Label;
		TArray<FText> Options;
		TFunction<int32()> Get;
		TFunction<void(int32)> Set;
		int32 NumSelectable = -1;   // options past this index are display-only ("Custom")
		TFunction<FText()> Display; // optional live value text (status rows)
		TFunction<void()> Action;   // optional: Right / Enter / > runs this instead of changing a value
		int32 Tab = 0;              // 0 graphics, 1 driving assists, 2 calibration (3 controls: a fixed table)
	};

	const FText TabNames[] = { LOCTEXT("TabGraphics", "Graphics"), LOCTEXT("TabAssists", "Driving Assists"), LOCTEXT("TabCalibration", "Calibration"),
		LOCTEXT("TabControls", "Controls") };
	constexpr int32 NumTabs = 4;
	constexpr int32 ControlsTab = 3;

	/** The controls page: action, keyboard, gamepad, wheel. Keep in step with ACambridgeRacerPlayerController's
	 *  scheme, AImprezaSTi::EnsureAssistInput, UTimeTrialSubsystem::OnKeyDown and docs/wheel_protocol.md. */
	struct FControlLine { const TCHAR* Action; const TCHAR* Keyboard; const TCHAR* Gamepad; const TCHAR* Wheel; };
	const FControlLine ControlLines[] = {
		{ TEXT("Steer"),                  TEXT("A / D, Left / Right"), TEXT("Left stick"),       TEXT("Rim") },
		{ TEXT("Throttle"),               TEXT("W / Up"),              TEXT("RT"),               TEXT("Right pedal") },
		{ TEXT("Brake / reverse"),        TEXT("S / Down"),            TEXT("LT"),               TEXT("Left pedal") },
		{ TEXT("Handbrake"),              TEXT("Space"),               TEXT("A"),                TEXT("-") },
		{ TEXT("Shift up / down"),        TEXT("E / Q"),               TEXT("B / X"),            TEXT("Right / left paddle") },
		{ TEXT("Reverse (manual)"),       TEXT("Q past N"),            TEXT("X past N"),         TEXT("Left paddle past N") },
		{ TEXT("Auto / manual gears"),    TEXT("G"),                   TEXT("-"),                TEXT("Paddle = manual") },
		{ TEXT("Traction control / ABS"), TEXT("T / B"),               TEXT("Menu: assists"),    TEXT("Menu: assists") },
		{ TEXT("Camera / look"),          TEXT("Tab / mouse"),         TEXT("RB / right stick"), TEXT("-") },
		{ TEXT("Start an event"),         TEXT("Enter in the box"),    TEXT("A, stopped in box"), TEXT("Start button") },
		{ TEXT("Reset / back on track"),  TEXT("R"),                   TEXT("Y / D-pad down"),   TEXT("Start (tap)") },
		{ TEXT("Restart event"),          TEXT("Hold R"),              TEXT("Hold Y / D-pad down"), TEXT("Hold start") },
		{ TEXT("Leave event"),            TEXT("Hold Backspace"),      TEXT("Hold D-pad up"),    TEXT("-") },
		{ TEXT("Full map"),               TEXT("M"),                   TEXT("View"),             TEXT("-") },
		{ TEXT("Settings / back"),        TEXT("Esc / Backspace"),     TEXT("Menu / B"),         TEXT("-") },
		{ TEXT("In this menu"),           TEXT("Tab, arrows"),         TEXT("LB RB, D-pad"),     TEXT("Paddles, rim, start") },
	};

	TArray<FText> Levels() { return { LOCTEXT("Low", "Low"), LOCTEXT("Medium", "Medium"), LOCTEXT("High", "High"), LOCTEXT("Epic", "Epic") }; }
	TArray<FText> OffOn() { return { LOCTEXT("Off", "Off"), LOCTEXT("On", "On") }; }

	TArray<FSettingRow> BuildRows()
	{
		UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get();
		TArray<FSettingRow> Rows;
		auto Quality = [&](FText Label, int32 (UGameUserSettings::*Getter)() const, void (UGameUserSettings::*Setter)(int32))
		{
			Rows.Add({ Label, Levels(), [S, Getter] { return (S->*Getter)(); }, [S, Setter](int32 V) { (S->*Setter)(V); } });
		};

		TArray<FText> Presets = Levels();
		Presets.Add(LOCTEXT("Custom", "Custom"));
		Rows.Add({ LOCTEXT("Preset", "Quality preset"), Presets,
			[S] { const int32 P = S->GetPreset(); return P < 0 ? 4 : P; }, [S](int32 V) { S->ApplyPreset(V); }, 4 });

		static const int32 Scales[] = { 50, 60, 67, 75, 83, 100 };
		TArray<FText> ScaleNames;
		for (int32 Pct : Scales)
		{
			// (of 1080p: a bigger window renders that many pixels and upscales, CambridgeGameUserSettings)
			ScaleNames.Add(FText::FromString(FString::Printf(TEXT("%d %%  (%dp)"), Pct, FMath::RoundToInt(10.8f * Pct))));
		}
		Rows.Add({ LOCTEXT("ResScale", "Resolution scale"), ScaleNames,
			[S] {
				float Norm, Value, Min, Max;
				S->GetResolutionScaleInformationEx(Norm, Value, Min, Max);
				int32 Best = 0;
				for (int32 i = 0; i < UE_ARRAY_COUNT(Scales); ++i)
				{
					if (FMath::Abs(Scales[i] - Value) < FMath::Abs(Scales[Best] - Value)) { Best = i; }
				}
				return Best;
			},
			[S](int32 V) { S->SetResolutionScaleValueEx(float(Scales[V])); } });

		Quality(LOCTEXT("Shadows", "Shadows"), &UGameUserSettings::GetShadowQuality, &UGameUserSettings::SetShadowQuality);
		Quality(LOCTEXT("GI", "Global illumination"), &UGameUserSettings::GetGlobalIlluminationQuality, &UGameUserSettings::SetGlobalIlluminationQuality);
		Quality(LOCTEXT("Reflections", "Reflections"), &UGameUserSettings::GetReflectionQuality, &UGameUserSettings::SetReflectionQuality);
		Quality(LOCTEXT("ViewDistance", "View distance"), &UGameUserSettings::GetViewDistanceQuality, &UGameUserSettings::SetViewDistanceQuality);
		Quality(LOCTEXT("PostProcess", "Post-processing"), &UGameUserSettings::GetPostProcessingQuality, &UGameUserSettings::SetPostProcessingQuality);
		Quality(LOCTEXT("Effects", "Effects"), &UGameUserSettings::GetVisualEffectQuality, &UGameUserSettings::SetVisualEffectQuality);
		Quality(LOCTEXT("Foliage", "Foliage"), &UGameUserSettings::GetFoliageQuality, &UGameUserSettings::SetFoliageQuality);
		Quality(LOCTEXT("Shading", "Shading"), &UGameUserSettings::GetShadingQuality, &UGameUserSettings::SetShadingQuality);
		Quality(LOCTEXT("AA", "Anti-aliasing"), &UGameUserSettings::GetAntiAliasingQuality, &UGameUserSettings::SetAntiAliasingQuality);
		Quality(LOCTEXT("Textures", "Textures"), &UGameUserSettings::GetTextureQuality, &UGameUserSettings::SetTextureQuality);

		Rows.Add({ LOCTEXT("Clouds", "Volumetric clouds"), OffOn(),
			[S] { return S->bVolumetricClouds ? 1 : 0; }, [S](int32 V) { S->bVolumetricClouds = V == 1; } });
		Rows.Add({ LOCTEXT("Trees", "Tree draw distance"), { LOCTEXT("T300", "300 m"), LOCTEXT("T400", "400 m"), LOCTEXT("T700", "700 m") },
			[S] { return S->TreeDistance; }, [S](int32 V) { S->TreeDistance = V; } });
		Rows.Add({ LOCTEXT("Geometry", "Geometry detail"), { LOCTEXT("GLow", "Low"), LOCTEXT("GMed", "Medium"), LOCTEXT("GHigh", "High") },
			[S] { return S->GeometryDetail; }, [S](int32 V) { S->GeometryDetail = V; } });

		Rows.Add({ LOCTEXT("VSync", "VSync"), OffOn(),
			[S] { return S->IsVSyncEnabled() ? 1 : 0; }, [S](int32 V) { S->SetVSyncEnabled(V == 1); } });
		static const float Limits[] = { 0.0f, 30.0f, 60.0f, 120.0f };
		Rows.Add({ LOCTEXT("FPSLimit", "Frame rate limit"), { LOCTEXT("Unlimited", "Unlimited"), LOCTEXT("L30", "30"), LOCTEXT("L60", "60"), LOCTEXT("L120", "120") },
			[S] {
				for (int32 i = 0; i < UE_ARRAY_COUNT(Limits); ++i) { if (FMath::IsNearlyEqual(S->GetFrameRateLimit(), Limits[i])) { return i; } }
				return 0;
			},
			[S](int32 V) { S->SetFrameRateLimit(Limits[V]); } });
		Rows.Add({ LOCTEXT("ShowFPS", "Show FPS"), OffOn(),
			[S] { return S->bShowFPS ? 1 : 0; }, [S](int32 V) { S->bShowFPS = V == 1; } });

		// --- driving assists (the car applies them; without a car they are just saved) ---
		const int32 AssistsStart = Rows.Num();
		auto Car = [] { return GEngine && GEngine->GameViewport && GEngine->GameViewport->GetWorld()
			? Cast<AImprezaSTi>(UGameplayStatics::GetPlayerPawn(GEngine->GameViewport->GetWorld(), 0)) : nullptr; };
		Rows.Add({ LOCTEXT("Gearbox", "Gearbox"), { LOCTEXT("Manual", "Manual"), LOCTEXT("Automatic", "Automatic") },
			[S] { return S->bAutomaticGearbox ? 1 : 0; },
			[S, Car](int32 V) { if (AImprezaSTi* C = Car()) { C->SetAutoShift(V == 1); } else { S->bAutomaticGearbox = V == 1; } } });
		Rows.Add({ LOCTEXT("TC", "Traction control"), { LOCTEXT("TCOff", "Off"), LOCTEXT("TCSport", "Sport"), LOCTEXT("TCFull", "Full") },
			[S] { return FMath::Clamp(S->TractionControlMode, 0, 2); },
			[S, Car](int32 V) { if (AImprezaSTi* C = Car()) { C->SetTractionControl((ETractionControlMode)V); } else { S->TractionControlMode = V; } } });
		Rows.Add({ LOCTEXT("ABS", "ABS"), OffOn(),
			[S] { return S->bABSEnabled ? 1 : 0; },
			[S, Car](int32 V) { if (AImprezaSTi* C = Car()) { C->SetABS(V == 1); } else { S->bABSEnabled = V == 1; } } });
		Rows.Add({ LOCTEXT("Line", "Racing line"), { LOCTEXT("LineOff", "Off"), LOCTEXT("LineCorners", "Corners Only"), LOCTEXT("LineFull", "Full") },
			[S] { return FMath::Clamp(S->RacingLineMode, 0, 2); }, [S](int32 V) { S->RacingLineMode = V; } });
		Rows.Add({ LOCTEXT("Minimap", "Minimap"), OffOn(),
			[S] { return S->bShowMinimap ? 1 : 0; }, [S](int32 V) { S->bShowMinimap = V == 1; } });
		for (int32 i = AssistsStart; i < Rows.Num(); ++i) { Rows[i].Tab = 1; }

		// the home-built wheel (CambridgeWheelSubsystem)
		const int32 CalibrationStart = Rows.Num();
		UCambridgeWheelSubsystem* W = GEngine && GEngine->GameViewport && GEngine->GameViewport->GetGameInstance()
			? GEngine->GameViewport->GetGameInstance()->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr;
		if (W)
		{
			FSettingRow Status{ LOCTEXT("Wheel", "Wheel"), { FText::GetEmpty() }, [] { return 0; }, [](int32) {} };
			Status.Display = [W] { return FText::FromString(W->GetStatusText()); };
			Rows.Add(Status);
			static const int32 Ranges[] = { 360, 450, 540, 720, 900 };
			TArray<FText> RangeNames;
			for (int32 R : Ranges) { RangeNames.Add(FText::FromString(FString::Printf(TEXT("%d deg"), R))); }
			Rows.Add({ LOCTEXT("WheelRange", "Wheel rotation"), RangeNames,
				[W] { int32 Best = 0; for (int32 i = 0; i < UE_ARRAY_COUNT(Ranges); ++i) { if (FMath::Abs(Ranges[i] - W->RotationRangeDeg) < FMath::Abs(Ranges[Best] - W->RotationRangeDeg)) { Best = i; } } return Best; },
				[W](int32 V) { W->RotationRangeDeg = float(Ranges[V]); } });
			TArray<FText> Pct;
			for (int32 i = 0; i <= 10; ++i) { Pct.Add(FText::FromString(FString::Printf(TEXT("%d %%"), i * 10))); }
			Rows.Add({ LOCTEXT("FFB", "Force feedback"), Pct,
				[W] { return FMath::RoundToInt(W->ForceFeedbackStrength * 10.0f); }, [W](int32 V) { W->ForceFeedbackStrength = V / 10.0f; } });
			FSettingRow Centre{ LOCTEXT("Centre", "Centre wheel"), { LOCTEXT("CentreGo", "press >") }, [] { return 0; }, [](int32) {} };
			Centre.Action = [W] { W->CentreWheel(); };
			Rows.Add(Centre);
			FSettingRow Pedals{ LOCTEXT("Pedals", "Recalibrate pedals"), { LOCTEXT("PedalsGo", "press >") }, [] { return 0; }, [](int32) {} };
			Pedals.Action = [W] { W->ResetPedalCalibration(); };
			Rows.Add(Pedals);
		}
		for (int32 i = CalibrationStart; i < Rows.Num(); ++i) { Rows[i].Tab = 2; }
		return Rows;
	}
}

class SCambridgeMenu : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCambridgeMenu) {}
		SLATE_EVENT(FSimpleDelegate, OnClose)
		SLATE_ATTRIBUTE(FText, TrayText)
	SLATE_END_ARGS()

	// "Luna Glass" look (CambridgeUIStyle): an XP window with IE tabs over a blurred, dimmed game,
	// an XP taskbar at the bottom. Rows, tabs, keys and settings logic are unchanged.
	void Construct(const FArguments& InArgs)
	{
		namespace CUI = CambridgeUI;
		OnClose = InArgs._OnClose;
		Rows = BuildRows();
		int32 MaxRows = 1;
		for (int32 t = 0; t < NumTabs; ++t)
		{
			int32 N = 0;
			for (const FSettingRow& R : Rows) { N += R.Tab == t ? 1 : 0; }
			MaxRows = FMath::Max(MaxRows, N);
		}
		MaxRows = FMath::Max(MaxRows, int32(UE_ARRAY_COUNT(ControlLines)));
		static const FName TabIcons[] = { FName(TEXT("icon_monitor")), FName(TEXT("icon_car")), FName(TEXT("icon_wheel")), FName(TEXT("icon_info")) };
		TSharedRef<SHorizontalBox> TabBar = SNew(SHorizontalBox);
		for (int32 t = 0; t < NumTabs; ++t)
		{
			TabBar->AddSlot().AutoWidth().VAlign(VAlign_Bottom).Padding(t == 0 ? 6.0f : 2.0f, 0, 0, 0)
			[
				// inactive tabs stop 1 px above the panel so its top border shows under them
				SNew(SBox)
				.Padding_Lambda([this, t]() { return t == Tab ? FMargin(0) : FMargin(0, 0, 0, 1); })
				[
					CUI::MakeXPTab(TabNames[t], TabIcons[t], TAttribute<bool>::CreateLambda([this, t]() { return t == Tab; }), [this, t]() { SetTab(t); })
				]
			];
		}
		auto Close = FOnClicked::CreateLambda([this]()
		{
			OnClose.ExecuteIfBound();
			return FReply::Handled();
		});
		auto Keys = [](std::initializer_list<const TCHAR*> List)
		{
			TArray<FText> Out;
			for (const TCHAR* K : List) { Out.Add(FText::FromString(K)); }
			return Out;
		};
		TSharedRef<SWidget> Footer = SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 20, 0)
			[
				CUI::MakeKeyHint(Keys({ TEXT("TAB") }), LOCTEXT("HintTab", "Section"), false)
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 20, 0)
			[
				CUI::MakeKeyHint(Keys({ TEXT("^"), TEXT("v") }), LOCTEXT("HintSelect", "Select"), false)
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 20, 0)
			[
				CUI::MakeKeyHint(Keys({ TEXT("<"), TEXT(">") }), LOCTEXT("HintChange", "Change"), false)
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				CUI::MakeKeyHint(Keys({ TEXT("ESC") }), LOCTEXT("HintClose", "Close"), false)
			]
			+ SHorizontalBox::Slot().FillWidth(1.0f)[ SNullWidget::NullWidget ]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				CUI::MakeXPButton(LOCTEXT("Resume", "Resume"), Close, true)
			];
		TSharedRef<SWidget> Content = SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 0)
			[
				// the tab strip is drawn over the panel's top edge so the active tab joins it
				SNew(SOverlay)
				+ SOverlay::Slot().Padding(0, 34, 0, 0)
				[
					CUI::MakeXPPanel(SNew(SBox).MinDesiredHeight(MaxRows * 32.0f + 4.0f)[ SAssignNew(ListHost, SBox) ], FMargin(8, 10))
				]
				+ SOverlay::Slot().VAlign(VAlign_Top)
				[
					SNew(SBox).HeightOverride(35)[ TabBar ]
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0, 14, 0, 2)
			[
				Footer
			];
		TSharedRef<SWidget> TaskButton = SNew(SBox)
			.HAlign(HAlign_Left)
			[
				SNew(SBorder)
				.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
				.BorderBackgroundColor(FLinearColor(FColor(0x1e, 0x52, 0xae)))
				.Padding(FMargin(10, 3, 48, 3))
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)[ SNew(SImage).Image(CUI::Brush("icon_cog")) ]
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)[ SNew(STextBlock).TextStyle(&CUI::Text("Tray")).Text(LOCTEXT("TaskSettings", "Settings")) ]
				]
			];
		ChildSlot
		[
			SNew(SOverlay)
			+ SOverlay::Slot()
			[
				SNew(SBackgroundBlur)
				.BlurStrength(8.0f)
				.Padding(0)
				[
					SNew(SImage).Image(FCoreStyle::Get().GetBrush("WhiteBrush")).ColorAndOpacity(FSlateColor(FLinearColor(0.0f, 0.0f, 0.0f, 0.35f)))
				]
			]
			+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center).Padding(0, 0, 0, 40)
			[
				SNew(SBox).WidthOverride(780 + 32)
				[
					CUI::MakeXPWindow(LOCTEXT("Title", "Settings"), Content, TEXT("icon_cog"), Close)
				]
			]
			+ SOverlay::Slot().VAlign(VAlign_Bottom)
			[
				CUI::MakeTaskbar(LOCTEXT("StartLabel", "forza-MIT"), TaskButton, InArgs._TrayText)
			]
		];
		SetTab(0);
	}

	virtual bool SupportsKeyboardFocus() const override { return true; }

	void ShowTab(int32 NewTab) { SetTab(FMath::Clamp(NewTab, 0, NumTabs - 1)); }

	virtual FReply OnKeyDown(const FGeometry&, const FKeyEvent& Event) override
	{
		const FKey K = Event.GetKey();
		const int32 N = Visible.Num();
		if (K == EKeys::Gamepad_FaceButton_Right || K == EKeys::BackSpace)
		{
			OnClose.ExecuteIfBound();     // back
		}
		else if (K == EKeys::Tab || K == EKeys::Gamepad_RightShoulder)
		{
			SetTab((Tab + (Event.IsShiftDown() ? NumTabs - 1 : 1)) % NumTabs);
		}
		else if (K == EKeys::Gamepad_LeftShoulder)
		{
			SetTab((Tab + NumTabs - 1) % NumTabs);
		}
		else if (N == 0)
		{
			return FReply::Unhandled();
		}
		else if (K == EKeys::Up || K == EKeys::Gamepad_DPad_Up || K == EKeys::W)
		{
			Selected = (Selected + N - 1) % N;
		}
		else if (K == EKeys::Down || K == EKeys::Gamepad_DPad_Down || K == EKeys::S)
		{
			Selected = (Selected + 1) % N;
		}
		else if (K == EKeys::Left || K == EKeys::Gamepad_DPad_Left || K == EKeys::A)
		{
			Change(Visible[Selected], -1);
		}
		else if (K == EKeys::Right || K == EKeys::Gamepad_DPad_Right || K == EKeys::D || K == EKeys::Enter || K == EKeys::Gamepad_FaceButton_Bottom)
		{
			Change(Visible[Selected], +1);
		}
		else
		{
			return FReply::Unhandled();
		}
		return FReply::Handled();
	}

private:
	void SetTab(int32 NewTab)
	{
		Tab = NewTab;
		Selected = 0;
		Visible.Reset();
		TSharedRef<SVerticalBox> List = SNew(SVerticalBox);
		for (int32 i = 0; i < Rows.Num(); ++i)
		{
			if (Rows[i].Tab != Tab)
			{
				continue;
			}
			const int32 V = Visible.Add(i);
			auto RowColour = [this, V]() { return CambridgeUI::RowTextColor(V == Selected); };
			TSharedRef<SWidget> RowContent = SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
				[
					SNew(STextBlock).TextStyle(&CambridgeUI::Text("Label")).ColorAndOpacity_Lambda(RowColour).Text(Rows[i].Label)
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					CambridgeUI::MakeSpinButton(false, FOnClicked::CreateLambda([this, i, V]() { Selected = V; Change(i, -1); return FReply::Handled(); }))
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(SBox).WidthOverride(190).HAlign(HAlign_Center)
					[
						SNew(STextBlock).TextStyle(&CambridgeUI::Text("Value")).ColorAndOpacity_Lambda(RowColour)
						.Text_Lambda([this, i]
						{
							if (Rows[i].Display) { return Rows[i].Display(); }
							const int32 Value = Rows[i].Get();
							return Rows[i].Options.IsValidIndex(Value) ? Rows[i].Options[Value] : FText::GetEmpty();
						})
					]
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					CambridgeUI::MakeSpinButton(true, FOnClicked::CreateLambda([this, i, V]() { Selected = V; Change(i, +1); return FReply::Handled(); }))
				];
			List->AddSlot().AutoHeight()
			[
				SNew(SBox).HeightOverride(32)
				[
					CambridgeUI::MakeListRow(RowContent, TAttribute<bool>::CreateLambda([this, V]() { return V == Selected; }), [this, V]() { Selected = V; })
				]
			];
		}
		if (Tab == ControlsTab)
		{
			ListHost->SetContent(MakeControlsTable());
			return;
		}
		if (Visible.Num() == 0)
		{
			List->AddSlot().AutoHeight().Padding(14, 8)
			[
				SNew(STextBlock).TextStyle(&CambridgeUI::Text("BodyDim")).Text(LOCTEXT("NoWheel", "No wheel support on this platform."))
			];
		}
		ListHost->SetContent(List);
	}

	TSharedRef<SWidget> MakeControlsTable() const
	{
		TSharedRef<SGridPanel> Grid = SNew(SGridPanel).FillColumn(0, 1.0f);
		auto Cell = [&Grid](int32 Col, int32 Row, const TCHAR* Text, bool bHeader)
		{
			Grid->AddSlot(Col, Row).Padding(6, bHeader ? 2 : 5, 10, bHeader ? 6 : 5).VAlign(VAlign_Center)
			[
				SNew(STextBlock).TextStyle(&CambridgeUI::Text(bHeader ? "Value" : (Col == 0 ? "Label" : "Body"))).Text(FText::FromString(Text))
			];
		};
		Cell(0, 0, TEXT(""), true);
		Cell(1, 0, TEXT("Keyboard"), true);
		Cell(2, 0, TEXT("Gamepad"), true);
		Cell(3, 0, TEXT("Wheel"), true);
		for (int32 i = 0; i < UE_ARRAY_COUNT(ControlLines); ++i)
		{
			const FControlLine& L = ControlLines[i];
			Cell(0, i + 1, L.Action, false);
			Cell(1, i + 1, L.Keyboard, false);
			Cell(2, i + 1, L.Gamepad, false);
			Cell(3, i + 1, L.Wheel, false);
		}
		return Grid;
	}

	void Change(int32 Row, int32 Delta)
	{
		const FSettingRow& R = Rows[Row];
		if (R.Action)
		{
			if (Delta > 0) { R.Action(); }
			return;
		}
		const int32 Last = (R.NumSelectable > 0 ? R.NumSelectable : R.Options.Num()) - 1;
		const int32 Current = FMath::Min(R.Get(), Last);
		const int32 Next = FMath::Clamp(Current + Delta, 0, Last);
		if (Next != R.Get())
		{
			R.Set(Next);
			if (UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
			{
				// not ApplySettings(): that also re-applies the saved window size / mode (a menu click resized the
				// window) and writes the ini on every press. Everything in this menu is a non-resolution setting;
				// the settings are saved when the menu closes
				FGlobalComponentRecreateRenderStateContext Recreate;    // one render-state rebuild for a preset change
				S->ApplyNonResolutionSettings();
			}
		}
	}

	FSimpleDelegate OnClose;
	TArray<FSettingRow> Rows;
	TArray<int32> Visible;      // row indices of the current tab
	TSharedPtr<SBox> ListHost;
	int32 Tab = 0;
	int32 Selected = 0;
};

class FCambridgeMenuInput : public IInputProcessor
{
public:
	explicit FCambridgeMenuInput(UCambridgeMenuSubsystem* InOwner) : Owner(InOwner) {}

	virtual void Tick(const float DeltaTime, FSlateApplication&, TSharedRef<ICursor>) override
	{
		if (Owner.IsValid())
		{
			Owner->Tick(DeltaTime);
		}
	}

	virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
	{
		const FKey K = Event.GetKey();
		if ((K == EKeys::Escape || K == EKeys::Gamepad_Special_Right) && !Event.IsRepeat() && Owner.IsValid())
		{
			Owner->ToggleMenu();
			return true;
		}
		return false;
	}

	virtual const TCHAR* GetDebugName() const override { return TEXT("CambridgeMenuInput"); }

private:
	TWeakObjectPtr<UCambridgeMenuSubsystem> Owner;
};

bool UCambridgeMenuSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return !IsRunningCommandlet() && Super::ShouldCreateSubsystem(Outer);
}

void UCambridgeMenuSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	// make sure the saved (or first-run High) graphics settings are in effect in every launch mode
	if (UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
	{
		S->ApplyNonResolutionSettings();
	}
	// automated runs keep clean screenshots and no pause menu
	const TCHAR* Cmd = FCommandLine::Get();
	bEnabled = !FParse::Param(Cmd, TEXT("nullrhi")) && !FCString::Strifind(Cmd, TEXT("-ShotTour")) && !FCString::Strifind(Cmd, TEXT("-DriveTest"));
	// register the UI style (fonts, brushes) now rather than mid-frame when the HUD or menu is first built
	if (FSlateApplication::IsInitialized() && !FParse::Param(Cmd, TEXT("nullrhi")))
	{
		FCambridgeUIStyle::Initialize();
	}
	if (bEnabled && FSlateApplication::IsInitialized())
	{
		Input = MakeShared<FCambridgeMenuInput>(this);
		FSlateApplication::Get().RegisterInputPreProcessor(Input);
		// Cmd-Tab / clicking another app pauses the game behind the settings menu (a car left driving in the
		// background crashes; the wheel's force feedback stops with the pause)
		ActivationHandle = FSlateApplication::Get().OnApplicationActivationStateChanged().AddUObject(this, &UCambridgeMenuSubsystem::OnApplicationActivationChanged);
	}
}

void UCambridgeMenuSubsystem::OnApplicationActivationChanged(bool bActive)
{
	if (bActive || IsMenuOpen())
	{
		return;
	}
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	UWorld* World = Viewport ? Viewport->GetWorld() : nullptr;
	if (!World || !World->IsGameWorld() || World->IsPaused())
	{
		return;         // (the full map already pauses the game)
	}
	const UMinimapSubsystem* Map = World->GetSubsystem<UMinimapSubsystem>();
	if (Map && Map->IsFullMapOpen())
	{
		return;
	}
	OpenMenu();
}

void UCambridgeMenuSubsystem::Deinitialize()
{
	if (Input.IsValid() && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().UnregisterInputPreProcessor(Input);
		FSlateApplication::Get().OnApplicationActivationStateChanged().Remove(ActivationHandle);
	}
	Input.Reset();
	CloseMenu();
	SetOverlayVisible(false);
	// quitting: keep what the T / G / B keys changed (the menu saves on close; automated runs save nothing)
	if (UCambridgeGameUserSettings* S = bEnabled ? UCambridgeGameUserSettings::Get() : nullptr)
	{
		S->SaveSettings();
	}
	Super::Deinitialize();
}

void UCambridgeMenuSubsystem::Tick(float DeltaTime)
{
	const double Alpha = 0.05;   // ~20-frame exponential average
	FrameMs = FMath::Lerp(FrameMs, double(DeltaTime) * 1000.0, FrameMs > 0.0 ? Alpha : 1.0);
	GpuMs = FMath::Lerp(GpuMs, double(FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles())), GpuMs > 0.0 ? Alpha : 1.0);
	const UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get();
	SetOverlayVisible(S && S->bShowFPS);
	TickWheelNavigation();
}

void UCambridgeMenuSubsystem::TickWheelNavigation()
{
	// the home-built wheel drives the open menu: paddles = up / down, rim turned past 50 deg = change the
	// value (left / right), start = next section. Esc / the gamepad still work as usual
	UCambridgeWheelSubsystem* W = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr;
	if (!IsMenuOpen() || !W || !W->IsActive())
	{
		bRimArmed = false;
		return;
	}
	TSharedPtr<SWidget> Menu = MenuWidget;
	auto Press = [&Menu](const FKey& Key)
	{
		Menu->OnKeyDown(FGeometry(), FKeyEvent(Key, FModifierKeysState(), 0, false, 0, 0));
	};
	const bool bUp = W->ConsumeDownshift();
	const bool bDown = W->ConsumeUpshift();
	const bool bStart = W->ConsumeStart();
	if (bUp && !bDown) { Press(EKeys::Up); }
	if (bDown && !bUp) { Press(EKeys::Down); }
	if (bStart) { Press(EKeys::Tab); }
	const float Rim = W->GetState().SteerDeg;
	if (!bRimArmed)
	{
		bRimArmed = FMath::Abs(Rim) < 25.0f;       // back near the centre: ready for the next turn
	}
	else if (FMath::Abs(Rim) > 50.0f)
	{
		bRimArmed = false;
		Press(Rim > 0.0f ? EKeys::Right : EKeys::Left);
	}
}

FText UCambridgeMenuSubsystem::GetFPSText() const
{
	return FText::FromString(FString::Printf(TEXT("%.0f fps   %.1f ms   GPU %.1f ms"), FrameMs > 0.0 ? 1000.0 / FrameMs : 0.0, FrameMs, GpuMs));
}

FText UCambridgeMenuSubsystem::GetFPSNumberText() const
{
	return FText::FromString(FString::Printf(TEXT("%.0f"), FrameMs > 0.0 ? 1000.0 / FrameMs : 0.0));
}

FText UCambridgeMenuSubsystem::GetFPSDetailText() const
{
	return FText::FromString(FString::Printf(TEXT("FPS   %.1f MS   GPU %.1f"), FrameMs, GpuMs));
}

FText UCambridgeMenuSubsystem::GetTrayText() const
{
	return FText::FromString(FString::Printf(TEXT("%.0f FPS   %s"), FrameMs > 0.0 ? 1000.0 / FrameMs : 0.0, *FDateTime::Now().ToString(TEXT("%H:%M"))));
}

void UCambridgeMenuSubsystem::SetOverlayVisible(bool bVisible)
{
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (OverlayWidget.IsValid() && (!bVisible || OverlayViewport.Get() != Viewport))
	{
		if (UGameViewportClient* Old = OverlayViewport.Get())
		{
			Old->RemoveViewportWidgetContent(OverlayWidget.ToSharedRef());
		}
		OverlayWidget.Reset();
	}
	if (bVisible && !OverlayWidget.IsValid() && Viewport)
	{
		OverlayWidget = SNew(SBox).HAlign(HAlign_Left).VAlign(VAlign_Top).Padding(FMargin(18, 16)).Visibility(EVisibility::HitTestInvisible)
		[
			CambridgeUI::MakeFpsChip(MakeAttributeUObject(this, &UCambridgeMenuSubsystem::GetFPSNumberText),
				MakeAttributeUObject(this, &UCambridgeMenuSubsystem::GetFPSDetailText))
		];
		Viewport->AddViewportWidgetContent(OverlayWidget.ToSharedRef(), 50);
		OverlayViewport = Viewport;
	}
}

void UCambridgeMenuSubsystem::ShowTab(int32 Tab)
{
	if (!IsMenuOpen())
	{
		OpenMenu();
	}
	if (IsMenuOpen())
	{
		StaticCastSharedPtr<SCambridgeMenu>(MenuWidget)->ShowTab(Tab);
	}
}

void UCambridgeMenuSubsystem::ToggleMenu()
{
	if (IsMenuOpen())
	{
		CloseMenu();
	}
	else
	{
		OpenMenu();
	}
}

void UCambridgeMenuSubsystem::OpenMenu()
{
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (!Viewport || !UCambridgeGameUserSettings::Get())
	{
		return;
	}
	// never over the full map: both pause the game, and closing the menu would unpause it under the map
	// (Esc with the map open closes the map: its input processor runs first)
	const UMinimapSubsystem* Map = Viewport->GetWorld() ? Viewport->GetWorld()->GetSubsystem<UMinimapSubsystem>() : nullptr;
	if (Map && Map->IsFullMapOpen())
	{
		return;
	}
	TSharedRef<SCambridgeMenu> Menu = SNew(SCambridgeMenu)
		.OnClose(FSimpleDelegate::CreateUObject(this, &UCambridgeMenuSubsystem::CloseMenu))
		.TrayText_UObject(this, &UCambridgeMenuSubsystem::GetTrayText);
	MenuWidget = Menu;
	Viewport->AddViewportWidgetContent(Menu, 100);
	if (APlayerController* PC = GetGameInstance()->GetFirstLocalPlayerController())
	{
		FInputModeUIOnly Mode;
		Mode.SetWidgetToFocus(Menu);
		PC->SetInputMode(Mode);
		PC->SetShowMouseCursor(true);
		UGameplayStatics::SetGamePaused(PC, true);
	}
	FSlateApplication::Get().SetKeyboardFocus(Menu);
}

void UCambridgeMenuSubsystem::CloseMenu()
{
	if (!MenuWidget.IsValid())
	{
		return;
	}
	if (UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr)
	{
		Viewport->RemoveViewportWidgetContent(MenuWidget.ToSharedRef());
	}
	MenuWidget.Reset();
	if (APlayerController* PC = GetGameInstance() ? GetGameInstance()->GetFirstLocalPlayerController() : nullptr)
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->SetShowMouseCursor(false);
		UGameplayStatics::SetGamePaused(PC, false);
	}
	// (automated runs - shot tours opening the menu with cr.Menu - never write the player's settings)
	if (UCambridgeGameUserSettings* S = bEnabled ? UCambridgeGameUserSettings::Get() : nullptr)
	{
		S->SaveSettings();
	}
	if (UCambridgeWheelSubsystem* W = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCambridgeWheelSubsystem>() : nullptr)
	{
		W->SaveSettings();       // (calibration, rotation, force feedback; nothing in test runs)
	}
}

#undef LOCTEXT_NAMESPACE
