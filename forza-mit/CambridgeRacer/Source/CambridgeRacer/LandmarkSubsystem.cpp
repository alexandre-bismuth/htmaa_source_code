#include "LandmarkSubsystem.h"

#include "CambridgeUIStyle.h"
#include "Components/PrimitiveComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/GameViewportClient.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Pawn.h"
#include "HAL/IConsoleManager.h"
#include "ImageUtils.h"
#include "Kismet/GameplayStatics.h"
#include "LandmarkActor.h"
#include "MinimapSubsystem.h"
#include "MinimapWidgets.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Rendering/DrawElements.h"
#include "Rendering/SlateRenderer.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "TextureResource.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "Landmarks"

DEFINE_LOG_CATEGORY_STATIC(LogLandmarks, Log, All);

namespace
{
	constexpr float LmsArriveCm = 4500.0f;        // "arrived" toast: car stopped within this of the sign's anchor
	constexpr float LmsRearmCm = 12000.0f;        // ... shown again only after driving this far away
	constexpr float LmsStoppedKmh = 8.0f;
	constexpr float LmsStoppedSeconds = 0.6f;
	constexpr double LmsToastSeconds = 5.0;

	FString LmsMapName(const UWorld* World)
	{
		return FPackageName::GetShortName(World->GetOutermost()->GetName()).Replace(TEXT("UEDPIE_0_"), TEXT(""));
	}

	FVector LmsVec(const TSharedPtr<FJsonObject>& O, const TCHAR* Field)
	{
		const TArray<TSharedPtr<FJsonValue>>* A;
		if (O->TryGetArrayField(Field, A) && A->Num() >= 2)
		{
			return FVector((*A)[0]->AsNumber(), (*A)[1]->AsNumber(), A->Num() > 2 ? (*A)[2]->AsNumber() : 0.0);
		}
		return FVector::ZeroVector;
	}

	FString LmsDistance(double Cm)
	{
		const double M = Cm / 100.0;
		return M >= 1000.0 ? FString::Printf(TEXT("%.1f km"), M / 1000.0) : FString::Printf(TEXT("%d m"), FMath::RoundToInt(M / 10.0) * 10);
	}

	FVector2D LmsMeasure(const FString& Text, const FSlateFontInfo& Font)
	{
		if (!FSlateApplication::IsInitialized())
		{
			return FVector2D(Text.Len() * 8.0, 14.0);
		}
		return FVector2D(FSlateApplication::Get().GetRenderer()->GetFontMeasureService()->Measure(Text, Font));
	}

	/** Largest t so that From + Dir * t stays inside [Margin, Size - Margin] (TopMargin for the top edge). */
	double LmsRayToRect(const FVector2D& From, const FVector2D& Dir, const FVector2D& Size, double Margin, double TopMargin)
	{
		double T = TNumericLimits<double>::Max();
		if (Dir.X > 1e-6) { T = FMath::Min(T, (Size.X - Margin - From.X) / Dir.X); }
		if (Dir.X < -1e-6) { T = FMath::Min(T, (Margin - From.X) / Dir.X); }
		if (Dir.Y > 1e-6) { T = FMath::Min(T, (Size.Y - Margin - From.Y) / Dir.Y); }
		if (Dir.Y < -1e-6) { T = FMath::Min(T, (TopMargin - From.Y) / Dir.Y); }
		return FMath::Max(0.0, T);
	}
}

// ------------------------------------------------------------------ subsystem

ULandmarkSubsystem* ULandmarkSubsystem::Get(const UObject* WorldContext)
{
	const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
	return World ? World->GetSubsystem<ULandmarkSubsystem>() : nullptr;
}

bool ULandmarkSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return Super::ShouldCreateSubsystem(Outer) && !IsRunningCommandlet();
}

TStatId ULandmarkSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(ULandmarkSubsystem, STATGROUP_Tickables);
}

void ULandmarkSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!InWorld.IsGameWorld())
	{
		return;
	}
	Load(LmsMapName(&InWorld));
	const bool bRender = FSlateApplication::IsInitialized() && !FParse::Param(FCommandLine::Get(), TEXT("nullrhi"));
	if (bRender && Landmarks.Num() > 0 && !FParse::Param(FCommandLine::Get(), TEXT("DriveTest")))
	{
		SpawnSigns();
	}
	StoppedFor.Init(0.0f, Landmarks.Num());
	Armed.Init(true, Landmarks.Num());
	bReady = Landmarks.Num() > 0;
}

void ULandmarkSubsystem::Deinitialize()
{
	if (ToastHost.IsValid() && ToastViewport.IsValid())
	{
		ToastViewport->RemoveViewportWidgetContent(ToastHost.ToSharedRef());
	}
	ToastHost.Reset();
	Super::Deinitialize();
}

void ULandmarkSubsystem::Load(const FString& MapName)
{
	const FString Path = FPaths::ProjectDir() / TEXT("Tracks") / (MapName + TEXT("_landmarks.json"));
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!FFileHelper::LoadFileToString(Text, *Path) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
	{
		UE_LOG(LogLandmarks, Display, TEXT("no landmarks for %s (%s): run `cd tools/mapgen && uv run ../minimap/landmarks.py %s`"), *MapName, *Path, *MapName);
		return;
	}
	const TArray<TSharedPtr<FJsonValue>>* Arr;
	if (!Root->TryGetArrayField(TEXT("landmarks"), Arr))
	{
		return;
	}
	for (const TSharedPtr<FJsonValue>& V : *Arr)
	{
		const TSharedPtr<FJsonObject> O = V->AsObject();
		FLandmarkDef& L = Landmarks.AddDefaulted_GetRef();
		L.Id = O->GetStringField(TEXT("id"));
		L.Label = O->GetStringField(TEXT("label"));
		L.Subtitle = O->GetStringField(TEXT("subtitle"));
		L.Address = O->GetStringField(TEXT("address"));
		L.Building = O->GetStringField(TEXT("building"));
		L.Icon = FName(*O->GetStringField(TEXT("icon")));
		L.IconLg = FName(*(L.Icon.ToString() + TEXT("_lg")));
		L.Accent = FLinearColor(FColor::FromHex(O->GetStringField(TEXT("accent"))));
		L.Entrance = LmsVec(O, TEXT("entrance"));
		L.Anchor = LmsVec(O, TEXT("anchor"));
		L.RoofCm = float(O->GetNumberField(TEXT("roof_m")) * 100.0);
		L.FadeFarM = FVector2D(LmsVec(O, TEXT("fade_far_m")));
		const TArray<TSharedPtr<FJsonValue>>* Views;
		if (O->TryGetArrayField(TEXT("viewpoints"), Views))
		{
			for (const TSharedPtr<FJsonValue>& VV : *Views)
			{
				const TSharedPtr<FJsonObject> VO = VV->AsObject();
				FLandmarkView& View = L.Views.AddDefaulted_GetRef();
				View.Location = LmsVec(VO, TEXT("loc"));
				View.Yaw = float(VO->GetNumberField(TEXT("yaw")));
				View.DistanceM = float(VO->GetNumberField(TEXT("d_m")));
			}
		}
	}
	UE_LOG(LogLandmarks, Display, TEXT("landmarks %s: %d"), *MapName, Landmarks.Num());
}

UTexture2D* ULandmarkSubsystem::LoadTexture(const FString& Path)
{
	FImage Image;
	if (!FImageUtils::LoadImage(*Path, Image))
	{
		UE_LOG(LogLandmarks, Warning, TEXT("cannot load %s (run tools/ui/make_landmark_signs.py)"), *Path);
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
	Tex->Filter = TF_Trilinear;      // the art is drawn 4 texels per pixel: mips keep it from shimmering far away
	Tex->LODGroup = TEXTUREGROUP_UI;
	Tex->AddressX = TA_Clamp;
	Tex->AddressY = TA_Clamp;
	FTexturePlatformData* PD = Tex->GetPlatformData();
	{
		void* Dest = PD->Mips[0].BulkData.Lock(LOCK_READ_WRITE);
		FMemory::Memcpy(Dest, Image.RawData.GetData(), int64(W) * H * 4);
		PD->Mips[0].BulkData.Unlock();
	}
	// box-filtered mips with premultiplied averaging (no dark fringes around the glow)
	TArray<FLinearColor> Prev;
	Prev.SetNumUninitialized(W * H);
	const FColor* Src = reinterpret_cast<const FColor*>(Image.RawData.GetData());
	for (int32 i = 0; i < W * H; ++i)
	{
		FLinearColor C(Src[i].R / 255.0f, Src[i].G / 255.0f, Src[i].B / 255.0f, Src[i].A / 255.0f);
		Prev[i] = FLinearColor(C.R * C.A, C.G * C.A, C.B * C.A, C.A);
	}
	int32 PW = W, PH = H;
	TArray<FLinearColor> Next;
	TArray<FColor> Out;
	while (PW > 1 || PH > 1)
	{
		const int32 NW = FMath::Max(1, PW / 2), NH = FMath::Max(1, PH / 2);
		Next.SetNumUninitialized(NW * NH);
		Out.SetNumUninitialized(NW * NH);
		for (int32 y = 0; y < NH; ++y)
		{
			const int32 y0 = FMath::Min(y * 2, PH - 1), y1 = FMath::Min(y * 2 + 1, PH - 1);
			for (int32 x = 0; x < NW; ++x)
			{
				const int32 x0 = FMath::Min(x * 2, PW - 1), x1 = FMath::Min(x * 2 + 1, PW - 1);
				const FLinearColor C = (Prev[y0 * PW + x0] + Prev[y0 * PW + x1] + Prev[y1 * PW + x0] + Prev[y1 * PW + x1]) * 0.25f;
				Next[y * NW + x] = C;
				const float A = FMath::Max(C.A, 1e-4f);
				Out[y * NW + x] = FColor(uint8(FMath::Clamp(C.R / A, 0.0f, 1.0f) * 255.0f + 0.5f), uint8(FMath::Clamp(C.G / A, 0.0f, 1.0f) * 255.0f + 0.5f),
					uint8(FMath::Clamp(C.B / A, 0.0f, 1.0f) * 255.0f + 0.5f), uint8(FMath::Clamp(C.A, 0.0f, 1.0f) * 255.0f + 0.5f));
			}
		}
		FTexture2DMipMap* Mip = new FTexture2DMipMap(NW, NH, 1);
		PD->Mips.Add(Mip);
		Mip->BulkData.Lock(LOCK_READ_WRITE);
		void* Dest = Mip->BulkData.Realloc(int64(NW) * NH * 4);
		FMemory::Memcpy(Dest, Out.GetData(), int64(NW) * NH * 4);
		Mip->BulkData.Unlock();
		Swap(Prev, Next);
		PW = NW;
		PH = NH;
	}
	Tex->UpdateResource();
	Textures.Add(Tex);
	return Tex;
}

void ULandmarkSubsystem::SpawnSigns()
{
	const FString Dir = FCambridgeUIStyle::GeneratedDir();
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!FFileHelper::LoadFileToString(Text, *(Dir / TEXT("landmark_signs.json"))) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
	{
		UE_LOG(LogLandmarks, Warning, TEXT("no %s: run `cd tools/ui && uv run make_landmark_signs.py`"), *(Dir / TEXT("landmark_signs.json")));
		return;
	}
	const float MPerPx = float(Root->GetNumberField(TEXT("m_per_art_px")));
	const TSharedPtr<FJsonObject>* Per;
	if (!Root->TryGetObjectField(TEXT("landmarks"), Per))
	{
		return;
	}
	for (const FLandmarkDef& L : Landmarks)
	{
		const TSharedPtr<FJsonObject>* Art;
		if (!(*Per)->TryGetObjectField(L.Id, Art))
		{
			UE_LOG(LogLandmarks, Warning, TEXT("no sign art for landmark %s"), *L.Id);
			continue;
		}
		const TSharedPtr<FJsonObject> P = (*Art)->GetObjectField(TEXT("panel"));
		const TSharedPtr<FJsonObject> A = (*Art)->GetObjectField(TEXT("arrow"));
		const TSharedPtr<FJsonObject> B = (*Art)->GetObjectField(TEXT("beam"));
		FLandmarkSignLayout Layout;
		Layout.MetresPerArtPx = MPerPx;
		const TArray<TSharedPtr<FJsonValue>>& PC = P->GetArrayField(TEXT("canvas"));
		Layout.PanelCanvas = FVector2D(PC[0]->AsNumber(), PC[1]->AsNumber());
		Layout.PanelTailY = float(P->GetNumberField(TEXT("tail_y")));
		const TArray<TSharedPtr<FJsonValue>>& AC = A->GetArrayField(TEXT("canvas"));
		Layout.ArrowCanvas = FVector2D(AC[0]->AsNumber(), AC[1]->AsNumber());
		Layout.ArrowTopY = float(A->GetNumberField(TEXT("top_y")));
		Layout.ArrowTipY = float(A->GetNumberField(TEXT("tip_y")));

		UTexture2D* PanelTex = LoadTexture(Dir / P->GetStringField(TEXT("file")));
		UTexture2D* ArrowTex = LoadTexture(Dir / A->GetStringField(TEXT("file")));
		UTexture2D* BeamTex = LoadTexture(Dir / B->GetStringField(TEXT("file")));
		FActorSpawnParameters SP;
		SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		SP.ObjectFlags |= RF_Transient;
		ALandmarkActor* Sign = GetWorld()->SpawnActor<ALandmarkActor>(ALandmarkActor::StaticClass(), FTransform(L.Anchor), SP);
		if (Sign)
		{
			Sign->Setup(L.Anchor, L.RoofCm, L.Accent, Layout, PanelTex, ArrowTex, BeamTex);
			if (L.FadeFarM.Y > L.FadeFarM.X && L.FadeFarM.X > 0.0)
			{
				Sign->SetFadeFar(float(L.FadeFarM.X * 100.0), float(L.FadeFarM.Y * 100.0));
			}
			Signs.Add(Sign);
		}
	}
	UE_LOG(LogLandmarks, Display, TEXT("landmark signs: %d"), Signs.Num());
}

int32 ULandmarkSubsystem::Find(const FString& IdOrIndex) const
{
	for (int32 i = 0; i < Landmarks.Num(); ++i)
	{
		if (Landmarks[i].Id.Equals(IdOrIndex, ESearchCase::IgnoreCase))
		{
			return i;
		}
	}
	if (IdOrIndex.IsNumeric())
	{
		const int32 N = FCString::Atoi(*IdOrIndex);
		return Landmarks.IsValidIndex(N) ? N : -1;
	}
	return -1;
}

void ULandmarkSubsystem::NavigateTo(int32 Index)
{
	UMinimapSubsystem* M = UMinimapSubsystem::Get(this);
	if (M && Landmarks.IsValidIndex(Index))
	{
		M->SetNamedDestination(FVector2D(Landmarks[Index].Anchor), Landmarks[Index].Label);
	}
}

void ULandmarkSubsystem::GoTo(int32 Index, float Metres)
{
	APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0);
	if (!Pawn || !Landmarks.IsValidIndex(Index) || Landmarks[Index].Views.Num() == 0)
	{
		return;
	}
	const FLandmarkView* Best = nullptr;
	for (const FLandmarkView& V : Landmarks[Index].Views)
	{
		if (!Best || FMath::Abs(V.DistanceM - Metres) < FMath::Abs(Best->DistanceM - Metres))
		{
			Best = &V;
		}
	}
	Pawn->SetActorTransform(FTransform(FRotator(0.0f, Best->Yaw, 0.0f), Best->Location), false, nullptr, ETeleportType::TeleportPhysics);
	if (UPrimitiveComponent* Body = Cast<UPrimitiveComponent>(Pawn->GetRootComponent()))
	{
		Body->SetPhysicsLinearVelocity(FVector::ZeroVector);
		Body->SetPhysicsAngularVelocityInDegrees(FVector::ZeroVector);
	}
	StoppedFor.Init(0.0f, Landmarks.Num());
	UE_LOG(LogLandmarks, Display, TEXT("car to %s view %.0f m (%.0f, %.0f) yaw %.0f"), *Landmarks[Index].Id, Best->DistanceM, Best->Location.X, Best->Location.Y, Best->Yaw);
}

void ULandmarkSubsystem::ShowToast(int32 Index)
{
	if (Landmarks.IsValidIndex(Index))
	{
		ToastIndex = Index;
		ToastAt = FPlatformTime::Seconds();
		UE_LOG(LogLandmarks, Display, TEXT("arrived at %s"), *Landmarks[Index].Label);
	}
}

void ULandmarkSubsystem::SetSignsVisible(bool bVisible)
{
	for (ALandmarkActor* S : Signs)
	{
		if (S)
		{
			S->SetActorTickEnabled(bVisible);
			S->SetActorHiddenInGame(!bVisible);
		}
	}
}

void ULandmarkSubsystem::AttachToastHost()
{
	UGameViewportClient* Viewport = GetWorld()->GetGameViewport();
	if (!Viewport || !FSlateApplication::IsInitialized() || (ToastHost.IsValid() && ToastViewport.Get() == Viewport))
	{
		return;
	}
	namespace CUI = CambridgeUI;
	TWeakObjectPtr<ULandmarkSubsystem> W(this);
	auto Valid = [W]() { return W.IsValid() && W->Landmarks.IsValidIndex(W->ToastIndex); };
	TSharedRef<SWidget> Header = SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0, 0, 10, 0)
		[
			SNew(SBox).WidthOverride(30).HeightOverride(30)
			[
				SNew(SImage).Image_Lambda([W, Valid]() -> const FSlateBrush*
				{
					const UMinimapSubsystem* M = W.IsValid() ? UMinimapSubsystem::Get(W.Get()) : nullptr;
					return M && Valid() ? M->GetIcon(W->Landmarks[W->ToastIndex].IconLg) : nullptr;
				})
			]
		]
		+ SHorizontalBox::Slot().FillWidth(1.0f).VAlign(VAlign_Center)
		[
			SNew(STextBlock).TextStyle(&CUI::Text("ToastTitle"))
			.Text_Lambda([W, Valid]() { return Valid() ? FText::FromString(W->Landmarks[W->ToastIndex].Label) : FText::GetEmpty(); })
		];
	TSharedRef<SWidget> Toast = CUI::MakeToastCustom(Header, TAttribute<FText>::CreateLambda([W, Valid]()
	{
		if (!Valid())
		{
			return FText::GetEmpty();
		}
		const FLandmarkDef& L = W->Landmarks[W->ToastIndex];
		return FText::Format(LOCTEXT("ToastBody", "You have arrived  ·  {0}\n{1}"), FText::FromString(L.Address), FText::FromString(L.Building));
	}), CUI::ETail::None, 380.0f);
	ToastHost = SNew(SOverlay).Visibility(EVisibility::HitTestInvisible)
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(0, 96, 0, 0)
		[
			SNew(SBox)
			.WidthOverride(420)
			.Visibility_Lambda([W, Valid]()
			{
				return Valid() && FPlatformTime::Seconds() - W->ToastAt < LmsToastSeconds ? EVisibility::HitTestInvisible : EVisibility::Collapsed;
			})
			[
				CUI::MakeAnimatedIn(Toast, TAttribute<float>::CreateLambda([W]() { return W.IsValid() ? float(FPlatformTime::Seconds() - W->ToastAt) : 10.0f; }), 0.18f, 0.9f)
			]
		];
	Viewport->AddViewportWidgetContent(ToastHost.ToSharedRef(), 42);
	ToastViewport = Viewport;
}

void ULandmarkSubsystem::Tick(float DeltaTime)
{
	AttachToastHost();
	const APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0);
	if (!Pawn)
	{
		return;
	}
	const FVector2D Car(Pawn->GetActorLocation());
	const float Kmh = float(Pawn->GetVelocity().Size2D() * 0.036);
	for (int32 i = 0; i < Landmarks.Num(); ++i)
	{
		const float D = float(FVector2D::Distance(Car, FVector2D(Landmarks[i].Anchor)));
		if (D > LmsRearmCm)
		{
			Armed[i] = true;
		}
		StoppedFor[i] = (D < LmsArriveCm && Kmh < LmsStoppedKmh) ? StoppedFor[i] + DeltaTime : 0.0f;
		if (Armed[i] && StoppedFor[i] > LmsStoppedSeconds)
		{
			Armed[i] = false;
			ShowToast(i);
		}
	}
}

// ------------------------------------------------------------------ map tags

namespace LandmarkMap
{
	void PaintMinimap(const UMinimapSubsystem& Map, const FMmXform& X, const FVector2D& S, const FGeometry& G,
		FSlateWindowElementList& Out, int32 Layer)
	{
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		if (!L)
		{
			return;
		}
		for (const FLandmarkDef& D : L->GetLandmarks())
		{
			const FSlateBrush* B = Map.GetIcon(D.Icon);
			if (!B)
			{
				continue;
			}
			const FVector2D P = X.ToLocal(FVector2D(D.Anchor));
			const double Margin = 14.0;
			const double Top = Map.HasInstruction() ? 50.0 : Margin;      // keep clear of the GPS instruction pill
			if (P.X >= Margin && P.Y >= Top && P.X <= S.X - Margin && P.Y <= S.Y - Margin)
			{
				FMmPainter::DrawIcon(B, P, FVector2D(24.0), G, Out, Layer);
			}
			else
			{
				// off the map: the tag rides the frame edge, with an accent arrow pointing at the landmark
				const FVector2D Dir = P - X.Origin;
				const FVector2D N = Dir.GetSafeNormal();
				const FVector2D E = X.Origin + Dir * LmsRayToRect(X.Origin, Dir, S, 9.0, Top - 5.0);
				const float Angle = float(FMath::Atan2(N.Y, N.X) + UE_HALF_PI);
				FMmPainter::DrawIcon(Map.GetIcon("minimap_edge"), E, FVector2D(13.0), G, Out, Layer, D.Accent, Angle);
				FMmPainter::DrawIcon(B, E - N * 16.0, FVector2D(19.0), G, Out, Layer, FLinearColor(1, 1, 1, 0.92f));
			}
		}
	}

	int32 HitTest(const UMinimapSubsystem& Map, const FMmXform& X, const FVector2D& Cursor)
	{
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		int32 Hovered = -1;
		double Best = 30.0;
		for (int32 i = 0; L && i < L->GetLandmarks().Num(); ++i)
		{
			const double D = FVector2D::Distance(X.ToLocal(FVector2D(L->GetLandmarks()[i].Anchor)), Cursor);
			if (D < Best) { Best = D; Hovered = i; }
		}
		return Hovered;
	}

	void PlaceTags(const UMinimapSubsystem& Map, const FMmXform& X, int32 Hovered, const TArray<FVector2D>& EventBadges,
		TArray<FMmLandmarkTag>& Out)
	{
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		const int32 Num = L ? L->GetLandmarks().Num() : 0;
		Out.Reset();
		Out.SetNum(Num);
		static const FSlateFontInfo NameFont = CambridgeUI::PixelFont(12.0f, true);
		static const FSlateFontInfo SubFont = CambridgeUI::CondensedFont(10.0f);
		// what the label must not cover: event badges and the name / best time under each
		TArray<FBox2D, TInlineAllocator<32>> Avoid;
		for (const FVector2D& E : EventBadges)
		{
			Avoid.Add(FBox2D(E - FVector2D(24.0, 24.0), E + FVector2D(24.0, 24.0)));
			Avoid.Add(FBox2D(E + FVector2D(-125.0, 18.0), E + FVector2D(125.0, 58.0)));
		}
		for (int32 i = 0; i < Num; ++i)
		{
			const FLandmarkDef& D = L->GetLandmarks()[i];
			if (!Map.GetIcon(D.IconLg) && !Map.GetIcon(D.Icon))
			{
				continue;
			}
			FMmLandmarkTag& T = Out[i];
			T.bShown = true;
			T.Center = X.ToLocal(FVector2D(D.Anchor));
			T.IconPx = i == Hovered ? 48.0 : 40.0;
			T.Icon = FBox2D(T.Center - FVector2D(T.IconPx * 0.5), T.Center + FVector2D(T.IconPx * 0.5));
			T.NameSize = LmsMeasure(D.Label, NameFont);
			T.SubSize = LmsMeasure(D.Subtitle, SubFont);
			const FVector2D P = T.Center;
			const FVector2D Block(FMath::Max(T.NameSize.X, T.SubSize.X) + 18.0, T.NameSize.Y + T.SubSize.Y + 7.0);
			const double Gap = T.IconPx * 0.5 + 3.0;
			const FVector2D Candidates[] = {
				FVector2D(P.X - Block.X * 0.5, P.Y + Gap),                          // below
				FVector2D(P.X - Block.X * 0.5, P.Y - Gap - Block.Y),                // above
				FVector2D(P.X + Gap + 3.0, P.Y - Block.Y * 0.5),                    // right
				FVector2D(P.X - Gap - 3.0 - Block.X, P.Y - Block.Y * 0.5),          // left
				FVector2D(P.X - Block.X * 0.5, P.Y + Gap + 44.0),                   // further below (under an event name)
				FVector2D(P.X - Block.X * 0.5, P.Y - Gap - Block.Y - 40.0) };       // further above
			// least covered placement (first one wins ties: below is the default)
			FVector2D TL = Candidates[0];
			double BestOverlap = TNumericLimits<double>::Max();
			for (const FVector2D& C : Candidates)
			{
				const FBox2D Box(C, C + Block);
				double Overlap = 0.0;
				for (const FBox2D& A : Avoid)
				{
					if (A.Intersect(Box)) { Overlap += A.Overlap(Box).GetArea(); }
				}
				if (Overlap < BestOverlap - 1.0) { BestOverlap = Overlap; TL = C; }
			}
			T.Block = FBox2D(TL, TL + Block);
		}
	}

	void PaintFullMap(const UMinimapSubsystem& Map, const TArray<FMmLandmarkTag>& Tags, int32 Hovered, const FGeometry& G,
		FSlateWindowElementList& Out, int32 Layer)
	{
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		if (!L)
		{
			return;
		}
		static const FSlateFontInfo NameFont = CambridgeUI::PixelFont(12.0f, true);
		static const FSlateFontInfo SubFont = CambridgeUI::CondensedFont(10.0f);
		const TArray<FLandmarkDef>& All = L->GetLandmarks();
		const FSlateBrush* Pill = CambridgeUI::Brush("glass_pill");
		for (int32 i = 0; i < All.Num() && i < Tags.Num(); ++i)
		{
			const FMmLandmarkTag& T = Tags[i];
			const FLandmarkDef& D = All[i];
			const FSlateBrush* B = Map.GetIcon(D.IconLg);
			if (!B)
			{
				B = Map.GetIcon(D.Icon);
			}
			if (!T.bShown || !B)
			{
				continue;
			}
			const bool bHover = i == Hovered;
			if (bHover)
			{
				FMmPainter::DrawIcon(Map.GetIcon("minimap_dot"), T.Center, FVector2D(64.0), G, Out, Layer, D.Accent.CopyWithNewOpacity(0.5f));
			}
			FMmPainter::DrawIcon(B, T.Center, FVector2D(T.IconPx), G, Out, Layer + 1);
			const FVector2D TL = T.Block.Min;
			const FVector2D Block = T.Block.GetSize();
			if (Pill)
			{
				FSlateDrawElement::MakeBox(Out, Layer + 1, G.ToPaintGeometry(FVector2f(Block), FSlateLayoutTransform(FVector2f(TL))), Pill,
					ESlateDrawEffect::None, FLinearColor(1.0f, 1.0f, 1.0f, bHover ? 1.0f : 0.85f));
			}
			const double Cx = TL.X + Block.X * 0.5;
			FMmPainter::DrawText(D.Label, FVector2D(Cx - T.NameSize.X * 0.5, TL.Y + 3.0), NameFont, G, Out, Layer + 2, FLinearColor::White);
			const FLinearColor SubCol = FMath::Lerp(D.Accent, FLinearColor::White, 0.3f);
			FMmPainter::DrawText(D.Subtitle, FVector2D(Cx - T.SubSize.X * 0.5, TL.Y + 4.0 + T.NameSize.Y), SubFont, G, Out, Layer + 2, SubCol, false);
		}
	}

	FText CursorTitle(const UMinimapSubsystem& Map, int32 Index)
	{
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		return L && L->GetLandmarks().IsValidIndex(Index) ? FText::FromString(L->GetLandmarks()[Index].Label) : FText::GetEmpty();
	}

	FText CursorBody(const UMinimapSubsystem& Map, int32 Index)
	{
		const ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		if (!L || !L->GetLandmarks().IsValidIndex(Index))
		{
			return FText::GetEmpty();
		}
		const FLandmarkDef& D = L->GetLandmarks()[Index];
		FString S = D.Address + TEXT("\n") + D.Building;
		FVector2D Car;
		float Yaw, Kmh;
		if (Map.GetCarPose(Car, Yaw, Kmh))
		{
			S += TEXT("\n") + LmsDistance(FVector2D::Distance(Car, FVector2D(D.Anchor))) + TEXT(" from your car");
		}
		S += TEXT("\nEnter / A / click: set a GPS waypoint here");
		return FText::FromString(S);
	}

	bool Navigate(UMinimapSubsystem& Map, int32 Index)
	{
		ULandmarkSubsystem* L = ULandmarkSubsystem::Get(&Map);
		if (!L || !L->GetLandmarks().IsValidIndex(Index))
		{
			return false;
		}
		L->NavigateTo(Index);
		return true;
	}
}

// ------------------------------------------------------------------ console

namespace
{
	ULandmarkSubsystem* LmsGet(UWorld* World)
	{
		return World ? World->GetSubsystem<ULandmarkSubsystem>() : nullptr;
	}

	FAutoConsoleCommandWithWorldAndArgs LmsGoToCmd(TEXT("cr.Landmark.GoTo"), TEXT("cr.Landmark.GoTo <id|index> [metres]: put the car on the road that far from the landmark (50 / 150 / 300), heading towards it"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (ULandmarkSubsystem* L = LmsGet(World); L && Args.Num())
			{
				L->GoTo(L->Find(Args[0]), Args.Num() > 1 ? FCString::Atof(*Args[1]) : 150.0f);
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs LmsNavigateCmd(TEXT("cr.Landmark.Navigate"), TEXT("cr.Landmark.Navigate <id|index>: GPS waypoint to the landmark"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (ULandmarkSubsystem* L = LmsGet(World); L && Args.Num())
			{
				L->NavigateTo(L->Find(Args[0]));
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs LmsToastCmd(TEXT("cr.Landmark.Toast"), TEXT("cr.Landmark.Toast <id|index>: show the landmark's arrival toast"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (ULandmarkSubsystem* L = LmsGet(World); L && Args.Num())
			{
				L->ShowToast(L->Find(Args[0]));
			}
		}));

	FAutoConsoleCommandWithWorldAndArgs LmsSignsCmd(TEXT("cr.Landmark.Signs"), TEXT("cr.Landmark.Signs 0|1: hide / show the floating landmark signs"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (ULandmarkSubsystem* L = LmsGet(World))
			{
				L->SetSignsVisible(!Args.Num() || FCString::Atoi(*Args[0]) != 0);
			}
		}));
}

#undef LOCTEXT_NAMESPACE
