// Charles River: two panning layers of a tileable normal map, glossy dark water reflecting the sky.
// Inputs: WP (float3), T (time s), WN (Texture2D normal), Col (float3)
// Outputs: return = base colour, Nrm, Rough
float2 p = WP.xy / 100.0;
float2 a = Texture2DSample(WN, WNSampler, p / 9.0 + float2(0.010, 0.006) * T).rg * 2.0 - 1.0;
float2 b = Texture2DSample(WN, WNSampler, p / 23.0 + float2(-0.004, 0.009) * T).rg * 2.0 - 1.0;
float2 nxy = (a + b) * 0.35;
Nrm = float3(nxy, sqrt(saturate(1.0 - dot(nxy, nxy))));
Rough = 0.04;
return Col;
