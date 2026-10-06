// Roofs: the orthophoto is literally the real roof (HVAC units, skylights, membranes), mapped from
// world position. Up close it is only ~0.3 m/px, so flat roofs get a tiled membrane / gravel detail
// texture on top, and pitched roofs get procedural asphalt-shingle courses tinted by the photo.
// Inputs: WP (float3), VN (float3 world vertex normal), UV1 (y = building seed), Ortho (Texture2D),
//         D/N/ARM (Texture2D detail set), OX = (x0 cm, y0 cm, side cm, unused),
//         P1 = (brightness, rough, detail tile m, detail strength)
// Outputs: return = base colour, Nrm (tangent), Rough
struct RoofFn
{
    float Hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
};
RoofFn R;
float seed = UV1.y;
float2 m = WP.xy / 100.0;
float2 ouv = (WP.xy - OX.xy) / OX.z;
// flatten the photo: a blurred (~2.5 m) base carries the roof's colour, the full-res photo only adds
// clamped relative detail, so JPEG blocks, glare and white blobs don't read as stair-stepped paint
float3 cHi = Texture2DSample(Ortho, OrthoSampler, ouv).rgb;
float3 cLo = Texture2DSampleBias(Ortho, OrthoSampler, ouv, 3.0).rgb;
float lHi = max(dot(cHi, float3(0.3, 0.59, 0.11)), 1e-3), lLo = max(dot(cLo, float3(0.3, 0.59, 0.11)), 1e-3);
float3 c = cLo * clamp(lHi / lLo, 0.7, 1.25);
c = lerp(dot(c, float3(0.3, 0.59, 0.11)).xxx, c, 0.75);           // photo chroma is mostly noise / tint cast
c *= min(1.0, 0.42 / max(dot(c, float3(0.3, 0.59, 0.11)), 1e-3)); // white blobs -> light membrane, not glare
c *= P1.x;
float lum = max(dot(c, float3(0.3, 0.59, 0.11)), 1e-3);
float tileM = max(P1.z, 0.5);
float2 duv = m / tileM + seed * 13.7;
float3 dd = Texture2DSample(D, DSampler, duv).rgb;
float3 da = Texture2DSample(ARM, ARMSampler, duv).rgb;
float2 nxy = Texture2DSample(N, NSampler, duv).rg * 2.0 - 1.0;
float dl = dot(dd, float3(0.3, 0.59, 0.11));
float rough = lerp(P1.y, da.g, 0.6);
float slope = sqrt(saturate(1.0 - VN.z * VN.z));      // sin of the roof pitch

// distance fade for the procedural detail (keeps aerial views clean)
float fw = length(float2(length(ddx(m)), length(ddy(m))));
float near = 1.0 - saturate((fw - 0.08) / 0.25);

if (slope > 0.3)
{
    // pitched: asphalt shingles, courses level along the eaves
    float3 T = normalize(float3(-VN.y, VN.x, 0.0) + 1e-5);
    float a = dot(m, T.xy);
    float s = (WP.z / 100.0) / slope;                 // metres up the slope
    float row = floor(s / 0.143);
    float fr = frac(s / 0.143);
    float tab = frac(a / 0.34 + row * 0.5 + R.Hash(float2(row, seed)) * 0.15);
    float gap = step(0.96, tab) + step(fr, 0.08);
    float3 sh = lerp(float3(0.16, 0.16, 0.17), float3(0.30, 0.24, 0.20), R.Hash(float2(seed, 2.2)));
    sh = lerp(sh, float3(0.22, 0.27, 0.27), step(0.8, R.Hash(float2(seed, 7.1))));
    float3 photo = c / lum * min(lum, 0.35);                     // photo hue, clamped brightness
    float3 shingle = lerp(sh, photo, 0.55) * (0.85 + 0.3 * R.Hash(float2(row, floor(a / 0.34 + row * 0.5)))) * (0.8 + 0.4 * dl);
    shingle *= 1.0 - gap * 0.45;
    c = lerp(c, shingle, near);
    rough = lerp(rough, 0.85, near);
    nxy *= 1.0 - near;          // tangent frame follows the world-XY UVs, not the slope: keep it flat
}
else
{
    // flat: membrane / gravel detail modulating the photo
    c *= lerp(1.0, saturate(dl / 0.45) * 0.8 + 0.2, P1.w * near);
    nxy *= P1.w * near;
}
Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
Rough = saturate(rough);
return saturate(c * (0.97 + 0.06 * R.Hash(float2(seed, 0.3))));
