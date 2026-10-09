#include "CambridgeUIStyle.h"

#include "Brushes/SlateBoxBrush.h"
#include "Brushes/SlateImageBrush.h"
#include "Fonts/CompositeFont.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/FileManager.h"
#include "Math/RandomStream.h"
#include "Math/Range.h"
#include "Misc/CoreDelegates.h"
#include "Misc/Paths.h"
#include "Rendering/DrawElements.h"
#include "Rendering/SlateRenderer.h"
#include "Styling/CoreStyle.h"
#include "Styling/SlateStyle.h"
#include "Styling/SlateStyleRegistry.h"
#include "Styling/StyleDefaults.h"
#include "Types/WidgetActiveTimerDelegate.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SLeafWidget.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

TSharedPtr<FSlateStyleSet> FCambridgeUIStyle::StyleInstance;

namespace
{
	const FName CuiStyleName(TEXT("CambridgeUI"));

	// Composite fonts must outlive every FSlateFontInfo that references them.
	TSharedPtr<FStandaloneCompositeFont> CuiPixelFont;      // Silkscreen + Press Start 2P digits
	TSharedPtr<FStandaloneCompositeFont> CuiDigitsFont;     // Press Start 2P
	TSharedPtr<FStandaloneCompositeFont> CuiDotsFont;       // Doto
	TSharedPtr<FStandaloneCompositeFont> CuiBodyFont;       // Open Sans (+ Condensed)
	bool bCuiExitHooked = false;

	// Press Start 2P digits inside the Silkscreen composite are scaled to sit with its capitals
	// (Silkscreen caps are 5/8 em, Press Start 2P 7/8 em). 0.75 keeps them on whole pixels at 24 / 48 / 72 pt.
	constexpr float CuiPixelDigitScale = 0.75f;

	FString CuiFontPath(const TCHAR* File)
	{
		return FCambridgeUIStyle::FontsDir() / File;
	}

	void CuiBuildFonts()
	{
		// Pixel fonts: no hinting (keeps the grid even when a size is not a whole multiple of the pixel)
		CuiPixelFont = MakeShared<FStandaloneCompositeFont>();
		CuiPixelFont->DefaultTypeface.AppendFont(TEXT("Regular"), CuiFontPath(TEXT("Silkscreen-Regular.ttf")), EFontHinting::None, EFontLoadingPolicy::LazyLoad);
		CuiPixelFont->DefaultTypeface.AppendFont(TEXT("Bold"), CuiFontPath(TEXT("Silkscreen-Bold.ttf")), EFontHinting::None, EFontLoadingPolicy::LazyLoad);
		{
			FCompositeSubFont& Digits = CuiPixelFont->SubTypefaces[CuiPixelFont->SubTypefaces.AddDefaulted()];
			Digits.CharacterRanges.Add(FInt32Range::Inclusive(0x30, 0x39));   // 0-9 only, like the website's unicode-range
			Digits.CharacterRanges.Add(FInt32Range::Inclusive(0x40, 0x40));   // and @ (Forza @ MIT): Silkscreen's reads as an e
			Digits.ScalingFactor = CuiPixelDigitScale;
			Digits.Typeface.AppendFont(TEXT("Regular"), CuiFontPath(TEXT("PressStart2P-Regular.ttf")), EFontHinting::None, EFontLoadingPolicy::LazyLoad);
			Digits.Typeface.AppendFont(TEXT("Bold"), CuiFontPath(TEXT("PressStart2P-Regular.ttf")), EFontHinting::None, EFontLoadingPolicy::LazyLoad);
		}
		// glyphs Silkscreen lacks fall back to Open Sans
		CuiPixelFont->FallbackTypeface.Typeface.AppendFont(TEXT("Regular"), CuiFontPath(TEXT("OpenSans-Regular.ttf")), EFontHinting::Default, EFontLoadingPolicy::LazyLoad);

		CuiDigitsFont = MakeShared<FStandaloneCompositeFont>(TEXT("Regular"), CuiFontPath(TEXT("PressStart2P-Regular.ttf")), EFontHinting::None, EFontLoadingPolicy::LazyLoad);

		CuiDotsFont = MakeShared<FStandaloneCompositeFont>();
		CuiDotsFont->DefaultTypeface.AppendFont(TEXT("Black"), CuiFontPath(TEXT("Doto-Black.ttf")), EFontHinting::Default, EFontLoadingPolicy::LazyLoad);
		CuiDotsFont->DefaultTypeface.AppendFont(TEXT("Bold"), CuiFontPath(TEXT("Doto-Bold.ttf")), EFontHinting::Default, EFontLoadingPolicy::LazyLoad);

		CuiBodyFont = MakeShared<FStandaloneCompositeFont>();
		CuiBodyFont->DefaultTypeface.AppendFont(TEXT("Regular"), CuiFontPath(TEXT("OpenSans-Regular.ttf")), EFontHinting::Default, EFontLoadingPolicy::LazyLoad);
		CuiBodyFont->DefaultTypeface.AppendFont(TEXT("Bold"), CuiFontPath(TEXT("OpenSans-Bold.ttf")), EFontHinting::Default, EFontLoadingPolicy::LazyLoad);
		CuiBodyFont->DefaultTypeface.AppendFont(TEXT("Condensed"), CuiFontPath(TEXT("OpenSansCondensed-Bold.ttf")), EFontHinting::Default, EFontLoadingPolicy::LazyLoad);
	}

	FLinearColor CuiHex(const TCHAR* HexString, float Alpha = 1.0f)
	{
		FLinearColor C = FLinearColor(FColor::FromHex(HexString));
		C.A = Alpha;
		return C;
	}

	FTextBlockStyle CuiTextStyle(const FSlateFontInfo& Font, const FLinearColor& Colour, FVector2D ShadowOffset = FVector2D::ZeroVector,
		const FLinearColor& ShadowColour = FLinearColor::Transparent)
	{
		return FTextBlockStyle()
			.SetFont(Font)
			.SetColorAndOpacity(FSlateColor(Colour))
			.SetShadowOffset(ShadowOffset)
			.SetShadowColorAndOpacity(ShadowColour);
	}

	FSlateFontInfo CuiWithOutline(FSlateFontInfo Font, int32 Size, const FLinearColor& Colour)
	{
		Font.OutlineSettings = FFontOutlineSettings(Size, Colour);
		return Font;
	}

	const FSlateBrush* CuiNoBrush()
	{
		return FStyleDefaults::GetNoBrush();
	}

	/** Lets a lambda bound before SAssignNew ask the widget whether it is hovered. */
	struct FCuiHoverProbe
	{
		TWeakPtr<SWidget> Widget;
		bool IsHovered() const
		{
			const TSharedPtr<SWidget> W = Widget.Pin();
			return W.IsValid() && W->IsHovered();
		}
	};

	double CuiSlateTime()
	{
		return FSlateApplication::IsInitialized() ? FSlateApplication::Get().GetCurrentTime() : FPlatformTime::Seconds();
	}
}

// ====================================================================== style set

FString FCambridgeUIStyle::GeneratedDir()
{
	return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir() / TEXT("UI") / TEXT("Generated"));
}

FString FCambridgeUIStyle::FontsDir()
{
	return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir() / TEXT("UI") / TEXT("Fonts"));
}

FName FCambridgeUIStyle::GetStyleSetName()
{
	return CuiStyleName;
}

bool FCambridgeUIStyle::IsInitialized()
{
	return StyleInstance.IsValid();
}

void FCambridgeUIStyle::Initialize()
{
	if (StyleInstance.IsValid())
	{
		return;
	}
	if (!IFileManager::Get().FileExists(*(GeneratedDir() / TEXT("xp_titlebar.png"))))
	{
		UE_LOG(LogTemp, Warning, TEXT("CambridgeUI: brushes missing in %s - run tools/ui/make_ui_assets.py"), *GeneratedDir());
	}
	CuiBuildFonts();
	StyleInstance = Create();
	FSlateStyleRegistry::RegisterSlateStyle(*StyleInstance);
	// styles registered after the renderer loaded its textures must load theirs explicitly
	if (FSlateApplication::IsInitialized() && FSlateApplication::Get().GetRenderer())
	{
		FSlateApplication::Get().GetRenderer()->LoadStyleResources(*StyleInstance);
	}
	if (!bCuiExitHooked)
	{
		bCuiExitHooked = true;
		FCoreDelegates::OnEnginePreExit.AddStatic(&FCambridgeUIStyle::Shutdown);
	}
}

void FCambridgeUIStyle::Shutdown()
{
	if (StyleInstance.IsValid())
	{
		FSlateStyleRegistry::UnRegisterSlateStyle(*StyleInstance);
		ensure(StyleInstance.IsUnique());
		StyleInstance.Reset();
	}
	CuiPixelFont.Reset();
	CuiDigitsFont.Reset();
	CuiDotsFont.Reset();
	CuiBodyFont.Reset();
}

const ISlateStyle& FCambridgeUIStyle::Get()
{
	if (!StyleInstance.IsValid())
	{
		Initialize();
	}
	return *StyleInstance;
}

TSharedRef<FSlateStyleSet> FCambridgeUIStyle::Create()
{
	TSharedRef<FSlateStyleSet> Style = MakeShared<FSlateStyleSet>(CuiStyleName);
	Style->SetContentRoot(GeneratedDir());

	// Brushes and colours, generated by tools/ui/make_ui_assets.py.
	//   box   brushes: 1x textures, margins are UV fractions (Slate draws corners at texel size)
	//   image brushes: 2x textures drawn at their 1x size
	//   tile  brushes: 1x, repeated horizontally
#define CUI_BOX(Name, W, H, L, T, R, B) \
	Style->Set(Name, new FSlateBoxBrush(Style->RootToContentDir(Name, TEXT(".png")), FVector2f(W, H), FMargin(L, T, R, B)));
#define CUI_IMAGE(Name, W, H) \
	Style->Set(Name, new FSlateImageBrush(Style->RootToContentDir(Name, TEXT(".png")), FVector2f(W, H)));
#define CUI_TILE(Name, W, H) \
	Style->Set(Name, new FSlateImageBrush(Style->RootToContentDir(Name, TEXT(".png")), FVector2f(W, H), FLinearColor::White, ESlateBrushTileType::Horizontal));
#define CUI_COLOR(Name, R, G, B) \
	Style->Set(Name, FLinearColor(FColor(R, G, B)));
#include "CambridgeUIBrushes.inl"
	// the launch menu (tools/ui/make_launch_assets.py): the blurred car backdrop (2560 x 1440 texture) and Neil
	// (cropped to the figure, aspect 1:2 = NEIL_ASPECT there, ~620 x 1240 texture)
	CUI_IMAGE("launch_bg", 1920, 1080)
	CUI_IMAGE("neil_mii", 434, 868)
#undef CUI_BOX
#undef CUI_IMAGE
#undef CUI_TILE
#undef CUI_COLOR

	// ---- fonts
	auto Pixel = [](float Size, bool bBold) { return FSlateFontInfo(CuiPixelFont, Size, bBold ? TEXT("Bold") : TEXT("Regular")); };
	auto Digits = [](float Size) { return FSlateFontInfo(CuiDigitsFont, Size, TEXT("Regular")); };
	auto Dots = [](float Size) { return FSlateFontInfo(CuiDotsFont, Size, TEXT("Black")); };
	auto Body = [](float Size, bool bBold) { return FSlateFontInfo(CuiBodyFont, Size, bBold ? TEXT("Bold") : TEXT("Regular")); };
	auto Cond = [](float Size) { return FSlateFontInfo(CuiBodyFont, Size, TEXT("Condensed")); };

	const FLinearColor White = FLinearColor::White;
	const FLinearColor Black = FLinearColor::Black;
	const FLinearColor Navy = CuiHex(TEXT("0a246a"));
	const FLinearColor Ink = CuiHex(TEXT("1e1e1e"));
	const FLinearColor InkDim = CuiHex(TEXT("5a5a55"));
	const FLinearColor GlassDim = CuiHex(TEXT("9ea3ad"));
	const FLinearColor DarkShadow = FLinearColor(0.0f, 0.0f, 0.0f, 0.7f);

	// ---- text styles (sizes in points; the comment is the pixel size at 1080p)
	auto Text = [&Style](const TCHAR* Name, const FTextBlockStyle& S) { Style->Set(FName(*(FString(TEXT("CUI.")) + Name)), S); };
	Text(TEXT("Title"),          CuiTextStyle(Pixel(12, true), White, FVector2D(1, 1), Navy));                 // 16 px, title bars
	Text(TEXT("Heading"),        CuiTextStyle(Pixel(18, true), Navy));                                         // 24 px
	Text(TEXT("Label"),          CuiTextStyle(Pixel(12, false), Black));                                       // 16 px, rows
	Text(TEXT("LabelSelected"),  CuiTextStyle(Pixel(12, false), White));
	Text(TEXT("Value"),          CuiTextStyle(Pixel(12, true), Black));
	Text(TEXT("Body"),           CuiTextStyle(Body(11, false), Ink));                                          // ~15 px
	Text(TEXT("BodyDim"),        CuiTextStyle(Body(11, false), InkDim));
	Text(TEXT("Small"),          CuiTextStyle(Cond(10.5f), InkDim));                                           // 14 px
	Text(TEXT("ButtonLabel"),    CuiTextStyle(Pixel(12, true), Black));
	Text(TEXT("ButtonPrimary"),  CuiTextStyle(Pixel(12, true), White, FVector2D(1, 1), CuiHex(TEXT("1f5a1f"))));
	Text(TEXT("ButtonBig"),      CuiTextStyle(Pixel(18, true), White, FVector2D(2, 2), CuiHex(TEXT("1f5a1f"))));
	Text(TEXT("Key"),            CuiTextStyle(Pixel(12, true), CuiHex(TEXT("222222"))));
	Text(TEXT("KeyDark"),        CuiTextStyle(Pixel(12, true), White));
	Text(TEXT("HudLabel"),       CuiTextStyle(Cond(11), GlassDim));                                            // 15 px
	Text(TEXT("HudLabelBright"), CuiTextStyle(Cond(11), White));
	Text(TEXT("HudHint"),        CuiTextStyle(Pixel(12, false), CuiHex(TEXT("e6e8ec")), FVector2D(1, 1), DarkShadow));
	Text(TEXT("Timer"),          CuiTextStyle(Digits(36), White, FVector2D(3, 3), FLinearColor(0, 0, 0, 0.6f)));  // 48 px
	Text(TEXT("TimerSmall"),     CuiTextStyle(Digits(18), White, FVector2D(2, 2), FLinearColor(0, 0, 0, 0.6f)));  // 24 px
	Text(TEXT("DigitsInk"),      CuiTextStyle(Digits(18), Navy));
	Text(TEXT("Speed"),          CuiTextStyle(Dots(72), White, FVector2D(2, 3), FLinearColor(0, 0, 0, 0.5f)));    // 96 px
	Text(TEXT("SpeedGhost"),     CuiTextStyle(Dots(72), FLinearColor(1, 1, 1, 0.09f)));
	Text(TEXT("Gear"),           CuiTextStyle(Digits(30), White, FVector2D(3, 3), Navy));                         // 40 px
	Text(TEXT("Countdown"),      CuiTextStyle(CuiWithOutline(Digits(132), 8, Navy), White, FVector2D(10, 12), FLinearColor(0, 0, 0, 0.55f)));
	Text(TEXT("CountdownGo"),    CuiTextStyle(CuiWithOutline(Digits(108), 8, CuiHex(TEXT("14501a"))), CuiHex(TEXT("7ef07e")), FVector2D(10, 12), FLinearColor(0, 0, 0, 0.55f)));
	Text(TEXT("SplitAhead"),     CuiTextStyle(Digits(18), CuiHex(TEXT("14962e"))));                               // on a balloon
	Text(TEXT("SplitBehind"),    CuiTextStyle(Digits(18), CuiHex(TEXT("d0301e"))));
	Text(TEXT("SplitAheadHud"),  CuiTextStyle(Digits(18), CuiHex(TEXT("3ddc5a")), FVector2D(2, 2), DarkShadow));  // on glass
	Text(TEXT("SplitBehindHud"), CuiTextStyle(Digits(18), CuiHex(TEXT("ff4f3f")), FVector2D(2, 2), DarkShadow));
	Text(TEXT("ToastTitle"),     CuiTextStyle(Pixel(12, true), Black));
	Text(TEXT("ToastBody"),      CuiTextStyle(Body(10.5f, false), CuiHex(TEXT("222222"))));
	Text(TEXT("ResultTime"),     CuiTextStyle(Digits(36), Navy, FVector2D(2, 2), FLinearColor(1, 1, 1, 0.9f)));
	Text(TEXT("Ribbon"),         CuiTextStyle(Pixel(18, true), CuiHex(TEXT("4a2a00")), FVector2D(1, 1), CuiHex(TEXT("fff3a0"))));
	Text(TEXT("Tray"),           CuiTextStyle(Pixel(12, false), White, FVector2D(1, 1), Navy));
	Text(TEXT("Fps"),            CuiTextStyle(Dots(18), CuiHex(TEXT("b8ff9a"))));

	// ---- buttons
	auto B = [&Style](const TCHAR* Name) { return *Style->GetBrush(Name); };
	Style->Set("CUI.Button", FButtonStyle()
		.SetNormal(B(TEXT("xp_button_normal"))).SetHovered(B(TEXT("xp_button_hover")))
		.SetPressed(B(TEXT("xp_button_pressed"))).SetDisabled(B(TEXT("xp_button_disabled")))
		.SetNormalForeground(FSlateColor(Black)).SetHoveredForeground(FSlateColor(Black))
		.SetPressedForeground(FSlateColor(Black)).SetDisabledForeground(FSlateColor(CuiHex(TEXT("aca899"))))
		.SetNormalPadding(FMargin(0, 0, 0, 1)).SetPressedPadding(FMargin(0, 1, 0, 0)));
	Style->Set("CUI.Button.Primary", FButtonStyle()
		.SetNormal(B(TEXT("xp_start_normal"))).SetHovered(B(TEXT("xp_start_hover")))
		.SetPressed(B(TEXT("xp_start_pressed"))).SetDisabled(B(TEXT("xp_start_pressed")))
		.SetNormalForeground(FSlateColor(White)).SetHoveredForeground(FSlateColor(White))
		.SetPressedForeground(FSlateColor(White)).SetDisabledForeground(FSlateColor(CuiHex(TEXT("cfe8cf"))))
		.SetNormalPadding(FMargin(0, 0, 0, 1)).SetPressedPadding(FMargin(0, 1, 0, 0)));
	Style->Set("CUI.Button.Blue", FButtonStyle()
		.SetNormal(B(TEXT("xp_blue_normal"))).SetHovered(B(TEXT("xp_blue_hover")))
		.SetPressed(B(TEXT("xp_blue_pressed"))).SetDisabled(B(TEXT("xp_blue_pressed")))
		.SetNormalForeground(FSlateColor(White)).SetHoveredForeground(FSlateColor(White))
		.SetPressedForeground(FSlateColor(White)).SetDisabledForeground(FSlateColor(CuiHex(TEXT("c6dcff"))))
		.SetNormalPadding(FMargin(0, 0, 0, 1)).SetPressedPadding(FMargin(0, 1, 0, 0)));
	Style->Set("CUI.Button.Close", FButtonStyle()
		.SetNormal(B(TEXT("xp_close_normal"))).SetHovered(B(TEXT("xp_close_hover")))
		.SetPressed(B(TEXT("xp_close_pressed"))).SetDisabled(B(TEXT("xp_close_normal")))
		.SetNormalPadding(FMargin(0)).SetPressedPadding(FMargin(0)));
	return Style;
}

// ====================================================================== lookups

namespace CambridgeUI
{
	const FSlateBrush* Brush(FName Name)
	{
		return FCambridgeUIStyle::Get().GetBrush(Name);
	}

	FLinearColor Color(FName Name)
	{
		return FCambridgeUIStyle::Get().GetColor(Name);
	}

	const FTextBlockStyle& Text(FName Name)
	{
		return FCambridgeUIStyle::Get().GetWidgetStyle<FTextBlockStyle>(FName(*(TEXT("CUI.") + Name.ToString())));
	}

	const FButtonStyle& Button(FName Name)
	{
		return FCambridgeUIStyle::Get().GetWidgetStyle<FButtonStyle>(FName(*(TEXT("CUI.") + Name.ToString())));
	}

	FSlateFontInfo PixelFont(float Size, bool bBold)
	{
		FCambridgeUIStyle::Get();
		return FSlateFontInfo(CuiPixelFont, Size, bBold ? TEXT("Bold") : TEXT("Regular"));
	}

	FSlateFontInfo DigitsFont(float Size)
	{
		FCambridgeUIStyle::Get();
		return FSlateFontInfo(CuiDigitsFont, Size, TEXT("Regular"));
	}

	FSlateFontInfo DotsFont(float Size, bool bBlack)
	{
		FCambridgeUIStyle::Get();
		return FSlateFontInfo(CuiDotsFont, Size, bBlack ? TEXT("Black") : TEXT("Bold"));
	}

	FSlateFontInfo BodyFont(float Size, bool bBold)
	{
		FCambridgeUIStyle::Get();
		return FSlateFontInfo(CuiBodyFont, Size, bBold ? TEXT("Bold") : TEXT("Regular"));
	}

	FSlateFontInfo CondensedFont(float Size)
	{
		FCambridgeUIStyle::Get();
		return FSlateFontInfo(CuiBodyFont, Size, TEXT("Condensed"));
	}

	// ====================================================================== XP chrome

	TSharedRef<SWidget> MakeXPWindow(const TAttribute<FText>& Title, const TSharedRef<SWidget>& Content, FName Icon, FOnClicked OnClose,
		FMargin ContentPadding, bool bFlagStrip)
	{
		const bool bHasClose = OnClose.IsBound();
		TSharedRef<SHorizontalBox> TitleRow = SNew(SHorizontalBox);
		if (!Icon.IsNone())
		{
			TitleRow->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 7, 0)
			[
				SNew(SImage).Image(Brush(Icon))
			];
		}
		TitleRow->AddSlot().FillWidth(1.0f).VAlign(VAlign_Center).Padding(Icon.IsNone() ? 3.0f : 0.0f, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text("Title")).Text(Title)
		];
		TitleRow->AddSlot().AutoWidth().VAlign(VAlign_Center)
		[
			SNew(SButton)
			.ButtonStyle(&Button("Button.Close"))
			.ContentPadding(FMargin(0))
			.IsFocusable(false)
			.Visibility(bHasClose ? EVisibility::Visible : EVisibility::Collapsed)
			.OnClicked(OnClose)
			[
				SNew(SBox).WidthOverride(22).HeightOverride(22)
			]
		];

		TSharedRef<SVerticalBox> Face = SNew(SVerticalBox);
		if (bFlagStrip)
		{
			Face->AddSlot().AutoHeight()
			[
				SNew(SBox).HeightOverride(16)
				[
					SNew(SImage).Image(Brush("flag_strip"))
				]
			];
		}
		Face->AddSlot().FillHeight(1.0f).Padding(ContentPadding)
		[
			Content
		];

		return SNew(SOverlay)
			// soft drop shadow, offset 4 px down (the window sits 16 / 12 / 16 / 20 inside it)
			+ SOverlay::Slot()
			[
				SNew(SImage).Image(Brush("shadow"))
			]
			+ SOverlay::Slot().Padding(FMargin(16, 12, 16, 20))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SBorder)
					.BorderImage(Brush("xp_titlebar"))
					.Padding(FMargin(7, 3, 5, 3))
					[
						SNew(SBox).HeightOverride(24)
						[
							TitleRow
						]
					]
				]
				+ SVerticalBox::Slot().FillHeight(1.0f)
				[
					SNew(SBorder)
					.BorderImage(Brush("xp_window"))
					.Padding(FMargin(3, 0, 3, 3))
					[
						Face
					]
				]
			];
	}

	TSharedRef<SWidget> MakeXPButton(const TAttribute<FText>& Label, FOnClicked OnClicked, bool bPrimary, FName Icon, bool bBig)
	{
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		if (!Icon.IsNone())
		{
			Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
			[
				SNew(SImage).Image(Brush(Icon))
			];
		}
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text(bBig ? "ButtonBig" : (bPrimary ? "ButtonPrimary" : "ButtonLabel"))).Text(Label)
		];
		return SNew(SButton)
			.ButtonStyle(&Button(bPrimary ? "Button.Primary" : "Button"))
			.ContentPadding(bBig ? FMargin(32, 14) : FMargin(20, 8))
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			.OnClicked(OnClicked)
			[
				Row
			];
	}

	TSharedRef<SWidget> MakeXPButtonFace(const TAttribute<FText>& Label, bool bPrimary, const TAttribute<bool>& bFocused, FName Icon, bool bBig)
	{
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		if (!Icon.IsNone())
		{
			Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 10, 0)
			[
				SNew(SImage).Image(Brush(Icon))
			];
		}
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text(bBig ? "ButtonBig" : (bPrimary ? "ButtonPrimary" : "ButtonLabel"))).Text(Label)
		];
		const FSlateBrush* Normal = Brush(bPrimary ? "xp_start_normal" : "xp_button_normal");
		const FSlateBrush* Focus = Brush(bPrimary ? "xp_start_focus" : "xp_button_focus");
		return SNew(SBorder)
			.BorderImage_Lambda([bFocused, Normal, Focus]() -> const FSlateBrush*
			{
				// the focus ring pulses twice a second, like a blinking XP default button
				return bFocused.Get() && FMath::Fmod(CuiSlateTime(), 1.0) < 0.65 ? Focus : Normal;
			})
			.Padding(bBig ? FMargin(32, 14) : FMargin(20, 8))
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			[
				Row
			];
	}

	TSharedRef<SWidget> MakeSpinButton(bool bRight, FOnClicked OnClicked)
	{
		return SNew(SButton)
			.ButtonStyle(&Button("Button"))
			.ContentPadding(FMargin(7, 6))
			.IsFocusable(false)
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			.OnClicked(OnClicked)
			[
				SNew(SImage)
				.Image(Brush(bRight ? "chevron_right" : "chevron_left"))
				.ColorAndOpacity(FSlateColor(CuiHex(TEXT("142666"))))
			];
	}

	TSharedRef<SWidget> MakeXPTab(const TAttribute<FText>& Label, FName Icon, const TAttribute<bool>& bActive, TFunction<void()> OnClicked)
	{
		TSharedRef<FCuiHoverProbe> Probe = MakeShared<FCuiHoverProbe>();
		const FSlateBrush* Normal = Brush("xp_tab_normal");
		const FSlateBrush* Hover = Brush("xp_tab_hover");
		const FSlateBrush* Active = Brush("xp_tab_active");
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		if (!Icon.IsNone())
		{
			Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
			[
				SNew(SImage).Image(Brush(Icon))
			];
		}
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text("Label")).Text(Label)
		];
		TSharedRef<SBorder> Tab = SNew(SBorder)
			.BorderImage_Lambda([bActive, Probe, Normal, Hover, Active]() -> const FSlateBrush*
			{
				return bActive.Get() ? Active : (Probe->IsHovered() ? Hover : Normal);
			})
			// the active tab is taller and overlaps the panel's top border by 1 px
			.Padding_Lambda([bActive]() -> FMargin { return bActive.Get() ? FMargin(12, 6, 14, 5) : FMargin(12, 4, 14, 3); })
			.OnMouseButtonDown_Lambda([OnClicked](const FGeometry&, const FPointerEvent&) -> FReply
			{
				if (OnClicked) { OnClicked(); }
				return FReply::Handled();
			})
			[
				Row
			];
		Probe->Widget = Tab;
		return Tab;
	}

	TSharedRef<SWidget> MakeListRow(const TSharedRef<SWidget>& Content, const TAttribute<bool>& bSelected, TFunction<void()> OnClicked)
	{
		TSharedRef<FCuiHoverProbe> Probe = MakeShared<FCuiHoverProbe>();
		const FSlateBrush* Select = Brush("xp_select");
		const FSlateBrush* Hover = Brush("xp_hover_row");
		TSharedRef<SBorder> Row = SNew(SBorder)
			.BorderImage_Lambda([bSelected, Probe, Select, Hover]() -> const FSlateBrush*
			{
				return bSelected.Get() ? Select : (Probe->IsHovered() ? Hover : CuiNoBrush());
			})
			.Padding(FMargin(18, 3, 8, 3))
			.OnMouseButtonDown_Lambda([OnClicked](const FGeometry&, const FPointerEvent&) -> FReply
			{
				if (OnClicked) { OnClicked(); }
				return FReply::Handled();
			})
			[
				Content
			];
		Probe->Widget = Row;
		return Row;
	}

	FSlateColor RowTextColor(bool bSelected)
	{
		return FSlateColor(bSelected ? FLinearColor::White : FLinearColor::Black);
	}

	TSharedRef<SWidget> MakeXPPanel(const TSharedRef<SWidget>& Content, FMargin Padding)
	{
		return SNew(SBorder).BorderImage(Brush("xp_panel")).Padding(Padding)[ Content ];
	}

	TSharedRef<SWidget> MakeTaskbar(const TAttribute<FText>& StartLabel, const TSharedRef<SWidget>& Middle, const TAttribute<FText>& TrayText)
	{
		return SNew(SBox).HeightOverride(40)
		[
			SNew(SOverlay)
			+ SOverlay::Slot()
			[
				SNew(SImage).Image(Brush("xp_taskbar"))
			]
			+ SOverlay::Slot()
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SBorder)
					.BorderImage(Brush("xp_startbtn"))
					.Padding(FMargin(12, 0, 30, 0))
					.VAlign(VAlign_Center)
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
						[
							SNew(SImage).Image(Brush("icon_flag"))
						]
						+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
						[
							SNew(STextBlock).TextStyle(&Text("ButtonPrimary")).Text(StartLabel)
						]
					]
				]
				+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center).Padding(12, 0)
				[
					Middle
				]
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(SBorder)
					.BorderImage(Brush("xp_tray"))
					.Padding(FMargin(22, 0))
					.VAlign(VAlign_Center)
					[
						SNew(STextBlock).TextStyle(&Text("Tray")).Text(TrayText)
					]
				]
			]
		];
	}

	// ====================================================================== glass HUD

	TSharedRef<SWidget> MakeGlassPanel(const TSharedRef<SWidget>& Content, FMargin Padding, FName BrushName)
	{
		return SNew(SBorder).BorderImage(Brush(BrushName)).Padding(Padding)[ Content ];
	}

	TSharedRef<SWidget> MakeBadge(const TAttribute<FText>& Label, FName BrushName)
	{
		return SNew(SBorder)
			.BorderImage(Brush(BrushName))
			.Padding(FMargin(9, 2, 9, 1))
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			[
				SNew(STextBlock).TextStyle(&Text("Title")).Text(Label)
			];
	}

	TSharedRef<SWidget> MakeHudPanel(const TAttribute<FText>& Title, FName Icon, const TSharedRef<SWidget>& Content,
		const TAttribute<FText>& Badge, const TSharedPtr<SWidget>& HeaderRight, FMargin Padding)
	{
		TSharedRef<SHorizontalBox> Header = SNew(SHorizontalBox);
		if (!Icon.IsNone())
		{
			Header->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 7, 0)
			[
				SNew(SImage).Image(Brush(Icon))
			];
		}
		Header->AddSlot().FillWidth(1.0f).VAlign(VAlign_Center).Padding(0, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text("Title")).Text(Title)
		];
		if (HeaderRight.IsValid())
		{
			Header->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(8, 0, 4, 0)
			[
				HeaderRight.ToSharedRef()
			];
		}
		if (Badge.IsSet())
		{
			Header->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(8, 0, 0, 0)
			[
				SNew(SBox).HeightOverride(22)
				[
					MakeBadge(Badge)
				]
			];
		}
		return SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SBorder)
				.BorderImage(Brush("xp_titlebar"))
				.Padding(FMargin(7, 3, 5, 3))
				[
					SNew(SBox).HeightOverride(24)
					[
						Header
					]
				]
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SBorder)
				.BorderImage(Brush("glass_panel_bottom"))
				.Padding(Padding)
				[
					Content
				]
			];
	}

	TSharedRef<SWidget> MakeToast(const TAttribute<FText>& Title, const TAttribute<FText>& Body, FName Icon, ETail Tail,
		const TSharedPtr<SWidget>& TitleRight, float WrapWidth)
	{
		TSharedRef<SHorizontalBox> TitleRow = SNew(SHorizontalBox);
		if (!Icon.IsNone())
		{
			TitleRow->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 8, 0)
			[
				SNew(SImage).Image(Brush(Icon))
			];
		}
		TitleRow->AddSlot().FillWidth(1.0f).VAlign(VAlign_Center).Padding(0, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text("ToastTitle")).Text(Title)
		];
		if (TitleRight.IsValid())
		{
			TitleRow->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(12, 0, 0, 0)
			[
				TitleRight.ToSharedRef()
			];
		}
		TSharedRef<SWidget> BodyText = SNew(STextBlock)
			.TextStyle(&Text("ToastBody"))
			.Text(Body)
			.WrapTextAt(WrapWidth)
			.Visibility_Lambda([Body]() { return Body.Get().IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; });

		// tail images overlap the body's border by 1 px: body padding 11 = tail height 12 - 1
		const float TailPad = 11.0f;
		TSharedRef<SOverlay> Overlay = SNew(SOverlay)
			+ SOverlay::Slot().Padding(FMargin(0, Tail == ETail::Up ? TailPad : 0.0f, 0, Tail == ETail::Down ? TailPad : 0.0f))
			[
				SNew(SBorder)
				.BorderImage(Brush("xp_balloon"))
				.Padding(FMargin(12, 9, 14, 10))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()[ TitleRow ]
					+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 0)[ BodyText ]
				]
			];
		if (Tail != ETail::None)
		{
			Overlay->AddSlot()
				.HAlign(HAlign_Center)
				.VAlign(Tail == ETail::Up ? VAlign_Top : VAlign_Bottom)
			[
				SNew(SImage).Image(Brush(Tail == ETail::Up ? "xp_balloon_tail_up" : "xp_balloon_tail_down"))
			];
		}
		return Overlay;
	}

	TSharedRef<SWidget> MakeToastCustom(const TSharedRef<SWidget>& Header, const TAttribute<FText>& Body, ETail Tail, float WrapWidth)
	{
		TSharedRef<SWidget> BodyText = SNew(STextBlock)
			.TextStyle(&Text("ToastBody"))
			.Text(Body)
			.WrapTextAt(WrapWidth)
			.Visibility_Lambda([Body]() { return Body.Get().IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; });
		const float TailPad = 11.0f;
		TSharedRef<SOverlay> Overlay = SNew(SOverlay)
			+ SOverlay::Slot().Padding(FMargin(0, Tail == ETail::Up ? TailPad : 0.0f, 0, Tail == ETail::Down ? TailPad : 0.0f))
			[
				SNew(SBorder)
				.BorderImage(Brush("xp_balloon"))
				.Padding(FMargin(12, 9, 14, 10))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()[ Header ]
					+ SVerticalBox::Slot().AutoHeight().Padding(0, 4, 0, 0)[ BodyText ]
				]
			];
		if (Tail != ETail::None)
		{
			Overlay->AddSlot()
				.HAlign(HAlign_Center)
				.VAlign(Tail == ETail::Up ? VAlign_Top : VAlign_Bottom)
			[
				SNew(SImage).Image(Brush(Tail == ETail::Up ? "xp_balloon_tail_up" : "xp_balloon_tail_down"))
			];
		}
		return Overlay;
	}

	TSharedRef<SWidget> MakeAnimatedIn(const TSharedRef<SWidget>& Content, const TAttribute<float>& Age, float Duration, float FromScale)
	{
		auto Progress = [Age, Duration]()
		{
			const float T = FMath::Clamp(Age.Get() / FMath::Max(Duration, 0.001f), 0.0f, 1.0f);
			return 1.0f - FMath::Pow(1.0f - T, 3.0f);   // ease-out cubic
		};
		return SNew(SBorder)
			.BorderImage(CuiNoBrush())
			.Padding(0)
			.ColorAndOpacity_Lambda([Progress]() -> FLinearColor { return FLinearColor(1, 1, 1, Progress()); })
			.RenderTransformPivot(FVector2D(0.5f, 0.5f))
			.RenderTransform_Lambda([Progress, FromScale]() -> TOptional<FSlateRenderTransform>
			{
				return FSlateRenderTransform(FMath::Lerp(FromScale, 1.0f, Progress()));
			})
			[
				Content
			];
	}

	TSharedRef<SWidget> MakeKeyCap(const FText& Key, bool bDark)
	{
		const FString K = Key.ToString();
		if (K == TEXT("pad_a") || K == TEXT("pad_b"))
		{
			return SNew(SImage).Image(Brush(*K));
		}
		TSharedPtr<SWidget> Glyph;
		const TCHAR* Chevron = K == TEXT("^") ? TEXT("chevron_up") : K == TEXT("v") ? TEXT("chevron_down")
			: K == TEXT("<") ? TEXT("chevron_left") : K == TEXT(">") ? TEXT("chevron_right") : nullptr;
		if (Chevron)
		{
			Glyph = SNew(SImage).Image(Brush(Chevron)).ColorAndOpacity(FSlateColor(bDark ? FLinearColor::White : CuiHex(TEXT("222222"))));
		}
		else
		{
			Glyph = SNew(STextBlock).TextStyle(&Text(bDark ? "KeyDark" : "Key")).Text(Key);
		}
		return SNew(SBox)
			.HeightOverride(26)
			.MinDesiredWidth(26)
			[
				SNew(SBorder)
				.BorderImage(Brush(bDark ? "key_cap_dark" : "key_cap"))
				.Padding(FMargin(8, 0, 8, 4))      // the bottom 4 px are the key's skirt
				.HAlign(HAlign_Center)
				.VAlign(VAlign_Center)
				[
					Glyph.ToSharedRef()
				]
			];
	}

	TSharedRef<SWidget> MakeKeyHint(const TArray<FText>& Keys, const TAttribute<FText>& Label, bool bDark)
	{
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		for (int32 i = 0; i < Keys.Num(); ++i)
		{
			Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(i == 0 ? 0.0f : 4.0f, 0, 0, 0)
			[
				MakeKeyCap(Keys[i], bDark)
			];
		}
		Row->AddSlot().AutoWidth().VAlign(VAlign_Center).Padding(8, 1, 0, 0)
		[
			SNew(STextBlock).TextStyle(&Text(bDark ? "HudHint" : "Label")).Text(Label)
		];
		return Row;
	}

	TSharedRef<SWidget> MakeSegmentBar(const TAttribute<float>& Fraction, int32 NumSegments, TFunction<FName(int32, int32)> SegmentBrush,
		FVector2D SegmentSize, float Gap, bool bDarkTrack)
	{
		const FSlateBrush* Off = Brush("seg_off");
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		for (int32 i = 0; i < NumSegments; ++i)
		{
			const FSlateBrush* Lit = Brush(SegmentBrush ? SegmentBrush(i, NumSegments) : FName("seg_green"));
			Row->AddSlot().AutoWidth().Padding(i == 0 ? 0.0f : Gap, 0, 0, 0)
			[
				SNew(SImage)
				.DesiredSizeOverride(SegmentSize)
				.Image_Lambda([Fraction, i, NumSegments, Lit, Off]() -> const FSlateBrush*
				{
					return FMath::RoundToInt(FMath::Clamp(Fraction.Get(), 0.0f, 1.0f) * NumSegments) > i ? Lit : Off;
				})
			];
		}
		return SNew(SBorder)
			.BorderImage(Brush(bDarkTrack ? "glass_track" : "xp_progress_track"))
			.Padding(FMargin(5, 4))
			[
				Row
			];
	}

	FName RpmSegment(int32 Index, int32 Num)
	{
		const float T = float(Index + 1) / float(FMath::Max(1, Num));
		return T <= 0.70f ? FName("seg_green") : T <= 0.88f ? FName("seg_amber") : FName("seg_red");
	}

	TSharedRef<SWidget> MakeGearBadge(const TAttribute<FText>& Gear, const TAttribute<bool>& bWarning)
	{
		const FSlateBrush* Blue = Brush("gear_badge_blue");
		const FSlateBrush* Red = Brush("gear_badge_red");
		return SNew(SBox)
			.WidthOverride(76)
			.HeightOverride(84)
			[
				SNew(SBorder)
				.BorderImage_Lambda([bWarning, Blue, Red]() -> const FSlateBrush* { return bWarning.Get() ? Red : Blue; })
				.Padding(FMargin(0, 10, 0, 6))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().FillHeight(1.0f).HAlign(HAlign_Center).VAlign(VAlign_Center)
					[
						SNew(STextBlock).TextStyle(&Text("Gear")).Text(Gear)
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
					[
						SNew(STextBlock).TextStyle(&Text("HudLabelBright")).Text(NSLOCTEXT("CambridgeUI", "Gear", "GEAR"))
					]
				]
			];
	}

	TSharedRef<SWidget> MakeDotReadout(const TAttribute<FText>& Value, const FText& Ghost, FName TextStyle)
	{
		return SNew(SOverlay)
			+ SOverlay::Slot().HAlign(HAlign_Right)
			[
				SNew(STextBlock).TextStyle(&Text("SpeedGhost")).Font(Text(TextStyle).Font).Text(Ghost)
			]
			+ SOverlay::Slot().HAlign(HAlign_Right)
			[
				SNew(STextBlock).TextStyle(&Text(TextStyle)).Text(Value)
			];
	}

	TSharedRef<SWidget> MakeStartLights(const TAttribute<int32>& NumLit, const TAttribute<bool>& bGreen, int32 NumLights)
	{
		const FSlateBrush* Off = Brush("light_off");
		const FSlateBrush* Red = Brush("light_red");
		const FSlateBrush* Green = Brush("light_green");
		TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
		for (int32 i = 0; i < NumLights; ++i)
		{
			Row->AddSlot().AutoWidth().Padding(i == 0 ? 0.0f : 8.0f, 0, 0, 0)
			[
				SNew(SImage).Image_Lambda([NumLit, bGreen, i, Off, Red, Green]() -> const FSlateBrush*
				{
					return i < NumLit.Get() ? (bGreen.Get() ? Green : Red) : Off;
				})
			];
		}
		return SNew(SBorder)
			.BorderImage(Brush("light_housing"))
			.Padding(FMargin(20, 14))
			[
				Row
			];
	}

	TSharedRef<SWidget> MakeCountdownDigit(const TAttribute<FText>& InText, const TAttribute<float>& Phase, const TAttribute<bool>& bGo)
	{
		const FTextBlockStyle* Digit = &Text("Countdown");
		const FTextBlockStyle* Go = &Text("CountdownGo");
		return SNew(SBorder)
			.BorderImage(CuiNoBrush())
			.Padding(0)
			// fade out over the last quarter of the second
			.ColorAndOpacity_Lambda([Phase]() -> FLinearColor
			{
				const float P = FMath::Clamp(Phase.Get(), 0.0f, 1.0f);
				return FLinearColor(1, 1, 1, P < 0.75f ? 1.0f : 1.0f - (P - 0.75f) / 0.25f * 0.7f);
			})
			// pop in: 1.6x -> 1x over the first quarter second (ease-out cubic)
			.RenderTransformPivot(FVector2D(0.5f, 0.5f))
			.RenderTransform_Lambda([Phase]() -> TOptional<FSlateRenderTransform>
			{
				const float T = FMath::Clamp(Phase.Get() * 4.0f, 0.0f, 1.0f);
				const float Ease = 1.0f - FMath::Pow(1.0f - T, 3.0f);
				return FSlateRenderTransform(1.6f - 0.6f * Ease);
			})
			[
				SNew(STextBlock)
				.Text(InText)
				.Font_Lambda([bGo, Digit, Go]() { return bGo.Get() ? Go->Font : Digit->Font; })
				.ColorAndOpacity_Lambda([bGo, Digit, Go]() { return bGo.Get() ? Go->ColorAndOpacity : Digit->ColorAndOpacity; })
				.ShadowOffset(FVector2D(10, 12))
				.ShadowColorAndOpacity(FLinearColor(0, 0, 0, 0.55f))
				.Justification(ETextJustify::Center)
			];
	}

	TSharedRef<SWidget> MakeRibbon(const TAttribute<FText>& Label)
	{
		return SNew(SBox)
			.HeightOverride(32)
			[
				SNew(SBorder)
				.BorderImage(Brush("ribbon_gold"))
				.Padding(FMargin(26, 0, 26, 0))
				.VAlign(VAlign_Center)
				[
					SNew(STextBlock).TextStyle(&Text("Ribbon")).Text(Label)
				]
			];
	}

	TSharedRef<SWidget> MakeTrophyBurst(float Size)
	{
		return SNew(SBox)
			.WidthOverride(Size)
			.HeightOverride(Size)
			[
				SNew(SOverlay)
				+ SOverlay::Slot()
				[
					SNew(SImage)
					.Image(Brush("burst_gold"))
					.RenderTransformPivot(FVector2D(0.5f, 0.5f))
					.RenderTransform_Lambda([]() -> TOptional<FSlateRenderTransform>
					{
						const float Angle = float(FMath::Fmod(CuiSlateTime() * 0.35, UE_DOUBLE_TWO_PI));   // slow spin
						return FSlateRenderTransform(FQuat2f(Angle));
					})
				]
				+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
				[
					SNew(SImage).Image(Brush("icon_trophy_lg"))
				]
			];
	}

	TSharedRef<SWidget> MakeFpsChip(const TAttribute<FText>& Fps, const TAttribute<FText>& Detail)
	{
		return SNew(SBorder)
			.BorderImage(Brush("glass_pill"))
			.Padding(FMargin(14, 2, 14, 2))
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center)
				[
					SNew(STextBlock).TextStyle(&Text("Fps")).Text(Fps)
				]
				+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(10, 2, 0, 0)
				[
					SNew(STextBlock).TextStyle(&Text("HudLabel")).Text(Detail)
				]
			];
	}
}

// ====================================================================== confetti

/** Falling pixel confetti in the Luna palette (paint only; repaints itself while it runs). */
class SCambridgeConfetti : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SCambridgeConfetti) : _Seconds(8.0f) {}
		SLATE_ARGUMENT(float, Seconds)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs)
	{
		Seconds = InArgs._Seconds;
		Start = CuiSlateTime();
		const FLinearColor Palette[] = { CuiHex(TEXT("3d95ff")), CuiHex(TEXT("5fd35f")), CuiHex(TEXT("ffd23f")), CuiHex(TEXT("e8734f")), CuiHex(TEXT("ffffff")), CuiHex(TEXT("0058ee")) };
		FRandomStream Rng(7);
		for (int32 i = 0; i < 140; ++i)
		{
			FBit& B = Bits.AddDefaulted_GetRef();
			B.X = Rng.FRand();
			B.Y = -Rng.FRandRange(0.0f, 1.0f);
			B.Speed = Rng.FRandRange(0.12f, 0.3f);
			B.Size = float(2 * Rng.RandRange(3, 5));
			B.Tall = Rng.FRand() < 0.4f ? 2.0f : 1.0f;
			B.Sway = Rng.FRandRange(0.0f, 6.28f);
			B.Colour = Palette[Rng.RandRange(0, int32(UE_ARRAY_COUNT(Palette)) - 1)];
		}
		SetCanTick(false);
		RegisterActiveTimer(0.0f, FWidgetActiveTimerDelegate::CreateSP(this, &SCambridgeConfetti::Animate));
	}

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
		FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override
	{
		const float T = float(CuiSlateTime() - Start);
		if (T > Seconds)
		{
			return LayerId;
		}
		const float Fade = FMath::Clamp((Seconds - T) / 1.5f, 0.0f, 1.0f);
		const FVector2f Area = AllottedGeometry.GetLocalSize();
		const FSlateBrush* White = FCoreStyle::Get().GetBrush("WhiteBrush");
		for (const FBit& B : Bits)
		{
			const float Y = FMath::Fmod(B.Y + B.Speed * T + 2.0f, 1.2f) - 0.1f;
			const float X = B.X * Area.X + FMath::Sin(T * 2.0f + B.Sway) * 12.0f;
			FLinearColor C = B.Colour;
			C.A *= Fade * InWidgetStyle.GetColorAndOpacityTint().A;
			FSlateDrawElement::MakeBox(OutDrawElements, LayerId,
				AllottedGeometry.ToPaintGeometry(FVector2f(B.Size, B.Size * B.Tall), FSlateLayoutTransform(FVector2f(X, Y * Area.Y))),
				White, ESlateDrawEffect::None, C);
		}
		return LayerId + 1;
	}

	virtual FVector2D ComputeDesiredSize(float) const override
	{
		return FVector2D(1.0, 1.0);
	}

private:
	EActiveTimerReturnType Animate(double, float)
	{
		Invalidate(EInvalidateWidgetReason::Paint);
		return CuiSlateTime() - Start > Seconds ? EActiveTimerReturnType::Stop : EActiveTimerReturnType::Continue;
	}

	struct FBit
	{
		float X = 0, Y = 0, Speed = 0, Size = 8, Tall = 1, Sway = 0;
		FLinearColor Colour = FLinearColor::White;
	};
	TArray<FBit> Bits;
	double Start = 0.0;
	float Seconds = 8.0f;
};

TSharedRef<SWidget> CambridgeUI::MakeConfetti(float Seconds)
{
	return SNew(SCambridgeConfetti).Seconds(Seconds).Visibility(EVisibility::HitTestInvisible);
}
