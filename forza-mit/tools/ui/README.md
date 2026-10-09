# forza-MIT UI: "Luna Glass"

The menus and HUD mix the Windows XP Luna look of the HTMAA site
(pub.cba.mit.edu/863.26/alexandre.bismuth) with the modern dark look of alexandre-bismuth.github.io:

- **XP chrome** for windows and dialogs (settings, start event, back on track, results): Luna blue title bar with a
  white pixel title, rounded top corners, red close button, beige `#ece9d8` face with the 3 px `#0831d9` frame,
  green Start-style primary buttons, IE-style tabs, balloon-tooltip toasts, the XP progress bar and taskbar.
- **Glass** for the always-on HUD: dark translucent panels (80 %) under a Luna title chip, dot-matrix speed
  (Doto) over unlit "888" dots, pixel timer digits (Press Start 2P), XP progress blocks for rpm, boost and gates.
- **Game feel**: F1-style start lights, a 3-2-1 digit that pops in (1.6x to 1x) with a thick outline, a green
  GO!, a pulsing focus ring on the Start button, a gold NEW BEST! ribbon and spinning trophy burst, pixel confetti.

Everything is plain Slate in C++; nothing is an asset.

## Files

| Path | What |
|---|---|
| `tools/ui/fetch_fonts.py` | downloads the OFL fonts into `CambridgeRacer/UI/Fonts/` (committed, ~480 KB) |
| `tools/ui/make_ui_assets.py` | draws every brush into `CambridgeRacer/UI/Generated/` (gitignored: rerun after a clone) and writes `staging/CambridgeUIBrushes.inl` |
| `tools/ui/make_mockups.py` | renders the approval mockups into `tools/ui/mockups/` from the real brushes and fonts |
| `tools/ui/make_launch_assets.py` | the launch menu's images into `UI/Generated/` (`launch_bg.png`, `neil_mii.png`) and the startup splash `Content/Splash/Splash.bmp` (all gitignored: rerun after a clone) |
| `tools/ui/make_neil_mii.py` | Neil (HTMAA's instructor) as a full-body Mii carrying the driver's helmet: SVG drawn in code, rasterised with `rsvg-convert` (`brew install librsvg`); `--all` writes every variant |
| `tools/ui/make_launch_mockups.py` | the launch menu design options (the game uses design D, the hero layout) |
| `tools/ui/uidraw.py` | shared SDF drawing, 9-slice and text helpers |
| `tools/ui/staging/CambridgeUIStyle.h/.cpp` | the `CambridgeUI` Slate style set + widget helpers (not compiled until copied into Source) |
| `tools/ui/staging/CambridgeUIBrushes.inl` | generated brush / colour table included by the .cpp |

```sh
cd tools/ui
uv run fetch_fonts.py        # only if the fonts are missing
uv run make_ui_assets.py     # required after every clone (PNGs are gitignored)
uv run make_launch_assets.py # required after every clone: the launch menu backdrop, Neil, the splash
uv run make_mockups.py       # optional; backgrounds come from mockups/bg/*.png (copy game screenshots there)
```

## Colours

Registered on the style set (`CambridgeUI::Color("Luna.Blue")`), sRGB:

| Name | Hex | Use |
|---|---|---|
| Luna.BlueLight / Blue / BlueMid / BlueDark | `#3d95ff` `#0058ee` `#0050e0` `#0040c0` | title bar gradient (0 / 18 / 82 / 100 %) |
| Luna.Frame / Navy | `#0831d9` `#0a246a` | window frame; title text shadow, headings |
| Luna.Face / FaceDark / Content / ContentBorder | `#ece9d8` `#aca899` `#fdfcf7` `#7f9db9` | dialog face, inset panels |
| Luna.Selection / Focus / Hover / TabOrange | `#316ac5` `#ffd54a` `#f8b330` `#e68b2c` | selected row, gamepad cursor, hover ring, active tab |
| Luna.GreenLight / Green / GreenDark | `#5fd35f` `#3c9a3c` `#2e8b2e` | Start buttons |
| Luna.RedLight / Red / RedDark | `#e8734f` `#c9391c` `#b02e12` | close button, reverse gear |
| Luna.Balloon | `#ffffe1` | toasts |
| Glass.Fill / Text / TextDim | `#121418` `#f2f3f5` `#9ea3ad` | HUD glass (alexandre-bismuth.github.io dark) |
| Race.Ahead / Behind / Gold / Amber | `#3ddc5a` `#ff4f3f` `#ffd23f` `#ffb000` | split deltas, new best, rpm |

## Fonts

All SIL OFL 1.1 (licences next to the fonts). Slate sizes are **points**: pixels = points x 4/3 at DPI scale 1
(1080p). The pixel fonts are on their grid at 6 / 12 / 18 / 24 / 36 / 48 / 72 pt.

| Function | Files | Use |
|---|---|---|
| `PixelFont(Size, bBold)` | Silkscreen Regular/Bold, digits 0-9 from Press Start 2P scaled 0.75 (composite sub-font, like the site's `unicode-range`) | titles, labels, buttons, hints |
| `DigitsFont(Size)` | Press Start 2P (monospaced, incl. `:` `.` `-`) | timer, splits, gear, countdown |
| `DotsFont(Size, bBlack)` | Doto Black/Bold (static instances, round dots, monospaced) | speed, FPS |
| `BodyFont(Size, bBold)` | Open Sans Regular/Bold | descriptions, toast text |
| `CondensedFont(Size)` | Open Sans Condensed Bold | small HUD labels (KM/H, GATE, BEST, assists) |

Text styles (`CambridgeUI::Text("Name")`, registered as `CUI.<Name>`), size in pt (px):

| Style | Font | Colour |
|---|---|---|
| Title | Pixel Bold 12 (16) | white, navy 1 px shadow |
| Heading | Pixel Bold 18 (24) | navy |
| Label / LabelSelected / Value | Pixel 12 / Pixel 12 / Pixel Bold 12 | black / white / black |
| Body / BodyDim / Small | Open Sans 11 / 11 / Condensed 10.5 | `#1e1e1e` / `#5a5a55` / `#5a5a55` |
| Button / ButtonPrimary / ButtonBig | Pixel Bold 12 / 12 / 18 | black / white + green shadow |
| Key / KeyDark | Pixel Bold 12 | `#222` / white |
| HudLabel / HudLabelBright / HudHint | Condensed 11 / 11 / Pixel 12 | `#9ea3ad` / white / `#e6e8ec` + shadow |
| Timer / TimerSmall / DigitsInk | Digits 36 (48) / 18 / 18 | white + shadow / white / navy |
| Speed / SpeedGhost | Dots Black 72 (96) | white / white 9 % |
| Gear | Digits 30 (40) | white, navy shadow |
| Countdown / CountdownGo | Digits 132 / 108, 8 px outline | white on navy / `#7ef07e` on `#14501a` |
| SplitAhead / SplitBehind (balloon), SplitAheadHud / SplitBehindHud (glass) | Digits 18 | `#14962e` / `#d0301e`, `#3ddc5a` / `#ff4f3f` |
| ToastTitle / ToastBody | Pixel Bold 12 / Open Sans 10.5 | black / `#222` |
| ResultTime / Ribbon / Tray / Fps | Digits 36 / Pixel Bold 18 / Pixel 12 / Dots 18 | navy / brown on gold / white / `#b8ff9a` |

Button styles (`CambridgeUI::Button(...)`): `Button` (beige XP), `Button.Primary` (green Start), `Button.Blue`
(Luna blue), `Button.Close` (red X).

## Brushes

Style name = PNG stem (`CambridgeUI::Brush("xp_titlebar")`). Sizes are Slate units at DPI scale 1.

**Texture density.** Slate draws box-brush corners at their *texel* size (`ElementBatcher.cpp`:
corner = `TextureWidth * Margin`), so **box brushes are exported at 1x** (`<name>.png`; a `<name>@2x.png` copy is
written for reference only). Image brushes are exported at **2x** and registered with their 1x `ImageSize`, so
icons, lights and blocks stay sharp at 1440p/4K. The tile brush is 1x. Margins in the C++ are UV fractions
(`margin_px / size`), generated into `CambridgeUIBrushes.inl`; `UI/Generated/brushes.json` lists everything.

Box brushes (9-slice), margins left/top/right/bottom in px:

| Brush | Size | Margins | Notes |
|---|---|---|---|
| `xp_titlebar` | 32x30 | 10/8/10/6 | Luna title bar, r 8 top corners; also the HUD header chip (30 high) |
| `xp_window` | 32x32 | 6/2/6/6 | beige face + 3 px frame on sides and bottom (sits under the title bar) |
| `xp_panel` | 16x16 | 4/4/4/4 | inset white content panel |
| `xp_groupbox` | 16x16 | 5/5/5/5 | etched frame, transparent centre |
| `xp_button_{normal,hover,pressed,focus,disabled}` | 24x24 | 6/6/6/6 | beige XP push button (hover = orange ring, focus = blue ring) |
| `xp_start_{normal,hover,pressed,focus}` | 40x40 | 12/12/12/12 | green glossy primary button (focus = yellow ring) |
| `xp_blue_{normal,hover,pressed,focus}` | 40x40 | 12/12/12/12 | Luna-blue glossy button (title-bar button colours) |
| `xp_tab_{normal,hover,active}` | 24x24 | 5/5/5/2 | IE tab, open bottom edge; active = white with orange top |
| `xp_select` | 24x24 | 8/5/5/5 | selected row: selection blue + yellow cursor bar on the left |
| `xp_hover_row` | 24x24 | 5/5/5/5 | faint blue mouse-over row |
| `xp_balloon` | 32x32 | 10/10/10/10 | balloon body (`#ffffe1`, 1 px black, r 8) |
| `glass_panel` | 32x32 | 10/10/10/10 | dark glass, hairline border, r 10 |
| `glass_panel_bottom` | 32x32 | 10/2/10/10 | glass under a title chip (square top) |
| `glass_pill` | 32x32 | 14/14/14/14 | glass capsule (hint bar, FPS chip, chips up to 28 high) |
| `shadow` | 64x64 | 24/24/24/24 | soft shadow; window inset 16/12/16/20 inside it |
| `xp_progress_track` / `glass_track` | 24x18 | 5/5/5/5 | trough for the blocks (light / dark) |
| `light_housing` | 40x40 | 14/14/14/14 | start-light gantry |
| `gear_badge_{blue,red,green}` | 48x48 | 14/14/14/14 | glossy Luna badges (gear, lap, countdown digit) |
| `key_cap` / `key_cap_dark` | 24x26 | 7/6/7/9 | key caps (4 px skirt at the bottom) |
| `ribbon_gold` | 48x32 | 14/6/14/6 | swallow-tail ribbon (keep it 32 high) |
| `xp_taskbar` | 16x40 | 0/6/0/4 | Luna taskbar |
| `xp_tray` | 16x40 | 4/6/1/4 | taskbar tray |
| `xp_startbtn` | 48x40 | 4/10/18/10 | taskbar Start button (rounded right end) |

Image brushes (2x textures): `xp_close_{normal,hover,pressed}` 22x22 · `xp_balloon_tail_up/down` 20x12 (overlap
the body border by 1 px) · `seg_{green,amber,red,blue,off}` 8x14 (XP progress blocks) · `light_{off,red,amber,green,blue}`
64x64 · `pad_a`, `pad_b` 24x24 · `burst_gold` 128x128 · `arrow_up` / `arrow_down` 20x20 · `chevron_{left,right,up,down}`
12x12 (white, tint them) · pixel-art icons `icon_{flag,trophy,clock,info,warn,monitor,car,wheel,cog,reset}` 24x24
and `icon_*_lg` 48x48. Tile: `flag_strip` 32x16 (checkered, `ESlateBrushTileType::Horizontal`).

## Helper functions (`namespace CambridgeUI`)

| Helper | Builds |
|---|---|
| `MakeXPWindow(Title, Content, Icon, OnClose, ContentPadding, bFlagStrip)` | shadow + title bar (icon, pixel title, close button if `OnClose` is bound) + face |
| `MakeXPButton(Label, OnClicked, bPrimary, Icon, bBig)` | clickable beige or green button (menus, cursor visible) |
| `MakeXPButtonFace(Label, bPrimary, bFocused, Icon, bBig)` | the same look, not clickable, focus ring pulsing (HUD prompts: the cursor is hidden in game) |
| `MakeSpinButton(bRight, OnClicked)` | small `<` / `>` value spinner |
| `MakeXPTab(Label, Icon, bActive, OnClicked)` | IE tab (taller when active) |
| `MakeListRow(Content, bSelected, OnClicked)` + `RowTextColor(bSelected)` | settings row with selection / hover |
| `MakeXPPanel(Content, Padding)` | inset white panel |
| `MakeTaskbar(StartLabel, Middle, TrayText)` | XP taskbar, 40 high |
| `MakeGlassPanel(Content, Padding, Brush)` | glass panel / pill |
| `MakeHudPanel(Title, Icon, Content, Badge, HeaderRight, Padding)` | Luna title chip over a glass body |
| `MakeBadge(Label, Brush)` | glossy badge with a pixel label (`LAP 1/2`) |
| `MakeToast(Title, Body, Icon, Tail, TitleRight, WrapWidth)` / `MakeToastCustom(Header, Body, Tail, WrapWidth)` | XP balloon (tail `None` / `Up` / `Down`) |
| `MakeAnimatedIn(Content, Age, Duration, FromScale)` | 0.94x to 1x + fade in (the site's window-open), driven by seconds since shown |
| `MakeKeyCap(Key, bDark)` / `MakeKeyHint(Keys, Label, bDark)` | key caps (`^ v < >` chevrons, `pad_a` / `pad_b`) + label |
| `MakeSegmentBar(Fraction, N, SegmentBrush, SegmentSize, Gap, bDarkTrack)` + `RpmSegment` | rpm / boost / gate / reset progress blocks |
| `MakeGearBadge(Gear, bWarning)` | 76x84 gear badge (red when warning) |
| `MakeDotReadout(Value, Ghost, Style)` | Doto readout over ghost dots |
| `MakeStartLights(NumLit, bGreen, NumLights)` | start-light gantry |
| `MakeCountdownDigit(Text, Phase, bGo)` | popping countdown digit / GO! |
| `MakeRibbon(Label)` / `MakeTrophyBurst(Size)` / `MakeConfetti(Seconds)` | results celebration |
| `MakeFpsChip(Fps, Detail)` | FPS pill |

All text / brush / visibility inputs are `TAttribute`s, so the existing `Text_UObject` / lambda bindings in the
subsystems plug straight in.

## Integration status

Integrated: the kit lives in its own module, `CambridgeRacer/Source/CambridgeUI/` (`Public/CambridgeUIStyle.h`,
`Private/CambridgeUIStyle.cpp` + `CambridgeUIBrushes.inl`), loaded in the PreLoadingScreen phase so the launch menu
(`CambridgeLaunchScreen.*`, same module) can be the engine's loading screen from the moment the game window opens;
`tools/ui/staging/` keeps the source copies (`make_ui_assets.py` regenerates the staging `.inl`; copy it over when
brushes change). `CambridgeMenuSubsystem.cpp` (settings window, FPS chip) and `TimeTrialSubsystem.cpp` (whole HUD)
use it, `FCambridgeUIStyle::Initialize()` runs in `UCambridgeMenuSubsystem::Initialize()`, and `CambridgeRacer.Build.cs`
stages `UI/Fonts` and `UI/Generated` as runtime dependencies. The notes below describe how each mockup maps to code.

## Integrating (reference)

1. **Copy** `staging/CambridgeUIStyle.h`, `CambridgeUIStyle.cpp` and `CambridgeUIBrushes.inl` into
   `CambridgeRacer/Source/CambridgeUI/` (Public / Private). Re-copy the `.inl` whenever `make_ui_assets.py` changes
   brushes. (The launch menu's `launch_bg` and `neil_mii` brushes are registered by hand after the `.inl` include.)
2. **Build.cs**: nothing new. The kit uses Slate (public) and SlateCore (private), which are already listed; it
   only includes Slate/SlateCore/Core headers. For **packaged** builds stage the loose files:
   ```csharp
   RuntimeDependencies.Add("$(ProjectDir)/UI/Fonts/...", StagedFileType.UFS);
   RuntimeDependencies.Add("$(ProjectDir)/UI/Generated/...", StagedFileType.UFS);
   ```
   (editor and development runs read them straight from the project directory).
3. **Registration**: `FCambridgeUIStyle::Get()` initialises lazily on first use and unregisters itself on
   `FCoreDelegates::OnEnginePreExit`, so no module change is required. To register at startup instead, replace
   `IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, ...)` in `CambridgeRacer.cpp` with a module whose
   `StartupModule()` calls `FCambridgeUIStyle::Initialize()` and `ShutdownModule()` calls `FCambridgeUIStyle::Shutdown()`.
   `Initialize()` calls `GetRenderer()->LoadStyleResources()` because the style is registered after Slate loaded
   its textures; it logs a warning if `UI/Generated` is empty (run `make_ui_assets.py`).
   Recommended: call `FCambridgeUIStyle::Initialize()` from `UCambridgeMenuSubsystem::Initialize()` inside the
   existing `if (bEnabled && FSlateApplication::IsInitialized())` block, so the textures are created at startup
   rather than mid-frame the first time the menu or HUD is built (the lazy path stays as a fallback).
4. **Map the mockups onto the code** (layout numbers are in `make_mockups.py`, which mirrors these helpers):

| Mockup | Where | Build it with |
|---|---|---|
| `a_settings.png` | `SCambridgeMenu::Construct` / `SetTab` (CambridgeMenuSubsystem.cpp) | full-screen `SBackgroundBlur` (strength ~8) + 35 % black, then `MakeXPWindow("Settings", Content, "icon_cog", OnClose = close menu)` 780 wide. Content: tab strip = `SHorizontalBox` of `MakeXPTab` (icons `icon_monitor`, `icon_car`, `icon_wheel`, slots `VAlign_Bottom`) directly above `MakeXPPanel(list)`; each row `MakeListRow(HBox[label Text("Label"), spin <, value Text("Value"), spin >], bSelected, select)`, 32 high, label/value colour `RowTextColor`; footer `MakeKeyHint({"TAB"},"Section",false)`, `{"^","v"}` Select, `{"<",">"}` Change, `{"ESC"}` Close and `MakeXPButton("Resume", close, true)`. Bottom of the screen: `MakeTaskbar("forza-MIT", <current-window button>, FPS + clock)`. Keep the existing row model and key handling. To join the active tab to the panel (no hairline under it), give the tab-strip slot `Padding(0, 0, 0, -1)` (negative padding works in `SVerticalBox`) or stack strip and panel in an `SOverlay`. |
| FPS overlay | `UCambridgeMenuSubsystem::SetOverlayVisible` | `MakeFpsChip(fps, "16.6 MS  GPU 9.8")` at top-left (18, 16) |
| `b_freeroam_hud.png` | `UTimeTrialSubsystem::AttachHUD`, bottom-right slot | `MakeHudPanel("Impreza STI", "icon_car", Content, unset, HeaderRight = assists text in HudLabelBright)`, 392 wide, 32 / 28 from the corner. Content: row [`KM/H` HudLabel] [`MakeDotReadout(GetSpeedText, "888")`] [`MakeGearBadge(GetGearText, gear == R)`]; `MakeSegmentBar(GetRpmFraction, 30, RpmSegment)`; row [`RPM` + rpm number] ... [`BOOST` + `MakeSegmentBar(boost, 12, seg_blue, (6,14))`]. Split `GetAssistText` into assists (header) and boost/rpm getters. Optional first-launch toast: `MakeToast("Welcome to MIT", ...)` bottom-left. |
| `c_start_prompt.png` | prompt slot (State == FreeRoam && NearMarker >= 0) | `MakeAnimatedIn(MakeXPWindow(Name + ".exe", ..., "icon_flag", unbound close, 12, bFlagStrip = true))`, 680 wide, top 180, centred: `gear_badge_blue` 104x104 with `icon_flag_lg`; Heading name; Body "Circuit · 3.8 km · 2 laps · 40 gates"; `icon_trophy` + BodyDim "Personal best" + DigitsInk time; `MakeXPButtonFace("START RACE", true, true, "icon_flag", true)` full width; centred row `MakeKeyCap("ENTER", false)` / `MakeKeyCap("pad_a")` / Label "both paddles"; Small "Drive away to dismiss". Needs getters for the near track's name, length, laps, gates and best instead of the single prompt string. |
| `d_race_hud.png` | top-centre event slot + split + prompt slots | `MakeHudPanel(GetEventTitle, "icon_flag", Content, Badge = "LAP 1/2")` 480 wide at top 20: Timer `GetTimerText`; `MakeSegmentBar(gates passed / total, 40, seg_blue)`; row "GATE 17/40" (HudLabelBright) ... "BEST 1:41.183" (HudLabel). Split: `MakeAnimatedIn(MakeToastCustom(HBox[SImage arrow_up/arrow_down, delta in SplitAhead/SplitBehind, fill, "GATE 17" ToastTitle], "Ahead of your best run", ETail::Up))` 300 wide just under the panel, visible 2.5 s. Running help: `MakeGlassPanel(HBox[MakeKeyHint({"R"},"Back on track"), {"ENTER"} Restart, {"BKSP"} Leave], (18,9), "glass_pill")` bottom centre. |
| `e_countdown.png`, `e2_countdown_go.png` | countdown slot | `SVerticalBox`: `MakeStartLights(lit, bGreen)` at y 290 (3 s countdown: 1, 2, 3 red lights, then 4 green at GO), `MakeCountdownDigit(GetCountdownText, Phase = frac(elapsed), bGo = State == Running)`, `MakeToast("Rev it up! Launch on GO", "", "icon_info")` during the countdown only. Timer shows 0:00.000. |
| `f_back_on_track.png` | new (R during an event) | `MakeXPWindow("Back on track", Content, "icon_reset")` 560 wide at y 380, no close: `icon_reset_lg`, Label "Before gate N", BodyDim "The clock keeps running - get ready to go!", `MakeSegmentBar(progress, 26, seg_green, (9,14), 2, bDarkTrack = false)` and a 64x64 `gear_badge_blue` with the seconds left in TimerSmall. Today `ResetToLastGate` is instant; the dialog assumes a short hold (e.g. 1.5-3 s with the car parked). |
| `g_results.png` | results slot (State == Finished) | full-screen 30 % black (+ optional `SBackgroundBlur` 3), `MakeConfetti()` when `bNewBest`, `MakeAnimatedIn(MakeXPWindow("Results - " + name, Content, "icon_trophy", unbound, 12, true))` 700 wide: `MakeTrophyBurst(150)`; Heading "FINISHED"; `ResultTime`; `MakeRibbon("NEW BEST!")` + `arrow_up` + SplitAhead delta + BodyDim "vs previous best" (keep the previous best before `Finish()` overwrites it); `MakeXPPanel` lap table (LAP / TIME / VS BEST LAP, best lap row tinted gold 22 %); buttons `MakeXPButtonFace("Free roam", false, false)` + `MakeKeyCap("BKSP", false)` and `MakeKeyCap("ENTER", false)` + `MakeXPButtonFace("RACE AGAIN", true, true)`. |

## Caveats

- The kit has **not been compiled** here (no UBT run). Every Slate identifier was checked against the UE 5.8
  headers; the path-based `FSlateFontInfo(FString, ...)` constructors are deprecated since 5.6, so fonts are built
  as `FStandaloneCompositeFont`s.
- Internal helpers are prefixed `Cui*` in an anonymous namespace so unity builds don't clash with the other
  `.cpp` files' anonymous-namespace helpers.
- Box brushes are 1x on purpose (see above): at 1440p and 4K their corners are bilinear-upscaled, the 2x image
  brushes stay sharp. Vector `FSlateRoundedBoxBrush`es are an option if the glass corners ever look soft.
- Countdown and digit pop animations are attribute lambdas (`RenderTransform_Lambda`, `ColorAndOpacity_Lambda`),
  so the HUD must keep painting every frame, as it does today. The confetti registers its own active timer.
- PIL's text stroke is a little heavier than Slate's outline, so the countdown digits will look slightly lighter
  in game.
