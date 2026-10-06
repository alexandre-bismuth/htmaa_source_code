// Building facades with procedural windows fitted to each wall plane.
// Inputs: UV  (u = metres along the wall plane from its left edge, v = metres above ground)
//         UV1 (x = wall plane width m, y = building seed 0..1; +2 when the plane is a street-facing
//              shopfront, tools/mapgen/build_meshes.py)
//         UV2 (x = wall plane bottom m, y = wall plane top m)
//         D/N/ARM (Texture2D wall material), WP (float3 world cm), CV (camera vector WS), VN (vertex normal WS)
//         P1 = (wall tile size m, nominal floor height m, bay width m, ground floor height m)
//         P2 = (window width frac of bay, window height frac of floor, sill frac of floor, style)
//              style: 0 masonry, 1 curtain-wall glass, 2 metal panels, 3 painted clapboard
//         P3 = (wall tint variation, glass roughness, frame width m, window recess darkening)
//         P4 = (interior emissive gain, room depth m, weathering strength, frame colour variation 0/1)
//         WallTint, GlassColor, FrameColor (float3)
// Outputs: return = base colour, Nrm (float3 tangent: x along +u, y up), Rough, Metal, AO, Emit
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
    // Interior mapping: the view ray (dl, wall-local: x along the plane, y up, z out of the wall)
    // enters a box room of size cell x depth at p; returns the room surface colour it hits.
    float3 Room(float2 p, float2 cell, float depth, float3 dl, float hr, float3 wallC, float lit)
    {
        dl.x = abs(dl.x) < 1e-4 ? 1e-4 : dl.x;
        dl.y = abs(dl.y) < 1e-4 ? 1e-4 : dl.y;
        dl.z = min(dl.z, -1e-3);
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
};
FacadeFn F;

float u = UV.x, v = UV.y;
float fw = max(length(float2(ddx(u), ddy(u))), length(float2(ddx(v), ddy(v))));   // metres of wall per pixel
float width = UV1.x;
bool shopPlane = UV1.y > 1.5;
float seed = shopPlane ? UV1.y - 2.0 : UV1.y;
seed = round(seed * 512.0) / 512.0;     // 16-bit UVs: same seed on shop (+2) and plain planes
float pb = UV2.x, pt = UV2.y;
float tile = P1.x, fhNominal = P1.y, bay = P1.z, ghNominal = P1.w;
float winW = P2.x, winH = P2.y, sill = P2.z;
int style = (int)round(P2.w);
float weather = P4.z;

// ---- per-building variation
float h1 = F.Hash(float2(seed, 1.7)), h2 = F.Hash(float2(seed, 4.3)), hf = F.Hash(float2(seed, 5.5));
float3 frameCol = FrameColor;
if (P4.w > 0.5)
{
    if (hf < 0.18) frameCol = float3(0.06, 0.06, 0.055);          // black / dark bronze
    else if (hf < 0.28) frameCol = float3(0.10, 0.17, 0.12);      // Boston green
    else if (hf < 0.42) frameCol = float3(0.72, 0.68, 0.60);      // cream
}

// ---- wall material
float2 tuv = float2(u, -v) / tile + float2(seed * 7.13, seed * 3.71);
float3 wall = Texture2DSample(D, DSampler, tuv).rgb;
float3 arm = Texture2DSample(ARM, ARMSampler, tuv).rgb;
float2 nxy = Texture2DSample(N, NSampler, tuv).rg * 2.0 - 1.0;
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

// ---- fit floors to this wall: ground floor only if the wall reaches the ground; a cornice /
// parapet band under the top; a whole number of floors in between
float cornice = style == 1 ? 0.4 : (style == 3 ? 0.6 : 1.1);
float top = pt - cornice;
bool reachesGround = pb < 1.0;
bool shop = shopPlane && reachesGround && style != 1 && pt > 5.5 && ghNominal < 5.0;   // not on the tall institutional (limestone) bases
float gh = reachesGround ? (shop ? max(ghNominal, 4.2) : ghNominal) : pb;
float span = top - gh;
float nfl = max(floor(span / fhNominal + 0.35), 0.0);
float fh = nfl > 0.0 ? span / nfl : fhNominal;

// ---- window grid, centred on the wall plane
float nb = floor(width / bay);
float margin = (width - nb * bay) * 0.5;
float bx = (u - margin) / bay;
float ix = floor(bx);
float fx = frac(bx);
bool inBays = nb >= 1.0 && ix >= 0.0 && ix < nb;
bool isGround = reachesGround && v < gh;
bool inUpper = v >= gh && v < top && nfl > 0.0;
float vv = v - gh;
float iz = isGround ? -1.0 : floor(vv / fh);
float fz = isGround ? 0.0 : frac(vv / fh);
float yloc = isGround ? v : fz * fh;
float wy0 = isGround ? 0.75 : sill * fh;
float wy1 = isGround ? gh - 0.55 : (sill + winH) * fh;
float halfW = winW * 0.5 * bay;
float dx = abs(fx - 0.5) * bay;
float frameW = P3.z;
bool rows = isGround || inUpper;
float cellH = isGround ? gh : fh;

// shopfront: big display windows between narrow piers, a painted sign band above, some doors
float signH0 = gh - 1.05, signH1 = gh - 0.3;
bool door = false;
if (shop && isGround)
{
    halfW = 0.5 * bay - 0.22;
    wy0 = 0.5;
    wy1 = signH0 - 0.08;
    door = F.Hash(float2(ix, seed * 13.0)) < 0.28;
    if (door) { wy0 = 0.02; halfW = min(halfW, 0.75); }
}

if (style == 1)
{
    // curtain wall: glass everywhere, thin mullions on the bay grid, spandrel band at each slab
    halfW = 0.5 * bay - 0.05;
    wy0 = isGround ? 0.05 : 0.0;
    wy1 = isGround ? gh - 0.25 : fh * 0.80;
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
    float3 base = lerp(float3(0.62, 0.63, 0.65), float3(0.75, 0.75, 0.77), ph);
    if (ph > 0.93) base = float3(0.85, 0.35, 0.15);
    else if (ph > 0.88) base = float3(0.85, 0.70, 0.20);
    float seam = step(0.97, max(pf.x, pf.y));
    col = base * (1.0 - seam * 0.6);
    wallCol = base;
    metal = 1.0; rough = lerp(0.28, 0.45, F.Hash(pc * 1.3));
    nxy = float2(0, 0);
    ao = 1.0 - seam * 0.5;
}

float ex = halfW - dx;                                 // > 0 inside the opening (m)
float ey = min(yloc - wy0, wy1 - yloc);
bool inWin = rows && inBays && ex > 0.0 && ey > 0.0 && (v > 0.3 || door);
float edge = min(ex, ey);

// ---- weathering on masonry / siding: soot at the base, drips under the parapet and the sills,
// broad blotchy staining. Only darkens, so it reads as dirt, not as a texture change.
if (style == 0 || style == 3)
{
    float plinth = (style == 0 && reachesGround && !shop) ? 1.0 - step(0.6, v) : 0.0;
    col = lerp(col, col * 0.55 + 0.08, plinth);
    bool sillBand = rows && !isGround && inBays && dx < halfW + 0.08 && yloc > wy0 - 0.12 && yloc < wy0;
    if (sillBand) { col = lerp(col, float3(0.62, 0.60, 0.56), 0.85); rough = 0.7; nxy = float2(0.0, 0.6); }
    if (v > top && v < top + 0.35) { col *= 0.78; ao *= 0.9; }           // cornice shadow line
    if (v > top + 0.35 && v < top + 0.45) { nxy = float2(0.0, -0.7); col *= 0.85; }   // cornice drip edge

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
    // shop name: a centred row of blocky pseudo-letters on the fascia (faded out before it can alias)
    float lfade = saturate((0.06 - fw) / 0.03);
    float ly = (v - (signH0 + 0.18)) / max(signH1 - signH0 - 0.36, 0.05);
    if (band && lfade > 0.0 && ly > 0.0 && ly < 1.0)
    {
        float shopW = 3.0 * bay;
        float sx = (u - margin) - floor(ix / 3.0) * shopW;
        float lx = (sx - shopW * (0.2 + 0.1 * F.Hash(float2(floor(ix / 3.0), seed * 5.0)))) / 0.3;
        float ci = floor(lx), cf = frac(lx);
        float gh2 = F.Hash(float2(ci, floor(ix / 3.0) + seed * 37.0));
        bool inText = lx > 0.0 && sx < shopW * 0.8 && gh2 > 0.12;
        float ink = 0.0;
        if (inText)
        {
            float hx = cf > 0.08 && cf < 0.72 ? 1.0 : 0.0;
            ink = max(ink, step(0.3, gh2) * step(0.08, cf) * step(cf, 0.2));                                  // left stem
            ink = max(ink, step(frac(gh2 * 7.0), 0.6) * step(0.6, cf) * step(cf, 0.72));                     // right stem
            ink = max(ink, hx * step(frac(gh2 * 13.0), 0.55) * step(0.84, ly));                              // top bar
            ink = max(ink, hx * step(0.4, frac(gh2 * 17.0)) * step(0.43, ly) * step(ly, 0.57));             // middle bar
            ink = max(ink, hx * step(frac(gh2 * 23.0), 0.5) * step(ly, 0.16));                              // bottom bar
        }
        float sl = dot(sc, float3(0.3, 0.59, 0.11));
        float3 inkC = sl < 0.08 ? (F.Hash(float2(seed, 2.7)) < 0.5 ? float3(0.62, 0.56, 0.42) : float3(0.55, 0.38, 0.09))
                                : float3(0.02, 0.02, 0.02);
        col = lerp(col, inkC, ink * lfade);
    }
}

if (inWin)
{
    float wr = F.Hash(float2(ix, iz) + seed * 31.7);
    float reveal = style == 1 ? 0.0 : 0.12;           // window set back into the wall
    bool header = (wy1 - yloc) < reveal * 1.4;        // shadowed lintel soffit
    bool jamb = ex < reveal * 0.7;                    // side reveal
    float meet = abs(yloc - (wy0 + wy1) * 0.5);       // double-hung meeting rail
    bool frame = edge < frameW + reveal || (style != 1 && dx < 0.025)
               || (style == 0 && !isGround && meet < 0.03) || (style == 3 && meet < 0.035);
    if (header || jamb)
    {
        col = wallCol * (header ? 0.45 : 0.7); rough = 0.8; ao = 0.6;
        nxy = header ? float2(0.0, -0.75) : float2((fx < 0.5 ? 0.75 : -0.75), 0.0);
    }
    else if (frame)
    {
        col = frameCol; rough = style == 1 ? 0.45 : 0.7; metal = style == 1 ? 0.8 : 0.0;   // painted joinery: matte (mid roughness sparkles under Lumen)
        nxy = float2(0, 0); ao = 0.9;
    }
    else
    {
        // glass: glossy (reflects the sky through Lumen) over a parallax room interior
        float depthShade = saturate(edge / 0.4);
        float blindLevel = F.Hash(float2(iz, ix) * 1.31 + seed) * (style == 1 ? 0.5 : 0.9) * (shop ? 0.0 : 1.0);
        float blinds = step(1.0 - blindLevel, (yloc - wy0) / max(wy1 - wy0, 0.01));
        float fadeW = saturate((fw - 0.35) / 0.65);
        float3 inside = GlassColor * lerp(0.25, 1.0, wr);
        float3 ie = 0.0;
        if (fadeW < 0.99)
        {
            float3 Nw = normalize(float3(VN.xy, 0.0) + 1e-5);
            float3 T = normalize(float3(-Nw.y, Nw.x, 0.0));
            // orient T with +u (screen-space derivatives; constant over a wall plane)
            float su = dot(T, ddx(WP)) * ddx(u) + dot(T, ddy(WP)) * ddy(u);
            T *= su < 0.0 ? -1.0 : 1.0;
            float3 d = -CV;
            float3 dl = float3(dot(d, T), d.z, dot(d, Nw));
            float lit = step(shop ? 0.1 : 0.55, F.Hash(float2(ix * 1.7, iz) + seed * 5.3));
            float3 roomC = lerp(float3(0.42, 0.40, 0.36), float3(0.36, 0.40, 0.44), F.Hash(float2(ix, iz * 2.1) + seed));
            if (shop) roomC = lerp(float3(0.55, 0.45, 0.32), float3(0.50, 0.50, 0.52), wr);
            float2 cell = float2(bay, cellH);
            float2 p = float2(fx * bay, isGround ? v : yloc);
            float3 r = F.Room(p, cell, P4.y * (shop ? 1.6 : 1.0), dl, wr, roomC, lit);
            float glassT = style == 1 ? 0.35 : 0.6;      // tinted curtain wall glass hides more
            float3 room = r * glassT * (0.45 + 0.55 * lit);
            inside = lerp(room * 0.25, inside, fadeW);
            ie = room * P4.x * (1.0 - fadeW) * (shop ? 1.6 : 1.0);
        }
        float3 blindC = float3(0.55, 0.53, 0.50) * 0.5;
        col = lerp(inside, blindC, blinds * 0.8);
        emit = ie * (1.0 - blinds * 0.85);
        rough = shop ? P3.y * 0.5 : P3.y;               // plate glass shopfronts: crisper reflections
        metal = 0.0;
        nxy = float2(0, 0);
        ao = lerp(1.0 - P3.w, 1.0, depthShade);
    }
}

// ---- distance anti-aliasing: once a pixel covers more than ~35 cm of wall the window pattern
// aliases (moire); fade towards the pattern's average colour instead
float fade = saturate((fw - 0.35) / 0.65);
float cover = (style == 1) ? 0.85 : saturate((2.0 * halfW / bay) * ((wy1 - wy0) / max(fh, 0.1))) * (inBays && rows ? 1.0 : 0.0);
if (inUpper && nb >= 1.0)
{
    // far field (skyline, aerials): floors and bays stay readable as filtered glass / wall bands
    // instead of collapsing to one flat colour
    float px = F.Pulse(bx, 0.5 - halfW / bay, 0.5 + halfW / bay, fw / bay);
    float py = F.Pulse(vv / fh, saturate(wy0 / fh), saturate(wy1 / fh), fw / fh);
    cover = px * py;
}
float3 avg = lerp(wallCol, GlassColor * 0.75 + frameCol * 0.1, cover);
col = lerp(col, avg, fade);
rough = lerp(rough, lerp(arm.g, P3.y, cover), fade);
nxy *= 1.0 - fade;

Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
Rough = saturate(rough);
Metal = metal * (1.0 - fade * 0.5);
AO = saturate(ao);
Emit = emit;
return saturate(col);
