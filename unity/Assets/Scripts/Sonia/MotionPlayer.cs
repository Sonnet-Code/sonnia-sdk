// Code-driven clip player on top of the Playables API.
//
// Replaces the Animator Controller: instead of a graph with hundreds of
// transitions that cut any gesture at an arbitrary point, each clip is played
// here with an explicit fade, it is known when it ends and it is chained
// with the next one. It is what paid "code animation" assets do, with no
// dependencies: only UnityEngine.Playables and UnityEngine.Animations, which
// ship with the engine.
//
// Graph structure:
//
//   AnimationClipPlayable (one per live clip)
//     -> AnimationMixerPlayable (one per layer; blends the fades)
//       -> AnimationLayerMixerPlayable (layer 0 full body, layer 1 masked torso)
//         -> AnimationPlayableOutput (avatar Animator)
//
// The Animator still exists because it is the graph output and applies the
// humanoid retargeting, but it has no controller.
//
// Fades advance linearly, but the weight reaching the mixer goes through a
// smooth curve (smoothstep): it starts and arrives slowly, like Genies fades
// (measured on the Genies demo characters: 0.07, 0.20, 0.37, 0.57, 0.75, 0.90, 0.98 and 1 every 0.1 s
// in a 0.8 s gesture). Weights are still normalized afterwards.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

namespace Sonia
{
    /// <summary>
    /// Plays animation clips with code-driven fades on layers: full body,
    /// torso (masked) and right arm. Each <see cref="Play"/> returns a handle
    /// for querying the clip's progress.
    /// </summary>
    [DisallowMultipleComponent]
    public class MotionPlayer : MonoBehaviour
    {
        /// <summary>Full-body layer.</summary>
        public const int BodyLayer = 0;

        /// <summary>Torso, arms and head layer; lets the legs of the body layer through.</summary>
        public const int UpperLayer = 1;

        /// <summary>Right-arm-only layer (pointing at an image); the rest follows whatever is below.</summary>
        public const int RightArmLayer = 2;

        /// <summary>Number of layers in the graph.</summary>
        public const int LayerCount = 3;

        /// <summary>Reference to a clip being played.</summary>
        public sealed class Handle
        {
            internal int Layer;
            internal int Slot;
            internal int Serial;
            internal MotionPlayer Owner;

            /// <summary>Clip being played.</summary>
            public AnimationClip Clip { get; internal set; }

            /// <summary>True while the clip is still connected (even if fading out).</summary>
            public bool IsAlive
            {
                get { return Owner != null && Owner.IsAlive(this); }
            }

            /// <summary>True if it is the leading clip of its layer (the last one started).</summary>
            public bool IsCurrent
            {
                get { return Owner != null && Owner.IsCurrent(this); }
            }

            /// <summary>Seconds played, counting loops if it is a loop.</summary>
            public float Time
            {
                get { return Owner != null ? Owner.TimeOf(this) : 0f; }
            }

            /// <summary>Progress 0..1 within the clip (for loops, that of the current iteration).</summary>
            public float NormalizedTime
            {
                get
                {
                    if (Clip == null || Clip.length <= 0f)
                    {
                        return 1f;
                    }

                    float t = Time / Clip.length;
                    return Clip.isLooping ? t - Mathf.Floor(t) : Mathf.Clamp01(t);
                }
            }

            /// <summary>True when a non-looping clip has reached the end.</summary>
            public bool IsDone
            {
                get { return Clip == null || (!Clip.isLooping && Time >= Clip.length - 0.0001f); }
            }

            /// <summary>Seconds left until a non-looping clip ends (0 if it loops).</summary>
            public float Remaining
            {
                get { return Clip == null || Clip.isLooping ? 0f : Mathf.Max(0f, Clip.length - Time); }
            }

            /// <summary>Playback speed (0 freezes the clip where it is).</summary>
            public void SetSpeed(float speed)
            {
                if (Owner != null)
                {
                    Owner.SetSpeedOf(this, speed);
                }
            }
        }

        private sealed class SlotState
        {
            public AnimationClipPlayable Playable;
            public AnimationClip Clip;
            public float Weight;
            public float Target;
            public float FadeSpeed;
            public bool Used;
            public int Serial;
        }

        private sealed class LayerState
        {
            public AnimationMixerPlayable Mixer;
            public SlotState[] Slots;
            public int Current = -1;
            public float LayerWeight;
            public float LayerTarget;
            public float LayerFadeSpeed;
        }

        [SerializeField]
        [Tooltip("Avatar Animator (no controller). If empty, it is looked up in the children.")]
        private Animator animator;

        [SerializeField]
        [Tooltip("Torso layer mask. If empty, one excluding the legs and root is generated.")]
        private AvatarMask upperBodyMask;

        [SerializeField]
        [Range(2, 8)]
        [Tooltip("Clips that can coexist in a layer during fades.")]
        private int slotsPerLayer = 4;

        [SerializeField]
        [Tooltip("Fades with a smooth curve (smoothstep), like Genies. Off: linear.")]
        private bool smoothFades = true;

        private PlayableGraph _graph;
        private AnimationLayerMixerPlayable _layers;
        private AvatarMask _rightArmMask;
        private LayerState[] _layerStates = new LayerState[0];
        private int _serial;
        private bool _ready;

        /// <summary>Animator that receives the result. Changing it (another avatar) rebuilds the graph.</summary>
        public Animator Animator
        {
            get { return animator; }
            set
            {
                if (animator == value)
                {
                    return;
                }

                animator = value;
                if (isActiveAndEnabled)
                {
                    Build();
                }
            }
        }

        /// <summary>True when the graph is built and playing.</summary>
        public bool IsReady
        {
            get { return _ready; }
        }

        private void Awake()
        {
            if (animator == null)
            {
                animator = GetComponentInChildren<Animator>(true);
            }
        }

        private void OnEnable()
        {
            Build();
        }

        private void OnDisable()
        {
            Teardown();
        }

        /// <summary>Builds the graph. Called automatically; can be repeated if the Animator changes.</summary>
        public void Build()
        {
            Teardown();
            if (animator == null)
            {
                return;
            }

            // The graph overrides any controller; it is removed so they do not compete.
            animator.runtimeAnimatorController = null;
            animator.applyRootMotion = false;

            _graph = PlayableGraph.Create("Sonnia.MotionPlayer");
            _graph.SetTimeUpdateMode(DirectorUpdateMode.GameTime);

            _layers = AnimationLayerMixerPlayable.Create(_graph, LayerCount);
            _layerStates = new LayerState[LayerCount];
            for (int layer = 0; layer < LayerCount; layer++)
            {
                LayerState state = new LayerState();
                state.Mixer = AnimationMixerPlayable.Create(_graph, slotsPerLayer);
                state.Slots = new SlotState[slotsPerLayer];
                for (int i = 0; i < slotsPerLayer; i++)
                {
                    state.Slots[i] = new SlotState();
                }

                _graph.Connect(state.Mixer, 0, _layers, layer);
                _layers.SetInputWeight(layer, layer == BodyLayer ? 1f : 0f);
                state.LayerWeight = layer == BodyLayer ? 1f : 0f;
                state.LayerTarget = state.LayerWeight;
                _layerStates[layer] = state;
            }

            if (upperBodyMask == null)
            {
                upperBodyMask = CreateUpperBodyMask();
            }

            _layers.SetLayerMaskFromAvatarMask(UpperLayer, upperBodyMask);
            _layers.SetLayerAdditive(UpperLayer, false);
            if (_rightArmMask == null)
            {
                _rightArmMask = CreateRightArmMask();
            }

            _layers.SetLayerMaskFromAvatarMask(RightArmLayer, _rightArmMask);
            _layers.SetLayerAdditive(RightArmLayer, false);

            AnimationPlayableOutput output = AnimationPlayableOutput.Create(_graph, "Sonnia.Animation", animator);
            output.SetSourcePlayable(_layers);
            _graph.Play();
            _ready = true;
        }

        private void Teardown()
        {
            _ready = false;
            if (_graph.IsValid())
            {
                _graph.Destroy();
            }

            _layerStates = new LayerState[0];
        }

        /// <summary>Default torso mask: everything except root, legs and their IK.</summary>
        /// <summary>Right arm mask with its fingers, for pointing without touching the rest.</summary>
        public static AvatarMask CreateRightArmMask()
        {
            AvatarMask mask = new AvatarMask();
            mask.name = "SonniaRightArm";
            for (int i = 0; i < (int)AvatarMaskBodyPart.LastBodyPart; i++)
            {
                mask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)i, false);
            }

            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightArm, true);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightFingers, true);
            return mask;
        }

        public static AvatarMask CreateUpperBodyMask()
        {
            AvatarMask mask = new AvatarMask();
            mask.name = "SonniaUpperBody";
            for (int i = 0; i < (int)AvatarMaskBodyPart.LastBodyPart; i++)
            {
                mask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)i, true);
            }

            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.Root, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftLeg, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightLeg, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.LeftFootIK, false);
            mask.SetHumanoidBodyPartActive(AvatarMaskBodyPart.RightFootIK, false);
            return mask;
        }

        // ------------------------------------------------------------------
        // API
        // ------------------------------------------------------------------

        /// <summary>
        /// Starts a clip on a layer with a fade-in; the other clips
        /// on that layer fade out over the same time. On the torso
        /// layer it also raises the layer weight.
        /// </summary>
        /// <param name="clip">Clip to play. If null, does nothing.</param>
        /// <param name="layer">0 full body, 1 torso, 2 right arm.</param>
        /// <param name="fadeSeconds">Crossfade duration.</param>
        /// <param name="speed">Playback speed.</param>
        /// <param name="startTime">Second of the clip to start from.</param>
        public Handle Play(AnimationClip clip, int layer, float fadeSeconds, float speed = 1f, float startTime = 0f)
        {
            if (!_ready || clip == null || layer < 0 || layer >= _layerStates.Length)
            {
                return null;
            }

            LayerState state = _layerStates[layer];
            int slot = FindFreeSlot(state);
            SlotState s = state.Slots[slot];
            ReleaseSlot(state, slot);

            AnimationClipPlayable playable = AnimationClipPlayable.Create(_graph, clip);
            playable.SetApplyFootIK(layer == BodyLayer);
            playable.SetApplyPlayableIK(false);
            playable.SetSpeed(speed);
            playable.SetTime(startTime);
            if (!clip.isLooping)
            {
                // A non-looping clip stays in its last pose; the duration
                // bounds the time so IsDone is reliable.
                playable.SetDuration(clip.length);
            }

            _graph.Connect(playable, 0, state.Mixer, slot);

            s.Playable = playable;
            s.Clip = clip;
            s.Used = true;
            s.Serial = ++_serial;
            s.Weight = 0f;
            s.Target = 1f;
            s.FadeSpeed = fadeSeconds > 0.0001f ? 1f / fadeSeconds : float.PositiveInfinity;

            for (int i = 0; i < state.Slots.Length; i++)
            {
                if (i != slot && state.Slots[i].Used)
                {
                    state.Slots[i].Target = 0f;
                    state.Slots[i].FadeSpeed = s.FadeSpeed;
                }
            }

            state.Current = slot;
            if (layer != BodyLayer)
            {
                state.LayerTarget = 1f;
                state.LayerFadeSpeed = s.FadeSpeed;
            }

            if (fadeSeconds <= 0.0001f)
            {
                ApplyWeights(state, layer);
            }

            return new Handle { Layer = layer, Slot = slot, Serial = s.Serial, Owner = this, Clip = clip };
        }

        /// <summary>Fades out everything playing on a layer (on the torso, lowers the layer too).</summary>
        public void FadeOut(int layer, float fadeSeconds)
        {
            if (!_ready || layer < 0 || layer >= _layerStates.Length)
            {
                return;
            }

            LayerState state = _layerStates[layer];
            float speed = fadeSeconds > 0.0001f ? 1f / fadeSeconds : float.PositiveInfinity;
            for (int i = 0; i < state.Slots.Length; i++)
            {
                if (state.Slots[i].Used)
                {
                    state.Slots[i].Target = 0f;
                    state.Slots[i].FadeSpeed = speed;
                }
            }

            if (layer != BodyLayer)
            {
                state.LayerTarget = 0f;
                state.LayerFadeSpeed = speed;
            }

            state.Current = -1;
        }

        /// <summary>Clip currently leading the layer, or null.</summary>
        public AnimationClip CurrentClip(int layer)
        {
            if (!_ready || layer < 0 || layer >= _layerStates.Length)
            {
                return null;
            }

            LayerState state = _layerStates[layer];
            return state.Current >= 0 && state.Slots[state.Current].Used ? state.Slots[state.Current].Clip : null;
        }

        /// <summary>Current torso layer weight (0 = body only).</summary>
        public float UpperLayerWeight
        {
            get { return _layerStates.Length > UpperLayer ? _layerStates[UpperLayer].LayerWeight : 0f; }
        }

        // ------------------------------------------------------------------
        // Fades
        // ------------------------------------------------------------------

        private void Update()
        {
            if (!_ready)
            {
                return;
            }

            float dt = UnityEngine.Time.deltaTime;
            for (int layer = 0; layer < _layerStates.Length; layer++)
            {
                LayerState state = _layerStates[layer];
                for (int i = 0; i < state.Slots.Length; i++)
                {
                    SlotState s = state.Slots[i];
                    if (!s.Used)
                    {
                        continue;
                    }

                    s.Weight = MoveTowards(s.Weight, s.Target, s.FadeSpeed * dt);
                    if (s.Weight <= 0f && s.Target <= 0f)
                    {
                        ReleaseSlot(state, i);
                    }
                }

                state.LayerWeight = MoveTowards(state.LayerWeight, state.LayerTarget, state.LayerFadeSpeed * dt);
                ApplyWeights(state, layer);
            }
        }

        private void ApplyWeights(LayerState state, int layer)
        {
            // Weights are normalized so the sum is 1 while anything is
            // playing: this way the crossfade does not pass through a "sunken" pose.
            float sum = 0f;
            for (int i = 0; i < state.Slots.Length; i++)
            {
                if (state.Slots[i].Used)
                {
                    sum += Ease(state.Slots[i].Weight);
                }
            }

            for (int i = 0; i < state.Slots.Length; i++)
            {
                SlotState s = state.Slots[i];
                float w = s.Used && sum > 0.0001f ? Ease(s.Weight) / sum : 0f;
                state.Mixer.SetInputWeight(i, w);
            }

            if (layer != BodyLayer)
            {
                _layers.SetInputWeight(layer, sum > 0.0001f ? Ease(state.LayerWeight) : 0f);
            }
        }

        /// <summary>Linear fade weight passed through the smooth curve (if enabled).</summary>
        private float Ease(float linear)
        {
            if (!smoothFades)
            {
                return linear;
            }

            float t = Mathf.Clamp01(linear);
            return t * t * (3f - 2f * t);
        }

        private static float MoveTowards(float value, float target, float maxDelta)
        {
            if (float.IsInfinity(maxDelta))
            {
                return target;
            }

            return Mathf.MoveTowards(value, target, maxDelta);
        }

        private int FindFreeSlot(LayerState state)
        {
            int best = -1;
            float lowest = float.MaxValue;
            for (int i = 0; i < state.Slots.Length; i++)
            {
                SlotState s = state.Slots[i];
                if (!s.Used)
                {
                    return i;
                }

                // If all are busy, the lightest one that is not the current one is recycled.
                if (i != state.Current && s.Weight < lowest)
                {
                    lowest = s.Weight;
                    best = i;
                }
            }

            return best >= 0 ? best : 0;
        }

        private void ReleaseSlot(LayerState state, int slot)
        {
            SlotState s = state.Slots[slot];
            if (!s.Used)
            {
                return;
            }

            if (s.Playable.IsValid())
            {
                _graph.Disconnect(state.Mixer, slot);
                s.Playable.Destroy();
            }

            state.Mixer.SetInputWeight(slot, 0f);
            s.Used = false;
            s.Clip = null;
            s.Weight = 0f;
            s.Target = 0f;
            if (state.Current == slot)
            {
                state.Current = -1;
            }
        }

        private bool IsAlive(Handle handle)
        {
            if (!_ready || handle.Layer >= _layerStates.Length)
            {
                return false;
            }

            SlotState s = _layerStates[handle.Layer].Slots[handle.Slot];
            return s.Used && s.Serial == handle.Serial;
        }

        private bool IsCurrent(Handle handle)
        {
            return IsAlive(handle) && _layerStates[handle.Layer].Current == handle.Slot;
        }

        private float TimeOf(Handle handle)
        {
            if (!IsAlive(handle))
            {
                return handle.Clip != null ? handle.Clip.length : 0f;
            }

            return (float)_layerStates[handle.Layer].Slots[handle.Slot].Playable.GetTime();
        }

        private void SetSpeedOf(Handle handle, float speed)
        {
            if (!IsAlive(handle))
            {
                return;
            }

            _layerStates[handle.Layer].Slots[handle.Slot].Playable.SetSpeed(speed);
        }
    }
}
