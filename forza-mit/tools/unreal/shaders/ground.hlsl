// Ground surfaces (road, sidewalk, paved, parking, grass, curbs). World-space mapped: mesh UVs are not used
// (16-bit UVs cannot hold kilometre-scale coordinates; world position can).
// Inputs: WP (float3, absolute world cm), VN (world vertex normal), CV (camera vector, pixel -> camera),
//   LEG / MRD / MGR / MCB: static switches (constants, folded by the compiler): Boston backdrop (ground_city) / road /
//   grass / curb; none = hard surfaces (sidewalk, paved, parking)
//   D/N/ARM (class set), D2/N2/ARM2 (brick pavers), D3/N3/ARM3 (asphalt_04: resurfaced roads, asphalt paths,
//   poured concrete and unsealed surfaces), Ortho, OX = (ortho UE x0 cm, y0 cm, side cm, -)
//   EMask (tools/mapgen/make_ground_mask.py edge_mask, exact distances): R = 0.5 + road-edge SDF / 8 m (> 0 off
//         the road), G = building distance / 6 m, B = 0.5 + lawn SDF / 6 m (> 0 inside a lawn)
//   SMask (surface_mask, uncompressed): RGBA = 0.5 + SDF / 4 m (> 0 inside) of brick / asphalt / unsealed / poured
//         concrete paving (City GIS; elsewhere pavers = the class texture)
//   SAng (surface_angle, point-sampled): 1 + theta / 1.5 deg, theta = polygon direction (snapped to the map's grid)
//   Parameters (per class, tools/unreal/materials.json "_comment_ground"): P1.x tile m, P2 = (rough mul, normal
//         strength, macro noise, median ortho luminance), P4.x brick tile m, Q1 = (ortho lum weight, ortho chroma
//         weight, ortho mip bias, masks on: 0 in the ctx ring), Q2..Q4, C1..C3 class specific,
//         Q5 = (curb top width m, paver tint rgb); ground_city only: P1.yz (ortho blend, chroma), Tint
// Outputs: return = base colour, Nrm (float3 tangent space), Rough, AO, Spec
struct GroundFn
{
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
    float2 Hash2B(float2 p)
    {
        float3 p3 = frac(float3(p.xyx) * float3(0.1031, 0.1030, 0.0973));
        p3 += dot(p3, p3.yzx + 33.33);
        return frac((p3.xx + p3.yz) * p3.zy);
    }
    // anti-aliased step: 0 below e, 1 above, over one pixel footprint w of x
    float AStep(float e, float x, float w) { return saturate((x - e) / max(w, 1e-5) + 0.5); }
    // rotate v by the angle whose (cos, sin) is cs
    float2 Rot(float2 v, float2 cs) { return float2(v.x * cs.x - v.y * cs.y, v.x * cs.y + v.y * cs.x); }
    // distance to the nearest Voronoi cell border (cells ~1 unit): crack networks
    float VorEdge(float2 p)
    {
        float2 ip = floor(p), fp = frac(p);
        float2 mg = 0, mr = 0;
        float md = 8.0;
        for (int j = -1; j <= 1; j++)
            for (int i = -1; i <= 1; i++)
            {
                float2 g = float2(i, j);
                float2 r = g + Hash2B(ip + g) * 0.8 + 0.1 - fp;
                float d = dot(r, r);
                if (d < md) { md = d; mr = r; mg = g; }
            }
        md = 8.0;
        for (int j2 = -1; j2 <= 1; j2++)
            for (int i2 = -1; i2 <= 1; i2++)
            {
                float2 g = mg + float2(i2, j2);
                float2 r = g + Hash2B(ip + g) * 0.8 + 0.1 - fp;
                if (dot(mr - r, mr - r) > 1e-5)
                    md = min(md, dot(0.5 * (mr + r), normalize(r - mr)));
            }
        return md;
    }
};
GroundFn G;

// =====================================================================================================================
// Boston backdrop (ground_city): mostly the aerial photo, a little texture and noise (the round-5 shader without its
// playable-area branches)
// =====================================================================================================================
if (LEG > 0.5)
{
    float2 UV = WP.xy / 100.0;
    float2 uvA = UV / P1.x;
    float2 uvB = float2(-uvA.y, uvA.x) * 0.83 + float2(0.37, 0.71);
    float w = smoothstep(0.3, 0.7, G.NoiseB(UV / 7.0));
    float3 col = lerp(Texture2DSample(D, DSampler, uvA).rgb, Texture2DSample(D, DSampler, uvB).rgb, w) * Tint;
    float3 arm = lerp(Texture2DSample(ARM, ARMSampler, uvA).rgb, Texture2DSample(ARM, ARMSampler, uvB).rgb, w);
    float2 nA = Texture2DSample(N, NSampler, uvA).rg * 2.0 - 1.0;
    float2 nB = Texture2DSample(N, NSampler, uvB).rg * 2.0 - 1.0;
    float2 nxy = lerp(nA, float2(nB.y, -nB.x), w) * P2.y;
    float2 ouv = (WP.xy - OX.xy) / OX.z;
    float3 ortho = Texture2DSampleBias(Ortho, OrthoSampler, ouv, 2.5).rgb;
    float lum = dot(ortho, float3(0.299, 0.587, 0.114));
    col *= lerp(1.0, clamp(lum / max(P2.w, 0.02), 0.75, 1.25), P1.y);
    col = lerp(col, ortho / max(lum, 1e-3) * dot(col, float3(0.299, 0.587, 0.114)), P1.z);
    col *= 1.0 + (G.NoiseB(UV / 23.0) * 0.6 + G.NoiseB(UV / 5.0) * 0.4 - 0.5) * P2.z;
    Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
    Rough = saturate(arm.g * P2.x);
    AO = arm.r;
    Spec = 0.5;
    return col;
}

// =====================================================================================================================
// Playable area: shared inputs first, then one block per mesh class (static switches).
// =====================================================================================================================
const float3 LW = float3(0.2126, 0.7152, 0.0722);
float2 P = WP.xy / 100.0;                       // world metres, UE axes (x east, y south)
float2 dPx = ddx(P), dPy = ddy(P);
float pix = max(length(dPx), length(dPy));      // metres per pixel on the surface
float2 ouv = (WP.xy - OX.xy) / OX.z;
bool useM = Q1.w > 0.5;

// exact edge distances
float dRoad = 4.0, dBld = 6.0, dLawn = 3.0;
if (useM)
{
    float4 em = Texture2DSample(EMask, EMaskSampler, ouv);
    dRoad = (em.r - 0.5) * 8.0;
    dBld = em.g * 6.0;
    dLawn = (em.b - 0.5) * 6.0;
}
float fwRoad = max(fwidth(dRoad), 1e-4);

// per-polygon direction (pavers / brick bond / sidewalk joints / mowing follow the path or street)
float code = 0.0;
if (useM)
{
    uint aw, ah;
    SAng.GetDimensions(aw, ah);
    int2 ip = clamp(int2(floor(ouv * float2(aw, ah))), int2(0, 0), int2(aw - 1, ah - 1));
    code = round(SAng.Load(int3(ip, 0)).r * 255.0);
}
bool hasAng = code > 0.5;
float theta = hasAng ? (code - 1.0) * 0.02617994 : 0.0;    // 1.5 deg steps; radians, East = 0, counter-clockwise (north)
float2 dirT = float2(cos(theta), -sin(theta));      // along the polygon, UE axes (y = south)
float2 dirB = float2(-dirT.y, dirT.x);
float u = dot(P, dirT), v = dot(P, dirB);
float2 duvx = float2(dot(dPx, dirT), dot(dPx, dirB));   // analytic derivatives: no seams where theta jumps
float2 duvy = float2(dot(dPy, dirT), dot(dPy, dirB));

// shared low-frequency noise (computed once)
float nL = G.NoiseB(P / 37.0 + 11.3);
float nM = G.NoiseB(P / 9.1 + 3.7);
float nS = G.NoiseB(P / 2.3 + 7.1);
float nF = G.NoiseB(P * 1.7 + 1.9);

// orthophoto: heavily blurred macro luminance (baked shadows, cars and edge bleed gone), optional chroma
float3 ortho = Texture2DSampleBias(Ortho, OrthoSampler, ouv, Q1.z).rgb;
float oLum = dot(ortho, float3(0.299, 0.587, 0.114));
float oMacro = clamp(oLum / max(P2.w, 0.02), 0.7, 1.3);
float3 oChroma = ortho / max(oLum, 1e-3);

float3 col = 0.5;
float2 nxy = 0.0;
float rough = 0.8, ao = 1.0, spec = 0.5;

// granite curb top: the first Q5.x m of the raised ground next to the road edge (hard surfaces and lawns)
float wCurbTop = (MRD < 0.5 && MCB < 0.5 && useM) ? G.AStep(0.0, Q5.x - dRoad, fwRoad) * step(-0.05, dRoad) : 0.0;

if (MRD > 0.5)
{
    // ------------------------------------------------------------------------------------------- ROAD (asphalt)
    // C1 = weathered asphalt tint (set 1, asphalt_02), C2 = resurfaced asphalt tint (set 3, asphalt_04)
    // Q2 = (resurfaced share, resurfaced zone size m, set-3 tile m, crack visibility)
    // Q3 = (repair patches, sealed crack network, oil stains, gutter grime), Q4 = (macro noise, -, -, -)
    float tile = P1.x;
    float2 uvA = P / tile;
    float2 uvB = float2(-uvA.y, uvA.x) * 0.83 + float2(0.37, 0.71);
    float2 gAx = dPx / tile, gAy = dPy / tile;
    float2 gBx = float2(-gAx.y, gAx.x) * 0.83, gBy = float2(-gAy.y, gAy.x) * 0.83;
    float wB = smoothstep(0.3, 0.7, nM);
    // resurfaced zones: whole stretches repaved with a newer, darker, smoother mix
    float zn = G.NoiseB(P / max(Q2.y, 1.0) + 2.9) * 0.85 + nS * 0.15;
    float zNew = G.AStep(1.0 - Q2.x, zn, fwidth(zn));
    float crackOn = smoothstep(0.4, 0.65, G.NoiseB(P / 13.0 + 5.3)) * Q2.w;

    float3 cO = 0, aO = 0; float2 nO = 0;
    if (zNew < 0.999)
    {
        float3 dA = Texture2DSampleGrad(D, DSampler, uvA, gAx, gAy).rgb;
        float3 dB = Texture2DSampleGrad(D, DSampler, uvB, gBx, gBy).rgb;
        float3 aA = Texture2DSampleGrad(ARM, ARMSampler, uvA, gAx, gAy).rgb;
        float3 aB = Texture2DSampleGrad(ARM, ARMSampler, uvB, gBx, gBy).rgb;
        float2 nA = Texture2DSampleGrad(N, NSampler, uvA, gAx, gAy).rg * 2.0 - 1.0;
        float2 nB = Texture2DSampleGrad(N, NSampler, uvB, gBx, gBy).rg * 2.0 - 1.0;
        nB = float2(nB.y, -nB.x);
        cO = lerp(dA, dB, wB);
        aO = lerp(aA, aB, wB);
        nO = lerp(nA, nB, wB);
        // the texture's cracks only where this stretch is cracked: lift the dark crack pixels elsewhere
        cO = lerp(max(cO, 0.075), cO, crackOn);
        nO *= lerp(0.55, 1.0, crackOn);
        cO *= C1;
    }
    float3 cN = 0, aN = 0; float2 nN = 0;
    if (zNew > 0.001)
    {
        float t3 = Q2.z;
        float2 cs3 = float2(0.866, 0.5);
        float2 uv3 = G.Rot(P, cs3) / t3 + float2(0.21, 0.63);
        float2 g3x = G.Rot(dPx, cs3) / t3, g3y = G.Rot(dPy, cs3) / t3;
        cN = Texture2DSampleGrad(D3, D3Sampler, uv3, g3x, g3y).rgb * C2;
        aN = Texture2DSampleGrad(ARM3, ARM3Sampler, uv3, g3x, g3y).rgb;
        nN = G.Rot(Texture2DSampleGrad(N3, N3Sampler, uv3, g3x, g3y).rg * 2.0 - 1.0, float2(cs3.x, -cs3.y));
    }
    col = lerp(cO, cN, zNew);
    float3 arm = lerp(aO, aN, zNew);
    nxy = lerp(nO, nN * 0.8, zNew) * P2.y;
    rough = saturate(arm.g * P2.x * lerp(1.0, 0.92, zNew));
    ao = arm.r;
    col *= lerp(1.0, oMacro, Q1.x);
    col *= 1.0 + (nL * 0.6 + nM * 0.4 - 0.5) * Q4.x;

    // utility-cut repair patches: rectangles aligned with the street (direction quantised to 10 deg so both
    // halves of a street agree), sealed edges
    {
        float qa = hasAng ? round(theta / 0.17453) * 0.17453 : 0.0;
        float2 qt = float2(cos(qa), -sin(qa));
        float2 pq = float2(dot(P, qt), dot(P, float2(-qt.y, qt.x)));
        float2 cell = floor(pq / 9.0);
        float2 cf = pq - cell * 9.0;
        float ph = G.HashB(cell + 0.37);
        float2 pc = G.Hash2B(cell + 1.3) * 4.0 + 2.5;
        float2 ps = G.Hash2B(cell + 4.1) * float2(2.6, 1.2) + float2(0.5, 0.4);
        float2 qd = abs(cf - pc) - ps;
        float sd = max(qd.x, qd.y);
        float aaP = max(pix, 0.004);
        float on = step(ph, 0.2) * Q3.x;
        float inP = (1.0 - G.AStep(0.0, sd, aaP)) * on;
        float seal = (1.0 - G.AStep(0.025, abs(sd), aaP)) * on;
        float newer = step(0.5, G.HashB(cell + 8.8));
        col = lerp(col, col * (newer > 0.5 ? 0.68 : 1.1), inP);
        rough = lerp(rough, newer > 0.5 ? rough * 0.85 : rough, inP);
        nxy *= 1.0 - inP * (newer > 0.5 ? 0.45 : 0.0);
        // sealed crack network (tar snakes): Voronoi cell borders, only on cracked old stretches
        float tw = 0.022 + 0.012 * nF;                                       // half width m
        float ve = G.VorEdge(P / 2.7 + nS * 0.35) * 2.7;
        float snake = (1.0 - G.AStep(tw, ve, max(pix * 1.2, 0.004))) * smoothstep(0.6, 0.85, G.NoiseB(P / 21.0 + 4.4)) * (1.0 - zNew) * Q3.y;
        snake *= smoothstep(0.4, 0.55, G.NoiseB(P / 1.9 + 7.3));            // broken runs, not a closed net
        snake *= saturate(1.5 - pix / 0.03);                                // sub-pixel far away: fade
        snake = max(snake, seal);
        col = lerp(col, float3(0.022, 0.022, 0.024), snake * 0.9);
        rough = lerp(rough, 0.32, snake);
        nxy *= 1.0 - snake;
        // oil drips
        float oil = smoothstep(0.64, 0.8, G.NoiseB(P / 1.3 + 7.7)) * smoothstep(0.5, 0.7, nM) * Q3.z;
        col *= 1.0 - oil * 0.3;
        rough = lerp(rough, rough * 0.8, oil);
    }
    // gutter: wet-dark grime line at the curb, then a dusty band (sand, grit, leaf bits)
    if (useM)
    {
        float g0 = (1.0 - smoothstep(0.0, 0.18 + 0.12 * nF, -dRoad)) * step(dRoad, 0.05);
        float g1 = (1.0 - smoothstep(0.25, 0.7 + 0.3 * nS, -dRoad)) * (1.0 - g0);
        float3 dust = float3(0.20, 0.185, 0.165) * (0.8 + 0.4 * nF);
        col = lerp(col, col * float3(0.62, 0.6, 0.57), g0 * Q3.w);
        col = lerp(col, dust, g1 * 0.45 * Q3.w * smoothstep(0.35, 0.6, nS * 0.5 + nM * 0.5));
        rough = lerp(rough, 0.95, g1 * Q3.w);
    }
}
else if (MGR > 0.5)
{
    // ------------------------------------------------------------------------------------------- GRASS (lawns)
    // C1 = healthy turf, C2 = dry / sun-faded, C3 = clover / lush; Q2 = (stripe width m, stripe strength, worn
    // patches near paths, mulch-bed share along walls); Q3 = (dry patches, clover, macro brightness, grazing greening)
    // Q4 = (second-sample scale, roughness, specular, share of the photo's own colour: leaf litter / thatch)
    float tile = P1.x;
    float2 uvA = P / tile;
    float2 csB = float2(0.8253, 0.5646);
    float2 uvB = G.Rot(P, csB) / (tile * Q4.x) + float2(0.31, 0.77);
    float3 dA = Texture2DSample(D, DSampler, uvA).rgb;
    float3 dB = Texture2DSample(D, DSampler, uvB).rgb;
    float2 nA = Texture2DSample(N, NSampler, uvA).rg * 2.0 - 1.0;
    float2 nB = G.Rot(Texture2DSample(N, NSampler, uvB).rg * 2.0 - 1.0, float2(csB.x, -csB.y));
    float lA = dot(dA, LW) / 0.25;                      // leafy_grass mean linear luminance ~0.25
    float lB = dot(dB, LW) / 0.25;
    float det = lA * lerp(1.0, lB, 0.4);                // blades x clumps

    float dryM = smoothstep(0.45, 0.85, nL * 0.55 + nM * 0.45) * Q3.x;
    float clov = smoothstep(0.6, 0.74, nS * 0.65 + nM * 0.35) * Q3.y * (1.0 - dryM);
    float3 turf = lerp(C1, C2, dryM);
    turf = lerp(turf, C3, clov);
    col = turf * det;
    col = lerp(col, dA * (dot(turf, LW) / 0.25), Q4.w);          // the photo's own leaf litter / thatch
    col *= 1.0 + (nL - 0.5) * Q3.z + (nM - 0.5) * Q3.z * 0.6;
    // orthophoto: macro brightness / hue, faded out near the lawn edge so paths do not bleed in
    float oW = smoothstep(0.6, 2.8, dLawn);
    col *= lerp(1.0, oMacro, Q1.x * oW);
    col = lerp(col, oChroma * dot(col, float3(0.299, 0.587, 0.114)), Q1.y * oW);
    // grazing view: blade sides (greener, no soil between the blades)
    float graze = 1.0 - saturate(CV.z);
    graze *= graze;
    col = lerp(col, col * float3(0.93, 1.04, 0.7), graze * Q3.w);

    // mowing stripes along the lawn's direction: blades lean +-dirT per stripe, lighter where they lean away
    if (hasAng && Q2.y > 0.0)
    {
        float sv = v / Q2.x;
        float fw = (abs(duvx.y) + abs(duvy.y)) / Q2.x;
        float tri = 1.0 - 4.0 * abs(frac(sv) - 0.5);
        float sq = clamp(tri / max(2.0 * fw, 0.3), -1.0, 1.0);
        float fade = saturate(1.0 - fw * 1.5) * smoothstep(1.5, 3.0, dLawn);
        float2 vh = -CV.xy;
        float vl = length(vh);
        vh = vl > 1e-4 ? vh / vl : float2(0, 0);
        float lean = dot(vh, dirT);
        col *= 1.0 + sq * (0.3 + 0.7 * lean) * Q2.y * fade;
    }
    // lawn edge: a band of denser, longer grass, then crisp worn patches near paths and kerbs
    float edgeB = 1.0 - smoothstep(0.0, 0.25 + 0.15 * nF, dLawn);
    col *= 1.0 - 0.1 * edgeB;
    float wearN = nS * 0.35 + nF * 0.4 + G.NoiseB(P * 6.5 + 2.3) * 0.25;     // ragged, broken-up patches
    float nearE = 1.0 - smoothstep(0.2, 1.6, dLawn);
    float wear = G.AStep(0.84 - 0.32 * nearE * Q2.z, wearN, fwidth(wearN)) * nearE * step(0.001, Q2.z);
    float3 soil = float3(0.15, 0.115, 0.08) * (0.75 + 0.5 * nF) * (0.8 + 0.3 * lA);
    col = lerp(col, soil, wear * (0.55 + 0.35 * nF));

    float2 nG = (nA * 0.7 + nB * 0.4) * P2.y * (1.0 - 0.35 * clov);
    rough = Q4.y * (0.9 + 0.2 * nF);
    rough = lerp(rough, 0.92, max(dryM * 0.6, wear));
    ao = saturate(0.55 + 0.45 * lA);
    spec = Q4.z;

    // mulch beds along some building walls (curved ends), with a spade-cut border
    if (useM && Q2.w > 0.0)
    {
        float bsel = nL * 0.7 + nM * 0.3;
        float bedOn = G.AStep(1.0 - Q2.w, bsel, fwidth(bsel));
        float bedW = 0.6 + 1.0 * nM;
        float bd = bedW - dBld;
        float bed = G.AStep(0.0, bd, fwidth(bd)) * bedOn;
        float3 mulch = float3(0.085, 0.052, 0.033) * (0.5 + 0.9 * saturate(lA * 0.8)) * (0.85 + 0.3 * nF);
        float cut = (1.0 - G.AStep(0.035, abs(bd), max(fwidth(bd), 0.003))) * bedOn;
        col = lerp(col, mulch, bed);
        col *= 1.0 - 0.45 * cut;
        rough = lerp(rough, 0.96, bed);
        spec = lerp(spec, 0.3, bed);
        nG = lerp(nG, nA * 1.3 * P2.y, bed);
        ao *= 1.0 - 0.2 * bed;
    }
    nxy = nG * (1.0 - 0.4 * wear);
}
else if (MCB > 0.5)
{
    // ------------------------------------------------------------------------------------------- CURBS (granite)
    // vertical faces: along = dominant horizontal axis, z = height (road at 0). The granite photo's tile joints are
    // avoided by mirror-sampling inside one stone; block joints are procedural. C1 = tint,
    // Q2 = (block length m, foot grime, arris highlight, curb top z m)
    float along = abs(VN.x) > abs(VN.y) ? P.y : P.x;
    float z = WP.z / 100.0;
    float bl = Q2.x;
    float bi = floor(along / bl);
    float hb = G.HashB(float2(bi, abs(VN.x) > abs(VN.y) ? 7.0 : 3.0));
    float2 tq = float2(along / 0.52 + hb * 7.0, z / 0.85 + hb * 3.0);
    float2 mr = 1.0 - abs(1.0 - 2.0 * frac(tq * 0.5));
    float2 uvC = float2(0.02, 0.02) + mr * float2(0.29, 0.46);
    float2 sc = float2(0.29 / 0.52, 0.46 / 0.85);
    float2 gcx = float2(ddx(along), ddx(z)) * sc, gcy = float2(ddy(along), ddy(z)) * sc;
    col = Texture2DSampleGrad(D, DSampler, uvC, gcx, gcy).rgb * C1;
    float3 arm = Texture2DSampleGrad(ARM, ARMSampler, uvC, gcx, gcy).rgb;
    nxy = (Texture2DSampleGrad(N, NSampler, uvC, gcx, gcy).rg * 2.0 - 1.0) * P2.y * 0.4;
    col *= 1.0 + (hb - 0.5) * 0.16;
    float fa = max(fwidth(along), 1e-4);
    float fj = frac(along / bl);
    float dj = min(fj, 1.0 - fj) * bl;
    float jj = 1.0 - G.AStep(0.004, dj, fa);
    col *= 1.0 - 0.55 * jj;
    float foot = 1.0 - smoothstep(0.0, 0.045 + 0.03 * nF, z);
    col *= lerp(1.0, 0.55, foot * Q2.y);
    float arr = smoothstep(Q2.w - 0.022, Q2.w - 0.005, z);
    col *= 1.0 + Q2.z * arr;
    col *= 1.0 - 0.12 * smoothstep(0.55, 0.8, G.NoiseB(float2(along * 3.0, z * 0.4) + hb * 9.0));
    float wet = 1.0 - smoothstep(-0.75, -0.5, z);                       // river walls: wet, algae
    col = lerp(col, col * float3(0.42, 0.48, 0.4), wet);
    rough = lerp(saturate(arm.g * P2.x), 0.4, wet);
    rough = lerp(rough, 0.95, foot * 0.5);
    ao = arm.r;
}
else
{
    // ------------------------------------------------------------------------------------------- HARD SURFACES
    // sidewalks, plazas / paths, parking. Base = Q2.x (0 pavers: set 1 rotated to the polygon, 1 poured concrete:
    // set 3 + saw-cut joints, 2 asphalt: set 3), per polygon from SAng; brick (set 2), asphalt paths (set 3) and
    // unsealed surfaces (Q4.x: 0 tree-well soil / mulch, 1 stone dust, 2 gravel) from the GIS type SDFs.
    // C1 = concrete tint, C2 = brick tint, C3 = asphalt tint; Q2 = (base, -, -, joint spacing m);
    // Q3 = (per-paver tint, pavers per tile, stains, -); Q4 = (unsealed style, set-3 tile m, kerb / base / lawn dirt, -)
    float4 sm = float4(0, 0, 0, 0);
    if (useM)
        sm = Texture2DSample(SMask, SMaskSampler, ouv);
    float4 sd4 = (sm - 0.5) * 4.0;
    float4 fw4 = max(fwidth(sd4), 1e-4);
    float wUns = G.AStep(0.0, sd4.z, fw4.z);
    float wBrick = G.AStep(0.0, sd4.x, fw4.x) * (1.0 - wUns);
    float wAsph = G.AStep(0.0, sd4.y, fw4.y) * (1.0 - wUns) * (1.0 - wBrick);
    float wBase = saturate(1.0 - wBrick - wAsph - wUns);
    // base surface: 2 = asphalt (parking); else poured concrete where the GIS says so (1 = always: sidewalks), pavers
    float wPour = Q2.x > 1.5 ? 1.0 : (Q2.x > 0.5 ? 1.0 : G.AStep(0.0, sd4.w, fw4.w));
    bool needS1 = wBase > 0.001 && wPour < 0.999 && Q2.x < 1.5;
    bool needS3 = wAsph + wUns > 0.001 || (wBase > 0.001 && wPour > 0.001);

    float3 cBase = 0, aBase = float3(1, 0.85, 0);
    float2 nBase = 0;
    if (needS1)
    {
        // pavers: grid along the polygon, every texture tile turned by a random quarter turn (square pavers:
        // the joints stay on the grid), every paver its own shade
        float t1 = P1.x;
        float2 uvT = float2(u, v) / t1;
        float2 cell = floor(uvT);
        float hr = G.HashB(cell + 17.0);
        float2 cs = hr < 0.25 ? float2(1, 0) : hr < 0.5 ? float2(0, 1) : hr < 0.75 ? float2(-1, 0) : float2(0, -1);
        float2 uvR = cell + 0.5 + G.Rot(uvT - cell - 0.5, cs);
        float2 gx = G.Rot(duvx / t1, cs), gy = G.Rot(duvy / t1, cs);
        cBase = Texture2DSampleGrad(D, DSampler, uvR, gx, gy).rgb;
        aBase = Texture2DSampleGrad(ARM, ARMSampler, uvR, gx, gy).rgb;
        float2 nt = G.Rot(Texture2DSampleGrad(N, NSampler, uvR, gx, gy).rg * 2.0 - 1.0, float2(cs.x, -cs.y));
        nBase = nt.x * dirT + nt.y * dirB;
        float2 pid = floor(uvT * Q3.y);
        float hp = G.HashB(pid + 3.1);
        cBase *= Q5.yzw * (1.0 + (hp - 0.5) * Q3.x) * (G.HashB(pid + 9.7) < 0.04 ? 0.8 : 1.0);
    }
    float3 c3 = 0, a3 = float3(1, 0.9, 0);
    float2 n3 = 0;
    if (needS3)
    {
        float t3 = Q4.y;
        float2 uv3 = P / t3;
        c3 = Texture2DSampleGrad(D3, D3Sampler, uv3, dPx / t3, dPy / t3).rgb;
        a3 = Texture2DSampleGrad(ARM3, ARM3Sampler, uv3, dPx / t3, dPy / t3).rgb;
        n3 = Texture2DSampleGrad(N3, N3Sampler, uv3, dPx / t3, dPy / t3).rg * 2.0 - 1.0;
    }
    float joint = 0.0;
    if (Q2.x > 1.5)
    {
        cBase = c3 * C3;
        aBase = a3;
        nBase = n3;
    }
    else if (wBase > 0.001 && wPour > 0.001)
    {
        // poured concrete: saw-cut joints every Q2.w m along / across the polygon, every panel its own shade
        float js = Q2.w;
        float2 jc = float2(u, v) / js;
        float2 pw = (abs(duvx) + abs(duvy));                               // m per pixel per axis
        float2 djm = abs(jc - round(jc)) * js;
        float2 jl = 1.0 - saturate((djm - 0.006) / max(pw, 1e-4) + 0.5);
        joint = max(jl.x, jl.y) * saturate(1.5 - max(pw.x, pw.y) / 0.03);
        float2 pnl = floor(jc + 0.5);
        float hq = G.HashB(pnl + 41.0);
        float3 pc = C1 * (1.0 + (hq - 0.5) * 0.12) * (G.HashB(pnl + 5.5) < 0.08 ? 0.86 : 1.0) * (G.HashB(pnl + 8.1) < 0.04 ? 1.12 : 1.0);
        float3 cc = lerp(dot(c3, LW).xxx, c3, 0.7);                         // greyer, calmer than the asphalt photo
        cc = lerp(float3(0.235, 0.235, 0.235), cc, 0.65);                     // less blotchy
        float3 cPour = lerp(cc * pc, cc * pc * 0.42, joint);
        float3 aPour = float3(a3.r * (1.0 - 0.4 * joint), saturate(a3.g * 0.95 + 0.1 * joint), 0);
        cBase = lerp(cBase, cPour, wPour);
        aBase = lerp(aBase, aPour, wPour);
        nBase = lerp(nBase, n3 * 0.7, wPour);
    }
    float3 cB = 0, aB = float3(1, 0.9, 0);
    float2 nBk = 0;
    if (wBrick > 0.001)
    {
        float t2 = P4.x;
        float2 uv2 = float2(u, v) / t2;
        cB = Texture2DSampleGrad(D2, D2Sampler, uv2, duvx / t2, duvy / t2).rgb * C2 * (0.9 + 0.2 * nS);
        aB = Texture2DSampleGrad(ARM2, ARM2Sampler, uv2, duvx / t2, duvy / t2).rgb;
        float2 nt = Texture2DSampleGrad(N2, N2Sampler, uv2, duvx / t2, duvy / t2).rg * 2.0 - 1.0;
        nBk = nt.x * dirT + nt.y * dirB;
    }
    float l3 = dot(c3, LW) / 0.235;                                       // asphalt_04 mean linear luminance
    float3 cU = Q4.x < 0.5 ? float3(0.10, 0.064, 0.04) * (0.4 + 1.0 * l3) * (0.75 + 0.5 * nF)      // soil / mulch
              : Q4.x < 1.5 ? float3(0.33, 0.29, 0.23) * (0.6 + 0.6 * l3) * (0.9 + 0.2 * nS)        // stone dust
              : float3(0.25, 0.24, 0.22) * (0.6 + 0.6 * l3);                                       // gravel
    col = cBase * wBase + cB * wBrick + c3 * C3 * wAsph + cU * wUns;
    float3 arm = aBase * wBase + aB * wBrick + a3 * wAsph + float3(0.8, 0.95, 0) * wUns;
    nxy = (nBase * wBase + nBk * wBrick + n3 * wAsph + n3 * 1.4 * wUns) * P2.y;
    rough = saturate(arm.g * P2.x);
    ao = arm.r;

    col *= lerp(1.0, oMacro, Q1.x);
    col *= 1.0 + (nL * 0.6 + nM * 0.4 - 0.5) * P2.z;
    float st = smoothstep(0.7, 0.82, nS * 0.7 + nF * 0.3) * Q3.z * (1.0 - wUns);
    col *= 1.0 - 0.22 * st;
    // kerb-side dirt, building-base splash, soil spilled from the lawns over the path edge (crisp, ragged)
    float kerb = 1.0 - smoothstep(Q5.x, Q5.x + 0.45 + 0.3 * nF, dRoad);
    float baseD = 1.0 - smoothstep(0.0, 0.3 + 0.25 * nF, dBld);
    col *= 1.0 - (0.1 * kerb * nS + 0.22 * baseD) * Q4.z;
    ao *= 1.0 - 0.3 * baseD * Q4.z;
    float spillD = dLawn + 0.06 + 0.3 * nF * nS;                           // > 0 inside the ragged spill band
    float spill = G.AStep(0.0, spillD, max(fwidth(spillD), 1e-4)) * (1.0 - wUns);
    col = lerp(col, float3(0.13, 0.11, 0.08) * (0.8 + 0.4 * nF), spill * 0.7 * Q4.z);
    rough = lerp(rough, 0.95, spill * Q4.z);
}

// granite curb top on hard surfaces and lawns (worn bright arris at the road edge, dark joint to the paving)
if (wCurbTop > 0.0)
{
    float sp = G.NoiseB(P * 37.0) * saturate(1.0 - pix * 25.0);
    float3 gr = float3(0.30, 0.29, 0.275) * (0.85 + 0.3 * sp) * (0.92 + 0.16 * nM);
    gr *= 1.0 + 0.3 * (1.0 - G.AStep(0.014, dRoad, fwRoad));
    gr *= 1.0 - 0.5 * (1.0 - G.AStep(0.008, abs(dRoad - Q5.x), fwRoad));
    col = lerp(col, gr, wCurbTop);
    rough = lerp(rough, 0.62, wCurbTop);
    nxy *= 1.0 - 0.7 * wCurbTop;
    spec = lerp(spec, 0.5, wCurbTop);
}

Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
Rough = rough;
AO = ao;
Spec = spec;
return col;
