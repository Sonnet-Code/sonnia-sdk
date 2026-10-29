// Layer between the face controllers and the avatar meshes.
//
// Lip-sync, blinking and expressions share a common vocabulary: Oculus
// visemes (viseme_aa, viseme_PP...) and ARKit blendshapes (eyeBlinkLeft,
// mouthSmileLeft...). Here each channel is translated to the avatar's real
// shapes and written to every mesh that has them:
//
//  - Genies avatars: the face uses Meta's FACS expressions (JAW_DROP,
//    LIP_PUCKER_L...) and is split across several meshes that share
//    names (face, teeth and tongue, lashes, brows and eyes). Each channel is a
//    recipe with weights; the vowels come from the VRM expressions that
//    Genies itself defines ("a" is JAW_DROP 0.57 plus the four LIP_FUNNELER at 0.18).
//    Any FACS shape can also be requested by its name (JAW_DROP).
//  - Any other avatar: the channel is the blendshape with the same name.
//
// Controllers add their contributions during the frame (Add) and here,
// after all of them, each shape is written exactly once with the sum
// clamped to 1. Whatever nobody writes in a frame goes back to 0.
//
// Visemes (the lip-sync) also get the per-shape gains that Genies uses in
// its own lip-sync (Genies demo characters): funnel, pucker and closures came
// out exaggerated and Genies tones them down.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Translates the face channels (visemes and ARKit) to the avatar's shapes.</summary>
    [DefaultExecutionOrder(12900)]
    [DisallowMultipleComponent]
    public class FaceRig : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Avatar root; every mesh with blendshapes under it is used.")]
        private Transform avatarRoot;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("How much of the Genies lip-sync per-shape gains is applied to visemes: funnel x0.5, pucker x0.75, LIPS_TOWARD x0.4 and CHIN_RAISER_T x0.3. 1: Genies gains; 0: recipes as they are; 0.5: halfway.")]
        private float lipShapeGains = 1f;

        /// <summary>
        /// Per-shape gains that Genies applies to its lip-sync (Genies demo
        /// characters). They only count on visemes: an expression (pucker
        /// while thinking, pressed lips) is left untouched.
        /// </summary>
        private static readonly Dictionary<string, float> GeniesLipSyncGains =
            new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase)
            {
                { "LIP_FUNNELER_LB", 0.5f },
                { "LIP_FUNNELER_LT", 0.5f },
                { "LIP_FUNNELER_RB", 0.5f },
                { "LIP_FUNNELER_RT", 0.5f },
                { "LIP_PUCKER_L", 0.75f },
                { "LIP_PUCKER_R", 0.75f },
                { "LIPS_TOWARD", 0.4f },
                { "CHIN_RAISER_T", 0.3f },
            };

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

            // Genies lip-sync gain for this shape (1 if it has none).
            public float LipGain;
        }

        private static Part P(string shape, float weight = 1f)
        {
            return new Part(shape, weight);
        }

        /// <summary>
        /// Recipes for the Genies face. Nothing is eyeballed:
        ///  - Vowels A, E, I and O: the VRM expressions that Genies defines for its
        ///    avatars (Genies Avatar Starter Pack).
        ///  - U and consonants: the ARKit blends of the Oculus visemes from
        ///    TalkingHead (github.com/met4citizen/TalkingHead,
        ///    blender/build-visemes-from-arkit.py, MIT), converted to FACS with
        ///    Meta's official table (meta-quest/agentic-tools, ARKitOVRCustomFace.cs,
        ///    Apache-2.0). Where Meta maps a central shape to a single side
        ///    (mouthFunnel to LipFunnelerLT, mouthPucker to LipPuckerL...), here it goes to
        ///    all sides, because Genies has each side separately.
        ///  - Standalone ARKit names: the same Meta table.
        /// Anything not listed here is looked up as-is among the mesh shapes.
        /// </summary>
        private static readonly Dictionary<string, Part[]> GeniesRecipes =
            new Dictionary<string, Part[]>(StringComparer.OrdinalIgnoreCase)
            {
                // Genies vowels.
                { "viseme_aa", new[] { P("JAW_DROP", 0.57f), P("LIP_FUNNELER_LB", 0.18f), P("LIP_FUNNELER_LT", 0.18f), P("LIP_FUNNELER_RB", 0.18f), P("LIP_FUNNELER_RT", 0.18f) } },
                { "viseme_E", new[] { P("JAW_DROP", 0.2f) } },
                { "viseme_I", new[] { P("JAW_DROP", 0.2f), P("LIP_STRETCHER_L", 1f), P("LIP_STRETCHER_R", 1f) } },
                { "viseme_O", new[] { P("JAW_DROP", 0.65f), P("LIP_FUNNELER_LB", 0.4f), P("LIP_FUNNELER_LT", 0.4f), P("LIP_FUNNELER_RB", 0.4f), P("LIP_FUNNELER_RT", 0.4f) } },

                // TalkingHead converted to FACS with Meta's table.
                { "viseme_sil", new Part[0] },
                { "viseme_U", new[] { P("LIP_FUNNELER_LB"), P("LIP_FUNNELER_LT"), P("LIP_FUNNELER_RB"), P("LIP_FUNNELER_RT") } },
                { "viseme_PP", new[] { P("LIP_SUCK_LB", 0.8f), P("LIP_SUCK_RB", 0.8f), P("LIP_SUCK_LT", 0.8f), P("LIP_SUCK_RT", 0.8f), P("UPPER_LIP_RAISER_L", 0.3f), P("UPPER_LIP_RAISER_R", 0.3f) } },
                { "viseme_FF", new[] { P("LIP_PUCKER_L"), P("LIP_PUCKER_R"), P("CHIN_RAISER_T"), P("LOWER_LIP_DEPRESSOR_L", 0.2f), P("LOWER_LIP_DEPRESSOR_R", 0.2f), P("DIMPLER_L"), P("DIMPLER_R"), P("LIP_SUCK_LB"), P("LIP_SUCK_RB") } },
                { "viseme_DD", new[] { P("LIP_PRESSOR_L", 0.8f), P("LIP_PRESSOR_R", 0.8f), P("LIP_FUNNELER_LB", 0.5f), P("LIP_FUNNELER_LT", 0.5f), P("LIP_FUNNELER_RB", 0.5f), P("LIP_FUNNELER_RT", 0.5f), P("JAW_DROP", 0.2f) } },
                { "viseme_SS", new[] { P("LIP_PRESSOR_L", 0.8f), P("LIP_PRESSOR_R", 0.8f), P("LOWER_LIP_DEPRESSOR_L", 0.5f), P("LOWER_LIP_DEPRESSOR_R", 0.5f), P("JAW_DROP", 0.1f) } },
                { "viseme_TH", new[] { P("LIP_SUCK_LT", 0.6f), P("LIP_SUCK_RT", 0.6f), P("JAW_DROP", 0.2f), P("TONGUE_OUT", 0.4f) } },
                { "viseme_CH", new[] { P("LIP_PUCKER_L", 0.5f), P("LIP_PUCKER_R", 0.5f), P("JAW_DROP", 0.2f) } },
                { "viseme_RR", new[] { P("LIP_PUCKER_L", 0.5f), P("LIP_PUCKER_R", 0.5f), P("JAW_DROP", 0.2f) } },
                { "viseme_kk", new[] { P("LOWER_LIP_DEPRESSOR_L", 0.4f), P("LOWER_LIP_DEPRESSOR_R", 0.4f), P("DIMPLER_L", 0.3f), P("DIMPLER_R", 0.3f), P("LIP_FUNNELER_LB", 0.3f), P("LIP_FUNNELER_LT", 0.3f), P("LIP_FUNNELER_RB", 0.3f), P("LIP_FUNNELER_RT", 0.3f), P("LIP_PUCKER_L", 0.3f), P("LIP_PUCKER_R", 0.3f), P("JAW_DROP", 0.15f) } },
                { "viseme_nn", new[] { P("LOWER_LIP_DEPRESSOR_L", 0.4f), P("LOWER_LIP_DEPRESSOR_R", 0.4f), P("DIMPLER_L", 0.3f), P("DIMPLER_R", 0.3f), P("LIP_FUNNELER_LB", 0.3f), P("LIP_FUNNELER_LT", 0.3f), P("LIP_FUNNELER_RB", 0.3f), P("LIP_FUNNELER_RT", 0.3f), P("LIP_PUCKER_L", 0.3f), P("LIP_PUCKER_R", 0.3f), P("JAW_DROP", 0.15f), P("TONGUE_OUT", 0.2f) } },

                // ARKit with Meta's table.
                { "jawOpen", new[] { P("JAW_DROP") } },
                { "mouthOpen", new[] { P("JAW_DROP") } },
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
        /// Raised when the meshes changed (another avatar): previously resolved
        /// channels are no longer valid and must be requested again with <see cref="Channel"/>.
        /// </summary>
        public event Action Rebuilt;

        /// <summary>Avatar root. Changing it triggers a new mesh search.</summary>
        public Transform AvatarRoot
        {
            get { return avatarRoot; }
            set
            {
                avatarRoot = value;
                Rebuild();
            }
        }

        /// <summary>True if the face is the Genies FACS one.</summary>
        public bool IsGenies
        {
            get
            {
                EnsureBuilt();
                return _genies;
            }
        }

        /// <summary>Mesh with the most face shapes, the one used for measuring.</summary>
        public SkinnedMeshRenderer PrimaryRenderer { get; private set; }

        /// <summary>How much of the Genies lip-sync gains is applied to visemes (0..1).</summary>
        public float LipShapeGains
        {
            get { return lipShapeGains; }
            set { lipShapeGains = Mathf.Clamp01(value); }
        }

        private void Awake()
        {
            EnsureBuilt();
        }

        /// <summary>
        /// Channel identifier (viseme, ARKit name or FACS shape), or -1 if the
        /// avatar has nothing to represent it. Resolved once and cached.
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

        /// <summary>Adds <paramref name="weight01"/> (0..1) to the channel for this frame.</summary>
        public void Add(int channel, float weight01)
        {
            if (channel < 0 || channel >= _channels.Count || weight01 == 0f)
            {
                return;
            }

            Contribution[] parts = _channels[channel];
            for (int i = 0; i < parts.Length; i++)
            {
                float factor = parts[i].Factor;
                if (parts[i].LipGain != 1f)
                {
                    factor *= Mathf.Lerp(1f, parts[i].LipGain, lipShapeGains);
                }

                _accum[parts[i].Target] += weight01 * factor;
            }
        }

        /// <summary>Searches the meshes again and re-resolves the channels.</summary>
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
            bool lipSync = _genies && channel.StartsWith("viseme_", StringComparison.OrdinalIgnoreCase);
            List<Contribution> parts = new List<Contribution>();
            for (int p = 0; p < recipe.Length; p++)
            {
                float lipGain;
                if (!lipSync || !GeniesLipSyncGains.TryGetValue(recipe[p].Shape, out lipGain))
                {
                    lipGain = 1f;
                }

                for (int r = 0; r < renderers.Length; r++)
                {
                    Mesh mesh = renderers[r].sharedMesh;
                    int index = LipSyncController.FindBlendShape(mesh, recipe[p].Shape);
                    if (index < 0)
                    {
                        continue;
                    }

                    parts.Add(new Contribution
                    {
                        Target = TargetFor(renderers[r], index), Factor = recipe[p].Weight, LipGain = lipGain
                    });
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
    }
}
