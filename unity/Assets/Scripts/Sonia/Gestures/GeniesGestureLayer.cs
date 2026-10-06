// Capa de gestos de Genies sobre el torso: reproduce los clips OZZ de un
// personaje del chat de Genies (GeniesGestureSet, de momento Sage) en el
// esqueleto vivo del avatar, igual que el motor de Genies.
//
// Los OZZ guardan cada hueso como diferencia con la pose de enlace del cuerpo.
// Genies los aplica a cualquier cuerpo con local = enlace · clip (comprobado
// contra su motor a 0,65°, gestos-genies/README.md); aquí se hace lo mismo con
// la pose de enlace de este avatar, que sale de las bindposes de sus mallas.
// No hay clips de Unity de por medio: ni retarget humanoide ni .anim en el repo.
//
// Solo mueve el torso: columna, cuello, cabeza, hombros, brazos, manos y dedos.
// La cadera y las piernas siguen con lo que toque MotionPlayer (reposo, IK de
// pies), como su capa de torso. Cada gesto entra y sale con el fundido del
// personaje (TransitionToClip_Duration de su demeanor, 0,8 s en Sage) con curva
// suave, y si llega otro gesto el anterior se funde hacia fuera a la vez.
//
// Además pasa a FaceRig las curvas de cara FACS que trae cada gesto (párpados,
// cejas, mejillas y comisuras), las mismas que reproduce Genies. Las de la boca
// y la mandíbula son del lip-sync y las de mirar (EYES_LOOK_*) de los ojos, así
// que esas no.
//
// Corre en LateUpdate después del Animator y antes que todo lo demás: las
// físicas del pelo de Genies (orden 0) colocan el pelo sobre la cabeza ya
// movida, y la cabeza que sigue al visitante, la mirada y la cara
// (AvatarStateController, EyeGazeController, FaceRig) suman encima.
//
// Qué gesto y cuándo lo decide el director de gestos del orquestador (mensaje
// gesture, docs/gestos.md); el coreógrafo y SoniaBootstrap deciden si se puede.

using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Reproduce los gestos OZZ de Genies sobre el torso del avatar.</summary>
    [DefaultExecutionOrder(-20)]
    [DisallowMultipleComponent]
    public sealed class GeniesGestureLayer : MonoBehaviour
    {
        /// <summary>Huesos que mueve la capa (nombres del esqueleto de Genies).</summary>
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

        /// <summary>Formas FACS de los gestos que se pasan a la cara (por prefijo).</summary>
        private static readonly string[] FacePrefixes =
        {
            "EYES_CLOSED", "UPPER_LID_RAISER", "LID_TIGHTENER",
            "BROW_LOWERER", "INNER_BROW_RAISER", "OUTER_BROW_RAISER",
            "CHEEK_RAISER", "NOSE_WRINKLER", "DIMPLER",
            "LIP_CORNER_PULLER", "LIP_CORNER_DEPRESSOR"
        };

        private const string FloatTrackPrefix = "Root-";

        [SerializeField]
        [Tooltip("Gestos del personaje (Sonia > Gestos de Genies > Crear set de Sage).")]
        private GeniesGestureSet gestureSet;

        [SerializeField]
        [Tooltip("De aquí sale el Animator del avatar enganchado. Si está vacío se busca en este objeto.")]
        private MotionPlayer motionPlayer;

        [SerializeField]
        [Tooltip("Cara del avatar para las curvas FACS de los gestos. Si está vacío se busca en este objeto.")]
        private FaceRig faceRig;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Cuánto manda el gesto sobre el torso (1: como en Genies).")]
        private float bodyWeight = 1f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Ganancia de las curvas de cara de los gestos (1: como en Genies; 0: sin cara).")]
        private float faceGain = 1f;

        [SerializeField]
        [Tooltip("Escribe en la consola cada gesto que empieza.")]
        private bool logGestures = true;

        private sealed class Bone
        {
            public Transform Transform;
            public Quaternion Bind;
        }

        private sealed class Instance
        {
            public GeniesGestureSet.Gesture Gesture;
            public GeniesOzzClip Clip;
            public int[] Joints;
            public int[] FaceChannels;
            public GeniesOzzClip.FloatTrack[] FaceTracks;
            public float Time;
            public float Fade;
            public bool Stopping;
            public float StopLeft = 1f;
            public float StopSpeed;
            public float Weight;
        }

        private readonly List<Bone> _bones = new List<Bone>();
        private readonly List<Instance> _active = new List<Instance>();
        private readonly Dictionary<string, GeniesOzzClip> _clips = new Dictionary<string, GeniesOzzClip>(StringComparer.Ordinal);
        private Animator _bound;
        private Coroutine _prewarm;

        /// <summary>Se lanza al empezar un gesto (nombre).</summary>
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

        /// <summary>Cierto mientras suena algún gesto (aunque se esté fundiendo hacia fuera).</summary>
        public bool IsActive
        {
            get { return _active.Count > 0; }
        }

        /// <summary>Gesto que manda ahora (el último lanzado y no parado), o null.</summary>
        public string Current
        {
            get
            {
                for (int i = _active.Count - 1; i >= 0; i--)
                {
                    if (!_active[i].Stopping)
                    {
                        return _active[i].Gesture.name;
                    }
                }

                return null;
            }
        }

        /// <summary>Cierto si el set tiene ese gesto.</summary>
        public bool Has(string gestureName)
        {
            return gestureSet != null && gestureSet.Find(gestureName) != null;
        }

        /// <summary>
        /// Lanza un gesto. Los que estuvieran sonando se funden hacia fuera a la
        /// vez que entra este. Devuelve falso si no existe, no hay avatar o el
        /// clip no se puede leer.
        /// </summary>
        public bool Play(string gestureName, float fadeSeconds = -1f)
        {
            if (!IsReady)
            {
                return false;
            }

            GeniesGestureSet.Gesture gesture = gestureSet.Find(gestureName);
            if (gesture == null)
            {
                return false;
            }

            GeniesOzzClip clip = ClipOf(gesture);
            if (clip == null)
            {
                return false;
            }

            float fade = fadeSeconds >= 0f ? fadeSeconds : gestureSet.transitionSeconds;
            fade = Mathf.Min(fade, clip.Duration * 0.45f);
            foreach (Instance running in _active)
            {
                BeginStop(running, fade);
            }

            Instance instance = new Instance
            {
                Gesture = gesture,
                Clip = clip,
                Fade = fade,
                Joints = new int[_bones.Count]
            };
            for (int i = 0; i < _bones.Count; i++)
            {
                instance.Joints[i] = _bones[i] != null ? clip.JointIndex(_bones[i].Transform.name) : -1;
            }

            BuildFace(instance);
            _active.Add(instance);
            if (logGestures)
            {
                Debug.Log("[Sonia] gesto de Genies: " + gesture.name + " (" + clip.Duration.ToString("0.0") + " s)", this);
            }

            Action<string> started = GestureStarted;
            if (started != null)
            {
                started(gesture.name);
            }

            return true;
        }

        /// <summary>Funde hacia fuera todo lo que suene (por defecto con el fundido del personaje).</summary>
        public void Stop(float fadeSeconds = -1f)
        {
            float fade = fadeSeconds >= 0f ? fadeSeconds : (gestureSet != null ? gestureSet.transitionSeconds : 0.8f);
            foreach (Instance running in _active)
            {
                BeginStop(running, fade);
            }
        }

        /// <summary>Corta todo sin fundido.</summary>
        public void StopNow()
        {
            _active.Clear();
        }

        /// <summary>
        /// Pone el torso en la pose del gesto en un instante (a peso 1), sin
        /// reproducirlo. Lo usan las comprobaciones del editor (hojas de
        /// contactos); el siguiente fotograma el Animator vuelve a mandar.
        /// </summary>
        public bool ApplyPose(string gestureName, float seconds)
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

            float ratio = clip.RatioAt(seconds);
            foreach (Bone bone in _bones)
            {
                int joint = clip.JointIndex(bone.Transform.name);
                if (joint >= 0)
                {
                    bone.Transform.localRotation = bone.Bind * GeniesOzzClip.ToUnity(clip.SampleRotation(joint, ratio));
                }
            }

            return true;
        }

        /// <summary>Duración del gesto en segundos (0 si no existe o no se puede leer).</summary>
        public float DurationOf(string gestureName)
        {
            GeniesGestureSet.Gesture gesture = gestureSet != null ? gestureSet.Find(gestureName) : null;
            GeniesOzzClip clip = gesture != null ? ClipOf(gesture) : null;
            return clip != null ? clip.Duration : 0f;
        }

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
            if (_active.Count == 0)
            {
                return;
            }

            float dt = UnityEngine.Time.deltaTime;
            for (int i = _active.Count - 1; i >= 0; i--)
            {
                Instance instance = _active[i];
                instance.Time += dt;
                if (instance.Stopping)
                {
                    instance.StopLeft = Mathf.Max(0f, instance.StopLeft - dt * instance.StopSpeed);
                }

                float duration = instance.Clip.Duration;
                if (instance.Time >= duration || (instance.Stopping && instance.StopLeft <= 0f) || _bones.Count == 0)
                {
                    _active.RemoveAt(i);
                    continue;
                }

                float fadeIn = instance.Fade > 0f ? Ease(instance.Time / instance.Fade) : 1f;
                float fadeOut = instance.Fade > 0f ? Ease((duration - instance.Time) / instance.Fade) : 1f;
                instance.Weight = Mathf.Min(fadeIn, Mathf.Min(fadeOut, Ease(instance.StopLeft)));
            }

            if (_active.Count == 0)
            {
                return;
            }

            for (int b = 0; b < _bones.Count; b++)
            {
                Bone bone = _bones[b];
                Quaternion rotation = bone.Transform.localRotation;
                bool touched = false;
                for (int i = 0; i < _active.Count; i++)
                {
                    Instance instance = _active[i];
                    int joint = instance.Joints[b];
                    float weight = instance.Weight * bodyWeight;
                    if (joint < 0 || weight <= 0f)
                    {
                        continue;
                    }

                    float ratio = instance.Clip.RatioAt(instance.Time);
                    Quaternion target = bone.Bind * GeniesOzzClip.ToUnity(instance.Clip.SampleRotation(joint, ratio));
                    rotation = Quaternion.Slerp(rotation, target, weight);
                    touched = true;
                }

                if (touched)
                {
                    bone.Transform.localRotation = rotation;
                }
            }

            if (faceRig != null && faceGain > 0f)
            {
                for (int i = 0; i < _active.Count; i++)
                {
                    Instance instance = _active[i];
                    if (instance.FaceChannels == null)
                    {
                        continue;
                    }

                    float ratio = instance.Clip.RatioAt(instance.Time);
                    float gain = faceGain * instance.Weight;
                    for (int k = 0; k < instance.FaceChannels.Length; k++)
                    {
                        faceRig.Add(instance.FaceChannels[k], instance.FaceTracks[k].Sample(ratio) * gain);
                    }
                }
            }
        }

        private static void BeginStop(Instance instance, float fade)
        {
            if (instance.Stopping && instance.StopSpeed >= 1f / Mathf.Max(fade, 0.01f))
            {
                return;
            }

            instance.Stopping = true;
            instance.StopSpeed = 1f / Mathf.Max(fade, 0.01f);
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

        private void BuildFace(Instance instance)
        {
            if (faceRig == null)
            {
                return;
            }

            List<int> channels = new List<int>();
            List<GeniesOzzClip.FloatTrack> tracks = new List<GeniesOzzClip.FloatTrack>();
            foreach (GeniesOzzClip.FloatTrack track in instance.Clip.FloatTracks)
            {
                if (!track.Name.StartsWith(FloatTrackPrefix, StringComparison.Ordinal) || !track.IsAnimated)
                {
                    continue;
                }

                string shape = track.Name.Substring(FloatTrackPrefix.Length);
                if (!IsFaceShape(shape))
                {
                    continue;
                }

                int channel = faceRig.Channel(shape);
                if (channel >= 0)
                {
                    channels.Add(channel);
                    tracks.Add(track);
                }
            }

            instance.FaceChannels = channels.ToArray();
            instance.FaceTracks = tracks.ToArray();
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
            if (animator == _bound)
            {
                return;
            }

            _bound = animator;
            _bones.Clear();
            _active.Clear();
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
            List<string> missing = new List<string>();
            foreach (string boneName in BoneNames)
            {
                Transform t;
                Quaternion world;
                Quaternion parentWorld;
                if (!byName.TryGetValue(boneName, out t) || t.parent == null
                    || !BindOf(t, bind, out world) || !BindOf(t.parent, bind, out parentWorld))
                {
                    missing.Add(boneName);
                    continue;
                }

                _bones.Add(new Bone { Transform = t, Bind = Normalize(Quaternion.Inverse(parentWorld) * world) });
            }

            if (missing.Count > 0)
            {
                Debug.LogWarning("[Sonia] gestos de Genies: el avatar " + animator.name + " no tiene la pose de enlace de "
                    + string.Join(", ", missing.ToArray()) + "; esos huesos no se mueven.", this);
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

        // Decodifica todos los clips poco a poco para que el primer gesto no dé un tirón.
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
        /// Rotación de enlace de un hueso. Los que no pesan en la malla (en Genies,
        /// casi todos los principales: pesan sus hijos "…Bind", que cuelgan sin
        /// giro) la sacan del primer descendiente que pesa, quitando el camino.
        /// </summary>
        private static bool BindOf(Transform bone, Dictionary<Transform, Matrix4x4> bind, out Quaternion rotation)
        {
            Matrix4x4 m;
            if (bind.TryGetValue(bone, out m))
            {
                rotation = m.rotation;
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
                if (bind.TryGetValue(t, out m))
                {
                    Matrix4x4 path = Matrix4x4.identity;
                    for (Transform c = t; c != bone; c = c.parent)
                    {
                        path = Matrix4x4.TRS(c.localPosition, c.localRotation, c.localScale) * path;
                    }

                    rotation = (m * path.inverse).rotation;
                    return true;
                }

                for (int i = 0; i < t.childCount; i++)
                {
                    queue.Enqueue(t.GetChild(i));
                }
            }

            rotation = Quaternion.identity;
            return false;
        }

        private static Quaternion Normalize(Quaternion q)
        {
            float n = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            return n > 1e-8f ? new Quaternion(q.x / n, q.y / n, q.z / n, q.w / n) : Quaternion.identity;
        }
    }
}
