// Las dos piezas de la iluminación estilo Genies que la escena no guarda por
// sí sola. Lo monta "Sonia > Iluminación estilo Genies" (SoniaGeniesLighting,
// en el editor) y lo quita "Sonia > Iluminación de estudio".
//
//   Ambiente  armónicos esféricos de orden 2 sacados del HDR de la demo Mia de
//             genies.com, con su luz ambiente plana y la "flatness" de su
//             megaStylizer (ver Assets/Sonia/Lighting/LEEME.md). Unity no guarda
//             RenderSettings.ambientProbe con la escena, y en los modos Trilight
//             y Flat lo rehace a partir de los colores e ignora el que se le
//             asigne. Así que, mientras está activo, pone el modo Custom y el SH,
//             y vuelve a ponerlos si algo los cambia. Al desactivarse deja el modo
//             y el SH que había.
//   Rims      las "normal lights" A y B del megaStylizer van en espacio de vista,
//             fijas respecto a la cámara. Aquí son direccionales sin sombra que
//             giran con la cámara principal: acompañan al plano medio, al
//             abierto, al del panel y al de salida igual que en la web.
//
// No toca materiales: vale igual para cualquier avatar.

using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace Sonia
{
    /// <summary>Ambiente SH y rims en espacio de vista de la iluminación estilo Genies.</summary>
    [ExecuteAlways]
    [DisallowMultipleComponent]
    [DefaultExecutionOrder(13000)]
    public class SoniaGeniesLook : MonoBehaviour
    {
        /// <summary>Coeficientes de un SphericalHarmonicsL2: 9 por canal (rojo, verde y azul).</summary>
        public const int CoefficientCount = 27;

        [SerializeField]
        [Tooltip("Cámara a la que siguen los rims. Vacía: la cámara principal.")]
        private Camera viewCamera;

        [SerializeField]
        [Tooltip("Luces que giran con la cámara (los rims del megaStylizer).")]
        private Light[] viewLights = new Light[0];

        [SerializeField]
        [Tooltip("Dirección hacia cada luz en el espacio de la cámara: x a la derecha, y arriba, z hacia delante.")]
        private Vector3[] viewDirections = new Vector3[0];

        [SerializeField]
        [Tooltip("Ambiente con el formato de SphericalHarmonicsL2: 9 coeficientes de rojo, 9 de verde y 9 de azul.")]
        private float[] ambientCoefficients = new float[CoefficientCount];

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Multiplica el ambiente entero (1: el de Mia).")]
        private float ambientIntensity = 1f;

        [NonSerialized]
        private SphericalHarmonicsL2 _ambient;

        [NonSerialized]
        private bool _hasAmbient;

        [NonSerialized]
        private SphericalHarmonicsL2 _previousAmbient;

        [NonSerialized]
        private AmbientMode _previousMode;

        [NonSerialized]
        private bool _overriding;

        /// <summary>Ambiente que impone este componente.</summary>
        public SphericalHarmonicsL2 Ambient
        {
            get { return _ambient; }
        }

        /// <summary>Lo llama la herramienta del editor que monta la iluminación.</summary>
        public void Configure(Camera camera, Light[] lights, Vector3[] directions, float[] coefficients)
        {
            viewCamera = camera;
            viewLights = lights ?? new Light[0];
            viewDirections = directions ?? new Vector3[0];
            ambientCoefficients = coefficients ?? new float[CoefficientCount];
            BuildAmbient();
            if (isActiveAndEnabled)
            {
                Apply();
            }
        }

        private void OnEnable()
        {
            BuildAmbient();
            Apply();
        }

        private void OnValidate()
        {
            BuildAmbient();
            if (isActiveAndEnabled)
            {
                Apply();
            }
        }

        private void LateUpdate()
        {
            Apply();
        }

        private void OnDisable()
        {
            if (_overriding)
            {
                // Volver a Trilight o Flat ya rehace el SH a partir de los colores.
                RenderSettings.ambientMode = _previousMode;
                RenderSettings.ambientProbe = _previousAmbient;
                _overriding = false;
            }
        }

        private void BuildAmbient()
        {
            _hasAmbient = ambientCoefficients != null && ambientCoefficients.Length == CoefficientCount;
            if (!_hasAmbient)
            {
                return;
            }

            SphericalHarmonicsL2 sh = new SphericalHarmonicsL2();
            for (int channel = 0; channel < 3; channel++)
            {
                for (int i = 0; i < 9; i++)
                {
                    sh[channel, i] = ambientCoefficients[channel * 9 + i] * ambientIntensity;
                }
            }

            _ambient = sh;
        }

        private void Apply()
        {
            if (_hasAmbient && (RenderSettings.ambientMode != AmbientMode.Custom || RenderSettings.ambientProbe != _ambient))
            {
                if (!_overriding)
                {
                    _previousMode = RenderSettings.ambientMode;
                    _previousAmbient = RenderSettings.ambientProbe;
                    _overriding = true;
                }

                if (RenderSettings.ambientMode != AmbientMode.Custom)
                {
                    RenderSettings.ambientMode = AmbientMode.Custom;
                }

                RenderSettings.ambientProbe = _ambient;
            }

            OrientLights();
        }

        private void OrientLights()
        {
            Camera camera = viewCamera != null ? viewCamera : Camera.main;
            if (camera == null || viewLights == null || viewDirections == null)
            {
                return;
            }

            Transform view = camera.transform;
            int count = Mathf.Min(viewLights.Length, viewDirections.Length);
            for (int i = 0; i < count; i++)
            {
                Light light = viewLights[i];
                if (light == null || viewDirections[i].sqrMagnitude < 1e-6f)
                {
                    continue;
                }

                // La luz apunta desde su dirección hacia la escena.
                Vector3 toLight = view.rotation * viewDirections[i].normalized;
                Quaternion rotation = Quaternion.LookRotation(-toLight, view.up);
                if (Quaternion.Angle(light.transform.rotation, rotation) > 0.01f)
                {
                    light.transform.rotation = rotation;
                }
            }
        }
    }
}
