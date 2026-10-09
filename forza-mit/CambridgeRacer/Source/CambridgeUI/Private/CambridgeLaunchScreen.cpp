#include "CambridgeLaunchScreen.h"

#include "CambridgeUIStyle.h"
#include "HAL/PlatformTime.h"
#include "InputCoreTypes.h"
#include "Styling/SlateBrush.h"
#include "Styling/StyleDefaults.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/Layout/SWidgetSwitcher.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "CambridgeLaunch"

namespace
{
	// (unique names: unity builds merge the anonymous namespaces of several .cpp files)
	const FText LaunchLabels[] = { LOCTEXT("OpenWorld", "Launch Open World"), LOCTEXT("TimedRace", "Timed Race"), LOCTEXT("Options", "Options") };
	const FName LaunchIcons[] = { FName(TEXT("icon_car_lg")), FName(TEXT("icon_flag_lg")), FName(TEXT("icon_cog_lg")) };
	const FText LaunchDescriptions[] = {
		LOCTEXT("OpenWorldDesc", "Explore Cambridge freely, from the Media Lab"),
		LOCTEXT("TimedRaceDesc", "12 time trials across MIT and Harvard"),
		LOCTEXT("OptionsDesc", "Graphics, sound, driving assists, wheel and controls") };
	constexpr int32 LaunchNumMain = UE_ARRAY_COUNT(LaunchLabels);

	// layout at 1080p (Slate units; the viewport's DPI scale takes it to the window)
	constexpr float LaunchLeft = 120.0f;
	constexpr float LaunchColumnW = 600.0f;
	constexpr float LaunchButtonH = 96.0f;
	constexpr float LaunchRowH = 36.0f;
	constexpr float LaunchFadeSeconds = 0.35f;

	/** A button that draws nothing itself: the content (an SBorder) draws the Luna face for its state. */
	const FButtonStyle& LaunchInvisibleButton()
	{
		static const FButtonStyle Style = FButtonStyle()
			.SetNormal(FSlateNoResource()).SetHovered(FSlateNoResource()).SetPressed(FSlateNoResource()).SetDisabled(FSlateNoResource())
			.SetNormalPadding(FMargin(0)).SetPressedPadding(FMargin(0));
		return Style;
	}

	bool LaunchKeyIn(const FKey& K, std::initializer_list<FKey> Keys)
	{
		for (const FKey& X : Keys) { if (K == X) { return true; } }
		return false;
	}

	FLinearColor LaunchHex(uint8 R, uint8 G, uint8 B, float A = 1.0f)
	{
		FLinearColor C(FColor(R, G, B));
		C.A = A;
		return C;
	}
}

void SCambridgeLaunchScreen::Construct(const FArguments& InArgs)
{
	bLive = InArgs._bLive;
	Events = InArgs._Events;
	LoadFraction = InArgs._LoadFraction;
	LoadText = InArgs._LoadText;
	bWheel = InArgs._bWheel;
	OnMainChoice = InArgs._OnMainChoice;
	OnEventChoice = InArgs._OnEventChoice;
	OnMoved = InArgs._OnMoved;
	ShownAt = FPlatformTime::Seconds();
	Selected = bLive ? 0 : -1;       // (the loading screen has no focus: all three buttons blue, dimmed)

	const FLinearColor White = FLinearColor::White;
	const FLinearColor Navy = LaunchHex(0x0a, 0x24, 0x6a);
	TitleStyle = FTextBlockStyle().SetFont(CambridgeUI::PixelFont(60, true)).SetColorAndOpacity(White)
		.SetShadowOffset(FVector2D(4, 4)).SetShadowColorAndOpacity(Navy);                                   // 80 px
	AtStyle = FTextBlockStyle(TitleStyle).SetFont(CambridgeUI::DigitsFont(45));                            // Silkscreen's @ reads as an e
	FSlateFontInfo Subtitle = CambridgeUI::CondensedFont(18);
	Subtitle.LetterSpacing = 170;
	SubtitleStyle = FTextBlockStyle().SetFont(Subtitle).SetColorAndOpacity(LaunchHex(0xc9, 0xd6, 0xf2));
	ButtonStyle = FTextBlockStyle().SetFont(CambridgeUI::PixelFont(24, true)).SetColorAndOpacity(White)
		.SetShadowOffset(FVector2D(2, 2)).SetShadowColorAndOpacity(Navy);                                   // 32 px
	RowStyle = FTextBlockStyle().SetFont(CambridgeUI::PixelFont(12, true)).SetColorAndOpacity(White)
		.SetShadowOffset(FVector2D(1, 1)).SetShadowColorAndOpacity(Navy);
	RowRightStyle = FTextBlockStyle().SetFont(CambridgeUI::DigitsFont(9)).SetColorAndOpacity(LaunchHex(0xe8, 0xee, 0xff))
		.SetShadowOffset(FVector2D(1, 1)).SetShadowColorAndOpacity(Navy);
	HeadingStyle = FTextBlockStyle().SetFont(CambridgeUI::PixelFont(24, true)).SetColorAndOpacity(White)
		.SetShadowOffset(FVector2D(2, 2)).SetShadowColorAndOpacity(Navy);
	DescStyle = FTextBlockStyle().SetFont(CambridgeUI::BodyFont(13.5f)).SetColorAndOpacity(LaunchHex(0xf2, 0xf3, 0xf5));
	LoadStyle = FTextBlockStyle().SetFont(CambridgeUI::PixelFont(12)).SetColorAndOpacity(White);

	// ---- main page: three buttons and the description of the selected one
	TSharedRef<SVerticalBox> MainButtons = SNew(SVerticalBox);
	for (int32 i = 0; i < LaunchNumMain; ++i)
	{
		MainButtons->AddSlot().AutoHeight().Padding(0, i == 0 ? 0.0f : 24.0f, 0, 0)
		[
			MakeButton(i, LaunchLabels[i], LaunchIcons[i], FText::GetEmpty(), false)
		];
	}
	auto Description = [this]()
	{
		return SNew(SBox).WidthOverride(LaunchColumnW).HeightOverride(74)
		[
			CambridgeUI::MakeGlassPanel(
				SNew(SBox).VAlign(VAlign_Center)
				[
					SNew(STextBlock).TextStyle(&DescStyle).AutoWrapText(true).Text(this, &SCambridgeLaunchScreen::GetDescription)
				],
				FMargin(24, 10))
		];
	};
	TSharedRef<SWidget> MainPageWidget = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(SBorder).BorderImage(FStyleDefaults::GetNoBrush()).Padding(0)
			.ColorAndOpacity_Lambda([this]() { const float V = GetButtonsOpacity(); return FLinearColor(V, V, V, 1.0f); })
			[
				MainButtons
			]
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(0, 30, 0, 0)
		[
			Description()
		];

	// ---- event page: TIMED RACE heading (with a back arrow), one row per event, the description
	TSharedRef<SVerticalBox> Rows = SNew(SVerticalBox);
	for (int32 i = 0; i < Events.Num(); ++i)
	{
		Rows->AddSlot().AutoHeight().Padding(0, i == 0 ? 0.0f : 4.0f, 0, 0)
		[
			MakeButton(i, Events[i].Name, NAME_None, Events[i].Short, true)
		];
	}
	TSharedRef<SWidget> EventPageWidget = SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight().Padding(0, 0, 0, 14)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 14, 0)
			[
				SNew(SBox).WidthOverride(30).HeightOverride(30)
				[
					CambridgeUI::MakeSpinButton(false, FOnClicked::CreateLambda([this]() { Back(); return FReply::Handled(); }))
				]
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
			[
				SNew(STextBlock).TextStyle(&HeadingStyle).Text(LOCTEXT("TimedRaceHeading", "TIMED RACE"))
			]
		]
		+ SVerticalBox::Slot().AutoHeight()
		[
			Rows
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(0, 16, 0, 0)
		[
			Description()
		];

	ChildSlot
	[
		SNew(SOverlay)
		// the backdrop (scaled to cover any aspect)
		+ SOverlay::Slot()
		[
			SNew(SScaleBox).Stretch(EStretch::ScaleToFill)
			[
				SNew(SImage).Image(CambridgeUI::Brush("launch_bg"))
			]
		]
		// Neil, standing on the street to the right of the car: 868 tall at 1080p (the user's sizing, 2026-10-08: 1.5x
		// then 1.1x, grown from the bottom-left corner, then 5 % of the screen to the left and 2 % back right)
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Bottom).Padding(0, 0, 42, 77)
		[
			SNew(SBox).WidthOverride(434).HeightOverride(868)
			[
				SNew(SImage).Image(CambridgeUI::Brush("neil_mii"))
			]
		]
		// title, subtitle, the page
		+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Top).Padding(LaunchLeft, 104, 0, 0)
		[
			SNew(SBox).WidthOverride(LaunchColumnW + 200)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					MakeTitle()
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(4, 2, 0, 0)
				[
					SNew(STextBlock).TextStyle(&SubtitleStyle).Text(LOCTEXT("Subtitle", "CAMBRIDGE, MA - HTMAA F26"))
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0, 58, 0, 0)
				[
					SAssignNew(Pages, SWidgetSwitcher)
					+ SWidgetSwitcher::Slot()[ MainPageWidget ]
					+ SWidgetSwitcher::Slot()[ EventPageWidget ]
				]
			]
		]
		// the keys and the loading bar
		+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom).Padding(LaunchLeft, 0, 0, 36)
		[
			MakeBottomBar()
		]
	];
}

TSharedRef<SWidget> SCambridgeLaunchScreen::MakeTitle() const
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom)
		[
			SNew(STextBlock).TextStyle(&TitleStyle).Text(LOCTEXT("TitleA", "FORZA "))
		]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom).Padding(0, 0, 0, 6)
		[
			SNew(STextBlock).TextStyle(&AtStyle).Text(LOCTEXT("TitleAt", "@"))
		]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom)
		[
			SNew(STextBlock).TextStyle(&TitleStyle).Text(LOCTEXT("TitleB", " MIT"))
		];
}

TSharedRef<SWidget> SCambridgeLaunchScreen::MakeButton(int32 Index, const FText& Label, FName Icon, const FText& Right, bool bRow)
{
	const FSlateBrush* Focus = CambridgeUI::Brush("xp_start_focus");
	const FSlateBrush* Pressed = CambridgeUI::Brush("xp_start_pressed");
	const FSlateBrush* Blue = CambridgeUI::Brush("xp_blue_normal");
	const FSlateBrush* BlueHover = CambridgeUI::Brush("xp_blue_hover");
	TSharedPtr<SButton> Button;
	const int32 RowPage = bRow ? EventPage : MainPage;

	TSharedRef<SHorizontalBox> Content = SNew(SHorizontalBox);
	if (!Icon.IsNone())
	{
		Content->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 26, 0)
		[
			SNew(SBox).WidthOverride(60).HeightOverride(60)[ SNew(SImage).Image(CambridgeUI::Brush(Icon)) ]
		];
	}
	Content->AddSlot().FillWidth(1.0f).VAlign(VAlign_Center)
	[
		SNew(STextBlock).TextStyle(bRow ? &RowStyle : &ButtonStyle).Text(FText::FromString(Label.ToString().ToUpper()))
	];
	if (!Right.IsEmpty())
	{
		Content->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(STextBlock).TextStyle(&RowRightStyle).Text(Right)
		];
	}

	SAssignNew(Button, SButton)
	.ButtonStyle(&LaunchInvisibleButton())
	.ContentPadding(0)
	.IsFocusable(false)
	.Visibility(bLive ? EVisibility::Visible : EVisibility::HitTestInvisible)
	.OnHovered_Lambda([this, Index, RowPage]() { if (Page == RowPage && Selected != Index) { Select(Index); OnMoved.ExecuteIfBound(); } })
	.OnClicked_Lambda([this, Index, RowPage]() { if (Page == RowPage) { Selected = Index; Activate(); } return FReply::Handled(); })
	[
		SNew(SBox).WidthOverride(LaunchColumnW).HeightOverride(bRow ? LaunchRowH : LaunchButtonH)
		[
			SNew(SBorder).BorderImage(FStyleDefaults::GetNoBrush()).Padding(bRow ? FMargin(18, 0) : FMargin(30, 0))
			[
				Content
			]
		]
	];
	// the face: the selected item is the green Start button with the yellow focus ring (pressed while the mouse
	// holds it), the others Luna blue (lighter under the mouse)
	const TWeakPtr<SButton> WeakButton = Button;
	return SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SImage)
			.Image_Lambda([this, Index, RowPage, Focus, Pressed, Blue, BlueHover, WeakButton]() -> const FSlateBrush*
			{
				const TSharedPtr<SButton> B = WeakButton.Pin();
				if (bLive && Page == RowPage && Selected == Index)
				{
					return B.IsValid() && B->IsPressed() ? Pressed : Focus;
				}
				return B.IsValid() && B->IsHovered() ? BlueHover : Blue;
			})
		]
		+ SOverlay::Slot()
		[
			Button.ToSharedRef()
		];
}

TSharedRef<SWidget> SCambridgeLaunchScreen::MakeBottomBar()
{
	auto Keys = [](std::initializer_list<const TCHAR*> List)
	{
		TArray<FText> Out;
		for (const TCHAR* K : List) { Out.Add(FText::FromString(K)); }
		return Out;
	};
	// the bar: live = the streaming progress; loading = a marquee (the loading thread draws it: time only)
	TSharedRef<SWidget> Bar = SNullWidget::NullWidget;
	if (bLive)
	{
		Bar = CambridgeUI::MakeSegmentBar(LoadFraction, 20, [](int32, int32) { return FName(TEXT("seg_blue")); }, FVector2D(8, 14), 3.0f, true);
	}
	else
	{
		const FSlateBrush* Lit = CambridgeUI::Brush("seg_blue");
		const FSlateBrush* Off = CambridgeUI::Brush("seg_off");
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		constexpr int32 N = 20;
		for (int32 i = 0; i < N; ++i)
		{
			Row->AddSlot().AutoWidth().Padding(i == 0 ? 0.0f : 3.0f, 0, 0, 0)
			[
				SNew(SImage)
				.DesiredSizeOverride(FVector2D(8, 14))
				.Image_Lambda([i, Lit, Off]() -> const FSlateBrush*
				{
					// three blocks sliding through the trough, like XP's boot bar
					const int32 Head = int32(FPlatformTime::Seconds() * 14.0) % (N + 3);
					return i <= Head && i > Head - 3 ? Lit : Off;
				})
			];
		}
		Bar = SNew(SBorder).BorderImage(CambridgeUI::Brush("glass_track")).Padding(FMargin(5, 4))[ Row ];
	}
	TAttribute<FText> Status = bLive ? LoadText : TAttribute<FText>(LOCTEXT("Starting", "STARTING THE ENGINE"));
	return SNew(SBox).WidthOverride(1240).HeightOverride(60)        // (room for the wheel's longer hints)
		[
			CambridgeUI::MakeGlassPanel(
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(SBorder).BorderImage(FStyleDefaults::GetNoBrush()).Padding(0)
					.ColorAndOpacity_Lambda([this]() { const float V = GetButtonsOpacity(); return FLinearColor(V, V, V, 1.0f); })
					[
						// keyboard / gamepad, or the home-built wheel's controls when it is connected
						SNew(SOverlay)
						+ SOverlay::Slot().VAlign(VAlign_Center)
						[
							SNew(SHorizontalBox)
							.Visibility_Lambda([this]() { return bWheel.Get(false) ? EVisibility::Collapsed : EVisibility::Visible; })
							+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 26, 0)
							[
								CambridgeUI::MakeKeyHint(Keys({ TEXT("^"), TEXT("v") }), LOCTEXT("HintSelect", "Select"))
							]
							+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 26, 0)
							[
								CambridgeUI::MakeKeyHint(Keys({ TEXT("ENTER") }), LOCTEXT("HintGo", "Go"))
							]
							+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
							[
								CambridgeUI::MakeKeyHint(Keys({ TEXT("ESC") }), LOCTEXT("HintBack", "Back"))
							]
						]
						+ SOverlay::Slot().VAlign(VAlign_Center)
						[
							SNew(SHorizontalBox)
							.Visibility_Lambda([this]() { return bWheel.Get(false) ? EVisibility::Visible : EVisibility::Collapsed; })
							+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 22, 0)
							[
								CambridgeUI::MakeKeyHint(Keys({ TEXT("LEFT"), TEXT("RIGHT") }), LOCTEXT("WheelSelect", "Paddle: select"))
							]
							+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 22, 0)
							[
								CambridgeUI::MakeKeyHint(Keys({ TEXT("BOTH PADDLES") }), LOCTEXT("WheelGo", "Go"))
							]
							+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
							[
								CambridgeUI::MakeKeyHint(Keys({ TEXT("HOLD BOTH") }), LOCTEXT("WheelBack", "Back"))
							]
						]
					]
				]
				+ SHorizontalBox::Slot().FillWidth(1.0f)[ SNullWidget::NullWidget ]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(24, 0, 14, 0)
				[
					SNew(STextBlock).TextStyle(&LoadStyle).Text(Status)
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					Bar
				],
				FMargin(30, 8, 22, 8), TEXT("glass_pill"))
		];
}

float SCambridgeLaunchScreen::GetButtonsOpacity() const
{
	// (a brightness: the loading screen shows the menu asleep, darkened; the live one lights it up as it takes over)
	constexpr float Asleep = 0.55f;
	if (!bLive)
	{
		return Asleep;
	}
	const float T = FMath::Clamp(float(FPlatformTime::Seconds() - ShownAt) / LaunchFadeSeconds, 0.0f, 1.0f);
	return FMath::Lerp(Asleep, 1.0f, T);
}

int32 SCambridgeLaunchScreen::NumItems() const
{
	return Page == MainPage ? LaunchNumMain : Events.Num();
}

FText SCambridgeLaunchScreen::GetDescription() const
{
	if (!bLive)
	{
		return LOCTEXT("LoadingDesc", "Starting up: the map of Cambridge is loading.");
	}
	if (Page == MainPage)
	{
		return LaunchDescriptions[FMath::Clamp(Selected, 0, LaunchNumMain - 1)];
	}
	return Events.IsValidIndex(Selected) ? Events[Selected].Detail : FText::GetEmpty();
}

void SCambridgeLaunchScreen::ShowPage(int32 NewPage, int32 Select)
{
	Page = NewPage == EventPage && Events.Num() > 0 ? EventPage : MainPage;
	if (Pages.IsValid())
	{
		Pages->SetActiveWidgetIndex(Page);
	}
	Selected = FMath::Clamp(Select, 0, FMath::Max(0, NumItems() - 1));
}

void SCambridgeLaunchScreen::Select(int32 Index)
{
	if (bLive && NumItems() > 0)
	{
		Selected = FMath::Clamp(Index, 0, NumItems() - 1);
	}
}

void SCambridgeLaunchScreen::Move(int32 Delta)
{
	const int32 N = NumItems();
	if (!bLive || N == 0)
	{
		return;
	}
	Selected = ((Selected + Delta) % N + N) % N;
	OnMoved.ExecuteIfBound();
}

void SCambridgeLaunchScreen::Activate()
{
	if (!bLive)
	{
		return;
	}
	if (Page == MainPage)
	{
		const int32 Choice = FMath::Clamp(Selected, 0, LaunchNumMain - 1);
		if (Choice == 1)
		{
			ShowPage(EventPage, 0);
		}
		OnMainChoice.ExecuteIfBound(Choice);
	}
	else if (Events.IsValidIndex(Selected))
	{
		OnEventChoice.ExecuteIfBound(Selected);
	}
}

bool SCambridgeLaunchScreen::Back()
{
	if (Page == EventPage)
	{
		ShowPage(MainPage, 1);
		OnMoved.ExecuteIfBound();
		return true;
	}
	return false;
}

FReply SCambridgeLaunchScreen::OnKeyDown(const FGeometry&, const FKeyEvent& Event)
{
	const FKey K = Event.GetKey();
	if (LaunchKeyIn(K, { EKeys::Up, EKeys::W, EKeys::Gamepad_DPad_Up, EKeys::Gamepad_LeftStick_Up }))
	{
		Move(-1);
		return FReply::Handled();
	}
	if (LaunchKeyIn(K, { EKeys::Down, EKeys::S, EKeys::Gamepad_DPad_Down, EKeys::Gamepad_LeftStick_Down, EKeys::Tab }))
	{
		Move(+1);
		return FReply::Handled();
	}
	if (LaunchKeyIn(K, { EKeys::Enter, EKeys::SpaceBar, EKeys::Gamepad_FaceButton_Bottom }))
	{
		if (!Event.IsRepeat()) { Activate(); }
		return FReply::Handled();
	}
	if (LaunchKeyIn(K, { EKeys::BackSpace, EKeys::Gamepad_FaceButton_Right, EKeys::Left, EKeys::Gamepad_DPad_Left }))
	{
		if (!Event.IsRepeat()) { Back(); }
		return FReply::Handled();
	}
	return FReply::Unhandled();
}

#undef LOCTEXT_NAMESPACE
