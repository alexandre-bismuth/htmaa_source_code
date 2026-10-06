// Ground surfaces (road, sidewalk, paved, parking, grass, curbs).
// Inputs: WP (float3, absolute world cm), VN (float3 world vertex normal), D/N/ARM, Ortho, Marks (Texture2D),
//         (mesh UVs are not used: 16-bit UVs cannot hold kilometre-scale coordinates; world position can)
//         P1 = (tile size m, ortho blend, ortho chroma blend, markings on)
//         P2 = (roughness mul, normal strength, macro noise strength, median ortho luminance of this class)
//         OX = (ortho UE x0 cm, ortho UE y0 cm, ortho side cm, unused)
//         Tint (float3)
//         P3 = (road repair patches, crack-sealant 'tar snakes', oil / tyre staining, edge-mask weathering)
//         D2/N2/ARM2 (second surface set), P4 = (set-2 tile m, set-2 share, block size m, worn lawn-edge strength; needs P3.w > 0)
//         Mask (Texture2D, ortho extent; tools/mapgen/make_ground_mask.py): R = 0.5 + signed distance to the
//              road edge / 8 m (> 0 off the road), G = distance to buildings / 6 m, B = distance into a lawn / 3 m
// Outputs: return = base colour, Nrm (float3 tangent space), Rough, AO
struct GroundFn
{
    float Hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
    float Noise(float2 p)
    {
        float2 i = floor(p), f = frac(p);
        float2 s = f * f * (3.0 - 2.0 * f);
        return lerp(lerp(Hash(i), Hash(i + float2(1, 0)), s.x), lerp(Hash(i + float2(0, 1)), Hash(i + float2(1, 1)), s.x), s.y);
    }
    // sin-free hash (Hoskins): stays random at km-scale world coordinates, where sin() of ~1e5 rad
    // on the GPU degenerates to near-constant values
    float HashB(float2 p)
    {
        float3 p3 = frac(float3(p.xyx) * 0.1031);
        p3 += dot(p3, p3.yzx + 33.33);
        return frac((p3.x + p3.y) * p3.z);
    }
    float NoiseB(float2 p)
    {
        float2 i = floor(p), f = frac(p);
        float2 s = f * f * (3.0 - 2.0 * f);
        return lerp(lerp(HashB(i), HashB(i + float2(1, 0)), s.x), lerp(HashB(i + float2(0, 1)), HashB(i + float2(1, 1)), s.x), s.y);
    }
};
GroundFn G;

// metres in the surface plane: horizontal faces use world XY; vertical faces (curbs) project
// along their dominant horizontal axis
float2 UV = abs(VN.z) > 0.5 ? WP.xy / 100.0
          : float2(abs(VN.x) > abs(VN.y) ? WP.y : WP.x, WP.z) / 100.0;
float tile = P1.x;
float2 uvA = UV / tile;
// anti-tiling: a second sample rotated 90 deg and offset, blended by smooth noise (~7 m)
float2 uvB = float2(-uvA.y, uvA.x) * 0.83 + float2(0.37, 0.71);
float w = smoothstep(0.3, 0.7, G.Noise(UV / 7.0));

float3 dA = Texture2DSample(D, DSampler, uvA).rgb;
float3 dB = Texture2DSample(D, DSampler, uvB).rgb;
float3 aA = Texture2DSample(ARM, ARMSampler, uvA).rgb;
float3 aB = Texture2DSample(ARM, ARMSampler, uvB).rgb;
float2 nA = Texture2DSample(N, NSampler, uvA).rg * 2.0 - 1.0;
float2 nB = Texture2DSample(N, NSampler, uvB).rg * 2.0 - 1.0;
nB = float2(nB.y, -nB.x);   // undo the 90 deg rotation of the second sample's tangent frame

float3 col = lerp(dA, dB, w) * Tint;
float3 arm = lerp(aA, aB, w);
float2 nxy = lerp(nA, nB, w) * P2.y;

// second surface set per block (sidewalks: Cambridge red brick vs concrete). Blocks are P4.z m
// world squares; west of Central Sq / Cambridgeport (x < 700 m) brick is more common.
float2 uv2 = UV / max(P4.x, 0.1);
float2 gx = ddx(uv2), gy = ddy(uv2);                 // outside the branch: derivatives stay valid
if (P4.y > 0.0)
{
    float2 blk = floor(UV / P4.z);
    float share = P4.y * (WP.x < 70000.0 ? 1.4 : 0.6);
    if (G.Hash(blk + 0.61) < share)
    {
        col = Texture2DSampleGrad(D2, D2Sampler, uv2, gx, gy).rgb * lerp(float3(1.08, 0.95, 0.9), float3(0.95, 0.95, 0.98), G.Hash(blk + 3.3));
        arm = Texture2DSampleGrad(ARM2, ARM2Sampler, uv2, gx, gy).rgb;
        nxy = (Texture2DSampleGrad(N2, N2Sampler, uv2, gx, gy).rg * 2.0 - 1.0) * P2.y;
    }
}

// macro variation from the orthophoto: luminance (clamped so baked shadows / cars stay subtle) and
// optionally its colour (grass). Sampled blurred (mip bias) to drop small objects.
float2 ouv = (WP.xy - OX.xy) / OX.z;
float3 ortho = Texture2DSampleBias(Ortho, OrthoSampler, ouv, 2.5).rgb;
float lum = dot(ortho, float3(0.299, 0.587, 0.114));
float macro = clamp(lum / max(P2.w, 0.02), 0.75, 1.25);   // centred on this surface class's median
col *= lerp(1.0, macro, P1.y);
float3 chroma = ortho / max(lum, 1e-3) * dot(col, float3(0.299, 0.587, 0.114));
col = lerp(col, chroma, P1.z);
// low-frequency procedural variation (dirt, wear) to break up large areas
float mn = G.Noise(UV / 23.0) * 0.6 + G.Noise(UV / 5.0) * 0.4;
col *= 1.0 + (mn - 0.5) * P2.z;

float rough = saturate(arm.g * P2.x);
float ao = arm.r;

// asphalt life: utility-cut repair patches, crack sealant, oil drips (world-space, no textures)
if (P3.x + P3.y + P3.z > 0.0)
{
    float2 cell = floor(UV / 9.0);
    float2 cf = UV - cell * 9.0;
    float ph = G.Hash(cell + 0.37);
    float2 pc = float2(G.Hash(cell + 1.3), G.Hash(cell + 2.9)) * 4.0 + 2.5;      // patch centre in the cell
    float2 ps = float2(G.Hash(cell + 4.1), G.Hash(cell + 5.7)) * float2(2.2, 1.6) + 0.6;   // half size
    float2 q = abs(cf - pc) - ps;
    float sd = max(q.x, q.y);                                                    // < 0 inside the patch
    float aaP = max(fwidth(sd), 0.01);
    float inP = (1.0 - smoothstep(-aaP, aaP, sd)) * step(ph, 0.22) * P3.x;
    float seal = (1.0 - smoothstep(0.02, 0.06 + aaP, abs(sd))) * step(ph, 0.22) * P3.x;
    float newer = step(0.5, G.Hash(cell + 8.8));
    col = lerp(col, col * (newer > 0.5 ? 0.72 : 1.12), inP);
    rough = lerp(rough, newer > 0.5 ? rough * 0.85 : rough, inP);
    nxy *= 1.0 - inP * (newer > 0.5 ? 0.5 : 0.0);

    float n = G.Noise(UV / 3.1) * 0.65 + G.Noise(UV / 0.9) * 0.35;
    float aaS = max(fwidth(n), 0.004);
    float snake = (1.0 - smoothstep(0.006, 0.006 + aaS * 1.5, abs(n - 0.5))) * smoothstep(0.55, 0.75, G.Noise(UV / 17.0 + 3.1)) * P3.y;
    snake = max(snake, seal);
    col = lerp(col, float3(0.025, 0.025, 0.027), snake * 0.85);
    rough = lerp(rough, 0.35, snake);
    nxy *= 1.0 - snake;

    float oil = smoothstep(0.62, 0.8, G.Noise(UV / 1.3 + 7.7)) * smoothstep(0.5, 0.7, G.Noise(UV / 11.0 + 1.9)) * P3.z;
    col *= 1.0 - oil * 0.35;
    rough = lerp(rough, rough * 0.8, oil);
}

// edge weathering from the distance-field mask: gutter grime along the curb, kerb-side dirt on the
// sidewalk, contact darkening where the ground meets building walls
if (P3.w > 0.0)
{
    float3 mk = Texture2DSample(Mask, MaskSampler, ouv).rgb;
    float dRoad = (mk.r - 0.5) * 8.0;
    float dBld = mk.g * 6.0;
    float nz = G.Noise(UV * 0.9) * 0.6 + G.Noise(UV * 3.7) * 0.4;
    float gutter = (1.0 - smoothstep(0.05, 0.75 + 0.35 * nz, -dRoad)) * step(dRoad, 0.1);
    float kerb = (1.0 - smoothstep(0.0, 0.5 + 0.4 * nz, dRoad)) * step(-0.1, dRoad);
    float base = 1.0 - smoothstep(0.0, 0.9 + 0.5 * nz, dBld);
    float3 grime = float3(0.30, 0.27, 0.22) * dot(col, float3(0.3, 0.59, 0.11));
    col = lerp(col, grime, saturate(gutter * (0.35 + 0.35 * nz)) * P3.w);
    rough = lerp(rough, min(rough + 0.15, 1.0), gutter * P3.w);
    col *= 1.0 - (kerb * 0.12 * nz + base * 0.3) * P3.w;
    ao *= 1.0 - base * 0.35 * P3.w;
    if (P4.w > 0.0)
    {
        // worn lawn edges: trampled, bare soil along kerbs and building bases (grass only)
        // metres from the nearest path / kerb / wall; the 0.58 m/px field reads ~0.8 m at the very edge
        float dLawn = max(mk.b * 3.0 - 0.8, 0.0);
        float lz = G.NoiseB(UV * 0.8) * 0.6 + G.NoiseB(UV * 3.1) * 0.4;
        float edgeW = 1.0 - smoothstep(0.0, 0.5 + 1.0 * lz, dLawn);
        edgeW *= smoothstep(0.15, 0.45, G.NoiseB(UV * 0.3 + 5.1));          // worn in patches, not a ribbon
        float3 soil = float3(0.30, 0.24, 0.16) * (0.8 + 0.4 * lz);         // dry, compacted, lighter than turf
        col = lerp(col, soil, saturate(edgeW * P4.w));
        rough = lerp(rough, 0.95, edgeW * P4.w);
        nxy *= 1.0 - 0.5 * edgeW * P4.w;
    }
}

// road markings: thresholded blurred mask -> crisp anti-aliased paint
if (P1.w > 0.5)
{
    float2 m = Texture2DSample(Marks, MarksSampler, ouv).rg;
    float aa = max(fwidth(m.r), 0.02);
    float white = smoothstep(0.42 - aa, 0.42 + aa, m.r);
    float yel = smoothstep(0.42 - aa, 0.42 + aa, m.g);
    float paintWear = lerp(0.75, 1.0, G.Noise(UV * 1.7));
    float paint = saturate(max(white, yel)) * paintWear;
    float3 paintCol = lerp(float3(0.78, 0.78, 0.74), float3(0.85, 0.62, 0.12), yel);
    col = lerp(col, paintCol, paint);
    rough = lerp(rough, 0.55, paint);
    nxy *= 1.0 - paint * 0.8;
}

Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
Rough = rough;
AO = ao;
return col;
