// Reproductor de clips por código sobre la Playables API.
//
// Sustituye al Animator Controller: en lugar de un grafo con cientos de
// transiciones que cortan cualquier gesto en un punto arbitrario, aquí se
// reproduce cada clip con un fundido explícito, se sabe cuándo termina y se
// encadena con el siguiente. Es lo mismo que hacen los assets de pago de
// "animación por código", sin dependencias: solo UnityEngine.Playables y
// UnityEngine.Animations, que vienen con el motor.
//
// Estructura del grafo:
//
//   AnimationClipPlayable (uno por clip vivo)
//     -> AnimationMixerPlayable (uno por capa; mezcla los fundidos)
//       -> AnimationLayerMixerPlayable (capa 0 cuerpo entero, capa 1 torso con máscara)
//         -> AnimationPlayableOutput (Animator del avatar)
//
// El Animator sigue existiendo porque es la salida del grafo y quien aplica el
// retargeting humanoide, pero no lleva controlador.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

namespace Sonia
{
    /// <summary>
    /// Reproduce clips de animación con fundidos por código en dos capas: cuerpo
    /// entero y torso (con máscara). Cada <see cref="Play"/> devuelve un handle
    /// con el que consultar el progreso del clip.
    /// </summary>
    [DisallowMultipleComponent]
    public class MotionPlayer : MonoBehaviour
    {
        /// <summary>Capa de cuerpo entero.</summary>
        public const int BodyLayer = 0;

        /// <summary>Capa de torso, brazos y cabeza; deja pasar las piernas de la capa de cuerpo.</summary>
        public const int UpperLayer = 1;

        /// <summary>Capa del brazo derecho solo (señalar una imagen); el resto sigue lo que haya debajo.</summary>
        public const int RightArmLayer = 2;

        /// <summary>Número de capas del grafo.</summary>
        public const int LayerCount = 3;

        /// <summary>Referencia a un clip en reproducción.</summary>
        public sealed class Handle
        {
            internal int Layer;
            internal int Slot;
            internal int Serial;
            internal MotionPlayer Owner;

            /// <summary>Clip que reproduce.</summary>
            public AnimationClip Clip { get; internal set; }

            /// <summary>Cierto mientras el clip sigue conectado (aunque esté fundiéndose hacia fuera).</summary>
            public bool IsAlive
            {
                get { return Owner != null && Owner.IsAlive(this); }
            }

            /// <summary>Cierto si es el clip que manda en su capa (el último lanzado).</summary>
            public bool IsCurrent
            {
                get { return Owner != null && Owner.IsCurrent(this); }
            }

            /// <summary>Segundos reproducidos, contando las vueltas si es un bucle.</summary>
            public float Time
            {
                get { return Owner != null ? Owner.TimeOf(this) : 0f; }
            }

            /// <summary>Progreso 0..1 dentro del clip (con bucles, el de la vuelta actual).</summary>
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

            /// <summary>Cierto cuando un clip que no es bucle ha llegado al final.</summary>
            public bool IsDone
            {
                get { return Clip == null || (!Clip.isLooping && Time >= Clip.length - 0.0001f); }
            }

            /// <summary>Segundos que faltan para que termine un clip que no es bucle (0 si es bucle).</summary>
            public float Remaining
            {
                get { return Clip == null || Clip.isLooping ? 0f : Mathf.Max(0f, Clip.length - Time); }
            }

            /// <summary>Velocidad de reproducción (0 congela el clip donde está).</summary>
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
        [Tooltip("Animator del avatar (sin controlador). Si está vacío se busca en los hijos.")]
        private Animator animator;

        [SerializeField]
        [Tooltip("Máscara de la capa de torso. Si está vacía se genera una que excluye las piernas y la raíz.")]
        private AvatarMask upperBodyMask;

        [SerializeField]
        [Range(2, 8)]
        [Tooltip("Clips que pueden convivir en una capa durante los fundidos.")]
        private int slotsPerLayer = 4;

        private PlayableGraph _graph;
        private AnimationLayerMixerPlayable _layers;
        private AvatarMask _rightArmMask;
        private LayerState[] _layerStates = new LayerState[0];
        private int _serial;
        private bool _ready;

        /// <summary>Animator que recibe el resultado.</summary>
        public Animator Animator
        {
            get { return animator; }
        }

        /// <summary>Cierto cuando el grafo está construido y sonando.</summary>
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

        /// <summary>Construye el grafo. Se llama sola; se puede repetir si cambia el Animator.</summary>
        public void Build()
        {
            Teardown();
            if (animator == null)
            {
                return;
            }

            // El grafo pisa cualquier controlador; se quita para que no compitan.
            animator.runtimeAnimatorController = null;
            animator.applyRootMotion = false;

            _graph = PlayableGraph.Create("Sonia.MotionPlayer");
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

            AnimationPlayableOutput output = AnimationPlayableOutput.Create(_graph, "Sonia.Animation", animator);
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

        /// <summary>Máscara de torso por defecto: todo menos raíz, piernas y sus IK.</summary>
        /// <summary>Máscara del brazo derecho con sus dedos, para señalar sin tocar el resto.</summary>
        public static AvatarMask CreateRightArmMask()
        {
            AvatarMask mask = new AvatarMask();
            mask.name = "SoniaRightArm";
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
            mask.name = "SoniaUpperBody";
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
        /// Lanza un clip en una capa con un fundido de entrada; los demás clips
        /// de esa capa se funden hacia fuera en el mismo tiempo. En la capa de
        /// torso, además, sube el peso de la capa.
        /// </summary>
        /// <param name="clip">Clip a reproducir. Si es null, no hace nada.</param>
        /// <param name="layer">0 cuerpo entero, 1 torso, 2 brazo derecho.</param>
        /// <param name="fadeSeconds">Duración del fundido cruzado.</param>
        /// <param name="speed">Velocidad de reproducción.</param>
        /// <param name="startTime">Segundo del clip por el que empezar.</param>
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
                // Un clip que no es bucle se queda en su última pose; la duración
                // acota el tiempo para que IsDone sea fiable.
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

        /// <summary>Funde hacia fuera todo lo que suena en una capa (en el torso, baja también la capa).</summary>
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

        /// <summary>Clip que manda ahora mismo en la capa, o null.</summary>
        public AnimationClip CurrentClip(int layer)
        {
            if (!_ready || layer < 0 || layer >= _layerStates.Length)
            {
                return null;
            }

            LayerState state = _layerStates[layer];
            return state.Current >= 0 && state.Slots[state.Current].Used ? state.Slots[state.Current].Clip : null;
        }

        /// <summary>Peso actual de la capa de torso (0 = solo cuerpo).</summary>
        public float UpperLayerWeight
        {
            get { return _layerStates.Length > UpperLayer ? _layerStates[UpperLayer].LayerWeight : 0f; }
        }

        // ------------------------------------------------------------------
        // Fundidos
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
            // Los pesos se normalizan para que la suma sea 1 mientras haya algo
            // sonando: así el fundido cruzado no pasa por una pose "hundida".
            float sum = 0f;
            for (int i = 0; i < state.Slots.Length; i++)
            {
                if (state.Slots[i].Used)
                {
                    sum += state.Slots[i].Weight;
                }
            }

            for (int i = 0; i < state.Slots.Length; i++)
            {
                SlotState s = state.Slots[i];
                float w = s.Used && sum > 0.0001f ? s.Weight / sum : 0f;
                state.Mixer.SetInputWeight(i, w);
            }

            if (layer != BodyLayer)
            {
                _layers.SetInputWeight(layer, sum > 0.0001f ? state.LayerWeight : 0f);
            }
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

                // Si todos están ocupados se recicla el que menos pesa que no sea el actual.
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
