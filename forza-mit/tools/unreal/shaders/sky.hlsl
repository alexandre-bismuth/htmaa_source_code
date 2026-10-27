// Sky dome: the equirect HDRI (tools/blender/make_sky.py) looked up by view direction.
// Inputs: Tex (Texture2D, linear HDR), CV (camera vector WS: pixel -> camera),
//         Off (u offset that puts the photo's sun where the directional light comes from), Int (brightness)
float3 d = -normalize(CV);
float u = atan2(d.y, d.x) * 0.15915494 + Off;
float v = acos(clamp(d.z, -1.0, 1.0)) * 0.31830989;
// gradients with atan2's wrap removed (due west it jumps by a whole turn: the 1x1 mip drew a 1-2 px line up the sky)
float2 gx = float2(ddx(u), ddx(v));
float2 gy = float2(ddy(u), ddy(v));
gx.x -= round(gx.x);
gy.x -= round(gy.x);
return Tex.SampleGrad(TexSampler, float2(frac(u), v), gx, gy).rgb * Int;
