// STi car paint: WR Blue Mica with metallic flakes under a clear coat, non-metallic vinyl livery decals.
// Built by tools/unreal/import_car.py (M_CarPaint, ClearCoat shading model, r.ClearCoatNormal=True).
// Inputs: UV (float2, livery atlas UV0, ~5 m per UV unit)
//         L  (Texture2D livery, sRGB)       PN (Texture2D paint normal, BC5, green already flipped)
//         FK (Texture2D flake normal, BC5)  AOT (Texture2D AO in R, or any texture when P4.z = 0)
//         MK (Texture2D decal mask in R, 1 = decal, or any texture when P5.x = 0)
//         D  (pixel depth, cm)  VN (vertex normal WS)  CV (camera vector WS)
//         P1 = (flake tiling per UV, flake strength, flake fade start cm, flake fade end cm)
//         P2 = (paint metallic, paint roughness (binder), flake roughness, decal roughness)
//         P3 = (paint coat, paint coat roughness, decal coat, decal coat roughness)
//         P4 = (mica flop, top normal strength, use AO texture, AO strength)
//         P5 = (use mask texture, decal metallic, paint green gain, 0)
//              green gain: the filmic tonemapper pushes saturated blues toward violet; a little more green
//              keeps WR Blue Mica's hue (~222 deg) on screen
// Outputs: return = base colour; Metal, Rough, CC, CCR, AO (float); Nrm (coat normal), BotNrm (base normal), tangent space
float3 livery = Texture2DSample(L, LSampler, UV).rgb;

// paint (blue mica) vs decal (gold / white / pink / black vinyl): blue clearly dominant = paint
float paint = saturate((livery.b - max(livery.r, livery.g)) * 12.0 - 0.6);
if (P5.x > 0.5)
    paint = 1.0 - Texture2DSample(MK, MKSampler, UV).r;

// coat surface: panel / shut-line detail from the body normal map
float2 pnxy = (Texture2DSample(PN, PNSampler, UV).rg * 2.0 - 1.0) * P4.y;
float3 pn = float3(pnxy, sqrt(saturate(1.0 - dot(pnxy, pnxy))));

// flakes: high-frequency tiled platelets, faded with distance (mips average them to flat anyway)
float fade = 1.0 - saturate((D - P1.z) / max(P1.w - P1.z, 1.0));
float2 fkxy = Texture2DSample(FK, FKSampler, UV * P1.x).rg * 2.0 - 1.0;
float flake = saturate(length(fkxy) * 8.0) * fade * paint;          // 1 on a tilted flake, 0 on binder / decal / far
float2 fxy = fkxy * (P1.y * fade * paint);
float3 bot = normalize(float3(pn.xy + fxy, pn.z));                   // whiteout-style blend onto the panel normal

// mica flop: a touch brighter face-on, deeper at grazing angles (the coat's own Fresnel does the rest)
float ndv = saturate(dot(normalize(VN), normalize(CV)));
float flop = lerp(1.0 - P4.x, 1.0 + 0.25 * P4.x, sqrt(ndv));
float3 base = livery * lerp(1.0, flop, paint) * lerp(float3(1, 1, 1), float3(1, P5.z, 1), paint);

AO = 1.0;
if (P4.z > 0.5)
{
    float ao = Texture2DSample(AOT, AOTSampler, UV).r;
    // the bake's off-island fill is 0.25 and some paint pieces (scoop, wing...) sample it: treat it as open
    ao = lerp(1.0, ao, smoothstep(0.27, 0.33, ao));
    AO = lerp(1.0, ao, P4.w);
    base *= lerp(1.0, AO, 0.5);    // cavity darkening in direct light too (AO itself only affects indirect)
}

Metal = lerp(P5.y, P2.x, paint);
Rough = lerp(P2.w, lerp(P2.y, P2.z, flake), paint);
CC = lerp(P3.z, P3.x, paint);
CCR = lerp(P3.w, P3.y, paint);
Nrm = pn;
BotNrm = bot;
return base;
