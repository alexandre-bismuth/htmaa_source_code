// Building facades with procedural windows fitted to each wall plane.
// Inputs: UV  (u = metres along the wall plane from its left edge, v = metres above ground)
//         UV1 (x = wall plane width m, y = building seed 0..1; +2 when the plane is a street-facing
//              shopfront, tools/mapgen/build_meshes.py)
//         UV2 (x = wall plane bottom m, y = wall plane top m: the eave on gable ends, windows stay below it)
//         D/N/ARM (Texture2D wall material), WP (float3 world cm), CV (camera vector WS), VN (vertex normal WS)
//         TS (TwoSidedSign: < 0 when the plane is seen from behind its mesh normal)
//         SUN (SkyAtmosphereLightDirection 0: world direction towards the sun)
//         P1 = (wall tile size m, nominal floor height m, bay width m, ground floor height m)
//         P2 = (window width frac of bay, window height frac of floor, sill frac of floor, style)
//              style: 0 masonry, 1 curtain-wall glass, 2 metal panels, 3 painted clapboard
//         P3 = (wall tint variation, glass roughness, frame width m, window recess darkening)
//         P4 = (interior emissive gain, room depth m, weathering strength, frame colour variation 0/1)
//         P5 = (sash: 0 plain/transom, 1 double-hung with muntins, 2 steel multi-light + spandrels, 3 casement pair,
//               4 Gothic lancet (pointed arch, double-hung), 5 round-arched head (double-hung);
//               muntin columns per sash, muntin rows per sash, window recess depth m)
//         P6 = (trim colour rgb, trim: 0 none, 1 stone sills + lintels (keystones on some), 2 painted casings
//               and corner boards, 3 stone sills + brick soldier-course lintels, 4 Victorian polychrome: black brick
//               bands at sill and springing level, sandstone sills)
//         style 2 (metal panels): WallTint is the panel colour, P4.w > 0.5 adds the odd coloured accent panel
//         P7 = (per-brick tint variation, share of dark clinker / burnt headers, unused, unused): bricks are told
//              apart by the id in ARM.b (fetch_textures.py make_brick_ids; mortar = 0); ids are re-hashed per texture
//              tile so the 1.4 m photo repeat no longer reads
//         WallTint, GlassColor, FrameColor (float3)
// Outputs: return = base colour, Nrm (float3 tangent: x along +u, y up), Rough, Metal, AO, Emit
//
// Windows are real recesses: the view ray is intersected with the box behind each opening (pane at the
// recess depth, lit jambs / head / sill board through their own normals) and the sun is traced back out
// of the box, so the reveals cast their shadow on the pane. Projecting sills, cornices and string courses
// cast analytic shadows on the wall below. Direct-light shadows the material cannot express through AO
// (AO only dims indirect light) are painted into the base colour, scaled by the surface's sun angle.
struct FacadeFn
{
    float Hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
    float Noise(float2 p)
    {
        float2 i = floor(p), f = frac(p);
        float2 s = f * f * (3.0 - 2.0 * f);
        return lerp(lerp(Hash(i), Hash(i + float2(1, 0)), s.x), lerp(Hash(i + float2(0, 1)), Hash(i + float2(1, 1)), s.x), s.y);
    }
    // box-filtered periodic pulse (1 on [a,b) of each unit period), filter width w: exact anti-aliasing
    // at any distance; tends to the duty cycle (b - a) once w spans several periods
    float PulseInt(float x, float a, float b) { return floor(x) * (b - a) + clamp(frac(x) - a, 0.0, b - a); }
    float Pulse(float x, float a, float b, float w)
    {
        w = max(w, 1e-4);
        return (PulseInt(x + 0.5 * w, a, b) - PulseInt(x - 0.5 * w, a, b)) / w;
    }
    // anti-aliased box [a, b] (1 inside), filter width w
    float Box(float x, float a, float b, float w) { return saturate((x - a) / w + 0.5) * saturate((b - x) / w + 0.5); }
    float3 Siding(float s)
    {
        float k = floor(s * 7.0);                       // Cambridge triple-decker palette
        if (k < 1.0) return float3(0.80, 0.80, 0.78);   // white
        if (k < 2.0) return float3(0.62, 0.66, 0.70);   // blue-grey
        if (k < 3.0) return float3(0.80, 0.74, 0.55);   // butter yellow
        if (k < 4.0) return float3(0.55, 0.62, 0.52);   // sage
        if (k < 5.0) return float3(0.52, 0.30, 0.25);   // barn red
        if (k < 6.0) return float3(0.70, 0.64, 0.56);   // tan
        return float3(0.36, 0.42, 0.50);                // slate blue
    }
    float3 ShopSign(float s)
    {
        float k = floor(s * 6.0);
        if (k < 1.0) return float3(0.05, 0.05, 0.05);   // black
        if (k < 2.0) return float3(0.05, 0.16, 0.10);   // racing green
        if (k < 3.0) return float3(0.35, 0.05, 0.04);   // oxblood
        if (k < 4.0) return float3(0.06, 0.08, 0.13);   // navy
        if (k < 5.0) return float3(0.30, 0.18, 0.09);   // stained wood
        return float3(0.55, 0.52, 0.48);                // grey
    }
    // 3x5 block font (bit 14 = top-left) for A B C D E F G H I K L M N O P R S T U Y Z, and 32 shop words of up to
    // six letters (5 bits per letter, 31 = none)
    uint Glyph(uint k)
    {
        static const uint g[21] = { 11245u, 27566u, 14627u, 27502u, 31143u, 31140u, 14699u, 23533u, 29847u, 23469u, 18727u, 24557u,
                       31597u, 31599u, 27556u, 27565u, 14478u, 29842u, 23407u, 23186u, 29351u };
        return g[min(k, 20u)];
    }
    uint Word(uint k)
    {
        static const uint w[32] = { 1072829442u, 1057273249u, 1040863502u, 1072965763u, 1073000449u, 1053206544u, 1073724417u, 1057392657u,
                       1048822352u, 574929931u, 547493889u, 1072955633u, 1073722606u, 1051009510u, 1056059651u, 1057105153u,
                       653403137u, 1057109232u, 1073237425u, 1073710670u, 539248077u, 1050822055u, 507723329u, 1052912655u,
                       144815532u, 1073709201u, 138581410u, 555299235u, 1043337697u, 1057527046u, 1041237129u, 1040760846u };
        return w[k & 31u];
    }
    // Interior mapping: the view ray (dl, wall-local: x along the plane, y up, z out of the wall)
    // enters a box room of size cell x depth at p; returns the room surface colour it hits.
    float3 Room(float2 p, float2 cell, float depth, float3 dl, float hr, float3 wallC, float lit)
    {
        dl.x = abs(dl.x) < 1e-4 ? 1e-4 : dl.x;
        dl.y = abs(dl.y) < 1e-4 ? 1e-4 : dl.y;
        dl.z = min(dl.z, -1e-3);
        p = clamp(p, 0.0, cell);
        float tx = ((dl.x > 0.0 ? cell.x : 0.0) - p.x) / dl.x;
        float ty = ((dl.y > 0.0 ? cell.y : 0.0) - p.y) / dl.y;
        float tz = -depth / dl.z;
        float t = min(min(tx, ty), tz);
        float3 h = float3(p, 0.0) + dl * t;
        float3 c;
        if (t == tz)
        {
            c = wallC;
            // furniture / partitions silhouette along the back wall
            float fur = step(h.y, 0.75 + 0.5 * Hash(float2(floor(h.x * 1.3), hr * 7.0)));
            c = lerp(c, wallC * 0.35, fur * step(0.35, hr));
        }
        else if (t == ty)
        {
            if (dl.y > 0.0)
            {
                // ceiling, with a light panel in lit rooms
                float panel = step(abs(h.x - cell.x * 0.5), cell.x * 0.25) * step(abs(h.z + depth * 0.5), depth * 0.2);
                c = wallC * 1.1 + panel * lit * 0.8;
            }
            else
            {
                c = lerp(float3(0.25, 0.18, 0.12), float3(0.22, 0.22, 0.24), Hash(float2(hr, 3.3))) * 0.8;   // floor
            }
        }
        else
        {
            c = wallC * 0.8;
        }
        return c * lerp(1.0, 0.45, saturate(-h.z / depth));
    }
    // painted-in direct shadow: a surface with sun cosine c keeps ~1 / (1 + 3 c) of its light in shadow. Calibrated on
    // the engine's own wall shadows under sun 10 / sky light 0.5 (2026-10-27: shadowed / sunlit brick = 0.41 after
    // the tonemapper, sun cosine ~0.75; Lumen bounce lifts real shade); s = shadow amount 0..1
    float ShadowMul(float s, float c) { return lerp(1.0f, 1.0f / (1.0f + 3.0f * saturate(c)), saturate(s)); }
};
FacadeFn F;

// ---- orientation. A plane whose mesh normal points into the building is seen from behind (two-sided):
// mirror u so text and layouts read left-to-right from the viewer's side, and remember to flip the
// tangent-space y at the end (the engine negates the whole normal on back faces)
bool back = TS < 0.0;
float width = UV1.x;
float u = back ? width - UV.x : UV.x;
float v = UV.y;
// metres of wall per pixel, from world position: the per-plane UVs jump across every wall-plane corner, which
// made fw and the texture mip selection blow up in a 1-2 px seam there
float3 wpx = ddx(WP) * 0.01, wpy = ddy(WP) * 0.01;
float fw = max(length(wpx), length(wpy));
bool shopPlane = UV1.y > 1.5;
float seed = shopPlane ? UV1.y - 2.0 : UV1.y;
seed = round(seed * 512.0) / 512.0;     // 16-bit UVs: same seed on shop (+2) and plain planes
float pb = UV2.x, pt = UV2.y;
float tile = P1.x, fhNominal = P1.y, bay = P1.z, ghNominal = P1.w;
float winW = P2.x, winH = P2.y, sill = P2.z;
int style = (int)round(P2.w);
float weather = P4.z;
int sash = (int)round(P5.x);
float recess = P5.w;
int trim = (int)round(P6.w);
float3 trimCol = P6.rgb;

// wall-local frame (x along +u as seen from outside, y up, z out of the wall), view ray and sun
float3 Nout = normalize(float3(VN.xy, 0.0) + float3(1e-5, 0.0, 0.0)) * (back ? -1.0f : 1.0f);
float3 Tr = float3(Nout.y, -Nout.x, 0.0);
float3 vd = -CV;
float3 dl = float3(dot(vd, Tr), vd.z, dot(vd, Nout));
// (the engine leaves the atmosphere light at straight up (0,0,1) when no directional light is flagged as the
// atmosphere's sun: then take the scene's main directional light, which every material view has)
float3 sunW = SUN;
if (sunW.z > 0.999 || dot(sunW, sunW) < 0.25) sunW = ResolvedView.DirectionalLightDirection;
if (dot(sunW, sunW) < 0.25) sunW = float3(-0.55, 0.55, 0.63);
sunW = normalize(sunW);
float3 Ls = float3(dot(sunW, Tr), sunW.z, dot(sunW, Nout));
float sunOn = saturate(Ls.z * 8.0) * saturate(Ls.y * 8.0);          // wall faces the sun, sun above the horizon
float LsZ = max(Ls.z, 0.05);

// ---- per-building variation
float h1 = F.Hash(float2(seed, 1.7)), h2 = F.Hash(float2(seed, 4.3)), hf = F.Hash(float2(seed, 5.5));
float hv1 = F.Hash(float2(seed, 2.9)), hv2 = F.Hash(float2(seed, 6.1)), hv3 = F.Hash(float2(seed, 8.3));
bay *= 0.9 + 0.2 * hv1;
fhNominal *= 0.95 + 0.1 * hv2;
winW *= 0.92 + 0.16 * hv3;
float3 frameCol = FrameColor;
if (P4.w > 0.5)
{
    if (hf < 0.18) frameCol = float3(0.06, 0.06, 0.055);          // black / dark bronze
    else if (hf < 0.28) frameCol = float3(0.10, 0.17, 0.12);      // Boston green
    else if (hf < 0.42) frameCol = float3(0.72, 0.68, 0.60);      // cream
}
// Georgian / Victorian sash variety: 6-over-6, 12-over-12 (taller), 2-over-2
float mcols = P5.y, mrows = P5.z;
if (sash == 1 && mcols > 1.5)
{
    float hs = F.Hash(float2(seed, 7.7));
    if (hs < 0.3) { mcols += 1.0; mrows += 1.0; }
    else if (hs > 0.85) { mcols = 1.0; mrows = 2.0; }
}

// ---- wall material
float2 tuv = float2(u, -v) / tile + float2(seed * 7.13, seed * 3.71);
float2 gx = float2(dot(wpx, Tr), -wpx.z) / tile, gy = float2(dot(wpy, Tr), -wpy.z) / tile;   // d(tuv) per pixel
float3 wall = Texture2DSampleGrad(D, DSampler, tuv, gx, gy).rgb;
float3 arm = Texture2DSampleGrad(ARM, ARMSampler, tuv, gx, gy).rgb;
float2 nxy = Texture2DSampleGrad(N, NSampler, tuv, gx, gy).rg * 2.0 - 1.0;
nxy.y = -nxy.y;                                     // texture V runs down the wall, tangent y up
float brickK = saturate((0.045 - fw) / 0.02);          // only while single bricks are resolved (mips average the ids)
if (P7.x > 0.0 && arm.b > 0.05 && brickK > 0.0)
{
    // per-brick colour: lighter / darker, redder / browner, some dark clinkers (Flemish-bond headers)
    // (re-hashed per tile row only: the ids continue across the texture's left / right edge, not its top / bottom)
    float bv = frac(arm.b * 7.31 + F.Hash(float2(0.0, floor(tuv.y)) + seed * 3.3));
    float bv2 = frac(bv * 13.7 + 0.37);
    float3 m = lerp(1.0 - P7.x, 1.0 + P7.x, bv) * float3(1.0 + (bv2 - 0.5) * P7.x * 0.6, 1.0, 1.0 - (bv2 - 0.5) * P7.x * 0.4);
    if (bv2 > 1.0 - P7.y) m *= float3(0.45, 0.42, 0.45);
    wall *= lerp(1.0, m, brickK);
}
float3 tint = WallTint * (1.0 + (h1 - 0.5) * 2.0 * P3.x);
tint *= lerp(float3(1.0 + P3.x * 0.4, 1.0, 1.0 - P3.x * 0.4), float3(1.0 - P3.x * 0.3, 1.0, 1.0 + P3.x * 0.3), h2);   // warm <-> cool
if (style == 3)
{
    tint = F.Siding(F.Hash(float2(seed, 9.1))) / max(dot(wall, float3(0.3, 0.59, 0.11)) * 1.6, 0.25);
}
float3 wallCol = wall * tint;
float3 col = wallCol;
float rough = arm.g;
float metal = 0.0;
float ao = arm.r;
float3 emit = 0.0;
float shade = 1.0;            // painted-in direct shadow multiplier
// stone trim: the trim colour with a soft mottling (the brick photo would print brick joints on it)
float3 stone = trimCol * (0.9 + 0.2 * F.Noise(float2(u, v) * 3.1 + seed * 17.0));

// ---- fit floors to this wall: ground floor only if the wall reaches the ground; a cornice /
// parapet band under the top; a whole number of floors in between
bool tall = pt - pb > 3.0;
float cornice = style == 1 ? 0.4 : (style == 3 ? 0.6 : (tall ? 1.1 : 0.3));
float top = pt - cornice;
bool reachesGround = pb < 1.0;
bool shop = shopPlane && reachesGround && style != 1 && pt > 5.5 && ghNominal < 5.0;   // not on the tall institutional (limestone) bases
float gh = reachesGround ? (shop ? max(ghNominal, 4.2) : ghNominal) : pb;
float span = top - gh;
float nfl = max(floor(span / fhNominal + 0.35), 0.0);
float fh = nfl > 0.0 ? span / nfl : fhNominal;

// ---- curtain walls (style 1) have their own path: a mullion / transom grid whose caps stand proud of the glass
// (the panes sit in a shallow box: lit / shadowed mullion sides), opaque spandrel panels over each slab, and per-pane
// glass: a slight tilt and tint (reflections break up per pane instead of one liquid smear across the facade),
// a faint interior with ceiling lights behind the vision glass, faded by Fresnel at grazing angles
if (style == 1)
{
    float modE = width / max(floor(width / bay + 0.5), 1.0);          // modules exactly fill the plane
    float mx = u / modE, mix_ = floor(mx);
    float cx1 = frac(mx) * modE;                                       // metres across the module
    bool gnd = reachesGround && v < gh;
    bool par = v >= top;                                               // parapet band above the last floor
    float fh1 = nfl > 0.5 ? fh : max(top - gh, 0.5);                   // (a short upper plane: one storey)
    float flr = gnd ? -1.0 : floor((v - gh) / fh1);
    float cellH1 = gnd ? gh : fh1;
    float yl = gnd ? v : (v - gh) - flr * fh1;                         // metres above this floor's slab line
    float spLo = gnd ? 0.0 : 0.75, spHi = gnd ? 0.45 : 0.4;            // spandrels: sill upstand, slab edge + plenum
    float mw = 0.035, tw = 0.03;                                       // mullion / transom half widths
    float zy0, zy1; int zone;                                          // 0 vision glass, 1 spandrel
    if (par) { zy0 = 0.0; zy1 = pt - top; yl = v - top; zone = 1; }
    else if (yl < spLo) { zy0 = 0.0; zy1 = spLo; zone = 1; }
    else if (yl > cellH1 - spHi) { zy0 = cellH1 - spHi; zy1 = cellH1; zone = 1; }
    else { zy0 = spLo; zy1 = cellH1 - spHi; zone = 0; }
    float px0 = mw, px1 = modE - mw, py0 = zy0 + tw, py1 = zy1 - tw;
    bool inPane = cx1 > px0 && cx1 < px1 && yl > py0 && yl < py1;
    float paneId = mix_ * 3.1 + flr * 17.3 + float(zone) * 7.7 + seed * 41.0;
    float ph = F.Hash(float2(paneId, 1.3)), ph2 = F.Hash(float2(paneId, 5.9));
    float3 cwCol = 0.0; float cwRough = 0.35, cwMetal = 0.7, cwAo = 1.0; float2 cwN = float2(0.0, 0.0);
    float3 cwEmit = 0.0; float cwShade = 1.0;
    float depth1 = max(P5.w, 0.12);
    // per building: mullion finish (clear anodised, dark bronze, black, white) and spandrel type (black glass,
    // light grey frit / aluminium panel, shadow box)
    float hm = F.Hash(float2(seed, 12.3)), hsp = F.Hash(float2(seed, 14.9));
    float3 mcol = hm < 0.35 ? frameCol : (hm < 0.6 ? float3(0.06, 0.055, 0.05) : (hm < 0.8 ? float3(0.025, 0.025, 0.027) : float3(0.62, 0.62, 0.6)));
    float3 spC = hsp < 0.4 ? GlassColor * 0.45 : (hsp < 0.8 ? float3(0.30, 0.31, 0.32) : GlassColor * 0.7);
    float spRough = hsp < 0.4 ? 0.12 : (hsp < 0.8 ? 0.38 : 0.1);
    float spMetal = (hsp >= 0.4 && hsp < 0.8) ? 0.3 : 0.0;
    if (!inPane)
    {
        // mullion / transom caps: brushed aluminium, rounded edges catch the light
        bool vert = !(cx1 > px0 && cx1 < px1);
        float eo = saturate(min(cx1, modE - cx1) / mw);                // 0 on the cap's centre line, 1 at its edge
        cwN = vert ? float2((cx1 < modE * 0.5 ? 1.0f : -1.0f) * 0.5f * eo, 0.0) : float2(0.0, 0.0);
        cwCol = mcol * (0.95 + 0.1 * ph);
    }
    else
    {
        float W1 = px1 - px0, H1 = py1 - py0;
        float2 p1 = float2(cx1 - px0, yl - py0);
        float3 r1 = float3(dl.x, dl.y, min(dl.z, -1e-3));
        float tz1 = depth1 / -r1.z;
        float tx1 = r1.x > 0.0 ? (W1 - p1.x) / max(r1.x, 1e-4) : p1.x / max(-r1.x, 1e-4);
        float ty1 = r1.y > 0.0 ? (H1 - p1.y) / max(r1.y, 1e-4) : p1.y / max(-r1.y, 1e-4);
        float t1 = min(tz1, min(tx1, ty1));
        float3 h1p = float3(p1, 0.0) + r1 * t1;
        h1p.xy = clamp(h1p.xy, 0.0, float2(W1, H1));
        int hit1 = t1 == tz1 ? 0 : (t1 == tx1 ? 1 : 2);
        float2 e1 = h1p.xy + Ls.xy * (-h1p.z / LsZ);
        float lit1 = F.Box(e1.x, 0.0, W1, 0.02) * F.Box(e1.y, 0.0, H1, 0.02);
        float3 n1 = float3(0.0, 0.0, 1.0);
        if (hit1 == 1) n1 = float3(r1.x > 0.0 ? -1.0f : 1.0f, 0.0, 0.0);
        if (hit1 == 2) n1 = float3(0.0, r1.y > 0.0 ? -1.0f : 1.0f, 0.0);
        cwShade = F.ShadowMul((1.0 - lit1) * sunOn, dot(n1, Ls));
        if (hit1 != 0)
        {
            // mullion side / transom soffit inside the module: anodised aluminium
            cwCol = mcol * 0.8; cwRough = 0.45; cwMetal = 0.6; cwAo = 0.8; cwN = n1.xy * 0.95;
        }
        else
        {
            // per-pane glass: a little tilt (heat-strengthened panes are never flat) and tint
            cwN = (float2(ph, ph2) - 0.5) * 0.03;
            float3 tintP = lerp(float3(0.92, 0.97, 1.0), float3(1.0, 1.0, 0.95), ph2) * (0.9 + 0.2 * ph);
            float cosV = saturate(-r1.z);
            float fres = 0.04 + 0.96 * pow(1.0 - cosV, 5.0);
            if (zone == 1)
            {
                // spandrel: back-painted (opaque) glass over the slab: darker, glossy but less sharp
                cwCol = spC * tintP;
                cwRough = spRough + 0.06 * ph; cwMetal = spMetal; cwAo = 0.9;
            }
            else
            {
                float3 inside = GlassColor * 0.5 * tintP;
                float fadeW1 = saturate((fw - 0.25) / 0.5);
                if (fadeW1 < 0.99)
                {
                    float lit = step(0.45, F.Hash(float2(mix_ * 1.7, flr) + seed * 5.3));
                    float3 roomC = lerp(float3(0.40, 0.40, 0.40), float3(0.34, 0.37, 0.42), ph);
                    float2 rp1 = float2(h1p.x + px0, h1p.y + py0);
                    float3 rc1 = F.Room(rp1, float2(modE, cellH1), P4.y, r1, ph, roomC, lit);
                    float3 room1 = rc1 * 0.3 * (0.4 + 0.6 * lit) * (1.0 - fres);    // tinted, Fresnel-weighted transmission
                    inside = lerp(inside + room1 * 0.35, inside, fadeW1);
                    cwEmit = room1 * P4.x * (1.0 - fadeW1);
                }
                cwCol = inside;
                cwRough = P3.y + 0.05 * ph;
                cwMetal = 0.0;
                cwAo = 1.0;
            }
        }
    }
    // far field: the module average (vision glass, spandrels, mullions) once panes shrink below a few pixels
    float fade1 = saturate((fw - 0.3) / 0.6);
    float vis = saturate((cellH1 - spLo - spHi) / cellH1);
    float3 avg1 = GlassColor * 0.5 * vis + spC * (1.0 - vis);
    avg1 = lerp(avg1, mcol, 2.0 * mw / modE);
    float3 c1 = lerp(cwCol * lerp(1.0, cwShade, saturate(1.0 - fw / 0.1)), avg1, fade1);
    cwN *= 1.0 - fade1;
    if (back) cwN.y = -cwN.y;
    Nrm = float3(cwN, sqrt(saturate(1.0 - dot(cwN, cwN))));
    Rough = saturate(lerp(cwRough, P3.y + 0.05, fade1));
    Metal = cwMetal * (1.0 - fade1);
    AO = cwAo;
    Emit = cwEmit * (1.0 - fade1);
    return saturate(c1);
}

// ---- window grid, centred on the wall plane; a narrow plane (a bay, a tower face) gets one centred window
float halfW0 = winW * 0.5 * bay;
float nb = floor(width / bay);
float bayE = bay;
if (nb < 1.0 && winW > 0.05 && width > 2.0 * halfW0 + 0.6 && style != 1) { nb = 1.0; bayE = width; }
float margin = (width - nb * bayE) * 0.5;
float bx = (u - margin) / bayE;
float ix = floor(bx);
float fx = frac(bx);
bool inBays = nb >= 1.0 && ix >= 0.0 && ix < nb;
bool isGround = reachesGround && v < gh;
bool inUpper = v >= gh && v < top && nfl > 0.0;
float vv = v - gh;
float iz = isGround ? -1.0 : floor(vv / fh);
float fz = isGround ? 0.0 : frac(vv / fh);
float yloc = isGround ? v : fz * fh;
float wy0 = isGround ? 0.95 : sill * fh;
float wy1 = isGround ? gh - 0.55 : (sill + winH) * fh;
float halfW = min(halfW0, 0.5 * bayE - 0.25);
float cx = (fx - 0.5) * bayE;                         // metres from the bay centre
float dx = abs(cx);
float frameW = P3.z;
bool rows = isGround || inUpper;
float cellH = isGround ? gh : fh;
float glassY0 = wy0, glassY1 = wy1;                   // glazed part of the opening (spandrels outside it)

// shopfront: big display windows between narrow piers, a painted sign band above, some doors
float signH0 = gh - 1.05, signH1 = gh - 0.3;
bool door = false;
if (shop && isGround)
{
    halfW = 0.5 * bayE - 0.22;
    wy0 = 0.5;
    wy1 = signH0 - 0.08;
    door = F.Hash(float2(ix, seed * 13.0)) < 0.28;
    if (door) { wy0 = 0.02; halfW = min(halfW, 0.75); }
    glassY0 = wy0; glassY1 = wy1;
}
else if (sash == 2 && !isGround && style == 0)
{
    // MIT steel windows: the recess runs through the floor; dark spandrel panels between the glazing
    wy0 = 0.0; wy1 = fh;
}

if (style == 1)
{
    // curtain wall: glass everywhere, thin mullions on the bay grid, spandrel band at each slab
    halfW = 0.5 * bayE - 0.05;
    wy0 = isGround ? 0.05 : 0.0;
    wy1 = isGround ? gh - 0.25 : fh * 0.80;
    glassY0 = wy0; glassY1 = wy1;
    inBays = width > 1.0;
    col = frameCol; rough = 0.35; metal = 0.8;
    wallCol = frameCol;
}
if (style == 2)
{
    // metal cladding panels with seams and a few colour accents; ribbon windows
    float2 pc = floor(float2(u / 1.5, v / 1.2));
    float2 pf = frac(float2(u / 1.5, v / 1.2));
    float ph = F.Hash(pc + seed * 17.0);
    float3 base = WallTint * lerp(0.9, 1.05, ph);
    if (P4.w > 0.5 && ph > 0.93) base = float3(0.85, 0.35, 0.15);
    else if (P4.w > 0.5 && ph > 0.88) base = float3(0.85, 0.70, 0.20);
    float seam = step(0.97, max(pf.x, pf.y));
    col = base * (1.0 - seam * 0.6);
    wallCol = base;
    metal = dot(WallTint, 0.333) < 0.8 ? 1.0f : 0.0f;    // white panels are painted, grey ones bare metal
    rough = lerp(0.28, 0.45, F.Hash(pc * 1.3)) + (1.0 - metal) * 0.15;
    nxy = float2(0, 0);
    ao = 1.0 - seam * 0.5;
}

float ex = halfW - dx;                                 // > 0 inside the opening (m)
float ey = min(yloc - wy0, wy1 - yloc);
// arched heads: the opening's top follows a pointed (equilateral) or round arch from the springing line ys
float ys = wy1;
if ((sash == 4 || sash == 5) && !isGround && style == 0)
{
    float rise = sash == 4 ? halfW * 1.732 : halfW;
    ys = wy1 - rise;
    float ay = sash == 4 ? sqrt(max(4.0 * halfW * halfW - (halfW + dx) * (halfW + dx), 0.0)) : sqrt(max(halfW * halfW - dx * dx, 0.0));
    ey = min(ey, ys + ay - yloc);
}
bool inWin = rows && inBays && ex > 0.0 && ey > 0.0 && (v > 0.3 || door);
float edge = min(ex, ey);
float near = 1.0 - saturate((fw - 0.02) / 0.06);       // fine joinery and trim fade out by ~8 cm / pixel
bool masonry = style == 0;

// ---- trim around the openings (outside them): stone sills with a shadow under the drip, lintels / flat
// arches with keystones, soldier courses, painted casings
if (rows && inBays && !inWin && !shop && style != 1 && style != 2)
{
    float ext = trim == 2 ? 0.12 : 0.09;
    float sillH = 0.11, linH = trim == 3 ? 0.23 : 0.2;
    bool inX = dx < halfW + ext;
    if (trim == 4)
    {
        // High Victorian polychromy (Memorial Hall): black brick courses under the sills and at the arch
        // springing, sandstone sills, a sandstone voussoir ring round the arch
        if ((yloc > wy0 - 0.45 && yloc < wy0 - 0.25) || abs(yloc - ys) < 0.09) { col = wallCol * float3(0.22, 0.21, 0.23); }
        if (inX && yloc > wy0 - sillH && yloc < wy0) { col = stone; nxy = yloc > wy0 - 0.035 ? float2(0.0, 0.75) : float2(0.0, 0.1); }
        if (dx < halfW + 0.2 && yloc > ys && ey > -0.2 && ey <= 0.0) col = (frac(atan2(yloc - ys, cx) * 3.0) < 0.5) ? stone : wallCol * 0.3;
    }
    else if (trim == 2)
    {
        // painted wood casing (clapboard houses): flat boards round the opening, a cap over it
        bool cas = dx < halfW + 0.11 && yloc > wy0 - 0.1 && yloc < wy1 + 0.16;
        if (cas)
        {
            col = frameCol * 0.95; rough = 0.6; ao = 1.0; nxy = float2(0.0, 0.0);
            if (yloc > wy1 + 0.1) { nxy = float2(0.0, 0.5); col *= 1.05; }                    // drip cap
            if (yloc < wy0 && yloc > wy0 - 0.04) nxy = float2(0.0, 0.6);                      // sill nose
        }
        float sh = (Ls.y / LsZ) * 0.03;                     // casing stands 3 cm proud: shadow below the cap
        if (!cas && dx < halfW + 0.11 && yloc < wy0 - 0.1 && yloc > wy0 - 0.1 - sh) shade = F.ShadowMul(sunOn, Ls.z);
    }
    else if (trim != 0 && masonry)
    {
        if (inX && yloc > wy0 - sillH && yloc < wy0)
        {
            // projecting stone sill: lit top bevel, front face
            col = stone; rough = 0.75; ao = 1.0;
            nxy = yloc > wy0 - 0.035 ? float2(0.0, 0.75) : float2(0.0, 0.1);
        }
        float sh = (Ls.y / LsZ) * 0.06;                     // sill projects 6 cm: shadow on the wall below
        if (inX && yloc <= wy0 - sillH && yloc > wy0 - sillH - sh) shade = F.ShadowMul(sunOn, Ls.z);
        if (inX && yloc > wy1 && yloc < wy1 + linH)
        {
            if (trim == 1)
            {
                // stone lintel / flat arch, keystone on some buildings
                bool key = F.Hash(float2(seed, 3.9)) < 0.6 && dx < 0.13;
                col = stone * (key ? 1.06f : 1.0f); rough = 0.75; ao = 1.0; nxy *= 0.2;
                if (key) nxy = float2(0.0, 0.0);
                if (yloc > wy1 + linH - 0.03) nxy = float2(0.0, 0.6);
            }
            else
            {
                // soldier course: bricks on end (the wall photo turned 90 degrees, darker)
                float2 suv = float2(v, u) / tile + seed * 5.1;
                col = Texture2DSampleGrad(D, DSampler, suv, gx.yx, gy.yx).rgb * tint * 0.82;
                nxy = Texture2DSampleGrad(N, NSampler, suv, gx.yx, gy.yx).gr * 2.0 - 1.0;
            }
        }
        if (inX && yloc >= wy1 + linH && yloc < wy1 + linH + (Ls.y / LsZ) * 0.03) shade = F.ShadowMul(sunOn, Ls.z);
    }
}

// ---- weathering on masonry / siding: soot at the base, drips under the parapet and the sills,
// broad blotchy staining. Only darkens, so it reads as dirt, not as a texture change.
if (style == 0 || style == 3)
{
    float plinth = (style == 0 && reachesGround && !shop && trim == 0) ? 1.0 - step(0.6, v) : 0.0;
    col = lerp(col, col * 0.55 + 0.08, plinth);
    if (trim == 0)
    {
        bool sillBand = rows && !isGround && inBays && dx < halfW + 0.08 && yloc > wy0 - 0.12 && yloc < wy0;
        if (sillBand) { col = lerp(col, float3(0.62, 0.60, 0.56), 0.85); rough = 0.7; nxy = float2(0.0, 0.6); }
    }

    float blotch = F.Noise(float2(u, v) / 5.0 + seed * 40.0) * 0.6 + F.Noise(float2(u, v) / 1.7 + seed * 11.0) * 0.4;
    float base = (1.0 - smoothstep(0.0, 1.6, v)) * (0.55 + 0.45 * F.Noise(float2(u * 0.9, seed * 30.0)));
    float drip = saturate((v - (pt - 4.0)) / 3.5) * F.Noise(float2(u * 2.3 + seed * 50.0, v * 0.12));
    float streak = 0.0;
    if (rows && !isGround && inBays && dx < halfW && yloc < wy0)
        streak = saturate(1.0 - (wy0 - yloc) / max(wy0, 0.1)) * F.Noise(float2(u * 7.0, iz + seed * 9.0));
    float dirt = saturate(base * 0.45 + drip * 0.35 + streak * 0.25 + (blotch - 0.5) * 0.25);
    col *= 1.0 - weather * dirt;
    rough = lerp(rough, 0.95, weather * dirt * 0.5);
}

// ---- horizontal bands on masonry: base course, string course over the ground floor, cornice + parapet
// coping at the top. Each casts its analytic shadow on the wall below.
if (masonry && tall)
{
    float cotSun = Ls.y / LsZ;                            // shadow drop per metre of projection
    if (reachesGround && trim != 0 && v < 0.75 && !(shop && isGround && inWin))
    {
        col = stone * 0.78; rough = 0.8; ao = 1.0; nxy *= 0.3;                           // granite base course
        if (v > 0.69) nxy = float2(0.0, 0.7);                                            // chamfered top
    }
    if (reachesGround && trim != 0 && !shop && v > gh - 0.04 && v < gh + 0.2 && nfl > 0.0)
    {
        col = stone; rough = 0.75; ao = 1.0; nxy = v > gh + 0.15 ? float2(0.0, 0.7) : float2(0.0, 0.05);   // string course
    }
    if (reachesGround && trim != 0 && !shop && v <= gh - 0.04 && v > gh - 0.04 - cotSun * 0.06 && nfl > 0.0 && !inWin)
        shade = F.ShadowMul(sunOn, Ls.z);
    // cornice zone (above the last floor): frieze, projecting cornice, parapet, coping
    float c0 = top + 0.25, c1 = top + 0.62;
    float3 cc = trim != 0 ? stone : wallCol * 1.08;
    if (v > c0 && v < c1)
    {
        col = cc; rough = 0.75; ao = 1.0;
        float k = (v - c0) / (c1 - c0);
        nxy = k < 0.25 ? float2(0.0, -0.8) : (k > 0.8 ? float2(0.0, 0.75) : float2(0.0, 0.0));   // bed moulding, corona, cymatium
        if (k < 0.25) col *= 0.7;
        // dentils under the corona on trimmed (classical) buildings
        if (trim == 1 && k > 0.25 && k < 0.45 && near > 0.0)
        {
            float den = F.Pulse(u / 0.16, 0.0, 0.55, fw / 0.16);
            col *= lerp(1.0, 0.55, (1.0 - den) * near);
        }
    }
    if (v <= c0 && v > c0 - cotSun * 0.4) shade = min(shade, F.ShadowMul(sunOn, Ls.z));   // the cornice projects 40 cm
    if (v > pt - 0.12 && v < pt + 0.02) { col = cc * 0.92; nxy = float2(0.0, 0.6); rough = 0.8; }   // coping (the gable above stays wall)
}

if (shop && isGround && !inWin)
{
    // shopfront joinery: painted piers and the fascia sign band (one colour per shop of ~3 bays)
    float3 sc = pow(F.ShopSign(F.Hash(float2(floor(ix / 3.0), seed * 21.0))), 2.2);   // palette is sRGB-authored
    bool band = v > signH0 && v < signH1;
    // piers: painted joinery in the shop colour (opaque paint, faint texture); masonry resumes above the sign cap
    float wl = dot(wall, float3(0.3, 0.59, 0.11));
    if (v < signH1) col = band ? sc : sc * (0.92 + 0.16 * saturate(wl * 2.0)) + 0.01;
    if (v < signH1) { rough = band ? 0.7 : 0.75; ao = 1.0; nxy *= 0.15; }   // flat paint hides the masonry relief
    if (band) nxy = float2(0.0, 0.0);
    if (v > signH1 - 0.06 && v < signH1) { nxy = float2(0.0, 0.7); col *= 1.2; }   // cap moulding
    if (v < signH0 && v > signH0 - (Ls.y / LsZ) * 0.08) shade = F.ShadowMul(sunOn, Ls.z);   // fascia overhang shadow
    // shop name: a real word ("CAFE", "BOOKS", "PIZZA"...) in a 3x5 block font, centred on the shop's fascia
    // (the old random pseudo-glyphs produced mirror-image letters); faded out before it can alias
    float lfade = saturate((0.06 - fw) / 0.03);
    if (band && lfade > 0.0)
    {
        float si = floor(ix / 3.0);
        float shopW = min(3.0, nb - si * 3.0) * bayE;
        float sx = (u - margin) - si * 3.0 * bayE;
        uint word = F.Word((uint)(F.Hash(float2(si, seed * 37.0)) * 31.99));
        float n = 0.0;
        [unroll] for (uint k = 0; k < 6; k++) n += ((word >> (5 * k)) & 31u) != 31u ? 1.0f : 0.0f;
        float th = min(signH1 - signH0 - 0.3, shopW * 0.8 / max(n * 0.8, 0.1));    // text height (m)
        float cw = th * 0.8;                                                       // letter cell: 3 + 1 font pixels
        float lx = (sx - 0.5 * shopW + 0.5 * (n * cw - 0.2 * th)) / cw;
        float ly = (v - 0.5 * (signH0 + signH1) + 0.5 * th) / th;
        float ink = 0.0;
        if (lx >= 0.0 && lx < n && ly >= 0.0 && ly < 1.0)
        {
            uint ci = (uint)lx;
            uint colp = (uint)(frac(lx) * 4.0);
            uint rowp = 4u - min((uint)(ly * 5.0), 4u);
            uint g = F.Glyph((word >> (5u * ci)) & 31u);
            ink = colp < 3u ? (float)((g >> (14u - (rowp * 3u + colp))) & 1u) : 0.0;
        }
        float sl = dot(sc, float3(0.3, 0.59, 0.11));
        float3 inkC = sl < 0.08 ? (F.Hash(float2(seed, 2.7)) < 0.5 ? float3(0.62, 0.56, 0.42) : float3(0.55, 0.38, 0.09))
                                : float3(0.02, 0.02, 0.02);
        if (sl > 0.25) inkC = float3(0.04, 0.05, 0.08);
        col = lerp(col, inkC, ink * lfade);
    }
}

if (inWin)
{
    float wr = F.Hash(float2(ix, iz) + seed * 31.7);
    // ---- the recess: intersect the view ray with the box behind the opening
    float W = 2.0 * halfW, H = wy1 - wy0;
    float2 p = float2(cx + halfW, yloc - wy0);               // position in the opening (m)
    float depth = style == 1 ? 0.0 : (shop && isGround ? 0.12 : recess);
    float3 r = float3(dl.x, dl.y, min(dl.z, -1e-3));
    float tz = depth / -r.z;
    float tx = r.x > 0.0 ? (W - p.x) / max(r.x, 1e-4) : p.x / max(-r.x, 1e-4);
    float ty = r.y > 0.0 ? (H - p.y) / max(r.y, 1e-4) : p.y / max(-r.y, 1e-4);
    float t = min(tz, min(tx, ty));
    float3 hp = float3(p, 0.0) + r * t;
    hp.xy = clamp(hp.xy, 0.0, float2(W, H));
    int hit = depth <= 0.0 ? 0 : (t == tz ? 0 : (t == tx ? 1 : 2));
    // sun traced back out of the box: lit where it leaves through the opening
    float2 e = hp.xy + Ls.xy * (-hp.z / LsZ);
    float litS = F.Box(e.x, 0.0, W, 0.03) * F.Box(e.y, 0.0, H, 0.03);
    float3 ns = float3(0.0, 0.0, 1.0);                       // normal of the surface the ray hit (local)
    if (hit == 1) ns = float3(r.x > 0.0 ? -1.0f : 1.0f, 0.0, 0.0);
    if (hit == 2) ns = float3(0.0, r.y > 0.0 ? -1.0f : 1.0f, 0.0);
    float recShade = F.ShadowMul((1.0 - litS) * sunOn, dot(ns, Ls));

    if (hit != 0)
    {
        // reveal (jamb, head soffit or inner sill board): the wall material turned into the opening,
        // darker towards the window (sky occluded)
        float occ = saturate(-hp.z / max(depth, 0.01));
        col = (trim == 1 && masonry ? stone : wallCol) * lerp(0.95, 0.7, occ);
        if (hit == 2 && r.y < 0.0) col = trim != 0 && trim != 2 ? stone : col;        // sill board
        rough = 0.8; metal = 0.0; ao = lerp(1.0, 0.55, occ);
        nxy = ns.xy * 0.95;
        if (style == 3 || trim == 2) col = frameCol * lerp(0.95, 0.75, occ);         // painted wood reveals
    }
    else
    {
        // ---- the window itself, at the back of the recess: sash frames, muntins, glass
        float2 q = hp.xy;                                     // on the pane plane, from the opening corner
        float fwF = fw * 1.5;
        float fr = frameW;
        float glassL = (q.y > glassY0 - wy0 && q.y < glassY1 - wy0) ? 1.0f : 0.0f;    // glazed rows of the opening
        float frm = 1.0 - F.Box(q.x, fr, W - fr, fwF) * F.Box(q.y, fr, H - fr, fwF);
        float mun = 0.0;
        float paneId = 0.0;
        float mw = 0.022;
        if ((sash == 1 || sash == 4 || sash == 5) && !(shop && isGround))
        {
            // double-hung: meeting rail at mid height, muntins in each sash
            float hm = H * 0.5;
            float rail = F.Box(q.y, hm - 0.035, hm + 0.035, fwF);
            float sy = q.y < hm ? q.y - fr : q.y - hm - 0.035;
            float sh = hm - fr - 0.035;
            float pcx = (W - 2.0 * fr) / max(mcols, 1.0), pcy = sh / max(mrows, 1.0);
            float mx = mcols > 1.0 ? F.Pulse((q.x - fr) / pcx + 0.5 * mw / pcx, 0.0, mw / pcx, fwF / pcx) : 0.0;
            float my = mrows > 1.0 ? F.Pulse(sy / pcy + 0.5 * mw / pcy, 0.0, mw / pcy, fwF / pcy) : 0.0;
            mun = max(rail, max(mx, my) * near);
            paneId = floor((q.x - fr) / pcx) + 7.0 * floor(q.y / max(pcy, 0.05));
        }
        else if (sash == 2 && !isGround)
        {
            // steel multi-light: slim bars on a grid, a heavier transom; spandrel panels outside the glazing
            float pcx = (W - 2.0 * fr) / max(mcols, 1.0), pcy = (glassY1 - glassY0) / max(mrows, 1.0);
            float gy = q.y - (glassY0 - wy0);
            float mx = F.Pulse((q.x - fr) / pcx + 0.5 * mw / pcx, 0.0, mw / pcx, fwF / pcx);
            float my = F.Pulse(gy / pcy + 0.5 * mw / pcy, 0.0, mw / pcy, fwF / pcy);
            float tr = F.Box(gy, (glassY1 - glassY0) * 0.72 - 0.03, (glassY1 - glassY0) * 0.72 + 0.03, fwF);
            mun = max(tr, max(mx, my) * near);
            paneId = floor((q.x - fr) / pcx) + 7.0 * floor(gy / max(pcy, 0.05));
        }
        else if (sash == 3)
        {
            // casement pair / modern: centre mullion, transom light on some
            float tr = F.Hash(float2(seed, 1.3)) < 0.5 ? F.Box(q.y, H * 0.76 - 0.03, H * 0.76 + 0.03, fwF) : 0.0;
            mun = max(F.Box(q.x, W * 0.5 - 0.03, W * 0.5 + 0.03, fwF), tr);
            paneId = step(W * 0.5, q.x) + 2.0 * step(H * 0.76, q.y);
        }
        else if (!(shop && isGround) && style != 1)
        {
            // plain sash / fixed light, a transom on some buildings
            mun = F.Hash(float2(seed, 1.9)) < 0.4 ? F.Box(q.y, H * 0.7 - 0.03, H * 0.7 + 0.03, fwF) : 0.0;
            if (style == 0 && !isGround) mun = max(mun, F.Box(q.y, H * 0.5 - 0.03, H * 0.5 + 0.03, fwF) * near);
        }
        if (style == 1)
        {
            frm = (edge < frameW || dx < 0.025) ? 1.0f : 0.0f;
            mun = 0.0;
        }
        float joinery = saturate(max(frm, mun));

        // glass: glossy (reflects the sky through Lumen) over a parallax room interior; each pane
        // slightly tilted (old crown glass, putty glazing) so reflections break up per pane
        float blindLevel = F.Hash(float2(iz, ix) * 1.31 + seed) * (style == 1 ? 0.5 : 0.9) * (shop ? 0.0 : 1.0);
        float blinds = step(1.0 - blindLevel, q.y / max(H, 0.01));
        float fadeW = saturate((fw - 0.35) / 0.65);
        float3 inside = GlassColor * lerp(0.25, 1.0, wr);
        float3 ie = 0.0;
        if (fadeW < 0.99)
        {
            float lit = step(shop ? 0.1 : 0.55, F.Hash(float2(ix * 1.7, iz) + seed * 5.3));
            float3 roomC = lerp(float3(0.42, 0.40, 0.36), float3(0.36, 0.40, 0.44), F.Hash(float2(ix, iz * 2.1) + seed));
            if (shop) roomC = lerp(float3(0.55, 0.45, 0.32), float3(0.50, 0.50, 0.52), wr);
            float2 cell = float2(bayE, cellH);
            float2 rp = float2(q.x - halfW + 0.5 * bayE, q.y + wy0);
            float3 rc = F.Room(rp, cell, P4.y * (shop ? 1.6 : 1.0), r, wr, roomC, lit);
            float glassT = style == 1 ? 0.35 : 0.6;      // tinted curtain wall glass hides more
            float3 room = rc * glassT * (0.45 + 0.55 * lit);
            inside = lerp(room * 0.25, inside, fadeW);
            ie = room * P4.x * (1.0 - fadeW) * (shop ? 1.6 : 1.0);
        }
        float3 blindC = float3(0.55, 0.53, 0.50) * 0.5;
        float3 glassC = lerp(inside, blindC, blinds * 0.8);
        float pr = F.Hash(float2(paneId, wr * 13.0));
        float2 tilt = (sash == 1 ? 0.06 : 0.025) * (float2(pr, frac(pr * 7.3)) - 0.5) * near;
        float3 spand = frameCol * 0.6;
        bool isSpandrel = glassL < 0.5 && style == 0;
        col = isSpandrel ? spand : glassC;
        rough = isSpandrel ? 0.5 : (shop ? P3.y * 0.5 : P3.y);   // plate glass shopfronts: crisper reflections
        metal = isSpandrel ? 0.6 : 0.0;
        nxy = isSpandrel ? float2(0.0, 0.0) : tilt;
        emit = isSpandrel ? 0.0 : ie * (1.0 - blinds * 0.85);
        ao = lerp(1.0 - P3.w * 0.5, 1.0, saturate(min(min(q.x, W - q.x), min(q.y, H - q.y)) / 0.3));
        // joinery on top
        col = lerp(col, frameCol, joinery);
        rough = lerp(rough, style == 1 ? 0.45 : 0.6, joinery);    // painted joinery: matte (mid roughness sparkles under Lumen)
        metal = lerp(metal, (style == 1 || sash == 2) ? 0.7 : 0.0, joinery);
        nxy = lerp(nxy, float2(0.0, 0.0), joinery);
        emit *= 1.0 - joinery;
    }
    // the recess blends into the flat window as it gets small on screen
    shade = lerp(1.0, recShade, near);
}

// ---- distance anti-aliasing: once a pixel covers more than ~35 cm of wall the window pattern
// aliases (moire); fade towards the pattern's average colour instead
float fade = saturate((fw - 0.35) / 0.65);
float cover = (style == 1) ? 0.85 : saturate((2.0 * halfW / bayE) * ((wy1 - wy0) / max(fh, 0.1))) * (inBays && rows ? 1.0f : 0.0f);
if (inUpper && nb >= 1.0)
{
    // far field (skyline, aerials): floors and bays stay readable as filtered glass / wall bands
    // instead of collapsing to one flat colour
    float px = F.Pulse(bx, 0.5 - halfW / bayE, 0.5 + halfW / bayE, fw / bayE);
    float py = F.Pulse(vv / fh, saturate(wy0 / fh), saturate(wy1 / fh), fw / fh);
    cover = px * py;
}
float3 avg = lerp(wallCol, GlassColor * 0.75 + frameCol * 0.1, cover);
col = lerp(col * shade, avg, fade);
rough = lerp(rough, lerp(arm.g, P3.y, cover), fade);
nxy *= 1.0 - fade;
if (back) nxy.y = -nxy.y;

Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
Rough = saturate(rough);
Metal = metal * (1.0 - fade * 0.5);
AO = saturate(ao);
Emit = emit;
return saturate(col);
