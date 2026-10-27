// Roofs: the orthophoto is literally the real roof (HVAC units, skylights, membranes), mapped from
// world position. Up close it is only ~0.3 m/px, so flat roofs get a tiled membrane / gravel detail
// texture on top, and pitched roofs get procedural asphalt-shingle courses tinted by the photo.
// Inputs: WP (float3), VN (float3 world vertex normal), UV1 (y = building seed), Ortho (Texture2D),
//         D/N/ARM (Texture2D detail set), OX = (x0 cm, y0 cm, side cm, unused),
//         D2/ARM2 (Texture2D: slate / shingle photo set for pitched roofs, laid along the eaves),
//         P1 = (brightness, rough, detail tile m, detail strength)
// Outputs: return = base colour, Nrm (tangent), Rough
struct RoofFn
{
    // sin-free hash (Hoskins): sin() of the large arguments here (row numbers x 127 at km scale) degenerates on GPUs
    float Hash(float2 p)
    {
        float3 p3 = frac(float3(p.xyx) * 0.1031);
        p3 += dot(p3, p3.yzx + 33.33);
        return frac((p3.x + p3.y) * p3.z);
    }
    float PulseInt(float x, float a, float b) { return floor(x) * (b - a) + clamp(frac(x) - a, 0.0f, b - a); }
    // box-filtered periodic pulse (1 on [a,b) of each unit period), filter width w
    float Pulse(float x, float a, float b, float w) { w = max(w, 1e-4f); return (PulseInt(x + 0.5f * w, a, b) - PulseInt(x - 0.5f * w, a, b)) / w; }
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

// pitched-roof coordinates (metres along the eaves / up the slope) and their screen gradients, outside the branch
float3 T = normalize(float3(-VN.y, VN.x, 0.0) + 1e-5);
float a = dot(m, T.xy);
float s = (WP.z / 100.0) / max(slope, 0.05);
float2 suv = float2(a, s) / 3.0 + seed * 5.3;
float2 sgx = ddx(suv), sgy = ddy(suv);
float fws = max(length(float2(ddx(s), ddy(s))), 1e-4);    // metres of slope per pixel
if (slope > 0.3)
{
    // pitched: asphalt shingles, courses level along the eaves
    float row = floor(s / 0.143);
    float fr = frac(s / 0.143);
    float tab = frac(a / 0.34 + row * 0.5 + R.Hash(float2(row, seed)) * 0.15);
    // anti-aliased gaps (hard steps on 1-cm lines made moire at 10-90 m)
    float gap = saturate(R.Pulse(a / 0.34 + row * 0.5 + R.Hash(float2(row, seed)) * 0.15, 0.96, 1.0, fws / 0.34)
                         + R.Pulse(s / 0.143, 0.0, 0.08, fws / 0.143));
    float3 sh = lerp(float3(0.16, 0.16, 0.17), float3(0.30, 0.24, 0.20), R.Hash(float2(seed, 2.2)));
    sh = lerp(sh, float3(0.22, 0.27, 0.27), step(0.8, R.Hash(float2(seed, 7.1))));
    float3 photo = c / lum * min(lum, 0.35);                     // photo hue, clamped brightness
    float3 shingle = lerp(sh, photo, 0.55) * (0.85 + 0.3 * R.Hash(float2(row, floor(a / 0.34 + row * 0.5)))) * (0.8 + 0.4 * dl);
    shingle *= 1.0 - gap * 0.45;
    // photographed slate / shingle courses (Poly Haven) laid along the eaves, coloured by the roof's own photo:
    // real chipped edges and per-slate variation instead of the procedural courses alone
    float3 sl = Texture2DSampleGrad(D2, D2Sampler, suv, sgx, sgy).rgb;
    float slr = Texture2DSampleGrad(ARM2, ARM2Sampler, suv, sgx, sgy).g;
    float sll = dot(sl, float3(0.3, 0.59, 0.11));
    shingle = lerp(shingle, lerp(sh, photo, 0.6) * (sll / 0.52) * (1.0 - gap * 0.2), 0.75);
    c = lerp(c, shingle, near);
    rough = lerp(rough, lerp(0.85, slr, 0.5), near);
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
