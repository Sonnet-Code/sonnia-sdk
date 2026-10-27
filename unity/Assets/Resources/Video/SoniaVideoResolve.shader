// Renderizador de vídeos (Sonia.Video.VideoFrameRecorder):
//   pasada 0: reduce el render supermuestreado con un promedio de caja N×N y lo suma
//             al acumulador con peso _Weight (subfotogramas del desenfoque de movimiento);
//   pasada 1: copia el acumulador al cuadro final y, si _FlipY, al revés (ffmpeg quiere
//             las filas de arriba abajo); opaco o, si _Transparent, con alfa sin premultiplicar;
//   pasada 2: como la 0 pero para el fondo transparente: con el render sobre blanco
//             (_MainTex) y sobre negro (_BlackTex), y los mismos sin Sonnia (_BgWhite,
//             _BgBlack: viñeta y tonemapping del fondo), saca el alfa por diferencia y suma
//             el color premultiplicado.
Shader "Hidden/Sonia/VideoResolve"
{
    Properties
    {
        _MainTex ("Textura", 2D) = "black" {}
    }

    SubShader
    {
        ZTest Always Cull Off ZWrite Off

        Pass
        {
            Blend One One

            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float4 _MainTex_TexelSize;
            float _Scale;
            float _Weight;

            fixed4 frag(v2f_img i) : SV_Target
            {
                int n = (int)clamp(_Scale, 1, 3);
                float4 sum = 0;
                [unroll(3)]
                for (int y = 0; y < n; y++)
                {
                    [unroll(3)]
                    for (int x = 0; x < n; x++)
                    {
                        float2 offset = (float2(x, y) - (n - 1) * 0.5) * _MainTex_TexelSize.xy;
                        sum += tex2Dlod(_MainTex, float4(i.uv + offset, 0, 0));
                    }
                }

                return sum / (n * n) * _Weight;
            }
            ENDCG
        }

        Pass
        {
            Blend Off

            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            float _FlipY;
            float _Transparent;

            float4 frag(v2f_img i) : SV_Target
            {
                float2 uv = i.uv;
                if (_FlipY > 0.5)
                {
                    uv.y = 1.0 - uv.y;
                }

                float4 c = tex2D(_MainTex, uv);
                if (_Transparent < 0.5)
                {
                    return float4(c.rgb, 1.0);
                }

                float a = saturate(c.a);
                return a > 0.002 ? float4(saturate(c.rgb / a), a) : float4(0, 0, 0, 0);
            }
            ENDCG
        }

        Pass
        {
            Blend One One

            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            sampler2D _BlackTex;
            sampler2D _BgWhite;
            sampler2D _BgBlack;
            float4 _MainTex_TexelSize;
            float _Scale;
            float _Weight;

            float4 frag(v2f_img i) : SV_Target
            {
                int n = (int)clamp(_Scale, 1, 3);
                float4 sum = 0;
                [unroll(3)]
                for (int y = 0; y < n; y++)
                {
                    [unroll(3)]
                    for (int x = 0; x < n; x++)
                    {
                        float4 uv = float4(i.uv + (float2(x, y) - (n - 1) * 0.5) * _MainTex_TexelSize.xy, 0, 0);
                        float3 w = tex2Dlod(_MainTex, uv).rgb;
                        float3 b = tex2Dlod(_BlackTex, uv).rgb;
                        float3 bw = tex2Dlod(_BgWhite, uv).rgb;
                        float3 bb = tex2Dlod(_BgBlack, uv).rgb;
                        float3 seen = (w - b) / max(bw - bb, 0.02);
                        float a = saturate(1.0 - (seen.r + seen.g + seen.b) / 3.0);
                        float3 premul = saturate(b - bb * (1.0 - a));
                        sum += float4(premul, a);
                    }
                }

                return sum / (n * n) * _Weight;
            }
            ENDCG
        }
    }
}
