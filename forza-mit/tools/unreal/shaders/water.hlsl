// Charles River. Inputs: WP (float3), T (time s), Col (near-bank water colour), CAM (camera position WS),
//   WW (water_waves.png: Phillips-spectrum wind ripples, wind along +x, generated as a 4 m tile, tiled here at 0.9 / 2.9 / 8.5 m), EMask (edge mask:
//   A = distance from the bank / 40 m), OX (ortho / mask transform), Deep (open-water colour),
//   WQ = (wave strength, masks on (0 in the ctx ring), wind direction deg (0 = east, ccw), fine-ripple fade distance m)
// Outputs: return = base colour, Nrm, Rough, Spec
struct WaterFn
{
    float2 Rot(float2 v, float2 cs) { return float2(v.x * cs.x - v.y * cs.y, v.x * cs.y + v.y * cs.x); }
};
WaterFn W;

// wind ripples: three octaves of the wind-wave tile, all aligned with the wind (UE y = south, so the wind angle
// is mirrored), each drifting downwind at its own speed; the finer octaves fade with distance (sub-pixel
// ripples alias) and their slope variance turns into roughness instead (the far river reads as a glossy sheen)
float2 p = WP.xy / 100.0;
float dist = length(WP - CAM) / 100.0;
float wa = radians(WQ.z);
float2 wcs = float2(cos(wa), -sin(wa));                 // wind direction in UE xy
float2 tx = W.Rot(p, float2(wcs.x, -wcs.y));           // world -> wind frame (x downwind)
float2 a = Texture2DSample(WW, WWSampler, tx / 0.9 + float2(-0.07, 0.0) * T).rg * 2.0 - 1.0;
float2 b = Texture2DSample(WW, WWSampler, W.Rot(tx, float2(0.94, 0.34)) / 2.9 + float2(-0.035, 0.012) * T).rg * 2.0 - 1.0;
float2 c = Texture2DSample(WW, WWSampler, W.Rot(tx, float2(0.97, -0.24)) / 8.5 + float2(-0.014, -0.005) * T).rg * 2.0 - 1.0;
b = W.Rot(b, float2(0.94, -0.34));
c = W.Rot(c, float2(0.97, 0.24));
float fa = saturate(1.0 - dist / WQ.w);
float fb = saturate(1.0 - dist / (WQ.w * 4.0));
float2 nw = a * 0.65 * fa + b * 0.3 * fb + c * 0.1;
float rough = lerp(0.09, 0.04, fa * 0.4 + fb * 0.6);

// bank distance: darker open water, calmer and murkier along the stone walls
float dBank = 30.0;
if (WQ.y > 0.5)
{
    float2 ouv = (WP.xy - OX.xy) / OX.z;
    dBank = Texture2DSample(EMask, EMaskSampler, ouv).a * 40.0;
}
float open = smoothstep(2.0, 25.0, dBank);
float3 col = lerp(Col, Deep, open);
float lee = 1.0 - smoothstep(0.0, 1.5, dBank);
col *= 1.0 - 0.35 * lee;
nw *= lerp(0.45, 1.0, smoothstep(0.0, 4.0, dBank));
nw = W.Rot(nw, wcs) * WQ.x;                              // wind frame -> world
Nrm = float3(nw, sqrt(saturate(1.0 - dot(nw, nw))));
Rough = rough;
Spec = 0.25;                                            // F0 = 0.02 (water)
return col;
