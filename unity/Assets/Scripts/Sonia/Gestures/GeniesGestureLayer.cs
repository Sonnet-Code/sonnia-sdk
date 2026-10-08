// El cuerpo de Genies: reproduce los clips OZZ de un personaje del chat de
// Genies (GeniesGestureSet, de momento Sage) en el esqueleto vivo del avatar,
// igual que el motor de Genies.
//
// Los OZZ guardan cada hueso como diferencia con la pose de enlace del cuerpo.
// Genies los aplica a cualquier cuerpo con local = enlace · clip (y la cadera
// se desplaza lo que diga el clip), comprobado contra su motor a 0,65°
// (gestos-genies/README.md). Aquí se hace lo mismo con la pose de enlace de
// este avatar, que sale de las bindposes de sus mallas. No hay clips de Unity
// de por medio: ni retarget humanoide ni .anim en el repo.
//
// Tres canales, de abajo arriba, como el grafo de Genies:
//
//   reposo    bucles de cuerpo entero (cadera, piernas y torso): el reposo
//             base, escuchar o pensar. Se cambia de uno a otro con fundido
//             cruzado y su peso total lo baja el coreógrafo cuando manda otro
//             clip de MotionPlayer (baile, caminar, reacciones de la trivia)
//   acciones  clips de cuerpo entero de una sola vez sobre el reposo:
//             aburrimiento, saludo, gestos hacia el público, movimientos
//             pedidos de viva voz y la vista previa del panel. Una acción
//             puede ir sostenida: entra a mitad del clip y va y viene en un
//             tramo hasta que se suelta (la mano en la barbilla al pensar)
//   gestos    gestos al hablar, solo el torso (columna, cabeza, brazos y manos),
//             que elige el director de gestos del orquestador
//
// Cada clip entra y sale con el fundido del personaje (TransitionToClip_Duration
// de su demeanor, 0,8 s en Sage) con curva suave. Acciones y gestos salen en
// espejo con probabilidad mirrorChance (Genies: 50 %): cada hueso toma el clip
// de su opuesto con el cuaternión reflejado, que en el rig de Genies es justo
// el valor del clip sin pasarlo a Unity (comprobado con un gesto simétrico).
//
// También pasa a FaceRig las curvas de cara FACS de cada clip (párpados, cejas,
// mejillas y comisuras). Las de la boca y la mandíbula son del lip-sync y las de
// mirar (EYES_LOOK_*) de los ojos. Los parpadeos animados solo van en los gestos
// al hablar: en reposo y acciones parpadea el parpadeo propio de Sonia, como en
// Genies, para no parpadear el doble.
//
// Corre en LateUpdate después del Animator y antes que todo lo demás: las
// físicas del pelo de Genies (orden 0) colocan el pelo sobre la cabeza ya
// movida, y la respiración, la cabeza que sigue al visitante, la mirada y la
// cara (AvatarStateController, EyeGazeController, FaceRig) suman encima.

using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Reproduce los clips OZZ de Genies sobre el avatar: reposo, acciones y gestos al hablar.</summary>
    [DefaultExecutionOrder(-20)]
    [DisallowMultipleComponent]
    public sealed class GeniesGestureLayer : MonoBehaviour
    {
        /// <summary>Huesos del torso, los que mueven los gestos al hablar (nombres del esqueleto de Genies).</summary>
        public static readonly string[] BoneNames =
        {
            "Spine", "Spine1", "Spine2", "Neck", "Head",
            "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
            "LeftHandThumb1", "LeftHandThumb2", "LeftHandThumb3",
            "LeftHandIndex1", "LeftHandIndex2", "LeftHandIndex3",
            "LeftHandMiddle1", "LeftHandMiddle2", "LeftHandMiddle3",
            "LeftHandRing1", "LeftHandRing2", "LeftHandRing3",
            "LeftHandPinky1", "LeftHandPinky2", "LeftHandPinky3",
            "RightShoulder", "RightArm", "RightForeArm", "RightHand",
            "RightHandThumb1", "RightHandThumb2", "RightHandThumb3",
            "RightHandIndex1", "RightHandIndex2", "RightHandIndex3",
            "RightHandMiddle1", "RightHandMiddle2", "RightHandMiddle3",
            "RightHandRing1", "RightHandRing2", "RightHandRing3",
            "RightHandPinky1", "RightHandPinky2", "RightHandPinky3"
        };

        /// <summary>Cadera y piernas: lo que añaden el reposo y las acciones al torso.</summary>
        public static readonly string[] LowerBoneNames =
        {
            "Hips",
            "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
            "RightUpLeg", "RightLeg", "RightFoot", "RightToeBase"
        };

        /// <summary>Formas FACS de los clips que se pasan a la cara (por prefijo).</summary>
        private static readonly string[] FacePrefixes =
        {
            "EYES_CLOSED", "UPPER_LID_RAISER", "LID_TIGHTENER",
            "BROW_LOWERER", "INNER_BROW_RAISER", "OUTER_BROW_RAISER",
            "CHEEK_RAISER", "NOSE_WRINKLER", "DIMPLER",
            "LIP_CORNER_PULLER", "LIP_CORNER_DEPRESSOR"
        };

        private const string BlinkPrefix = "EYES_CLOSED";
        private const string FloatTrackPrefix = "Root-";

        /// <summary>Altura de la cadera del cuerpo de los clips (avatar de la web de Genies), para escalar su desplazamiento.</summary>
        private const float ClipHipsHeight = 0.7785f;

        [SerializeField]
        [Tooltip("Gestos del personaje (Sonia > Gestos de Genies > Crear set de Sage).")]
        private GeniesGestureSet gestureSet;

        [SerializeField]
        [Tooltip("De aquí sale el Animator del avatar enganchado. Si está vacío se busca en este objeto.")]
        private MotionPlayer motionPlayer;

        [SerializeField]
        [Tooltip("Cara del avatar para las curvas FACS de los clips. Si está vacío se busca en este objeto.")]
        private FaceRig faceRig;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto mandan los gestos al hablar sobre el torso (1: como en Genies).")]
        private float bodyWeight = 1f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Ganancia de las curvas de cara de los clips (1: como en Genies; 0: sin cara).")]
        private float faceGain = 1f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de reproducir en espejo cada acción y cada gesto al hablar (Genies: 0,5).")]
        private float mirrorChance = 0.5f;

        [SerializeField]
        [Tooltip("Escribe en la consola cada clip que empieza.")]
        private bool logGestures = true;

        private enum Channel
        {
            Rest,
            Action,
            Gesture
        }

        private sealed class Bone
        {
            public string Name;
            public Transform Transform;
            public Quaternion Bind;
            public bool Torso;
            public bool RightArm;
        }

        /// <summary>Un clip sonando en un canal.</summary>
        private sealed class Track
        {
            public Channel Channel;
            public GeniesGestureSet.Gesture Gesture;
            public GeniesOzzClip Clip;
            public bool Mirror;
            public int[] Joints;
            public int HipsJoint = -1;
            public int[] FaceChannels;
            public GeniesOzzClip.FloatTrack[] FaceTracks;
            public float Time;
            public float Fade;

            // Reposo: mezcla del fundido cruzado (0..1, lineal) y hacia dónde va.
            public float Mix;
            public float MixTarget = 1f;
            public bool LoopEndSignaled;

            // Acciones y gestos: parada antes de tiempo.
            public bool Stopping;
            public float StopLeft = 1f;
            public float StopSpeed;
            public float Weight;

            // Segundos desde que entró (el fundido de entrada; Time puede empezar a
            // mitad del clip) y fundido de entrada si no es el de siempre (Fade).
            public float Age;
            public float FadeIn = -1f;

            // Acción sostenida: va y viene entre HoldFrom y HoldTo hasta que se suelta.
            public bool Holding;
            public float HoldFrom;
            public float HoldTo;
            public float HoldPhase;
            public float HoldRate;

            public float Ratio
            {
                get
                {
                    if (Clip.Duration <= 0f)
                    {
                        return 0f;
                    }

                    if (Channel == Channel.Rest)
                    {
                        return Mathf.Repeat(Time, Clip.Duration) / Clip.Duration;
                    }

                    return Clip.RatioAt(Time);
                }
            }
        }

        private readonly List<Bone> _bones = new List<Bone>();
        private readonly List<Track> _rest = new List<Track>();
        private readonly List<Track> _actions = new List<Track>();
        private readonly List<Track> _gestures = new List<Track>();
        private readonly Dictionary<string, GeniesOzzClip> _clips = new Dictionary<string, GeniesOzzClip>(StringComparer.Ordinal);
        private Animator _bound;
        private float _nextBindRetry;
        private Coroutine _prewarm;
        private int _hips = -1;
        private Vector3 _hipsBindPosition;
        private float _hipsScale = 1f;

        // Peso total del canal de reposo (0..1, lineal; se aplica con curva suave).
        private float _restWeight;
        private float _restTarget;
        private float _restSpeed = 1f;
        private bool _maskRightArm;

        /// <summary>Se lanza al empezar un gesto al hablar (nombre).</summary>
        public event Action<string> GestureStarted;

        /// <summary>Gestos que puede reproducir.</summary>
        public GeniesGestureSet Set
        {
            get { return gestureSet; }
            set
            {
                gestureSet = value;
                _clips.Clear();
                StopNow();
            }
        }

        /// <summary>Cierto si tiene gestos y un avatar enganchado.</summary>
        public bool IsReady
        {
            get
            {
                EnsureBound();
                return gestureSet != null && gestureSet.gestures.Length > 0 && _bones.Count > 0;
            }
        }

        /// <summary>Huesos del avatar enganchados (0: sin avatar o sin su pose de enlace todavía).</summary>
        public int BoneCount
        {
            get
            {
                EnsureBound();
                return _bones.Count;
            }
        }

        /// <summary>Cierto si el set trae reposos de cuerpo entero.</summary>
        public bool HasRest
        {
            get { return gestureSet != null && gestureSet.HasRest; }
        }

        /// <summary>
        /// Cierto mientras el cuerpo lo llevan los clips de Genies (reposo o una
        /// acción a la vista): los movimientos por código de AvatarStateController
        /// (asentir, ladear, acentos) se apartan.
        /// </summary>
        public bool DrivesBody
        {
            get { return _bones.Count > 0 && (_restWeight > 0.01f && _rest.Count > 0 || _actions.Count > 0); }
        }

        // ------------------------------------------------------------------
        // Gestos al hablar (torso)
        // ------------------------------------------------------------------

        /// <summary>Cierto mientras suena algún gesto al hablar (aunque se esté fundiendo hacia fuera).</summary>
        public bool IsActive
        {
            get { return _gestures.Count > 0; }
        }

        /// <summary>Gesto al hablar que manda ahora (el último lanzado y no parado), o null.</summary>
        public string Current
        {
            get { return Latest(_gestures); }
        }

        /// <summary>Segundos que le quedan al gesto al hablar que manda (0 si no hay).</summary>
        public float GestureRemaining
        {
            get
            {
                for (int i = _gestures.Count - 1; i >= 0; i--)
                {
                    if (!_gestures[i].Stopping)
                    {
                        return Mathf.Max(0f, _gestures[i].Clip.Duration - _gestures[i].Time);
                    }
                }

                return 0f;
            }
        }

        /// <summary>Cierto si el set tiene ese gesto.</summary>
        public bool Has(string gestureName)
        {
            return gestureSet != null && gestureSet.Find(gestureName) != null;
        }

        /// <summary>
        /// Lanza un gesto al hablar sobre el torso. Los que estuvieran sonando se
        /// funden hacia fuera a la vez que entra este. Devuelve falso si no
        /// existe, no hay avatar o el clip no se puede leer.
        /// </summary>
        public bool Play(string gestureName, float fadeSeconds = -1f)
        {
            Track track = Start(Channel.Gesture, gestureName, fadeSeconds, UnityEngine.Random.value < mirrorChance);
            if (track == null)
            {
                return false;
            }

            Action<string> started = GestureStarted;
            if (started != null)
            {
                started(track.Gesture.name);
            }

            return true;
        }

        /// <summary>Funde hacia fuera los gestos al hablar (por defecto con el fundido del personaje).</summary>
        public void Stop(float fadeSeconds = -1f)
        {
            StopAll(_gestures, FadeOr(fadeSeconds));
        }

        /// <summary>Corta todo sin fundido (los tres canales).</summary>
        public void StopNow()
        {
            _gestures.Clear();
            _actions.Clear();
            _rest.Clear();
            _restWeight = 0f;
            _restTarget = 0f;
        }

        // ------------------------------------------------------------------
        // Reposo (cuerpo entero, en bucle)
        // ------------------------------------------------------------------

        /// <summary>Reposo que manda ahora, o null.</summary>
        public string CurrentRest
        {
            get
            {
                for (int i = _rest.Count - 1; i >= 0; i--)
                {
                    if (_rest[i].MixTarget > 0f)
                    {
                        return _rest[i].Gesture.name;
                    }
                }

                return null;
            }
        }

        /// <summary>Peso total del reposo ahora mismo (0..1).</summary>
        public float RestWeight
        {
            get { return Ease(_restWeight); }
        }

        /// <summary>
        /// Pasa al reposo <paramref name="gestureName"/> con fundido cruzado (si
        /// ya es el que manda, no hace nada). Suena en bucle hasta el siguiente.
        /// </summary>
        public bool PlayRest(string gestureName, float fadeSeconds = -1f)
        {
            if (CurrentRest == gestureName)
            {
                return true;
            }

            float fade = FadeOr(fadeSeconds);
            Track track = Start(Channel.Rest, gestureName, fade, false);
            if (track == null)
            {
                return false;
            }

            foreach (Track other in _rest)
            {
                if (other != track)
                {
                    other.MixTarget = 0f;
                    other.Fade = fade;
                }
            }

            // Si no se veía ninguno, entra entero de golpe: el fundido lo hace el peso del canal.
            if (_restWeight <= 0.001f)
            {
                track.Mix = 1f;
                _rest.RemoveAll(t => t != track);
            }

            return true;
        }

        /// <summary>Sube o baja el peso del reposo (0: se ve lo que reproduzca MotionPlayer).</summary>
        public void SetRestWeight(float target, float fadeSeconds)
        {
            target = Mathf.Clamp01(target);
            if (Mathf.Approximately(target, _restTarget) && fadeSeconds > 0f)
            {
                return;
            }

            _restTarget = target;
            _restSpeed = 1f / Mathf.Max(0.01f, fadeSeconds);
            if (fadeSeconds <= 0f)
            {
                _restWeight = target;
            }
        }

        /// <summary>
        /// Cierto una sola vez por vuelta, cuando al reposo que manda le quedan
        /// <paramref name="seconds"/> para acabar la vuelta: el momento de elegir
        /// el siguiente.
        /// </summary>
        public bool ConsumeRestLoopEnd(float seconds)
        {
            for (int i = _rest.Count - 1; i >= 0; i--)
            {
                Track track = _rest[i];
                if (track.MixTarget <= 0f)
                {
                    continue;
                }

                float left = track.Clip.Duration - Mathf.Repeat(track.Time, track.Clip.Duration);
                if (left <= seconds && !track.LoopEndSignaled)
                {
                    track.LoopEndSignaled = true;
                    return true;
                }

                return false;
            }

            return false;
        }

        /// <summary>
        /// Deja el brazo derecho a MotionPlayer (señalar una imagen con su capa de
        /// brazo) mientras el resto del cuerpo sigue en el reposo.
        /// </summary>
        public void MaskRightArm(bool masked)
        {
            _maskRightArm = masked;
        }

        // ------------------------------------------------------------------
        // Acciones (cuerpo entero, una vez)
        // ------------------------------------------------------------------

        /// <summary>Cierto mientras suena una acción (aunque se esté fundiendo hacia fuera).</summary>
        public bool IsActionPlaying
        {
            get { return _actions.Count > 0; }
        }

        /// <summary>Acción que manda ahora, o null.</summary>
        public string CurrentAction
        {
            get { return Latest(_actions); }
        }

        /// <summary>Segundos que le quedan a la acción que manda (0 si no hay).</summary>
        public float ActionRemaining
        {
            get
            {
                for (int i = _actions.Count - 1; i >= 0; i--)
                {
                    if (!_actions[i].Stopping)
                    {
                        return Mathf.Max(0f, _actions[i].Clip.Duration - _actions[i].Time);
                    }
                }

                return 0f;
            }
        }

        /// <summary>
        /// Lanza una acción de cuerpo entero sobre el reposo (en espejo según
        /// mirrorChance si <paramref name="mirror"/> es null). Las acciones y los
        /// gestos que sonaran se funden hacia fuera.
        /// </summary>
        public bool PlayAction(string gestureName, float fadeSeconds = -1f, bool? mirror = null)
        {
            bool flip = mirror.HasValue ? mirror.Value : UnityEngine.Random.value < mirrorChance;
            Track track = Start(Channel.Action, gestureName, fadeSeconds, flip);
            if (track == null)
            {
                return false;
            }

            StopAll(_gestures, track.Fade);
            return true;
        }

        /// <summary>
        /// Acción sostenida: entra ya en el segundo <paramref name="from"/> del clip
        /// (el fundido la lleva desde la pose de antes) y va y viene entre
        /// <paramref name="from"/> y <paramref name="to"/> con vaivén suave, a
        /// <paramref name="speed"/> de su velocidad, hasta <see cref="ReleaseHold"/>.
        /// Para poses que duran lo que dure algo, como la mano en la barbilla
        /// mientras una tarea tarda.
        /// </summary>
        public bool PlayHeldAction(string gestureName, float from, float to, float speed, float fadeSeconds = -1f, bool? mirror = null)
        {
            if (!PlayAction(gestureName, fadeSeconds, mirror))
            {
                return false;
            }

            Track track = _actions[_actions.Count - 1];
            float last = Mathf.Max(0f, track.Clip.Duration - track.Fade - 0.05f);
            track.HoldFrom = Mathf.Clamp(Mathf.Min(from, to), 0f, last);
            track.HoldTo = Mathf.Clamp(Mathf.Max(from, to), track.HoldFrom, last);
            track.Time = track.HoldFrom;
            track.HoldPhase = 0f;
            track.HoldRate = track.HoldTo > track.HoldFrom
                ? Mathf.PI * Mathf.Max(0.05f, speed) / (track.HoldTo - track.HoldFrom)
                : 0f;
            track.Holding = true;
            return true;
        }

        /// <summary>Cierto mientras una acción sostenida sigue sostenida.</summary>
        public bool IsHolding
        {
            get
            {
                foreach (Track track in _actions)
                {
                    if (track.Holding && !track.Stopping)
                    {
                        return true;
                    }
                }

                return false;
            }
        }

        /// <summary>
        /// Suelta las acciones sostenidas: del punto del vaivén en que vayan pasan
        /// con un fundido de <paramref name="fadeSeconds"/> al final del tramo
        /// sostenido (la misma pose, más o menos) y desde ahí el clip sigue hasta
        /// el final. Seguir desde donde iba dejaba la mano en la barbilla hasta 1,5 s
        /// más, ya hablando.
        /// </summary>
        public void ReleaseHold(float fadeSeconds = 0.35f)
        {
            int count = _actions.Count;
            for (int i = 0; i < count; i++)
            {
                Track held = _actions[i];
                if (!held.Holding)
                {
                    continue;
                }

                held.Holding = false;
                if (held.Stopping)
                {
                    continue;
                }

                Track exit = NewTrack(Channel.Action, held.Gesture, held.Clip, held.Mirror, held.Fade);
                exit.Time = held.HoldTo;
                exit.FadeIn = Mathf.Max(0.05f, fadeSeconds);
                _actions.Add(exit);
                held.Stopping = true;
                held.StopSpeed = 1f / exit.FadeIn;
            }
        }

        /// <summary>Funde hacia fuera las acciones.</summary>
        public void StopActions(float fadeSeconds = -1f)
        {
            StopAll(_actions, FadeOr(fadeSeconds));
        }

        // ------------------------------------------------------------------
        // Comprobaciones del editor
        // ------------------------------------------------------------------

        /// <summary>
        /// Pone el avatar en la pose del clip en un instante (a peso 1), sin
        /// reproducirlo: el torso, o el cuerpo entero con la cadera si
        /// <paramref name="fullBody"/>. Lo usan las hojas de contactos del
        /// editor; el siguiente fotograma el Animator vuelve a mandar.
        /// </summary>
        public bool ApplyPose(string gestureName, float seconds, bool fullBody = false, bool mirror = false)
        {
            if (!IsReady)
            {
                return false;
            }

            GeniesGestureSet.Gesture gesture = gestureSet.Find(gestureName);
            GeniesOzzClip clip = gesture != null ? ClipOf(gesture) : null;
            if (clip == null)
            {
                return false;
            }

            Track track = NewTrack(fullBody ? Channel.Action : Channel.Gesture, gesture, clip, mirror, 0f);
            track.Time = seconds;
            float ratio = track.Ratio;
            for (int b = 0; b < _bones.Count; b++)
            {
                if (track.Joints[b] >= 0)
                {
                    _bones[b].Transform.localRotation = Target(track, b, ratio);
                }
            }

            if (fullBody && _hips >= 0 && track.HipsJoint >= 0)
            {
                _bones[_hips].Transform.localPosition = HipsTarget(track, ratio);
            }

            return true;
        }

        /// <summary>Duración del clip en segundos (0 si no existe o no se puede leer).</summary>
        public float DurationOf(string gestureName)
        {
            GeniesGestureSet.Gesture gesture = gestureSet != null ? gestureSet.Find(gestureName) : null;
            GeniesOzzClip clip = gesture != null ? ClipOf(gesture) : null;
            return clip != null ? clip.Duration : 0f;
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void Awake()
        {
            if (motionPlayer == null)
            {
                motionPlayer = GetComponentInChildren<MotionPlayer>(true);
            }

            if (faceRig == null)
            {
                faceRig = GetComponentInChildren<FaceRig>(true);
            }
        }

        private void OnDisable()
        {
            StopNow();
            _prewarm = null;
        }

        private void LateUpdate()
        {
            EnsureBound();
            float dt = UnityEngine.Time.deltaTime;
            AdvanceRest(dt);
            AdvanceOneShots(_actions, dt);
            AdvanceOneShots(_gestures, dt);
            if (_bones.Count == 0)
            {
                return;
            }

            float restWeight = Ease(_restWeight);
            bool rest = restWeight > 0f && _rest.Count > 0;
            if (!rest && _actions.Count == 0 && _gestures.Count == 0)
            {
                return;
            }

            for (int b = 0; b < _bones.Count; b++)
            {
                Bone bone = _bones[b];
                Quaternion rotation = bone.Transform.localRotation;
                bool touched = false;
                bool masked = _maskRightArm && bone.RightArm;
                if (rest && !masked)
                {
                    foreach (Track track in _rest)
                    {
                        float w = Ease(track.Mix) * restWeight;
                        if (track.Joints[b] >= 0 && w > 0f)
                        {
                            rotation = Quaternion.Slerp(rotation, Target(track, b, track.Ratio), w);
                            touched = true;
                        }
                    }
                }

                if (!masked)
                {
                    foreach (Track track in _actions)
                    {
                        if (track.Joints[b] >= 0 && track.Weight > 0f)
                        {
                            rotation = Quaternion.Slerp(rotation, Target(track, b, track.Ratio), track.Weight);
                            touched = true;
                        }
                    }
                }

                if (bone.Torso)
                {
                    foreach (Track track in _gestures)
                    {
                        float w = track.Weight * bodyWeight;
                        if (track.Joints[b] >= 0 && w > 0f)
                        {
                            rotation = Quaternion.Slerp(rotation, Target(track, b, track.Ratio), w);
                            touched = true;
                        }
                    }
                }

                if (touched)
                {
                    bone.Transform.localRotation = rotation;
                }
            }

            ApplyHips(restWeight, rest);
            ApplyFace(restWeight, rest);
        }

        private void AdvanceRest(float dt)
        {
            _restWeight = Mathf.MoveTowards(_restWeight, _restTarget, dt * _restSpeed);
            for (int i = _rest.Count - 1; i >= 0; i--)
            {
                Track track = _rest[i];
                float before = Mathf.Repeat(track.Time, track.Clip.Duration);
                track.Time += dt;
                if (Mathf.Repeat(track.Time, track.Clip.Duration) < before)
                {
                    track.LoopEndSignaled = false;
                }

                track.Mix = Mathf.MoveTowards(track.Mix, track.MixTarget, dt / Mathf.Max(0.01f, track.Fade));
                if (track.MixTarget <= 0f && track.Mix <= 0f)
                {
                    _rest.RemoveAt(i);
                }
            }

            // Con el canal oculto del todo no hace falta seguir arrastrando reposos viejos.
            if (_restWeight <= 0f && _restTarget <= 0f)
            {
                _rest.RemoveAll(t => t.MixTarget <= 0f);
            }
        }

        private static void AdvanceOneShots(List<Track> tracks, float dt)
        {
            for (int i = tracks.Count - 1; i >= 0; i--)
            {
                Track track = tracks[i];
                track.Age += dt;
                if (track.Holding)
                {
                    // Vaivén con coseno: frena y cambia de sentido sin tirones en los extremos.
                    track.HoldPhase += dt * track.HoldRate;
                    track.Time = track.HoldFrom + (track.HoldTo - track.HoldFrom) * (0.5f - 0.5f * Mathf.Cos(track.HoldPhase));
                }
                else
                {
                    track.Time += dt;
                }

                if (track.Stopping)
                {
                    track.StopLeft = Mathf.Max(0f, track.StopLeft - dt * track.StopSpeed);
                }

                float duration = track.Clip.Duration;
                if (track.Time >= duration || (track.Stopping && track.StopLeft <= 0f))
                {
                    tracks.RemoveAt(i);
                    continue;
                }

                float fadeInSeconds = track.FadeIn > 0f ? track.FadeIn : track.Fade;
                float fadeIn = fadeInSeconds > 0f ? Ease(track.Age / fadeInSeconds) : 1f;
                float fadeOut = track.Fade > 0f ? Ease((duration - track.Time) / track.Fade) : 1f;
                track.Weight = Mathf.Min(fadeIn, Mathf.Min(fadeOut, Ease(track.StopLeft)));
            }
        }

        private void ApplyHips(float restWeight, bool rest)
        {
            if (_hips < 0)
            {
                return;
            }

            Transform hips = _bones[_hips].Transform;
            Vector3 position = hips.localPosition;
            bool touched = false;
            if (rest)
            {
                foreach (Track track in _rest)
                {
                    float w = Ease(track.Mix) * restWeight;
                    if (track.HipsJoint >= 0 && w > 0f)
                    {
                        position = Vector3.Lerp(position, HipsTarget(track, track.Ratio), w);
                        touched = true;
                    }
                }
            }

            foreach (Track track in _actions)
            {
                if (track.HipsJoint >= 0 && track.Weight > 0f)
                {
                    position = Vector3.Lerp(position, HipsTarget(track, track.Ratio), track.Weight);
                    touched = true;
                }
            }

            if (touched)
            {
                hips.localPosition = position;
            }
        }

        private void ApplyFace(float restWeight, bool rest)
        {
            if (faceRig == null || faceGain <= 0f)
            {
                return;
            }

            if (rest)
            {
                foreach (Track track in _rest)
                {
                    AddFace(track, Ease(track.Mix) * restWeight);
                }
            }

            foreach (Track track in _actions)
            {
                AddFace(track, track.Weight);
            }

            foreach (Track track in _gestures)
            {
                AddFace(track, track.Weight);
            }
        }

        private void AddFace(Track track, float weight)
        {
            if (track.FaceChannels == null || weight <= 0f)
            {
                return;
            }

            float ratio = track.Ratio;
            float gain = faceGain * weight;
            for (int k = 0; k < track.FaceChannels.Length; k++)
            {
                faceRig.Add(track.FaceChannels[k], track.FaceTracks[k].Sample(ratio) * gain);
            }
        }

        // Rotación local del hueso b según el clip: enlace · clip, o en espejo el
        // clip del hueso opuesto reflejado (en el rig de Genies, el valor del OZZ
        // sin pasarlo a Unity).
        private Quaternion Target(Track track, int b, float ratio)
        {
            Quaternion delta = track.Clip.SampleRotation(track.Joints[b], ratio);
            return _bones[b].Bind * (track.Mirror ? delta : GeniesOzzClip.ToUnity(delta));
        }

        private Vector3 HipsTarget(Track track, float ratio)
        {
            Vector3 delta = track.Clip.SampleTranslation(track.HipsJoint, ratio);
            Vector3 local = track.Mirror ? delta : GeniesOzzClip.ToUnity(delta);
            return _hipsBindPosition + local * _hipsScale;
        }

        // ------------------------------------------------------------------
        // Clips
        // ------------------------------------------------------------------

        private Track Start(Channel channel, string gestureName, float fadeSeconds, bool mirror)
        {
            if (!IsReady)
            {
                return null;
            }

            GeniesGestureSet.Gesture gesture = gestureSet.Find(gestureName);
            GeniesOzzClip clip = gesture != null ? ClipOf(gesture) : null;
            if (clip == null)
            {
                return null;
            }

            float fade = FadeOr(fadeSeconds);
            if (channel != Channel.Rest)
            {
                fade = Mathf.Min(fade, clip.Duration * 0.45f);
                StopAll(channel == Channel.Action ? _actions : _gestures, fade);
            }

            Track track = NewTrack(channel, gesture, clip, mirror, fade);
            switch (channel)
            {
                case Channel.Rest:
                    track.Mix = 0f;
                    _rest.Add(track);
                    break;
                case Channel.Action:
                    _actions.Add(track);
                    break;
                default:
                    _gestures.Add(track);
                    break;
            }

            if (logGestures)
            {
                string what = channel == Channel.Rest ? "reposo" : channel == Channel.Action ? "acción" : "gesto";
                Debug.Log("[Sonia] " + what + " de Genies: " + gesture.name + (mirror ? " (espejo)" : string.Empty)
                    + " (" + clip.Duration.ToString("0.0") + " s)", this);
            }

            return track;
        }

        private Track NewTrack(Channel channel, GeniesGestureSet.Gesture gesture, GeniesOzzClip clip, bool mirror, float fade)
        {
            Track track = new Track
            {
                Channel = channel,
                Gesture = gesture,
                Clip = clip,
                Mirror = mirror,
                Fade = fade,
                Joints = new int[_bones.Count]
            };
            bool fullBody = channel != Channel.Gesture;
            for (int b = 0; b < _bones.Count; b++)
            {
                Bone bone = _bones[b];
                track.Joints[b] = fullBody || bone.Torso ? clip.JointIndex(mirror ? Opposite(bone.Name) : bone.Name) : -1;
            }

            if (fullBody)
            {
                track.HipsJoint = clip.JointIndex("Hips");
            }

            BuildFace(track, channel == Channel.Gesture);
            return track;
        }

        private static string Latest(List<Track> tracks)
        {
            for (int i = tracks.Count - 1; i >= 0; i--)
            {
                if (!tracks[i].Stopping)
                {
                    return tracks[i].Gesture.name;
                }
            }

            return null;
        }

        private static void StopAll(List<Track> tracks, float fade)
        {
            foreach (Track track in tracks)
            {
                if (track.Stopping && track.StopSpeed >= 1f / Mathf.Max(fade, 0.01f))
                {
                    continue;
                }

                track.Stopping = true;
                track.StopSpeed = 1f / Mathf.Max(fade, 0.01f);
            }
        }

        private float FadeOr(float fadeSeconds)
        {
            return fadeSeconds >= 0f ? fadeSeconds : (gestureSet != null ? gestureSet.transitionSeconds : 0.8f);
        }

        private static string Opposite(string name)
        {
            if (name.StartsWith("Left", StringComparison.Ordinal))
            {
                return "Right" + name.Substring(4);
            }

            if (name.StartsWith("Right", StringComparison.Ordinal))
            {
                return "Left" + name.Substring(5);
            }

            return name;
        }

        // Curva suave de los fundidos, como MotionPlayer y Genies.
        private static float Ease(float t)
        {
            t = Mathf.Clamp01(t);
            return t * t * (3f - 2f * t);
        }

        private GeniesOzzClip ClipOf(GeniesGestureSet.Gesture gesture)
        {
            GeniesOzzClip clip;
            if (_clips.TryGetValue(gesture.name, out clip))
            {
                return clip;
            }

            try
            {
                clip = gesture.clip != null ? gesture.clip.Decode() : null;
            }
            catch (FormatException e)
            {
                Debug.LogWarning("[Sonia] el gesto " + gesture.name + " no se puede leer: " + e.Message, this);
                clip = null;
            }

            _clips[gesture.name] = clip;
            return clip;
        }

        private void BuildFace(Track track, bool withBlinks)
        {
            if (faceRig == null)
            {
                return;
            }

            List<int> channels = new List<int>();
            List<GeniesOzzClip.FloatTrack> tracks = new List<GeniesOzzClip.FloatTrack>();
            foreach (GeniesOzzClip.FloatTrack floatTrack in track.Clip.FloatTracks)
            {
                if (!floatTrack.Name.StartsWith(FloatTrackPrefix, StringComparison.Ordinal) || !floatTrack.IsAnimated)
                {
                    continue;
                }

                string shape = floatTrack.Name.Substring(FloatTrackPrefix.Length);
                if (!IsFaceShape(shape) || (!withBlinks && shape.StartsWith(BlinkPrefix, StringComparison.Ordinal)))
                {
                    continue;
                }

                // En espejo, la forma izquierda va a la derecha y al revés.
                int channel = faceRig.Channel(track.Mirror ? OppositeShape(shape) : shape);
                if (channel >= 0)
                {
                    channels.Add(channel);
                    tracks.Add(floatTrack);
                }
            }

            track.FaceChannels = channels.ToArray();
            track.FaceTracks = tracks.ToArray();
        }

        private static string OppositeShape(string shape)
        {
            if (shape.EndsWith("_L", StringComparison.Ordinal))
            {
                return shape.Substring(0, shape.Length - 2) + "_R";
            }

            if (shape.EndsWith("_R", StringComparison.Ordinal))
            {
                return shape.Substring(0, shape.Length - 2) + "_L";
            }

            return shape;
        }

        private static bool IsFaceShape(string shape)
        {
            foreach (string prefix in FacePrefixes)
            {
                if (shape.StartsWith(prefix, StringComparison.Ordinal))
                {
                    return true;
                }
            }

            return false;
        }

        // ------------------------------------------------------------------
        // Avatar y pose de enlace
        // ------------------------------------------------------------------

        private void EnsureBound()
        {
            Animator animator = motionPlayer != null ? motionPlayer.Animator : null;
            // Mismo avatar: nada que hacer, salvo que se quedara sin huesos (un avatar
            // recién cargado puede no tener aún sus mallas): se reintenta cada segundo.
            if (animator == _bound && (_bones.Count > 0 || animator == null || UnityEngine.Time.unscaledTime < _nextBindRetry))
            {
                return;
            }

            _nextBindRetry = UnityEngine.Time.unscaledTime + 1f;
            bool retry = animator == _bound;
            _bound = animator;
            _bones.Clear();
            _gestures.Clear();
            _actions.Clear();
            _rest.Clear();
            _hips = -1;
            if (animator == null || !animator.isHuman)
            {
                return;
            }

            Dictionary<string, Transform> byName = new Dictionary<string, Transform>(StringComparer.Ordinal);
            foreach (Transform t in animator.GetComponentsInChildren<Transform>(true))
            {
                if (!byName.ContainsKey(t.name))
                {
                    byName[t.name] = t;
                }
            }

            Dictionary<Transform, Matrix4x4> bind = BindPoses(animator);
            Matrix4x4 toAnimator = animator.transform.worldToLocalMatrix;
            List<string> missing = new List<string>();
            List<string> names = new List<string>(LowerBoneNames);
            names.AddRange(BoneNames);
            foreach (string boneName in names)
            {
                Transform t;
                Matrix4x4 world;
                if (!byName.TryGetValue(boneName, out t) || t.parent == null || !BindOf(t, bind, out world))
                {
                    missing.Add(boneName);
                    continue;
                }

                // La cadera cuelga de Root, que no pesa en la malla y no se anima:
                // su enlace es donde está. El resto de padres sacan el suyo de la malla.
                Matrix4x4 parentWorld;
                if (boneName == "Hips")
                {
                    parentWorld = toAnimator * t.parent.localToWorldMatrix;
                }
                else if (!BindOf(t.parent, bind, out parentWorld))
                {
                    missing.Add(boneName);
                    continue;
                }

                Matrix4x4 local = parentWorld.inverse * world;
                if (boneName == "Hips")
                {
                    _hips = _bones.Count;
                    _hipsBindPosition = local.GetColumn(3);
                    _hipsScale = _hipsBindPosition.y > 0.1f ? _hipsBindPosition.y / ClipHipsHeight : 1f;
                }

                _bones.Add(new Bone
                {
                    Name = boneName,
                    Transform = t,
                    Bind = Normalize(local.rotation),
                    Torso = Array.IndexOf(BoneNames, boneName) >= 0,
                    RightArm = boneName.StartsWith("RightShoulder", StringComparison.Ordinal)
                               || boneName.StartsWith("RightArm", StringComparison.Ordinal)
                               || boneName.StartsWith("RightForeArm", StringComparison.Ordinal)
                               || boneName.StartsWith("RightHand", StringComparison.Ordinal)
                });
            }

            if (missing.Count > 0 && (!retry || _bones.Count > 0))
            {
                Debug.LogWarning("[Sonia] clips de Genies: el avatar " + animator.name + " no tiene la pose de enlace de "
                    + string.Join(", ", missing.ToArray()) + "; esos huesos no se mueven.", this);
            }

            if (_bones.Count > 0 && logGestures)
            {
                Debug.Log("[Sonia] clips de Genies enganchados a " + animator.name + ": " + _bones.Count + " huesos"
                    + (_hips >= 0 ? ", cadera a " + _hipsBindPosition.y.ToString("0.00") + " m" : string.Empty), this);
            }

            if (_prewarm != null)
            {
                StopCoroutine(_prewarm);
            }

            if (isActiveAndEnabled && gestureSet != null)
            {
                _prewarm = StartCoroutine(Prewarm());
            }
        }

        // Decodifica todos los clips poco a poco para que el primero no dé un tirón.
        private IEnumerator Prewarm()
        {
            int perFrame = 6;
            int done = 0;
            foreach (GeniesGestureSet.Gesture gesture in gestureSet.gestures)
            {
                if (gesture == null || gesture.clip == null)
                {
                    continue;
                }

                ClipOf(gesture);
                if (++done % perFrame == 0)
                {
                    yield return null;
                }
            }

            _prewarm = null;
        }

        /// <summary>
        /// Enlace de cada hueso que pesa en alguna malla, en el espacio del Animator
        /// (bindposes de las mallas).
        /// </summary>
        private static Dictionary<Transform, Matrix4x4> BindPoses(Animator animator)
        {
            Dictionary<Transform, Matrix4x4> bind = new Dictionary<Transform, Matrix4x4>();
            Matrix4x4 toAnimator = animator.transform.worldToLocalMatrix;
            foreach (SkinnedMeshRenderer smr in animator.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (smr.sharedMesh == null)
                {
                    continue;
                }

                Transform[] bones = smr.bones;
                Matrix4x4[] poses = smr.sharedMesh.bindposes;
                Matrix4x4 meshToAnimator = toAnimator * smr.transform.localToWorldMatrix;
                for (int i = 0; i < bones.Length && i < poses.Length; i++)
                {
                    if (bones[i] != null && !bind.ContainsKey(bones[i]))
                    {
                        bind[bones[i]] = meshToAnimator * poses[i].inverse;
                    }
                }
            }

            return bind;
        }

        /// <summary>
        /// Enlace de un hueso en el espacio del Animator. Los que no pesan en la
        /// malla (en Genies, casi todos los principales: pesan sus hijos "…Bind",
        /// que cuelgan sin giro) lo sacan del primer descendiente que pesa,
        /// quitando el camino.
        /// </summary>
        private static bool BindOf(Transform bone, Dictionary<Transform, Matrix4x4> bind, out Matrix4x4 world)
        {
            if (bind.TryGetValue(bone, out world))
            {
                return true;
            }

            Queue<Transform> queue = new Queue<Transform>();
            for (int i = 0; i < bone.childCount; i++)
            {
                queue.Enqueue(bone.GetChild(i));
            }

            while (queue.Count > 0)
            {
                Transform t = queue.Dequeue();
                Matrix4x4 m;
                if (bind.TryGetValue(t, out m))
                {
                    Matrix4x4 path = Matrix4x4.identity;
                    for (Transform c = t; c != bone; c = c.parent)
                    {
                        path = Matrix4x4.TRS(c.localPosition, c.localRotation, c.localScale) * path;
                    }

                    world = m * path.inverse;
                    return true;
                }

                for (int i = 0; i < t.childCount; i++)
                {
                    queue.Enqueue(t.GetChild(i));
                }
            }

            world = Matrix4x4.identity;
            return false;
        }

        private static Quaternion Normalize(Quaternion q)
        {
            float n = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            return n > 1e-8f ? new Quaternion(q.x / n, q.y / n, q.z / n, q.w / n) : Quaternion.identity;
        }
    }
}
