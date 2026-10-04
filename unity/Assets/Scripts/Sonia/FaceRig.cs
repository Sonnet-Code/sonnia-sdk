// Capa entre los controladores de cara y las mallas del avatar.
//
// El lip-sync, el parpadeo y las expresiones hablan un vocabulario común:
// visemas Oculus (viseme_aa, viseme_PP...) y blendshapes ARKit (eyeBlinkLeft,
// mouthSmileLeft...). Aquí cada canal se traduce a las formas reales del avatar
// y se escribe en todas las mallas que las tengan:
//
//  - Avatares de Genies: la cara usa las expresiones FACS de Meta (JAW_DROP,
//    LIP_PUCKER_L...) y está repartida entre varias mallas que comparten
//    nombres (cara, dientes y lengua, pestañas, cejas y ojos). Cada canal es una
//    receta con pesos; las vocales salen de las expresiones VRM que define el
//    propio Genies (la "a" es JAW_DROP 0,57 más los cuatro LIP_FUNNELER a 0,18).
//    Cualquier forma FACS se puede pedir también por su nombre (JAW_DROP).
//  - Cualquier otro avatar: el canal es el blendshape del mismo nombre.
//
// Los controladores suman sus aportaciones durante el fotograma (Add) y aquí,
// después de todos ellos, se escribe cada forma una sola vez con la suma
// recortada a 1. Lo que nadie escribe en un fotograma vuelve a 0.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Traduce los canales de cara (visemas y ARKit) a las formas del avatar.</summary>
    [DefaultExecutionOrder(12900)]
    [DisallowMultipleComponent]
    public class FaceRig : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Raíz del avatar; se usan todas las mallas con blendshapes que cuelgan de ella.")]
        private Transform avatarRoot;

        private readonly struct Part
        {
            public readonly string Shape;
            public readonly float Weight;

            public Part(string shape, float weight)
            {
                Shape = shape;
                Weight = weight;
            }
        }

        private struct Target
        {
            public SkinnedMeshRenderer Renderer;
            public int Index;
            public float Scale;
        }

        private struct Contribution
        {
            public int Target;
            public float Factor;
        }

        private static Part P(string shape, float weight = 1f)
        {
            return new Part(shape, weight);
        }

        /// <summary>
        /// Recetas de la cara de Genies. Lo que no está aquí se busca tal cual
        /// entre las formas FACS de las mallas.
        /// </summary>
        private static readonly Dictionary<string, Part[]> GeniesRecipes =
            new Dictionary<string, Part[]>(StringComparer.OrdinalIgnoreCase)
            {
                // Visemas. A, E, I y O parten de las expresiones VRM de Genies;
                // la U no la trae y se hace con los labios en pico.
                { "viseme_sil", new Part[0] },
                { "viseme_aa", new[] { P("JAW_DROP", 0.57f), P("LIP_FUNNELER_LB", 0.18f), P("LIP_FUNNELER_LT", 0.18f), P("LIP_FUNNELER_RB", 0.18f), P("LIP_FUNNELER_RT", 0.18f) } },
                { "viseme_E", new[] { P("JAW_DROP", 0.3f), P("LIP_STRETCHER_L", 0.45f), P("LIP_STRETCHER_R", 0.45f) } },
                { "viseme_I", new[] { P("JAW_DROP", 0.2f), P("LIP_STRETCHER_L", 0.8f), P("LIP_STRETCHER_R", 0.8f) } },
                { "viseme_O", new[] { P("JAW_DROP", 0.65f), P("LIP_FUNNELER_LB", 0.4f), P("LIP_FUNNELER_LT", 0.4f), P("LIP_FUNNELER_RB", 0.4f), P("LIP_FUNNELER_RT", 0.4f) } },
                { "viseme_U", new[] { P("JAW_DROP", 0.15f), P("LIP_PUCKER_L", 0.75f), P("LIP_PUCKER_R", 0.75f), P("LIP_FUNNELER_LB", 0.45f), P("LIP_FUNNELER_LT", 0.45f), P("LIP_FUNNELER_RB", 0.45f), P("LIP_FUNNELER_RT", 0.45f) } },
                { "viseme_PP", new[] { P("LIP_PRESSOR_L", 0.8f), P("LIP_PRESSOR_R", 0.8f), P("LIPS_TOWARD", 0.3f) } },
                { "viseme_FF", new[] { P("JAW_DROP", 0.05f), P("LIP_SUCK_LB", 0.5f), P("LIP_SUCK_RB", 0.5f), P("UPPER_LIP_RAISER_L", 0.2f), P("UPPER_LIP_RAISER_R", 0.2f) } },
                { "viseme_TH", new[] { P("JAW_DROP", 0.15f), P("TONGUE_TIP_OUT", 0.5f) } },
                { "viseme_DD", new[] { P("JAW_DROP", 0.2f), P("LIP_STRETCHER_L", 0.25f), P("LIP_STRETCHER_R", 0.25f) } },
                { "viseme_kk", new[] { P("JAW_DROP", 0.3f), P("LIP_STRETCHER_L", 0.2f), P("LIP_STRETCHER_R", 0.2f) } },
                { "viseme_CH", new[] { P("JAW_DROP", 0.15f), P("LIP_PUCKER_L", 0.2f), P("LIP_PUCKER_R", 0.2f), P("LIP_FUNNELER_LB", 0.5f), P("LIP_FUNNELER_LT", 0.5f), P("LIP_FUNNELER_RB", 0.5f), P("LIP_FUNNELER_RT", 0.5f) } },
                { "viseme_SS", new[] { P("JAW_DROP", 0.05f), P("LIP_STRETCHER_L", 0.45f), P("LIP_STRETCHER_R", 0.45f), P("UPPER_LIP_RAISER_L", 0.15f), P("UPPER_LIP_RAISER_R", 0.15f) } },
                { "viseme_nn", new[] { P("JAW_DROP", 0.15f), P("LIP_STRETCHER_L", 0.15f), P("LIP_STRETCHER_R", 0.15f) } },
                { "viseme_RR", new[] { P("JAW_DROP", 0.2f), P("LIP_FUNNELER_LB", 0.35f), P("LIP_FUNNELER_LT", 0.35f), P("LIP_FUNNELER_RB", 0.35f), P("LIP_FUNNELER_RT", 0.35f) } },
                { "jawOpen", new[] { P("JAW_DROP") } },
                { "mouthOpen", new[] { P("JAW_DROP") } },

                // ARKit (equivalencias ARKit / OpenXR de Meta).
                { "eyeBlinkLeft", new[] { P("EYES_CLOSED_L") } },
                { "eyeBlinkRight", new[] { P("EYES_CLOSED_R") } },
                { "eyeSquintLeft", new[] { P("LID_TIGHTENER_L") } },
                { "eyeSquintRight", new[] { P("LID_TIGHTENER_R") } },
                { "eyeWideLeft", new[] { P("UPPER_LID_RAISER_L") } },
                { "eyeWideRight", new[] { P("UPPER_LID_RAISER_R") } },
                { "browInnerUp", new[] { P("INNER_BROW_RAISER_L"), P("INNER_BROW_RAISER_R") } },
                { "browOuterUpLeft", new[] { P("OUTER_BROW_RAISER_L") } },
                { "browOuterUpRight", new[] { P("OUTER_BROW_RAISER_R") } },
                { "browDownLeft", new[] { P("BROW_LOWERER_L") } },
                { "browDownRight", new[] { P("BROW_LOWERER_R") } },
                { "cheekSquintLeft", new[] { P("CHEEK_RAISER_L") } },
                { "cheekSquintRight", new[] { P("CHEEK_RAISER_R") } },
                { "cheekPuff", new[] { P("CHEEK_PUFF_L"), P("CHEEK_PUFF_R") } },
                { "noseSneerLeft", new[] { P("NOSE_WRINKLER_L") } },
                { "noseSneerRight", new[] { P("NOSE_WRINKLER_R") } },
                { "mouthSmileLeft", new[] { P("LIP_CORNER_PULLER_L") } },
                { "mouthSmileRight", new[] { P("LIP_CORNER_PULLER_R") } },
                { "mouthFrownLeft", new[] { P("LIP_CORNER_DEPRESSOR_L") } },
                { "mouthFrownRight", new[] { P("LIP_CORNER_DEPRESSOR_R") } },
                { "mouthDimpleLeft", new[] { P("DIMPLER_L") } },
                { "mouthDimpleRight", new[] { P("DIMPLER_R") } },
                { "mouthPressLeft", new[] { P("LIP_PRESSOR_L") } },
                { "mouthPressRight", new[] { P("LIP_PRESSOR_R") } },
                { "mouthStretchLeft", new[] { P("LIP_STRETCHER_L") } },
                { "mouthStretchRight", new[] { P("LIP_STRETCHER_R") } },
                { "mouthUpperUpLeft", new[] { P("UPPER_LIP_RAISER_L") } },
                { "mouthUpperUpRight", new[] { P("UPPER_LIP_RAISER_R") } },
                { "mouthLowerDownLeft", new[] { P("LOWER_LIP_DEPRESSOR_L") } },
                { "mouthLowerDownRight", new[] { P("LOWER_LIP_DEPRESSOR_R") } },
                { "mouthLeft", new[] { P("MOUTH_LEFT") } },
                { "mouthRight", new[] { P("MOUTH_RIGHT") } },
                { "mouthPucker", new[] { P("LIP_PUCKER_L"), P("LIP_PUCKER_R") } },
                { "mouthFunnel", new[] { P("LIP_FUNNELER_LB"), P("LIP_FUNNELER_LT"), P("LIP_FUNNELER_RB"), P("LIP_FUNNELER_RT") } },
                { "mouthRollLower", new[] { P("LIP_SUCK_LB"), P("LIP_SUCK_RB") } },
                { "mouthRollUpper", new[] { P("LIP_SUCK_LT"), P("LIP_SUCK_RT") } },
                { "mouthShrugLower", new[] { P("CHIN_RAISER_B") } },
                { "mouthShrugUpper", new[] { P("CHIN_RAISER_T") } },
                { "mouthClose", new[] { P("LIPS_TOWARD") } },
                { "jawForward", new[] { P("JAW_THRUST") } },
                { "jawLeft", new[] { P("JAW_SIDEWAYS_LEFT") } },
                { "jawRight", new[] { P("JAW_SIDEWAYS_RIGHT") } },
                { "tongueOut", new[] { P("TONGUE_OUT") } },
            };

        private readonly List<Target> _targets = new List<Target>();
        private readonly Dictionary<string, int> _channelIds = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        private readonly List<Contribution[]> _channels = new List<Contribution[]>();
        private float[] _accum = new float[0];
        private bool[] _written = new bool[0];
        private bool _genies;
        private bool _built;

        /// <summary>
        /// Avisa de que las mallas cambiaron (otro avatar): los canales resueltos
        /// antes dejan de valer y hay que volver a pedirlos con <see cref="Channel"/>.
        /// </summary>
        public event Action Rebuilt;

        /// <summary>Raíz del avatar. Al cambiarla se vuelven a buscar las mallas.</summary>
        public Transform AvatarRoot
        {
            get { return avatarRoot; }
            set
            {
                avatarRoot = value;
                Rebuild();
            }
        }

        /// <summary>Cierto si la cara es la FACS de Genies.</summary>
        public bool IsGenies
        {
            get
            {
                EnsureBuilt();
                return _genies;
            }
        }

        /// <summary>Malla con más formas de cara, la que se mide y se enseña en el laboratorio.</summary>
        public SkinnedMeshRenderer PrimaryRenderer { get; private set; }

        private void Awake()
        {
            EnsureBuilt();
        }

        /// <summary>
        /// Identificador del canal (visema, nombre ARKit o forma FACS), o -1 si el
        /// avatar no tiene nada que lo represente. Se resuelve una vez y se cachea.
        /// </summary>
        public int Channel(string name)
        {
            EnsureBuilt();
            if (string.IsNullOrEmpty(name))
            {
                return -1;
            }

            int id;
            if (_channelIds.TryGetValue(name, out id))
            {
                return id;
            }

            Contribution[] parts = Resolve(name);
            id = parts.Length > 0 || IsKnownEmpty(name) ? _channels.Count : -1;
            if (id >= 0)
            {
                _channels.Add(parts);
            }

            _channelIds[name] = id;
            return id;
        }

        /// <summary>Suma <paramref name="weight01"/> (0..1) al canal durante este fotograma.</summary>
        public void Add(int channel, float weight01)
        {
            if (channel < 0 || channel >= _channels.Count || weight01 == 0f)
            {
                return;
            }

            Contribution[] parts = _channels[channel];
            for (int i = 0; i < parts.Length; i++)
            {
                _accum[parts[i].Target] += weight01 * parts[i].Factor;
            }
        }

        /// <summary>Peso actual (0..1) de cada forma de la malla principal, para registrar en el laboratorio.</summary>
        public void ReadPrimaryWeights(List<KeyValuePair<string, float>> into)
        {
            into.Clear();
            if (PrimaryRenderer == null || PrimaryRenderer.sharedMesh == null)
            {
                return;
            }

            Mesh mesh = PrimaryRenderer.sharedMesh;
            float scale = LipSyncController.BlendShapeScale(mesh) * 100f;
            for (int i = 0; i < mesh.blendShapeCount; i++)
            {
                into.Add(new KeyValuePair<string, float>(ShortName(mesh.GetBlendShapeName(i)), PrimaryRenderer.GetBlendShapeWeight(i) / scale));
            }
        }

        /// <summary>Vuelve a buscar las mallas y a resolver los canales.</summary>
        public void Rebuild()
        {
            _built = false;
            EnsureBuilt();
            Action handler = Rebuilt;
            if (handler != null)
            {
                handler();
            }
        }

        private void LateUpdate()
        {
            for (int t = 0; t < _targets.Count; t++)
            {
                if (!_written[t])
                {
                    continue;
                }

                Target target = _targets[t];
                if (target.Renderer != null)
                {
                    target.Renderer.SetBlendShapeWeight(target.Index, Mathf.Clamp01(_accum[t]) * 100f * target.Scale);
                }

                _accum[t] = 0f;
            }
        }

        private void EnsureBuilt()
        {
            if (_built)
            {
                return;
            }

            _built = true;
            _targets.Clear();
            _channelIds.Clear();
            _channels.Clear();
            _genies = false;
            PrimaryRenderer = null;

            Transform root = avatarRoot != null ? avatarRoot : transform;
            SkinnedMeshRenderer[] renderers = root.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            int bestCount = 0;
            for (int r = 0; r < renderers.Length; r++)
            {
                Mesh mesh = renderers[r].sharedMesh;
                if (mesh == null || mesh.blendShapeCount == 0)
                {
                    continue;
                }

                if (mesh.blendShapeCount > bestCount)
                {
                    bestCount = mesh.blendShapeCount;
                    PrimaryRenderer = renderers[r];
                }

                if (LipSyncController.FindBlendShape(mesh, "JAW_DROP") >= 0
                    && LipSyncController.FindBlendShape(mesh, "LIP_FUNNELER_LB") >= 0)
                {
                    _genies = true;
                }
            }

            _accum = new float[0];
            _written = new bool[0];
        }

        private Contribution[] Resolve(string channel)
        {
            Part[] recipe;
            if (!_genies || !GeniesRecipes.TryGetValue(channel, out recipe))
            {
                recipe = new[] { P(channel) };
            }

            Transform root = avatarRoot != null ? avatarRoot : transform;
            SkinnedMeshRenderer[] renderers = root.GetComponentsInChildren<SkinnedMeshRenderer>(true);
            List<Contribution> parts = new List<Contribution>();
            for (int p = 0; p < recipe.Length; p++)
            {
                for (int r = 0; r < renderers.Length; r++)
                {
                    Mesh mesh = renderers[r].sharedMesh;
                    int index = LipSyncController.FindBlendShape(mesh, recipe[p].Shape);
                    if (index < 0)
                    {
                        continue;
                    }

                    parts.Add(new Contribution { Target = TargetFor(renderers[r], index), Factor = recipe[p].Weight });
                }
            }

            return parts.ToArray();
        }

        private bool IsKnownEmpty(string channel)
        {
            Part[] recipe;
            return _genies && GeniesRecipes.TryGetValue(channel, out recipe) && recipe.Length == 0;
        }

        private int TargetFor(SkinnedMeshRenderer renderer, int index)
        {
            for (int t = 0; t < _targets.Count; t++)
            {
                if (_targets[t].Renderer == renderer && _targets[t].Index == index)
                {
                    return t;
                }
            }

            _targets.Add(new Target
            {
                Renderer = renderer,
                Index = index,
                Scale = LipSyncController.BlendShapeScale(renderer.sharedMesh)
            });

            Array.Resize(ref _accum, _targets.Count);
            Array.Resize(ref _written, _targets.Count);
            _written[_targets.Count - 1] = true;
            return _targets.Count - 1;
        }

        private static string ShortName(string name)
        {
            int dot = name.LastIndexOf('.');
            return dot >= 0 && dot + 1 < name.Length ? name.Substring(dot + 1) : name;
        }
    }
}
