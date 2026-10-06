#include "MinimapSubsystem.h"

#include "CambridgeGameUserSettings.h"
#include "CambridgeMenuSubsystem.h"
#include "CambridgeUIStyle.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "ImageUtils.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "MinimapWidgets.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "TextureResource.h"
#include "TimeTrialSubsystem.h"
#include "Widgets/SOverlay.h"

#define LOCTEXT_NAMESPACE "Minimap"

DEFINE_LOG_CATEGORY_STATIC(LogMinimap, Log, All);

namespace
{
	constexpr double MmsArriveCm = 2500.0;        // waypoint reached
	constexpr double MmsArriveEventCm = 2000.0;   // event start reached (the start box is 16 m)
	constexpr double MmsOffRouteCm = 2500.0;      // recompute when the car is this far off the route
	constexpr double MmsRecomputeSeconds = 2.0;
	constexpr double MmsUTurnCm = 6000.0;         // routing cost of turning round at the start
	constexpr double MmsArrivedNoteSeconds = 4.0;

	FString MmsDistance(double Cm)
	{
		const double M = FMath::Max(0.0, Cm / 100.0);
		return M >= 1000.0 ? FString::Printf(TEXT("%.1f KM"), M / 1000.0) : FString::Printf(TEXT("%d M"), FMath::RoundToInt(M / 10.0) * 10);
	}

	FString MmsMapName(const UWorld* World)
	{
		return FPackageName::GetShortName(World->GetOutermost()->GetName()).Replace(TEXT("UEDPIE_0_"), TEXT(""));
	}

	FVector2D MmsClosestOnSegment(const FVector2D& P, const FVector2D& A, const FVector2D& B, double& OutT)
	{
		const FVector2D AB = B - A;
		const double L2 = AB.SizeSquared();
		OutT = L2 > 1e-6 ? FMath::Clamp(FVector2D::DotProduct(P - A, AB) / L2, 0.0, 1.0) : 0.0;
		return A + AB * OutT;
	}
}

// ------------------------------------------------------------------ input (M / View; the open map's controls)

class FMinimapInput : public IInputProcessor
{
public:
	explicit FMinimapInput(UMinimapSubsystem* InOwner) : Owner(InOwner) {}

	virtual void Tick(const float DeltaTime, FSlateApplication&, TSharedRef<ICursor>) override
	{
		UMinimapSubsystem* M = Owner.Get();
		TSharedPtr<SFullMapView> View = M ? M->GetFullMapView() : nullptr;
		if (!View.IsValid())
		{
			Reset();
			return;
		}
		auto Held = [this](std::initializer_list<FKey> Keys) { for (const FKey& K : Keys) { if (Down.Contains(K)) { return 1.0; } } return 0.0; };
		FVector2D Dir(
			Held({ EKeys::D, EKeys::Right, EKeys::Gamepad_DPad_Right }) - Held({ EKeys::A, EKeys::Left, EKeys::Gamepad_DPad_Left }),
			Held({ EKeys::S, EKeys::Down, EKeys::Gamepad_DPad_Down }) - Held({ EKeys::W, EKeys::Up, EKeys::Gamepad_DPad_Up }));
		const FVector2D Stick(FMath::Abs(StickX) > 0.2f ? StickX : 0.0f, FMath::Abs(StickY) > 0.2f ? -StickY : 0.0f);
		Dir += Stick;
		const double Dt = FMath::Min(double(DeltaTime), 0.1);
		if (!Dir.IsNearlyZero())
		{
			const double Fast = Down.Contains(EKeys::LeftShift) ? 2.0 : 1.0;
			View->PanLocal(-Dir.GetClampedToMaxSize(1.0) * 650.0 * Fast * Dt);
			View->CenterCursor();
		}
		double ZoomDir = Held({ EKeys::E, EKeys::PageUp, EKeys::Add, EKeys::Equals, EKeys::Gamepad_RightShoulder })
			- Held({ EKeys::Q, EKeys::PageDown, EKeys::Subtract, EKeys::Hyphen, EKeys::Gamepad_LeftShoulder });
		ZoomDir += (RightTrigger > 0.1f ? RightTrigger : 0.0f) - (LeftTrigger > 0.1f ? LeftTrigger : 0.0f);
		if (FMath::Abs(ZoomDir) > 0.01)
		{
			View->ZoomBy(float(FMath::Exp(ZoomDir * Dt * 1.8)));
		}
	}

	virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
	{
		UMinimapSubsystem* M = Owner.Get();
		if (!M)
		{
			return false;
		}
		const FKey K = Event.GetKey();
		if (!M->IsFullMapOpen())
		{
			if ((K == EKeys::M || K == EKeys::Gamepad_Special_Left) && !Event.IsRepeat())
			{
				M->OpenFullMap();
				return M->IsFullMapOpen();
			}
			return false;
		}
		// the map owns the keyboard while it is open (Enter / Backspace / R must not reach the time trials)
		if (K == EKeys::Tilde || K == EKeys::F1 || K == EKeys::F9 || K == EKeys::F11 || K == EKeys::F12)
		{
			return false;
		}
		if (K == EKeys::M || K == EKeys::Gamepad_Special_Left || K == EKeys::Escape || K == EKeys::Gamepad_Special_Right)
		{
			if (!Event.IsRepeat()) { M->CloseFullMap(); }
			return true;
		}
		TSharedPtr<SFullMapView> View = M->GetFullMapView();
		if (K == EKeys::Enter || K == EKeys::SpaceBar || K == EKeys::Gamepad_FaceButton_Bottom)
		{
			if (!Event.IsRepeat() && View.IsValid()) { View->Confirm(); }
			return true;
		}
		if (K == EKeys::BackSpace || K == EKeys::Delete || K == EKeys::Gamepad_FaceButton_Right)
		{
			if (!Event.IsRepeat()) { M->ClearDestination(); }
			return true;
		}
		Down.Add(K);
		return true;
	}

	virtual bool HandleKeyUpEvent(FSlateApplication&, const FKeyEvent& Event) override
	{
		Down.Remove(Event.GetKey());
		return Owner.IsValid() && Owner->IsFullMapOpen();
	}

	virtual bool HandleAnalogInputEvent(FSlateApplication&, const FAnalogInputEvent& Event) override
	{
		if (!Owner.IsValid() || !Owner->IsFullMapOpen())
		{
			return false;
		}
		const FKey K = Event.GetKey();
		const float V = Event.GetAnalogValue();
		if (K == EKeys::Gamepad_LeftX) { StickX = V; }
		else if (K == EKeys::Gamepad_LeftY) { StickY = V; }
		else if (K == EKeys::Gamepad_LeftTriggerAxis) { LeftTrigger = V; }
		else if (K == EKeys::Gamepad_RightTriggerAxis) { RightTrigger = V; }
		return true;
	}

	virtual bool HandleMouseMoveEvent(FSlateApplication&, const FPointerEvent& Event) override
	{
		TSharedPtr<SFullMapView> View = OpenView();
		if (!View.IsValid())
		{
			return false;
		}
		const FVector2D Pos = Event.GetScreenSpacePosition();
		if (bLeftDown)
		{
			if (!bDragging && FVector2D::Distance(Pos, PressPos) > 5.0)
			{
				bDragging = true;
			}
			if (bDragging)
			{
				View->PanLocal(View->ScreenToLocal(Pos) - View->ScreenToLocal(LastMouse));
			}
			LastMouse = Pos;
		}
		if (View->IsInside(Pos))
		{
			View->SetCursorLocal(View->ScreenToLocal(Pos));
		}
		return false;     // the OS cursor keeps moving, the close button keeps its hover
	}

	virtual bool HandleMouseButtonDownEvent(FSlateApplication&, const FPointerEvent& Event) override
	{
		TSharedPtr<SFullMapView> View = OpenView();
		const FVector2D Pos = Event.GetScreenSpacePosition();
		if (!View.IsValid() || !View->IsInside(Pos))
		{
			return false;
		}
		if (Event.GetEffectingButton() == EKeys::LeftMouseButton)
		{
			bLeftDown = true;
			bDragging = false;
			PressPos = LastMouse = Pos;
		}
		else if (Event.GetEffectingButton() == EKeys::RightMouseButton)
		{
			Owner->ClearDestination();
		}
		return true;
	}

	virtual bool HandleMouseButtonUpEvent(FSlateApplication&, const FPointerEvent& Event) override
	{
		TSharedPtr<SFullMapView> View = OpenView();
		if (Event.GetEffectingButton() != EKeys::LeftMouseButton || !bLeftDown)
		{
			return View.IsValid() && View->IsInside(Event.GetScreenSpacePosition());
		}
		bLeftDown = false;
		if (View.IsValid() && !bDragging && View->IsInside(Event.GetScreenSpacePosition()))
		{
			View->SetCursorLocal(View->ScreenToLocal(Event.GetScreenSpacePosition()));
			View->Confirm();
		}
		bDragging = false;
		return View.IsValid();
	}

	virtual bool HandleMouseWheelOrGestureEvent(FSlateApplication&, const FPointerEvent& Event, const FPointerEvent*) override
	{
		TSharedPtr<SFullMapView> View = OpenView();
		const FVector2D Pos = Event.GetScreenSpacePosition();
		if (!View.IsValid() || !View->IsInside(Pos))
		{
			return false;
		}
		const FVector2D L = View->ScreenToLocal(Pos);
		View->ZoomBy(FMath::Pow(1.25f, Event.GetWheelDelta()), &L);
		return true;
	}

	virtual const TCHAR* GetDebugName() const override { return TEXT("MinimapInput"); }

	void Reset()
	{
		Down.Reset();
		StickX = StickY = LeftTrigger = RightTrigger = 0.0f;
		bLeftDown = bDragging = false;
	}

private:
	TSharedPtr<SFullMapView> OpenView() const
	{
		return Owner.IsValid() && Owner->IsFullMapOpen() ? Owner->GetFullMapView() : nullptr;
	}

	TWeakObjectPtr<UMinimapSubsystem> Owner;
	TSet<FKey> Down;
	float StickX = 0.0f, StickY = 0.0f, LeftTrigger = 0.0f, RightTrigger = 0.0f;
	bool bLeftDown = false, bDragging = false;
	FVector2D PressPos = FVector2D::ZeroVector, LastMouse = FVector2D::ZeroVector;
};

// ------------------------------------------------------------------ lifecycle

UMinimapSubsystem* UMinimapSubsystem::Get(const UObject* WorldContext)
{
	const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UMinimapSubsystem>() : nullptr;
}

float UMinimapSubsystem::GetHudFootprint()
{
	const UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get();
	return (!S || S->bShowMinimap) ? MinimapUI::HudMarginBottom + MinimapUI::HudHeight : 0.0f;
}

bool UMinimapSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return Super::ShouldCreateSubsystem(Outer) && !IsRunningCommandlet();
}

TStatId UMinimapSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UMinimapSubsystem, STATGROUP_Tickables);
}

void UMinimapSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!InWorld.IsGameWorld())
	{
		return;
	}
	const FString MapName = MmsMapName(&InWorld);
	const TCHAR* Cmd = FCommandLine::Get();
	const bool bRender = FSlateApplication::IsInitialized() && !FParse::Param(Cmd, TEXT("nullrhi"));
	if (bRender)
	{
		LoadMap(MapName);       // decode the textures now, not on the first paint
	}
	LoadGraph(MapName);
	const bool bAutomated = FCString::Strifind(Cmd, TEXT("-ShotTour")) || FCString::Strifind(Cmd, TEXT("-DriveTest"));
	if (bRender && !bAutomated)
	{
		Input = MakeShared<FMinimapInput>(this);
		FSlateApplication::Get().RegisterInputPreProcessor(Input, 0);   // before the time trials' Enter / Backspace and the menu's Esc
	}
	bReady = true;
}

void UMinimapSubsystem::Deinitialize()
{
	if (Input.IsValid() && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().UnregisterInputPreProcessor(Input);
	}
	Input.Reset();
	CloseFullMap();
	DetachHUD();
	Super::Deinitialize();
}

UTexture2D* UMinimapSubsystem::LoadTexture(const FString& Path, bool bMips)
{
	FImage Image;
	if (!FImageUtils::LoadImage(*Path, Image))
	{
		UE_LOG(LogMinimap, Warning, TEXT("cannot load %s (run tools/minimap/make_map.py)"), *Path);
		return nullptr;
	}
	Image.ChangeFormat(ERawImageFormat::BGRA8, EGammaSpace::sRGB);
	const int32 W = Image.SizeX, H = Image.SizeY;
	UTexture2D* Tex = UTexture2D::CreateTransient(W, H, PF_B8G8R8A8);
	if (!Tex)
	{
		return nullptr;
	}
	Tex->NeverStream = true;
	Tex->SRGB = true;
	Tex->Filter = TF_Trilinear;               // Slate samples UTextures with their own filter: mips stop the shimmer when minified
	Tex->LODGroup = TEXTUREGROUP_UI;
	Tex->AddressX = TA_Clamp;
	Tex->AddressY = TA_Clamp;
	FTexturePlatformData* PD = Tex->GetPlatformData();
	{
		FTexture2DMipMap& Mip0 = PD->Mips[0];
		void* Dest = Mip0.BulkData.Lock(LOCK_READ_WRITE);
		FMemory::Memcpy(Dest, Image.RawData.GetData(), int64(W) * H * 4);
		Mip0.BulkData.Unlock();
	}
	if (bMips)
	{
		// box-filtered mip chain (sRGB average: good enough for flat map colours)
		TArray<FColor> Prev;
		Prev.SetNumUninitialized(W * H);
		FMemory::Memcpy(Prev.GetData(), Image.RawData.GetData(), int64(W) * H * 4);
		Image = FImage();       // (the decoded PNG is in mip 0 and Prev now: free it before the chain, lower peak)
		int32 PW = W, PH = H;
		TArray<FColor> Next;
		while (PW > 1 || PH > 1)
		{
			const int32 NW = FMath::Max(1, PW / 2), NH = FMath::Max(1, PH / 2);
			Next.SetNumUninitialized(NW * NH);
			for (int32 y = 0; y < NH; ++y)
			{
				const int32 y0 = FMath::Min(y * 2, PH - 1), y1 = FMath::Min(y * 2 + 1, PH - 1);
				for (int32 x = 0; x < NW; ++x)
				{
					const int32 x0 = FMath::Min(x * 2, PW - 1), x1 = FMath::Min(x * 2 + 1, PW - 1);
					const FColor& A = Prev[y0 * PW + x0];
					const FColor& B = Prev[y0 * PW + x1];
					const FColor& C = Prev[y1 * PW + x0];
					const FColor& D = Prev[y1 * PW + x1];
					Next[y * NW + x] = FColor(uint8((A.R + B.R + C.R + D.R + 2) / 4), uint8((A.G + B.G + C.G + D.G + 2) / 4),
						uint8((A.B + B.B + C.B + D.B + 2) / 4), uint8((A.A + B.A + C.A + D.A + 2) / 4));
				}
			}
			FTexture2DMipMap* Mip = new FTexture2DMipMap(NW, NH, 1);
			PD->Mips.Add(Mip);
			Mip->BulkData.Lock(LOCK_READ_WRITE);
			void* Dest = Mip->BulkData.Realloc(int64(NW) * NH * 4);
			FMemory::Memcpy(Dest, Next.GetData(), int64(NW) * NH * 4);
			Mip->BulkData.Unlock();
			Swap(Prev, Next);
			PW = NW;
			PH = NH;
		}
	}
	// the mips only need to reach the GPU: single-use bulk data is handed to the RHI upload and freed
	// (FTexturePlatformData::TryLoadMipsWithSizes -> GetCopy(.., bDiscardInternalCopy) discards it only with this
	// flag; without it a transient texture keeps a second, CPU copy of every mip for the whole session)
	int64 Bytes = 0;
	for (FTexture2DMipMap& Mip : PD->Mips)
	{
		Bytes += Mip.BulkData.GetBulkDataSize();
		Mip.BulkData.SetBulkDataFlags(BULKDATA_SingleUse);
	}
	Tex->UpdateResource();
	Textures.Add(Tex);
	TextureBytes += Bytes;
	UE_LOG(LogMinimap, Display, TEXT("map texture %s: %d x %d, %d mips, %.1f MB on the GPU"), *FPaths::GetCleanFilename(Path), W, H, PD->Mips.Num(),
		double(Bytes) / (1024.0 * 1024.0));
	return Tex;
}

void UMinimapSubsystem::LoadMap(const FString& MapName)
{
	const FString Dir = FCambridgeUIStyle::GeneratedDir();
	const FString Path = Dir / FString::Printf(TEXT("minimap_%s.json"), *MapName);
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!FFileHelper::LoadFileToString(Text, *Path) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
	{
		UE_LOG(LogMinimap, Display, TEXT("no minimap for %s (%s): run `cd tools/mapgen && uv run ../minimap/make_map.py %s`"), *MapName, *Path, *MapName);
		return;
	}
	const double Start = FPlatformTime::Seconds();
	const TArray<TSharedPtr<FJsonValue>>* Arr;
	if (Root->TryGetArrayField(TEXT("layers"), Arr))
	{
		Layers.Reserve(Arr->Num());
		for (const TSharedPtr<FJsonValue>& V : *Arr)
		{
			const TSharedPtr<FJsonObject> O = V->AsObject();
			UTexture2D* Tex = LoadTexture(Dir / O->GetStringField(TEXT("file")), true);
			if (!Tex)
			{
				continue;
			}
			FMinimapLayer& L = Layers.AddDefaulted_GetRef();
			L.Min = FVector2D(O->GetNumberField(TEXT("x0")), O->GetNumberField(TEXT("y0")));
			L.Max = FVector2D(O->GetNumberField(TEXT("x1")), O->GetNumberField(TEXT("y1")));
			L.MetresPerPixel = O->GetNumberField(TEXT("m_per_px"));
			L.Brush.SetResourceObject(Tex);
			L.Brush.ImageSize = FVector2D(Tex->GetSizeX(), Tex->GetSizeY());
			L.Brush.DrawAs = ESlateBrushDrawType::Image;
			MapBounds += FBox2D(L.Min, L.Max);
		}
	}
	if (Root->TryGetArrayField(TEXT("labels"), Arr))
	{
		for (const TSharedPtr<FJsonValue>& V : *Arr)
		{
			const TSharedPtr<FJsonObject> O = V->AsObject();
			FMinimapLabel& L = Labels.AddDefaulted_GetRef();
			L.Text = O->GetStringField(TEXT("t"));
			L.Pos = FVector2D(O->GetNumberField(TEXT("x")), O->GetNumberField(TEXT("y")));
			L.AngleDeg = O->GetNumberField(TEXT("a"));
			const FString Kind = O->GetStringField(TEXT("k"));
			L.Kind = Kind == TEXT("area") ? 1 : Kind == TEXT("water") ? 2 : 0;
			if (L.Kind == 1)
			{
				L.Text.ToUpperInline();     // area names are drawn in capitals (once here, not per paint)
			}
			L.Priority = uint8(O->GetIntegerField(TEXT("p")));
		}
	}
	const TSharedPtr<FJsonObject>* IconObj;
	if (Root->TryGetObjectField(TEXT("icons"), IconObj))
	{
		for (const auto& Pair : (*IconObj)->Values)
		{
			const FString Name(Pair.Key);
			const TArray<TSharedPtr<FJsonValue>>& Size = Pair.Value->AsArray();
			UTexture2D* Tex = Size.Num() == 2 ? LoadTexture(Dir / (Name + TEXT(".png")), true) : nullptr;
			if (!Tex)
			{
				continue;
			}
			FSlateBrush B;
			B.SetResourceObject(Tex);
			B.ImageSize = FVector2D(Size[0]->AsNumber(), Size[1]->AsNumber());
			B.DrawAs = ESlateBrushDrawType::Image;
			Icons.Add(FName(*Name), B);
		}
	}
	UE_LOG(LogMinimap, Display, TEXT("minimap %s: %d layers, %d labels, %d icons, %.1f MB of textures (%.0f ms)"), *MapName, Layers.Num(), Labels.Num(), Icons.Num(),
		double(TextureBytes) / (1024.0 * 1024.0), (FPlatformTime::Seconds() - Start) * 1000.0);
}

void UMinimapSubsystem::LoadGraph(const FString& MapName)
{
	const FString Path = FPaths::ProjectDir() / TEXT("Tracks") / (MapName + TEXT("_roads.json"));
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!FFileHelper::LoadFileToString(Text, *Path) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
	{
		UE_LOG(LogMinimap, Display, TEXT("no road graph for %s (%s): GPS disabled"), *MapName, *Path);
		return;
	}
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("streets")))
	{
		StreetNames.Add(V->AsString());
	}
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("nodes")))
	{
		const TArray<TSharedPtr<FJsonValue>>& A = V->AsArray();
		Nodes.Add(FVector2D(A[0]->AsNumber(), A[1]->AsNumber()));
	}
	NodeEdges.SetNum(Nodes.Num());
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("edges")))
	{
		const TSharedPtr<FJsonObject> O = V->AsObject();
		FEdge E;
		E.A = int32(O->GetNumberField(TEXT("a")));
		E.B = int32(O->GetNumberField(TEXT("b")));
		E.Street = int32(O->GetNumberField(TEXT("s")));
		E.First = EdgePts.Num();
		double Cum = 0.0;
		for (const TSharedPtr<FJsonValue>& P : O->GetArrayField(TEXT("pts")))
		{
			const TArray<TSharedPtr<FJsonValue>>& A = P->AsArray();
			const FVector2D Pt(A[0]->AsNumber(), A[1]->AsNumber());
			if (EdgePts.Num() > E.First)
			{
				Cum += FVector2D::Distance(EdgePts.Last(), Pt);
			}
			EdgePts.Add(Pt);
			EdgeCum.Add(Cum);
		}
		E.Num = EdgePts.Num() - E.First;
		E.Length = Cum;
		if (E.Num < 2 || !Nodes.IsValidIndex(E.A) || !Nodes.IsValidIndex(E.B))
		{
			continue;
		}
		const int32 Index = Edges.Add(E);
		NodeEdges[E.A].Add(Index);
		NodeEdges[E.B].Add(Index);
	}
	BuildRoadGrid();
	UE_LOG(LogMinimap, Display, TEXT("road graph %s: %d nodes, %d edges, %d streets, %d segments in a %d x %d grid of %.0f m cells"), *MapName,
		Nodes.Num(), Edges.Num(), StreetNames.Num(), GridSegs.Num(), GridW, GridH, GridCellCm / 100.0);
}

void UMinimapSubsystem::BuildRoadGrid()
{
	PtEdge.Init(-1, EdgePts.Num());
	FBox2D Box(ForceInit);
	for (int32 e = 0; e < Edges.Num(); ++e)
	{
		const FEdge& E = Edges[e];
		for (int32 k = E.First; k < E.First + E.Num; ++k)
		{
			PtEdge[k] = e;
			Box += EdgePts[k];
		}
	}
	GridW = GridH = 0;
	GridStart.Reset();
	GridSegs.Reset();
	if (!Box.bIsValid)
	{
		return;
	}
	// 50 m cells (a city block: a query touches a handful); coarser only if the network were huge (<= 1M cells)
	GridMin = Box.Min - FVector2D(100.0);
	const FVector2D Span = Box.Max - GridMin + FVector2D(100.0);
	GridCellCm = 5000.0;
	while ((FMath::CeilToDouble(Span.X / GridCellCm) * FMath::CeilToDouble(Span.Y / GridCellCm)) > double(1 << 20))
	{
		GridCellCm *= 2.0;
	}
	GridW = FMath::Max(1, FMath::CeilToInt32(Span.X / GridCellCm));
	GridH = FMath::Max(1, FMath::CeilToInt32(Span.Y / GridCellCm));
	auto CellRange = [this](int32 i, int32& X0, int32& Y0, int32& X1, int32& Y1)
	{
		const FVector2D& A = EdgePts[i];
		const FVector2D& B = EdgePts[i + 1];
		X0 = FMath::Clamp(FMath::FloorToInt32((FMath::Min(A.X, B.X) - GridMin.X) / GridCellCm), 0, GridW - 1);
		X1 = FMath::Clamp(FMath::FloorToInt32((FMath::Max(A.X, B.X) - GridMin.X) / GridCellCm), 0, GridW - 1);
		Y0 = FMath::Clamp(FMath::FloorToInt32((FMath::Min(A.Y, B.Y) - GridMin.Y) / GridCellCm), 0, GridH - 1);
		Y1 = FMath::Clamp(FMath::FloorToInt32((FMath::Max(A.Y, B.Y) - GridMin.Y) / GridCellCm), 0, GridH - 1);
	};
	// two passes (count, fill) into one flat array: segments of cell c at GridSegs[GridStart[c] .. GridStart[c + 1])
	GridStart.Init(0, GridW * GridH + 1);
	for (int32 Pass = 0; Pass < 2; ++Pass)
	{
		TArray<int32> Cursor;
		if (Pass == 1)
		{
			for (int32 c = 0; c < GridW * GridH; ++c) { GridStart[c + 1] += GridStart[c]; }
			GridSegs.SetNumUninitialized(GridStart.Last());
			Cursor = GridStart;
		}
		for (const FEdge& E : Edges)
		{
			for (int32 i = E.First; i + 1 < E.First + E.Num; ++i)
			{
				int32 X0, Y0, X1, Y1;
				CellRange(i, X0, Y0, X1, Y1);
				for (int32 y = Y0; y <= Y1; ++y)
				{
					for (int32 x = X0; x <= X1; ++x)
					{
						const int32 c = y * GridW + x;
						if (Pass == 0) { ++GridStart[c + 1]; }
						else { GridSegs[Cursor[c]++] = i; }
					}
				}
			}
		}
	}
}

void UMinimapSubsystem::AttachHUD()
{
	UGameViewportClient* Viewport = GetWorld()->GetGameViewport();
	if (!Viewport || !HasMap() || (HUD.IsValid() && HUDViewport.Get() == Viewport))
	{
		return;
	}
	DetachHUD();
	HUD = SNew(SOverlay).Visibility(EVisibility::HitTestInvisible)
		+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom).Padding(MinimapUI::HudMarginLeft, 0, 0, MinimapUI::HudMarginBottom)
		[
			MinimapUI::MakeHudPanel(this)
		];
	Viewport->AddViewportWidgetContent(HUD.ToSharedRef(), 41);
	HUDViewport = Viewport;
}

void UMinimapSubsystem::DetachHUD()
{
	if (HUD.IsValid() && HUDViewport.IsValid())
	{
		HUDViewport->RemoveViewportWidgetContent(HUD.ToSharedRef());
	}
	HUD.Reset();
}

// ------------------------------------------------------------------ queries

const FSlateBrush* UMinimapSubsystem::GetIcon(FName Name) const
{
	return Icons.Find(Name);
}

bool UMinimapSubsystem::GetCarPose(FVector2D& OutLoc, float& OutYawDeg, float& OutSpeedKmh) const
{
	const APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0);
	if (!Pawn)
	{
		return false;
	}
	OutLoc = FVector2D(Pawn->GetActorLocation());
	OutYawDeg = Pawn->GetActorRotation().Yaw;
	OutSpeedKmh = Pawn->GetVelocity().Size2D() * 0.036f;
	return true;
}

FText UMinimapSubsystem::GetStreetText() const
{
	if (StreetTextFor != CarStreet)
	{
		StreetTextFor = CarStreet;
		StreetText = StreetNames.IsValidIndex(CarStreet) ? FText::FromString(StreetNames[CarStreet].ToUpper()) : LOCTEXT("OffStreet", "GPS");
	}
	return StreetText;
}

UTimeTrialSubsystem* UMinimapSubsystem::GetTimeTrial() const
{
	return GetWorld() ? GetWorld()->GetSubsystem<UTimeTrialSubsystem>() : nullptr;
}

bool UMinimapSubsystem::IsInEvent() const
{
	const UTimeTrialSubsystem* TT = GetTimeTrial();
	return TT && TT->IsInEvent();
}

const TArray<FVector2D>& UMinimapSubsystem::GetEventLine(int32 TrackIndex) const
{
	if (const TArray<FVector2D>* Found = EventLines.Find(TrackIndex))
	{
		return *Found;
	}
	TArray<FVector2D>& Line = EventLines.Add(TrackIndex);
	if (const UTimeTrialSubsystem* TT = GetTimeTrial(); TT && TT->GetTracks().IsValidIndex(TrackIndex))
	{
		const FTimeTrialTrack& T = TT->GetTracks()[TrackIndex];
		for (const FVector4& P : T.Line)
		{
			Line.Add(FVector2D(P.X, P.Y));
		}
		if (Line.Num() < 2)   // no racing line: gate to gate
		{
			Line.Reset();
			for (const FTimeTrialGateDef& G : T.Gates) { Line.Add(FVector2D(G.Location)); }
		}
	}
	return Line;
}

bool UMinimapSubsystem::IsMinimapVisible() const
{
	const UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get();
	// hidden behind the results window (it would draw over the results dim)
	const UTimeTrialSubsystem* TT = GetWorld() ? GetWorld()->GetSubsystem<UTimeTrialSubsystem>() : nullptr;
	const bool bResults = TT && TT->GetState() == ETimeTrialState::Finished;
	return HasMap() && !IsFullMapOpen() && !bResults && (!S || S->bShowMinimap);
}

FString UMinimapSubsystem::StreetNear(const FVector2D& World, double MaxCm) const
{
	int32 Edge;
	double Along, Dist;
	FVector2D Pt;
	if (Project(World, Edge, Along, Pt, Dist, nullptr, MaxCm) && Dist <= MaxCm && StreetNames.IsValidIndex(Edges[Edge].Street))
	{
		return StreetNames[Edges[Edge].Street];
	}
	return FString();
}

// ------------------------------------------------------------------ GPS

bool UMinimapSubsystem::NearestRoad(const FVector2D& World, FVector2D& OutPoint, FVector2D& OutDir, double& OutDistCm, FString* OutStreet) const
{
	int32 Edge;
	double Along;
	if (!Project(World, Edge, Along, OutPoint, OutDistCm, &OutDir))
	{
		return false;
	}
	if (OutStreet)
	{
		*OutStreet = StreetNames.IsValidIndex(Edges[Edge].Street) ? StreetNames[Edges[Edge].Street] : FString();
	}
	return !OutDir.IsNearlyZero();
}

bool UMinimapSubsystem::Project(const FVector2D& P, int32& OutEdge, double& OutAlong, FVector2D& OutPoint, double& OutDist, FVector2D* OutDir,
	double MaxCm) const
{
	OutEdge = -1;
	OutDist = TNumericLimits<double>::Max();
	if (GridW <= 0 || GridH <= 0)
	{
		return false;
	}
	// rings of grid cells around P's cell, nearest first. Ring R is at least (R - 1) cells away from P (also when P is
	// off the grid), so the search stops once the best distance found is within that: exact, and a few cells on a street.
	const bool bCapped = MaxCm < TNumericLimits<double>::Max();
	double Best2 = bCapped ? MaxCm * MaxCm : TNumericLimits<double>::Max();
	int32 BestSeg = -1;
	double BestT = 0.0;
	FVector2D BestC = FVector2D::ZeroVector;
	auto Visit = [&](int32 X, int32 Y)
	{
		const int32 Cell = Y * GridW + X;
		for (int32 s = GridStart[Cell]; s < GridStart[Cell + 1]; ++s)
		{
			const int32 i = GridSegs[s];
			double T;
			const FVector2D C = MmsClosestOnSegment(P, EdgePts[i], EdgePts[i + 1], T);
			const double D2 = FVector2D::DistSquared(P, C);
			if (D2 < Best2 || (D2 == Best2 && BestSeg < 0))
			{
				Best2 = D2;
				BestSeg = i;
				BestT = T;
				BestC = C;
			}
		}
	};
	const int32 Cx = FMath::FloorToInt32((P.X - GridMin.X) / GridCellCm);
	const int32 Cy = FMath::FloorToInt32((P.Y - GridMin.Y) / GridCellCm);
	const int32 RFirst = FMath::Max(FMath::Max(-Cx, Cx - (GridW - 1)), FMath::Max(-Cy, Cy - (GridH - 1)));   // first ring touching the grid
	const int32 RLast = FMath::Max(FMath::Max(Cx, GridW - 1 - Cx), FMath::Max(Cy, GridH - 1 - Cy));          // last ring touching it
	for (int32 R = FMath::Max(RFirst, 0); R <= RLast; ++R)
	{
		if (R > 0 && (BestSeg >= 0 || bCapped) && double(R - 1) * GridCellCm >= FMath::Sqrt(Best2))
		{
			break;
		}
		if (R == 0)
		{
			Visit(Cx, Cy);      // (R = 0 only when P's cell is on the grid)
			continue;
		}
		// the ring's top and bottom rows, then its left and right columns without their corners
		const int32 X0 = FMath::Max(Cx - R, 0), X1 = FMath::Min(Cx + R, GridW - 1);
		const int32 Y0 = FMath::Max(Cy - R + 1, 0), Y1 = FMath::Min(Cy + R - 1, GridH - 1);
		for (const int32 Y : { Cy - R, Cy + R })
		{
			if (Y >= 0 && Y < GridH)
			{
				for (int32 X = X0; X <= X1; ++X) { Visit(X, Y); }
			}
		}
		for (const int32 X : { Cx - R, Cx + R })
		{
			if (X >= 0 && X < GridW)
			{
				for (int32 Y = Y0; Y <= Y1; ++Y) { Visit(X, Y); }
			}
		}
	}
	if (BestSeg < 0 || !PtEdge.IsValidIndex(BestSeg) || PtEdge[BestSeg] < 0)
	{
		return false;
	}
	OutEdge = PtEdge[BestSeg];
	OutPoint = BestC;
	OutAlong = FMath::Lerp(EdgeCum[BestSeg], EdgeCum[BestSeg + 1], BestT);
	OutDist = FMath::Sqrt(Best2);
	if (OutDir) { *OutDir = (EdgePts[BestSeg + 1] - EdgePts[BestSeg]).GetSafeNormal(); }
	return true;
}

FVector2D UMinimapSubsystem::EdgePointAt(int32 Edge, double Along) const
{
	const FEdge& E = Edges[Edge];
	for (int32 k = 0; k + 1 < E.Num; ++k)
	{
		const double C0 = EdgeCum[E.First + k], C1 = EdgeCum[E.First + k + 1];
		if (Along <= C1 || k + 2 == E.Num)
		{
			const double T = C1 > C0 ? FMath::Clamp((Along - C0) / (C1 - C0), 0.0, 1.0) : 0.0;
			return FMath::Lerp(EdgePts[E.First + k], EdgePts[E.First + k + 1], T);
		}
	}
	return EdgePts[E.First];
}

FVector2D UMinimapSubsystem::RoutePointAt(double Along) const
{
	if (Route.Num() == 0)
	{
		return FVector2D::ZeroVector;
	}
	for (int32 i = 0; i + 1 < Route.Num(); ++i)
	{
		if (Along <= RouteCum[i + 1] || i + 2 == Route.Num())
		{
			const double L = RouteCum[i + 1] - RouteCum[i];
			return FMath::Lerp(Route[i], Route[i + 1], L > 0.0 ? FMath::Clamp((Along - RouteCum[i]) / L, 0.0, 1.0) : 0.0);
		}
	}
	return Route.Last();
}

void UMinimapSubsystem::AddRoutePoint(const FVector2D& P, int32 Street)
{
	if (Route.Num() > 0 && FVector2D::DistSquared(Route.Last(), P) < 1.0)
	{
		return;
	}
	Route.Add(P);
	RouteStreets.Add(Street);
}

void UMinimapSubsystem::AppendEdgePart(int32 Edge, double From, double To)
{
	const FEdge& E = Edges[Edge];
	if (From <= To)
	{
		for (int32 k = 0; k < E.Num; ++k)
		{
			const double C = EdgeCum[E.First + k];
			if (C > From + 1.0 && C < To - 1.0) { AddRoutePoint(EdgePts[E.First + k], E.Street); }
		}
	}
	else
	{
		for (int32 k = E.Num - 1; k >= 0; --k)
		{
			const double C = EdgeCum[E.First + k];
			if (C < From - 1.0 && C > To + 1.0) { AddRoutePoint(EdgePts[E.First + k], E.Street); }
		}
	}
	AddRoutePoint(EdgePointAt(Edge, To), E.Street);
}

bool UMinimapSubsystem::ComputeRoute(const FVector2D& From, const FVector2D& Forward)
{
	Route.Reset();
	RouteStreets.Reset();
	RouteCum.Reset();
	Maneuvers.Reset();
	RouteSeg = 0;
	RouteAlong = 0.0;
	bArriveAtRoadEnd = false;
	const bool bFailedBefore = bRouteFailed;
	bRouteFailed = false;
	// no road route (no graph, or the two ends on networks that don't connect): a straight line to the destination,
	// drawn and followed like a route, recomputed on the 2 s cadence only (not every 0.5 s while "off" it)
	auto StraightLine = [&](const TCHAR* Why)
	{
		Route.Reset();
		RouteStreets.Reset();
		Maneuvers.Reset();
		AddRoutePoint(From, -1);
		AddRoutePoint(Destination, -1);
		RouteCum.SetNum(Route.Num());
		RouteCum[0] = 0.0;
		for (int32 i = 1; i < Route.Num(); ++i) { RouteCum[i] = RouteCum[i - 1] + FVector2D::Distance(Route[i - 1], Route[i]); }
		RoadEnd = Destination;
		bRouteFailed = true;
		UE_CLOG(!bFailedBefore, LogMinimap, Display, TEXT("GPS: no road route to %s (%s): straight line"), *DestinationName(), Why);
		return false;
	};
	int32 Es, Eg;
	double As, Ag, Ds, Dg;
	FVector2D Ps, Pg, Dir;
	if (!Project(From, Es, As, Ps, Ds, &Dir) || !Project(Destination, Eg, Ag, Pg, Dg))
	{
		return StraightLine(TEXT("no road graph"));
	}
	// turning round where you are costs a little: prefer routes that start the way the car points
	double PenA = 0.0, PenB = 0.0;
	if (!Forward.IsNearlyZero())
	{
		const double Dot = FVector2D::DotProduct(Forward, Dir);
		if (Dot > 0.3) { PenA = MmsUTurnCm; }
		if (Dot < -0.3) { PenB = MmsUTurnCm; }
	}
	const int32 N = Nodes.Num();
	const int32 S = N, G = N + 1;
	TArray<double> Cost;
	TArray<int32> Prev, PrevEdge;
	Cost.Init(TNumericLimits<double>::Max(), N + 2);
	Prev.Init(-1, N + 2);
	PrevEdge.Init(-1, N + 2);
	TArray<bool> Done;
	Done.Init(false, N + 2);
	struct FOpen { double F; int32 Node; bool operator<(const FOpen& O) const { return F < O.F; } };
	TArray<FOpen> Open;
	auto Pos = [&](int32 n) { return n == S ? Ps : n == G ? Pg : Nodes[n]; };
	auto Relax = [&](int32 From_, int32 To_, double C, int32 Edge)
	{
		const double NC = Cost[From_] + C;
		if (NC < Cost[To_])
		{
			Cost[To_] = NC;
			Prev[To_] = From_;
			PrevEdge[To_] = Edge;
			Open.HeapPush({ NC + FVector2D::Distance(Pos(To_), Pg), To_ });
		}
	};
	Cost[S] = 0.0;
	Open.HeapPush({ 0.0, S });
	while (Open.Num() > 0)
	{
		FOpen Top;
		Open.HeapPop(Top, EAllowShrinking::No);
		const int32 U = Top.Node;
		if (Done[U]) { continue; }
		Done[U] = true;
		if (U == G) { break; }
		if (U == S)
		{
			const FEdge& E = Edges[Es];
			Relax(S, E.A, As + PenA, Es);
			Relax(S, E.B, E.Length - As + PenB, Es);
			if (Es == Eg) { Relax(S, G, FMath::Abs(Ag - As) + (Ag >= As ? PenB : PenA), Es); }
			continue;
		}
		for (int32 e : NodeEdges[U])
		{
			const FEdge& E = Edges[e];
			Relax(U, E.A == U ? E.B : E.A, E.Length, e);
			if (e == Eg) { Relax(U, G, E.A == U ? Ag : E.Length - Ag, e); }
		}
	}
	if (Prev[G] < 0)
	{
		return StraightLine(TEXT("unreachable on the road graph"));
	}
	TArray<int32> Chain;
	for (int32 n = G; n >= 0; n = Prev[n]) { Chain.Insert(n, 0); }
	AddRoutePoint(Ps, Edges[Es].Street);
	for (int32 i = 1; i < Chain.Num(); ++i)
	{
		const int32 P = Chain[i - 1], Q = Chain[i];
		const int32 e = PrevEdge[Q];
		const FEdge& E = Edges[e];
		if (P == S && Q == G) { AppendEdgePart(e, As, Ag); }
		else if (P == S) { AppendEdgePart(e, As, Q == E.A ? 0.0 : E.Length); }
		else if (Q == G) { AppendEdgePart(e, P == E.A ? 0.0 : E.Length, Ag); }
		else { AppendEdgePart(e, P == E.A ? 0.0 : E.Length, P == E.A ? E.Length : 0.0); }
	}
	RoadEnd = Pg;
	bArriveAtRoadEnd = Dg > MmsArriveCm;    // (in a building, a park, over the river: reaching the street end is arriving)
	if (Dg > 500.0)
	{
		AddRoutePoint(Destination, -1);     // off-road destination: the last bit straight across
	}
	if (Route.Num() < 2)
	{
		AddRoutePoint(Destination, -1);
	}
	RouteCum.SetNum(Route.Num());
	RouteCum[0] = 0.0;
	for (int32 i = 1; i < Route.Num(); ++i) { RouteCum[i] = RouteCum[i - 1] + FVector2D::Distance(Route[i - 1], Route[i]); }
	// turns: where the street changes, with the heading change over +-15 m
	for (int32 i = 1; i + 1 < Route.Num(); ++i)
	{
		const int32 S0 = RouteStreets[i], S1 = RouteStreets[i + 1];
		if (S1 < 0 || S0 == S1)
		{
			continue;
		}
		const FVector2D D0 = (Route[i] - RoutePointAt(RouteCum[i] - 1500.0)).GetSafeNormal();
		const FVector2D D1 = (RoutePointAt(RouteCum[i] + 1500.0) - Route[i]).GetSafeNormal();
		const double Angle = FMath::RadiansToDegrees(FMath::Atan2(D0.X * D1.Y - D0.Y * D1.X, FVector2D::DotProduct(D0, D1)));
		Maneuvers.Add({ RouteCum[i], Angle > 30.0 ? 1 : Angle < -30.0 ? -1 : 0, S1 });   // X east, Y south: positive = clockwise = right
	}
	return true;
}

void UMinimapSubsystem::UpdateProgress(const FVector2D& Car)
{
	if (Route.Num() < 2)
	{
		return;
	}
	double Best = TNumericLimits<double>::Max();
	for (int32 i = 0; i + 1 < Route.Num(); ++i)
	{
		double T;
		const FVector2D C = MmsClosestOnSegment(Car, Route[i], Route[i + 1], T);
		const double D = FVector2D::DistSquared(Car, C);
		if (D < Best)
		{
			Best = D;
			RouteSeg = i;
			RouteProj = C;
			RouteAlong = FMath::Lerp(RouteCum[i], RouteCum[i + 1], T);
		}
	}
	OffRouteCm = FMath::Sqrt(Best);
}

void UMinimapSubsystem::SetDestination(const FVector2D& World, int32 EventIndex)
{
	bHasDestination = true;
	DestinationLabel.Reset();
	Destination = MapBounds.bIsValid ? FVector2D(FMath::Clamp(World.X, MapBounds.Min.X, MapBounds.Max.X), FMath::Clamp(World.Y, MapBounds.Min.Y, MapBounds.Max.Y)) : World;
	DestinationEvent = EventIndex;
	ArrivedAt = -100.0;
	Route.Reset();
	bRouteFailed = false;
	FVector2D Car;
	float Yaw, Kmh;
	if (GetCarPose(Car, Yaw, Kmh))
	{
		ComputeRoute(Car, FVector2D(FMath::Cos(FMath::DegreesToRadians(Yaw)), FMath::Sin(FMath::DegreesToRadians(Yaw))));
		UpdateProgress(Car);
	}
	SinceRoute = 0.0;
	UE_LOG(LogMinimap, Display, TEXT("GPS to %s (%.0f, %.0f): %d route points, %.0f m"), *DestinationName(), Destination.X, Destination.Y, Route.Num(),
		RouteCum.Num() ? RouteCum.Last() / 100.0 : 0.0);
}

void UMinimapSubsystem::NavigateToEvent(int32 EventIndex)
{
	const UTimeTrialSubsystem* TT = GetTimeTrial();
	if (TT && TT->GetTracks().IsValidIndex(EventIndex))
	{
		SetDestination(FVector2D(TT->GetTracks()[EventIndex].StartLocation), EventIndex);
	}
}

void UMinimapSubsystem::SetNamedDestination(const FVector2D& World, const FString& Name)
{
	SetDestination(World);
	DestinationLabel = Name;
}

void UMinimapSubsystem::ClearDestination()
{
	bHasDestination = false;
	DestinationEvent = -1;
	DestinationLabel.Reset();
	Route.Reset();
	RouteStreets.Reset();
	RouteCum.Reset();
	Maneuvers.Reset();
	bRouteFailed = false;
	bArriveAtRoadEnd = false;
}

FString UMinimapSubsystem::DestinationName() const
{
	const UTimeTrialSubsystem* TT = GetTimeTrial();
	if (TT && TT->GetTracks().IsValidIndex(DestinationEvent))
	{
		return TT->GetTracks()[DestinationEvent].Name;
	}
	if (!DestinationLabel.IsEmpty())
	{
		return DestinationLabel;
	}
	return TEXT("Waypoint");
}

void UMinimapSubsystem::Arrive()
{
	ArrivedName = DestinationName();
	ArrivedAt = FPlatformTime::Seconds();
	UE_LOG(LogMinimap, Display, TEXT("GPS: arrived at %s"), *ArrivedName);
	ClearDestination();
}

void UMinimapSubsystem::Tick(float DeltaTime)
{
	AttachHUD();
	FVector2D Car;
	float Yaw, Kmh;
	if (!GetCarPose(Car, Yaw, Kmh))
	{
		return;
	}
	// street under the car (title chip)
	{
		int32 Edge;
		double Along, Dist;
		FVector2D Pt;
		CarStreet = Project(Car, Edge, Along, Pt, Dist, nullptr, 2000.0) && Dist < 2000.0 ? Edges[Edge].Street : -1;
	}
	if (!bHasDestination)
	{
		return;
	}
	const UTimeTrialSubsystem* TT = GetTimeTrial();
	if (IsInEvent())
	{
		if (TT && TT->GetActiveTrack() == DestinationEvent)
		{
			ClearDestination();     // started the event we were driving to
		}
		return;
	}
	const double Dist = FVector2D::Distance(Car, Destination);
	if ((DestinationEvent >= 0 && (Dist < MmsArriveEventCm || (TT && TT->GetNearMarker() == DestinationEvent))) || (DestinationEvent < 0 && Dist < MmsArriveCm)
		|| (bArriveAtRoadEnd && !bRouteFailed && FVector2D::Distance(Car, RoadEnd) < MmsArriveCm))
	{
		Arrive();
		return;
	}
	SinceRoute += DeltaTime;
	UpdateProgress(Car);
	if (((Route.Num() < 2 || OffRouteCm > MmsOffRouteCm) && SinceRoute > 0.5 && !bRouteFailed) || SinceRoute > MmsRecomputeSeconds)
	{
		ComputeRoute(Car, FVector2D(FMath::Cos(FMath::DegreesToRadians(Yaw)), FMath::Sin(FMath::DegreesToRadians(Yaw))));
		UpdateProgress(Car);
		SinceRoute = 0.0;
	}
}

FText UMinimapSubsystem::GetDistanceText() const
{
	if (!bHasDestination || IsInEvent())      // during an event the race HUD shows the distance to the next checkpoint
	{
		return FText::GetEmpty();
	}
	double Cm;
	if (Route.Num() >= 2 && RouteCum.Num() == Route.Num())
	{
		Cm = RouteCum.Last() - RouteAlong + OffRouteCm;
	}
	else
	{
		FVector2D Car;
		float Yaw, Kmh;
		Cm = GetCarPose(Car, Yaw, Kmh) ? FVector2D::Distance(Car, Destination) : 0.0;
	}
	return FText::FromString(MmsDistance(Cm));
}

bool UMinimapSubsystem::HasInstruction() const
{
	if (bHasDestination)
	{
		return Route.Num() >= 2 && !IsInEvent();
	}
	return FPlatformTime::Seconds() - ArrivedAt < MmsArrivedNoteSeconds;
}

FText UMinimapSubsystem::GetInstructionText() const
{
	if (!bHasDestination)
	{
		return FText::Format(LOCTEXT("Arrived", "Arrived: {0}"), FText::FromString(ArrivedName));
	}
	for (const FMinimapManeuver& Mv : Maneuvers)
	{
		if (Mv.Along > RouteAlong + 300.0)
		{
			const FText Street = StreetNames.IsValidIndex(Mv.Street) ? FText::FromString(StreetNames[Mv.Street]) : LOCTEXT("TheRoad", "the road");
			return Mv.Turn < 0 ? FText::Format(LOCTEXT("TurnLeft", "Turn left onto {0}"), Street)
				: Mv.Turn > 0 ? FText::Format(LOCTEXT("TurnRight", "Turn right onto {0}"), Street)
				: FText::Format(LOCTEXT("Continue", "Continue onto {0}"), Street);
		}
	}
	return FText::FromString(DestinationName());
}

FText UMinimapSubsystem::GetInstructionDistanceText() const
{
	if (!bHasDestination)
	{
		return FText::GetEmpty();
	}
	for (const FMinimapManeuver& Mv : Maneuvers)
	{
		if (Mv.Along > RouteAlong + 300.0)
		{
			return FText::FromString(MmsDistance(Mv.Along - RouteAlong));
		}
	}
	return GetDistanceText();
}

const FSlateBrush* UMinimapSubsystem::GetInstructionIcon() const
{
	if (bHasDestination)
	{
		for (const FMinimapManeuver& Mv : Maneuvers)
		{
			if (Mv.Along > RouteAlong + 300.0)
			{
				return GetIcon(Mv.Turn < 0 ? "minimap_turn_left" : Mv.Turn > 0 ? "minimap_turn_right" : "minimap_turn_straight");
			}
		}
	}
	return GetIcon("minimap_arrive");
}

// ------------------------------------------------------------------ full map

void UMinimapSubsystem::ToggleFullMap()
{
	IsFullMapOpen() ? CloseFullMap() : OpenFullMap();
}

void UMinimapSubsystem::OpenFullMap()
{
	UWorld* World = GetWorld();
	UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr;
	if (IsFullMapOpen() || !HasMap() || !Viewport)
	{
		return;
	}
	UGameInstance* GI = World->GetGameInstance();
	if (const UCambridgeMenuSubsystem* Menu = GI ? GI->GetSubsystem<UCambridgeMenuSubsystem>() : nullptr; Menu && Menu->IsMenuOpen())
	{
		return;     // the menu unpauses on close: never have both open
	}
	FVector2D Center = MapBounds.GetCenter();
	float Yaw, Kmh;
	GetCarPose(Center, Yaw, Kmh);
	FullMapWidget = MinimapUI::MakeFullMapScreen(this, FullMapView, Center, SavedZoom);
	Viewport->AddViewportWidgetContent(FullMapWidget.ToSharedRef(), 90);
	if (APlayerController* PC = World->GetFirstPlayerController())
	{
		FInputModeUIOnly Mode;
		Mode.SetWidgetToFocus(FullMapView);
		PC->SetInputMode(Mode);
		PC->SetShowMouseCursor(true);
		bPausedByMap = !PC->IsPaused();
		if (bPausedByMap)
		{
			UGameplayStatics::SetGamePaused(PC, true);
		}
	}
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().SetKeyboardFocus(FullMapView);
	}
}

void UMinimapSubsystem::CloseFullMap()
{
	if (!FullMapWidget.IsValid())
	{
		return;
	}
	if (FullMapView.IsValid())
	{
		SavedZoom = FullMapView->GetZoom();
	}
	UWorld* World = GetWorld();
	if (UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr)
	{
		Viewport->RemoveViewportWidgetContent(FullMapWidget.ToSharedRef());
	}
	FullMapWidget.Reset();
	FullMapView.Reset();
	if (Input.IsValid())
	{
		Input->Reset();
	}
	if (APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr)
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->SetShowMouseCursor(false);
		if (bPausedByMap)
		{
			UGameplayStatics::SetGamePaused(PC, false);
		}
	}
	bPausedByMap = false;
}

void UMinimapSubsystem::SetFullMapView(const FVector2D& Center, float PxPerM)
{
	OpenFullMap();
	if (FullMapView.IsValid())
	{
		FullMapView->SetView(Center, PxPerM);
	}
}

#undef LOCTEXT_NAMESPACE

// ------------------------------------------------------------------ console (tests / screenshots)

namespace
{
	UMinimapSubsystem* MmsGet(UWorld* World)
	{
		return World ? World->GetSubsystem<UMinimapSubsystem>() : nullptr;
	}

	FAutoConsoleCommandWithWorldAndArgs MmsToggleCmd(TEXT("cr.Map.Toggle"), TEXT("Open / close the full-screen map (cr.Map.Toggle [0|1])"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UMinimapSubsystem* M = MmsGet(World))
			{
				if (Args.Num() == 0) { M->ToggleFullMap(); }
				else if (FCString::Atoi(*Args[0]) != 0) { M->OpenFullMap(); }
				else { M->CloseFullMap(); }
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs MmsWaypointCmd(TEXT("cr.Map.SetWaypoint"), TEXT("GPS to a world point: cr.Map.SetWaypoint X Y (UE cm)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UMinimapSubsystem* M = MmsGet(World); M && Args.Num() >= 2)
			{
				M->SetDestination(FVector2D(FCString::Atod(*Args[0]), FCString::Atod(*Args[1])));
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs MmsEventCmd(TEXT("cr.Map.NavigateToEvent"), TEXT("GPS to event N's start: cr.Map.NavigateToEvent N"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UMinimapSubsystem* M = MmsGet(World))
			{
				M->NavigateToEvent(Args.Num() ? FCString::Atoi(*Args[0]) : 0);
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs MmsClearCmd(TEXT("cr.Map.Clear"), TEXT("Clear the GPS waypoint"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
		{
			if (UMinimapSubsystem* M = MmsGet(World)) { M->ClearDestination(); }
		}));

	FAutoConsoleCommandWithWorldAndArgs MmsViewCmd(TEXT("cr.Map.View"), TEXT("Open the full map centred on X Y (UE cm), optional zoom in px per metre"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (UMinimapSubsystem* M = MmsGet(World); M && Args.Num() >= 2)
			{
				M->SetFullMapView(FVector2D(FCString::Atod(*Args[0]), FCString::Atod(*Args[1])), Args.Num() >= 3 ? FCString::Atof(*Args[2]) : 0.0f);
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs MmsCursorEventCmd(TEXT("cr.Map.CursorToEvent"), TEXT("Open the full map with the cursor on event N (hover card)"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			UMinimapSubsystem* M = MmsGet(World);
			const UTimeTrialSubsystem* TT = M ? M->GetTimeTrial() : nullptr;
			const int32 N = Args.Num() ? FCString::Atoi(*Args[0]) : 0;
			if (TT && TT->GetTracks().IsValidIndex(N) && TT->GetTracks()[N].Gates.Num() > 0)
			{
				M->SetFullMapView(FVector2D(TT->GetTracks()[N].Gates[0].Location), Args.Num() >= 2 ? FCString::Atof(*Args[1]) : 0.0f);
				if (TSharedPtr<SFullMapView> View = M->GetFullMapView()) { View->FocusEvent(N); }
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs MmsMinimapCmd(TEXT("cr.Map.Minimap"), TEXT("HUD minimap off / on (cr.Map.Minimap 0|1), saved like the menu setting"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld*)
		{
			if (UCambridgeGameUserSettings* S = UCambridgeGameUserSettings::Get())
			{
				S->bShowMinimap = Args.Num() ? FCString::Atoi(*Args[0]) != 0 : !S->bShowMinimap;
				S->SaveSettings();
			}
		}));
}
