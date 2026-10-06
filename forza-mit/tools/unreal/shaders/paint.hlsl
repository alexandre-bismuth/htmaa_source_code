// Road paint (vector markings from TRAFFIC_PavementMarkings, tools/mapgen/build_meshes.py).
// Inputs: WP (world position, cm), Col (paint colour), P (x: wear amount, y: roughness).
// Outputs: return = base colour, Rough.
struct PaintFn
{
    float Hash(float2 p) { return frac(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
    float Noise(float2 p)
    {
        float2 i = floor(p), f = frac(p);
        float2 u = f * f * (3.0 - 2.0 * f);
        return lerp(lerp(Hash(i), Hash(i + float2(1, 0)), u.x), lerp(Hash(i + float2(0, 1)), Hash(i + float2(1, 1)), u.x), u.y);
    }
};
PaintFn F;
float2 m = WP.xy / 100.0;
// tyre wear: large blotches plus fine grit
float wear = saturate(F.Noise(m * 0.35) * 0.65 + F.Noise(m * 3.1) * 0.35 - 0.25) * P.x;
float grit = F.Noise(m * 40.0);
Rough = saturate(P.y + 0.25 * wear);
return lerp(Col, Col * 0.35 + float3(0.04, 0.04, 0.045), saturate(wear * 0.9 + (grit - 0.5) * 0.15));
