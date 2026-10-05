// Suelo invisible que solo pinta la sombra de la luz principal, como el
// ShadowMaterial del "shadow catcher" de la demo Mia de Genies (negro al 40 %).
//
// Transparente y sin escribir profundidad: donde no hay sombra no se ve nada, y
// el telón (opaco, detrás) lo tapa más allá de su plano. La sombra se apaga en
// un degradado radial alrededor del centro del objeto para que no se vea el
// borde del plano y la sombra larga de una luz baja no manche la parte de abajo
// del plano medio.

Shader "Sonia/Shadow Catcher"
{
    Properties
    {
        _ShadowColor ("Color de la sombra", Color) = (0, 0, 0, 1)
        _Opacity ("Opacidad", Range(0, 1)) = 0.4
        _FadeStart ("Empieza a desvanecerse (m)", Float) = 0.8
        _FadeEnd ("Desvanecida del todo (m)", Float) = 1.6
    }

    SubShader
    {
        Tags
        {
            "RenderType" = "Transparent"
            "Queue" = "Transparent-10"
            "RenderPipeline" = "UniversalPipeline"
            "IgnoreProjector" = "True"
        }

        Pass
        {
            Name "ShadowCatcher"
            Tags { "LightMode" = "UniversalForward" }

            Blend SrcAlpha OneMinusSrcAlpha
            ZWrite Off
            ZTest LEqual
            Cull Back

            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            #pragma multi_compile_instancing
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile_fragment _ _SHADOWS_SOFT _SHADOWS_SOFT_LOW _SHADOWS_SOFT_MEDIUM _SHADOWS_SOFT_HIGH

            // Transparente: la sombra se lee del mapa de sombras, nunca de la de pantalla.
            #define _SURFACE_TYPE_TRANSPARENT 1

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            CBUFFER_START(UnityPerMaterial)
                half4 _ShadowColor;
                half _Opacity;
                float _FadeStart;
                float _FadeEnd;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                float3 centerWS : TEXCOORD1;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            Varyings Vert(Attributes input)
            {
                Varyings output;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_TRANSFER_INSTANCE_ID(input, output);
                output.positionWS = TransformObjectToWorld(input.positionOS.xyz);
                output.positionCS = TransformWorldToHClip(output.positionWS);
                output.centerWS = TransformObjectToWorld(float3(0.0, 0.0, 0.0));
                return output;
            }

            half4 Frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_INSTANCE_ID(input);
                float4 shadowCoord = TransformWorldToShadowCoord(input.positionWS);
                // 1 = a plena luz, 0 = en sombra; ya incluye el desvanecido por distancia de sombras.
                half lit = MainLightShadow(shadowCoord, input.positionWS, half4(1.0, 1.0, 1.0, 1.0), _MainLightOcclusionProbes);
                float distanceToCenter = length(input.positionWS.xz - input.centerWS.xz);
                half fade = 1.0 - smoothstep(_FadeStart, max(_FadeEnd, _FadeStart + 0.001), distanceToCenter);
                half alpha = (1.0 - lit) * _Opacity * fade * _ShadowColor.a;
                return half4(_ShadowColor.rgb, alpha);
            }
            ENDHLSL
        }
    }

    Fallback Off
}
