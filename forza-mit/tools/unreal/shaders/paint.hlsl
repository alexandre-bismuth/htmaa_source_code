// Road paint (vector markings from TRAFFIC_PavementMarkings, tools/mapgen/build_meshes.py), 6 mm above the road.
// Inputs: WP (world position, cm), Col (paint colour), P (x: wear amount, y: roughness), RN / RD (the road's
//   asphalt_02 normal and colour: thin paint follows the asphalt's grain, chipped spots show the asphalt),
//   PQ = (road tile m, asphalt normal through the paint, asphalt pores darkening, dirt)
// Outputs: return = base colour, Rough, Nrm.
struct PaintFn
{
    // sin-free (Hoskins) hash / value noise: stays random at km-scale coordinates
    float HashB(float2 p)
    {
        float3 p3 = frac(float3(p.xyx) * 0.1031);
        p3 += dot(p3, p3.yzx + 33.33);
        return frac((p3.x + p3.y) * p3.z);
    }
    float NoiseB(float2 p)
    {
        float2 i = floor(p), f = frac(p);
        float2 u = f * f * (3.0 - 2.0 * f);
        return lerp(lerp(HashB(i), HashB(i + float2(1, 0)), u.x), lerp(HashB(i + float2(0, 1)), HashB(i + float2(1, 1)), u.x), u.y);
    }
};
PaintFn F;
float2 m = WP.xy / 100.0;
float2 dmx = ddx(m), dmy = ddy(m);
float pixm = max(length(dmx), length(dmy));
float2 uvA = m / PQ.x;                                  // same mapping as the road's first sample
float2 nr = Texture2DSampleGrad(RN, RNSampler, uvA, dmx / PQ.x, dmy / PQ.x).rg * 2.0 - 1.0;
float3 asph = Texture2DSampleGrad(RD, RDSampler, uvA, dmx / PQ.x, dmy / PQ.x).rgb * float3(0.95, 0.94, 0.92);
float al = saturate(dot(asph, float3(0.2126, 0.7152, 0.0722)) / 0.11);
// tyre wear: large blotches (where wheels cross the line), dirtier and thinner there
float wear = saturate(F.NoiseB(m * 0.35 + 3.1) * 0.65 + F.NoiseB(m * 3.1 + 1.7) * 0.35 - 0.25) * P.x;
// chipped spots through to the asphalt; faded out before they get sub-pixel (no shimmer on far lines)
float hn = F.NoiseB(m * 19.0 + 5.3) * 0.7 + F.NoiseB(m * 47.0) * 0.3;
float hf = saturate(1.0 - pixm * 30.0);
float holes = saturate((hn - (1.0 - 0.55 * wear)) / max(fwidth(hn), 1e-3) + 0.5) * hf;
float3 col = Col * (0.94 + 0.1 * F.NoiseB(m * 6.0 + 0.7));
col = lerp(col, col * 0.62 + float3(0.035, 0.034, 0.032), saturate(wear * 0.8));
col *= lerp(1.0, 0.82 + 0.18 * al, PQ.z);               // asphalt pores the paint did not fill
col *= 1.0 - PQ.w * (0.5 + 0.5 * F.NoiseB(m * 1.3 + 9.1)) * 0.2;
col = lerp(col, asph, holes);
Rough = lerp(saturate(P.y + 0.2 * wear), 0.8, holes);
float2 nxy = nr * lerp(PQ.y, 1.0, holes);
Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
return col;
