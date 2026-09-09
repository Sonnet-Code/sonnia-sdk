// Lip-sync del avatar.
//
// Tres fuentes, por orden de preferencia:
//  1. Fonemas analizados en tiempo real sobre el audio que suena (uLipSync a
//     través de PhonemeLipSyncBridge): vocales A/I/U/E/O y nasal, con
//     proporciones que ya vienen mezcladas, así que la boca pasa de una forma a
//     otra sin saltos. Es lo único que va de verdad al compás de la voz.
//  2. Visemas con timestamp que envía el orquestador, alineados con el tiempo
//     del audio reproducido (AudioStreamPlayer.CurrentUtteranceTime). Hoy son
//     una estimación por texto repartida uniformemente en la duración, así que
//     solo se usan si no hay fonemas (preferRealtimePhonemes apagado o sin
//     analizador).
//  3. Apertura de boca según la envolvente de amplitud de la frase o, si
//     tampoco hay envolvente, según el nivel RMS del audio que suena.
//
// Los pesos se suavizan con ataque rápido y caída más lenta, que es como se
// mueve una boca real, y se acotan para que nunca se abra del todo.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>
    /// Anima los blendshapes de la cara siguiendo los visemas de cada frase.
    /// Todo es opcional: sin SkinnedMeshRenderer o sin blendshapes de visemas el
    /// componente cae al modo de envolvente y no lanza nada.
    /// </summary>
    // Corre después del LateUpdate de Vrm10Instance (orden 11000), que aplica sus
    // expresiones (a cero) y la mirada; así los blendshapes de boca y parpadeo
    // que escribimos aquí prevalecen y los ojos ya tienen la mirada aplicada.
    [DefaultExecutionOrder(12000)]
    [DisallowMultipleComponent]
    public class LipSyncController : MonoBehaviour
    {
        /// <summary>Relación entre un identificador de visema y un blendshape de la malla.</summary>
        [Serializable]
        public class VisemeBinding
        {
            [Tooltip("Identificador del protocolo: sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, ih, oh, ou.")]
            public string viseme = VisemeIds.Sil;

            [Tooltip("Nombre del blendshape en la malla del avatar.")]
            public string blendShape = "viseme_sil";
        }

        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Malla con los blendshapes de la cara (en Ready Player Me suele ser Wolf3D_Head).")]
        private SkinnedMeshRenderer faceRenderer;

        [SerializeField]
        [Tooltip("Reproductor del que se leen la frase y el tiempo actuales.")]
        private AudioStreamPlayer audioPlayer;

        [Header("Visemas")]
        [SerializeField]
        [Tooltip("Mapa visema del protocolo a blendshape. Se rellena con la convención Ready Player Me / Oculus.")]
        private VisemeBinding[] visemeBindings = CreateDefaultBindings();

        [SerializeField]
        [Range(1f, 60f)]
        [Tooltip("Velocidad con la que un visema sube (ataque). Más alto, boca más nerviosa.")]
        private float attackSpeed = 28f;

        [SerializeField]
        [Range(1f, 60f)]
        [Tooltip("Velocidad con la que un visema baja (caída). Más bajo, transiciones más suaves.")]
        private float releaseSpeed = 11f;

        [SerializeField]
        [Tooltip("Desfase en segundos entre el audio y los visemas. Negativo adelanta la boca.")]
        private float timeOffsetSeconds;

        [SerializeField]
        [Range(0f, 100f)]
        [Tooltip("Peso máximo que se aplica a un visema con w = 1. Al 100 la boca se abre del todo y parece un grito.")]
        private float visemeMaxWeight = 75f;

        [Header("Fonemas en tiempo real")]
        [SerializeField]
        [Tooltip("Segundos de validez de un frame de fonemas. Pasado ese tiempo sin noticias se vuelve al respaldo.")]
        private float phonemeFrameTimeout = 0.25f;

        [SerializeField]
        [Tooltip("Con fonemas frescos, usarlos aunque el orquestador haya enviado visemas. Los visemas del orquestador son una estimación por texto repartida uniformemente en la duración del audio y llegan al terminar la síntesis; si tomaran el mando a mitad de frase la boca se desincroniza, sobre todo en la cola.")]
        private bool preferRealtimePhonemes = true;

        [Header("Respaldo por envolvente")]
        [SerializeField]
        [Tooltip("Blendshape de apertura de mandíbula (convención ARKit).")]
        private string jawOpenBlendShape = "jawOpen";

        [SerializeField]
        [Tooltip("Blendshape alternativo de apertura de boca si no existe el anterior.")]
        private string mouthOpenBlendShape = "mouthOpen";

        [SerializeField]
        [Tooltip("Hueso de la mandíbula, por si el avatar no tiene blendshapes de boca.")]
        private Transform jawBone;

        [SerializeField]
        [Tooltip("Eje local del hueso alrededor del que se abre la mandíbula.")]
        private Vector3 jawOpenAxis = new Vector3(1f, 0f, 0f);

        [SerializeField]
        [Tooltip("Grados que baja la mandíbula con la boca del todo abierta.")]
        private float jawBoneMaxAngle = 14f;

        [SerializeField]
        [Range(0f, 4f)]
        [Tooltip("Ganancia aplicada a la envolvente antes de abrir la boca.")]
        private float envelopeGain = 1.2f;

        [SerializeField]
        [Range(0.1f, 1f)]
        [Tooltip("Apertura máxima de la mandíbula en el respaldo por envolvente. Con jawOpen al 100 % parece un grito.")]
        private float maxMouthOpen = 0.6f;

        [SerializeField]
        [Range(0f, 40f)]
        [Tooltip("Ganancia aplicada al RMS cuando no hay ni visemas ni envolvente.")]
        private float rmsGain = 12f;

        private readonly Dictionary<int, List<VisemeFrame>> _visemesByUtterance =
            new Dictionary<int, List<VisemeFrame>>();

        private readonly Dictionary<int, EnvelopeData> _envelopesByUtterance =
            new Dictionary<int, EnvelopeData>();

        private readonly List<int> _cleanupBuffer = new List<int>();

        private int[] _shapeIndices = new int[0];
        private float[] _currentWeights = new float[0];
        private float[] _targetWeights = new float[0];
        private int _jawShapeIndex = -1;
        private int _mouthShapeIndex = -1;
        private bool _hasVisemeShapes;

        // Los FBX y VRM definen los blendshapes de 0 a 100; los GLB de glTFast
        // (Ready Player Me) de 0 a 1. Se escribe siempre en la escala de la malla.
        private float _shapeScale = 1f;
        private float _openCurrent;
        private int _lastUtteranceId = -1;

        // Frame de fonemas en tiempo real: pesos 0..1 por vocal (ya escalados por
        // el volumen) y momento en que llegó.
        private float _phA, _phI, _phU, _phE, _phO, _phN;
        private float _phonemeFrameTime = -999f;
        private bool _usingPhonemes;
        private int _frameCursor;
        private Quaternion _jawInitialRotation = Quaternion.identity;
        private bool _hasJawBone;

        /// <summary>Cierto si la malla tiene blendshapes de visemas utilizables.</summary>
        public bool HasVisemeShapes
        {
            get { return _hasVisemeShapes; }
        }

        /// <summary>Apertura actual de la boca, 0..1, sea cual sea la fuente. Sirve para acompasar gestos a la voz.</summary>
        public float MouthOpen
        {
            get
            {
                float best = _openCurrent;
                for (int i = 0; i < _currentWeights.Length; i++)
                {
                    if (_shapeIndices[i] >= 0 && _currentWeights[i] > best * 100f)
                    {
                        best = _currentWeights[i] / 100f;
                    }
                }

                return Mathf.Clamp01(best);
            }
        }

        /// <summary>Cierto mientras la boca se mueve por los fonemas analizados en tiempo real.</summary>
        public bool UsingPhonemes
        {
            get { return _usingPhonemes; }
        }

        /// <summary>
        /// Recibe un frame de fonemas en tiempo real (PhonemeLipSyncBridge). Cada
        /// valor es la fuerza 0..1 de esa vocal ya escalada por el volumen; la
        /// nasal (n) cierra casi la boca.
        /// </summary>
        public void SetPhonemeFrame(float a, float i, float u, float e, float o, float n)
        {
            _phA = Mathf.Clamp01(a);
            _phI = Mathf.Clamp01(i);
            _phU = Mathf.Clamp01(u);
            _phE = Mathf.Clamp01(e);
            _phO = Mathf.Clamp01(o);
            _phN = Mathf.Clamp01(n);
            _phonemeFrameTime = Time.time;
        }

        /// <summary>Olvida el último frame de fonemas (por ejemplo al desactivar el analizador).</summary>
        public void ClearPhonemeFrame()
        {
            _phonemeFrameTime = -999f;
        }

        /// <summary>Malla de la cara. Al cambiarla se vuelven a resolver los blendshapes.</summary>
        public SkinnedMeshRenderer FaceRenderer
        {
            get { return faceRenderer; }
            set
            {
                faceRenderer = value;
                RebindBlendShapes();
            }
        }

        private void Awake()
        {
            if (audioPlayer == null)
            {
                audioPlayer = GetComponentInParent<AudioStreamPlayer>();
            }

            if (jawBone != null)
            {
                _jawInitialRotation = jawBone.localRotation;
                _hasJawBone = true;
            }

            RebindBlendShapes();
        }

        /// <summary>Mapa por defecto: identificadores del protocolo a nombres Ready Player Me / Oculus.</summary>
        public static VisemeBinding[] CreateDefaultBindings()
        {
            return new[]
            {
                new VisemeBinding { viseme = VisemeIds.Sil, blendShape = "viseme_sil" },
                new VisemeBinding { viseme = VisemeIds.PP, blendShape = "viseme_PP" },
                new VisemeBinding { viseme = VisemeIds.FF, blendShape = "viseme_FF" },
                new VisemeBinding { viseme = VisemeIds.TH, blendShape = "viseme_TH" },
                new VisemeBinding { viseme = VisemeIds.DD, blendShape = "viseme_DD" },
                new VisemeBinding { viseme = VisemeIds.KK, blendShape = "viseme_kk" },
                new VisemeBinding { viseme = VisemeIds.CH, blendShape = "viseme_CH" },
                new VisemeBinding { viseme = VisemeIds.SS, blendShape = "viseme_SS" },
                new VisemeBinding { viseme = VisemeIds.NN, blendShape = "viseme_nn" },
                new VisemeBinding { viseme = VisemeIds.RR, blendShape = "viseme_RR" },
                new VisemeBinding { viseme = VisemeIds.AA, blendShape = "viseme_aa" },
                new VisemeBinding { viseme = VisemeIds.E, blendShape = "viseme_E" },
                new VisemeBinding { viseme = VisemeIds.IH, blendShape = "viseme_I" },
                new VisemeBinding { viseme = VisemeIds.OH, blendShape = "viseme_O" },
                new VisemeBinding { viseme = VisemeIds.OU, blendShape = "viseme_U" }
            };
        }

        /// <summary>
        /// Busca en la malla el índice de cada blendshape del mapa. Se puede llamar
        /// a mano si el avatar se asigna en tiempo de ejecución.
        /// </summary>
        public void RebindBlendShapes()
        {
            if (visemeBindings == null || visemeBindings.Length == 0)
            {
                visemeBindings = CreateDefaultBindings();
            }

            int count = visemeBindings.Length;
            _shapeIndices = new int[count];
            _currentWeights = new float[count];
            _targetWeights = new float[count];
            _hasVisemeShapes = false;
            _jawShapeIndex = -1;
            _mouthShapeIndex = -1;

            Mesh mesh = faceRenderer != null ? faceRenderer.sharedMesh : null;
            if (mesh == null)
            {
                for (int i = 0; i < count; i++)
                {
                    _shapeIndices[i] = -1;
                }

                return;
            }

            for (int i = 0; i < count; i++)
            {
                VisemeBinding binding = visemeBindings[i];
                int index = binding == null ? -1 : FindBlendShape(mesh, binding.blendShape);
                _shapeIndices[i] = index;
                if (index >= 0)
                {
                    _hasVisemeShapes = true;
                }
            }

            _jawShapeIndex = FindBlendShape(mesh, jawOpenBlendShape);
            if (_jawShapeIndex < 0)
            {
                _mouthShapeIndex = FindBlendShape(mesh, mouthOpenBlendShape);
            }

            _shapeScale = BlendShapeScale(mesh);
        }

        /// <summary>
        /// Factor que convierte un peso de 0..100 a la escala real de la malla:
        /// 1 para FBX/VRM (frames a 100) y 0,01 para GLB de glTFast (frames a 1).
        /// </summary>
        public static float BlendShapeScale(Mesh mesh)
        {
            if (mesh == null || mesh.blendShapeCount == 0)
            {
                return 1f;
            }

            int frames = mesh.GetBlendShapeFrameCount(0);
            float full = frames > 0 ? mesh.GetBlendShapeFrameWeight(0, frames - 1) : 100f;
            return full > 0.0001f ? full / 100f : 1f;
        }

        /// <summary>
        /// Busca un blendshape por nombre. Acepta diferencias de mayúsculas y el
        /// prefijo con punto que añaden algunos importadores ("Head.viseme_aa").
        /// </summary>
        private static int FindBlendShape(Mesh mesh, string name)
        {
            if (mesh == null || string.IsNullOrEmpty(name))
            {
                return -1;
            }

            int direct = mesh.GetBlendShapeIndex(name);
            if (direct >= 0)
            {
                return direct;
            }

            int total = mesh.blendShapeCount;
            for (int i = 0; i < total; i++)
            {
                string candidate = mesh.GetBlendShapeName(i);
                if (string.IsNullOrEmpty(candidate))
                {
                    continue;
                }

                if (string.Equals(candidate, name, StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }

                int dot = candidate.LastIndexOf('.');
                if (dot >= 0 && dot + 1 < candidate.Length)
                {
                    string suffix = candidate.Substring(dot + 1);
                    if (string.Equals(suffix, name, StringComparison.OrdinalIgnoreCase))
                    {
                        return i;
                    }
                }
            }

            return -1;
        }

        // ------------------------------------------------------------------
        // Datos que llegan por el protocolo
        // ------------------------------------------------------------------

        /// <summary>Guarda los visemas de una frase.</summary>
        public void SetVisemes(VisemesMessage message)
        {
            if (message == null || message.Frames == null)
            {
                return;
            }

            List<VisemeFrame> frames = new List<VisemeFrame>(message.Frames.Count);
            for (int i = 0; i < message.Frames.Count; i++)
            {
                VisemeFrame frame = message.Frames[i];
                if (frame != null)
                {
                    frames.Add(frame);
                }
            }

            frames.Sort(CompareByTime);
            _visemesByUtterance[message.UtteranceId] = frames;
            if (message.UtteranceId == _lastUtteranceId)
            {
                _frameCursor = 0;
            }
        }

        /// <summary>Guarda la envolvente de amplitud de una frase.</summary>
        public void SetEnvelope(EnvelopeMessage message)
        {
            if (message == null || message.Values == null || message.Values.Count == 0)
            {
                return;
            }

            EnvelopeData data = new EnvelopeData
            {
                IntervalSeconds = Mathf.Max(0.001f, message.IntervalMs / 1000f),
                Values = message.Values.ToArray()
            };
            _envelopesByUtterance[message.UtteranceId] = data;
        }

        /// <summary>Suelta los datos de una frase que ya terminó de reproducirse.</summary>
        public void NotifyUtteranceFinished(int utteranceId)
        {
            _visemesByUtterance.Remove(utteranceId);
            _envelopesByUtterance.Remove(utteranceId);
        }

        /// <summary>
        /// Estado interno en texto, para depurar el lip-sync desde el editor o el HUD
        /// sin necesidad de reflexión.
        /// </summary>
        public string DebugInfo()
        {
            int utteranceId = -1;
            float time = 0f;
            float rms = 0f;
            if (audioPlayer != null)
            {
                audioPlayer.GetPlaybackPosition(out utteranceId, out time, out rms);
            }

            System.Text.StringBuilder sb = new System.Text.StringBuilder();
            sb.Append("hasVisemeShapes=").Append(_hasVisemeShapes)
              .Append(" face=").Append(faceRenderer != null ? faceRenderer.name : "null")
              .Append(" player=").Append(audioPlayer != null)
              .Append(" utt=").Append(utteranceId).Append(" t=").Append(time.ToString("F2"))
              .Append(" lastUtt=").Append(_lastUtteranceId).Append(" cursor=").Append(_frameCursor)
              .Append(" visemasGuardados=[");
            foreach (KeyValuePair<int, List<VisemeFrame>> pair in _visemesByUtterance)
            {
                sb.Append(pair.Key).Append(':').Append(pair.Value.Count).Append(' ');
            }

            sb.Append("] envolventes=").Append(_envelopesByUtterance.Count).Append(" slots=[");
            if (_shapeIndices != null)
            {
                for (int i = 0; i < _shapeIndices.Length; i++)
                {
                    string viseme = visemeBindings != null && i < visemeBindings.Length && visemeBindings[i] != null
                        ? visemeBindings[i].viseme
                        : "?";
                    sb.Append(viseme).Append('=').Append(_shapeIndices[i]).Append(' ');
                }
            }

            sb.Append("] target=[");
            if (_targetWeights != null)
            {
                for (int i = 0; i < _targetWeights.Length; i++)
                {
                    sb.Append(_targetWeights[i].ToString("F0")).Append(' ');
                }
            }

            sb.Append("] open=").Append(_openCurrent.ToString("F2")).Append(" fonemas=").Append(_usingPhonemes);
            List<VisemeFrame> frames;
            if (utteranceId >= 0 && _visemesByUtterance.TryGetValue(utteranceId, out frames) && frames.Count > 0)
            {
                int active = FindActiveFrame(frames, time + timeOffsetSeconds);
                sb.Append(" activo=").Append(active);
                if (active >= 0)
                {
                    sb.Append(" v=").Append(frames[active].V).Append(" slot=").Append(FindBindingSlot(frames[active].V));
                }
            }

            return sb.ToString();
        }

        /// <summary>Interrupción: se olvida todo y se cierra la boca de golpe.</summary>
        public void StopAndClose()
        {
            _visemesByUtterance.Clear();
            _envelopesByUtterance.Clear();
            _lastUtteranceId = -1;
            _frameCursor = 0;
            _openCurrent = 0f;

            for (int i = 0; i < _currentWeights.Length; i++)
            {
                _currentWeights[i] = 0f;
                _targetWeights[i] = 0f;
            }

            ApplyWeights();
            ApplyMouthOpen(0f);
        }

        // ------------------------------------------------------------------
        // Animación
        // ------------------------------------------------------------------

        private void LateUpdate()
        {
            int utteranceId = -1;
            float time = 0f;
            float rms = 0f;
            if (audioPlayer != null)
            {
                audioPlayer.GetPlaybackPosition(out utteranceId, out time, out rms);
            }

            time += timeOffsetSeconds;

            if (utteranceId != _lastUtteranceId)
            {
                _lastUtteranceId = utteranceId;
                _frameCursor = 0;
                DiscardOlderThan(utteranceId);
            }

            for (int i = 0; i < _targetWeights.Length; i++)
            {
                _targetWeights[i] = 0f;
            }

            float openTarget = 0f;
            bool usedVisemes = false;
            bool phonemesFresh = Time.time - _phonemeFrameTime <= Mathf.Max(0.05f, phonemeFrameTimeout);
            bool phonemesFirst = preferRealtimePhonemes && phonemesFresh;

            if (_hasVisemeShapes && utteranceId >= 0 && !phonemesFirst)
            {
                List<VisemeFrame> frames;
                if (_visemesByUtterance.TryGetValue(utteranceId, out frames) && frames.Count > 0)
                {
                    int active = FindActiveFrame(frames, time);
                    if (active >= 0)
                    {
                        int slot = FindBindingSlot(frames[active].V);
                        if (slot >= 0 && slot < _targetWeights.Length)
                        {
                            _targetWeights[slot] = Mathf.Clamp01(frames[active].W) * visemeMaxWeight;
                        }

                        usedVisemes = true;
                    }
                }
            }

            _usingPhonemes = false;
            if (!usedVisemes && _hasVisemeShapes && utteranceId >= 0 && phonemesFresh)
            {
                AddPhonemeTarget(VisemeIds.AA, _phA);
                AddPhonemeTarget(VisemeIds.IH, _phI);
                AddPhonemeTarget(VisemeIds.OU, _phU);
                AddPhonemeTarget(VisemeIds.E, _phE);
                AddPhonemeTarget(VisemeIds.OH, _phO);
                AddPhonemeTarget(VisemeIds.NN, _phN);
                usedVisemes = true;
                _usingPhonemes = true;
            }

            if (!usedVisemes && utteranceId >= 0)
            {
                openTarget = ComputeFallbackOpen(utteranceId, time, rms);
            }

            float attack = 1f - Mathf.Exp(-Mathf.Max(0.01f, attackSpeed) * Time.deltaTime);
            float release = 1f - Mathf.Exp(-Mathf.Max(0.01f, releaseSpeed) * Time.deltaTime);
            for (int i = 0; i < _currentWeights.Length; i++)
            {
                float target = _targetWeights[i];
                float step = target > _currentWeights[i] ? attack : release;
                _currentWeights[i] = Mathf.Lerp(_currentWeights[i], target, step);
            }

            _openCurrent = Mathf.Lerp(_openCurrent, openTarget, openTarget > _openCurrent ? attack : release);

            // El blendshape de "boca abierta" del respaldo puede ser el mismo que
            // el de un visema (por ejemplo "Aa"). Con visemas activos, el respaldo
            // se escribe primero (a cero) y los visemas después, para que nunca
            // pisen la vocal que toca. Sin visemas, el orden es el contrario.
            if (usedVisemes)
            {
                ApplyMouthOpen(_openCurrent);
                ApplyWeights();
            }
            else
            {
                ApplyWeights();
                ApplyMouthOpen(_openCurrent);
            }
        }

        /// <summary>Suma el peso de una vocal al visema que le corresponde.</summary>
        private void AddPhonemeTarget(string viseme, float weight01)
        {
            if (weight01 <= 0f)
            {
                return;
            }

            int slot = FindBindingSlot(viseme);
            if (slot >= 0 && slot < _targetWeights.Length)
            {
                _targetWeights[slot] = Mathf.Min(visemeMaxWeight, _targetWeights[slot] + weight01 * visemeMaxWeight);
            }
        }

        private float ComputeFallbackOpen(int utteranceId, float time, float rms)
        {
            EnvelopeData envelope;
            if (_envelopesByUtterance.TryGetValue(utteranceId, out envelope)
                && envelope.Values != null
                && envelope.Values.Length > 0)
            {
                int index = Mathf.FloorToInt(time / envelope.IntervalSeconds);
                if (index < 0)
                {
                    index = 0;
                }
                else if (index >= envelope.Values.Length)
                {
                    index = envelope.Values.Length - 1;
                }

                return Mathf.Clamp01(envelope.Values[index] * envelopeGain);
            }

            return Mathf.Clamp01(rms * rmsGain);
        }

        /// <summary>
        /// Índice del visema activo en el instante dado. Avanza con un cursor
        /// incremental porque el tiempo casi siempre crece frame a frame.
        /// </summary>
        private int FindActiveFrame(List<VisemeFrame> frames, float time)
        {
            if (frames.Count == 0 || time < frames[0].T)
            {
                return -1;
            }

            int cursor = _frameCursor;
            if (cursor < 0 || cursor >= frames.Count)
            {
                cursor = 0;
            }

            if (frames[cursor].T > time)
            {
                cursor = 0;
            }

            while (cursor + 1 < frames.Count && frames[cursor + 1].T <= time)
            {
                cursor++;
            }

            _frameCursor = cursor;
            return cursor;
        }

        private int FindBindingSlot(string viseme)
        {
            if (string.IsNullOrEmpty(viseme) || visemeBindings == null)
            {
                return -1;
            }

            int usable = Mathf.Min(visemeBindings.Length, _shapeIndices.Length);
            for (int i = 0; i < usable; i++)
            {
                VisemeBinding binding = visemeBindings[i];
                if (binding == null || _shapeIndices[i] < 0)
                {
                    continue;
                }

                if (string.Equals(binding.viseme, viseme, StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }
            }

            return -1;
        }

        private void ApplyWeights()
        {
            if (faceRenderer == null)
            {
                return;
            }

            for (int i = 0; i < _currentWeights.Length; i++)
            {
                int index = _shapeIndices[i];
                if (index >= 0)
                {
                    faceRenderer.SetBlendShapeWeight(index, _currentWeights[i] * _shapeScale);
                }
            }
        }

        private void ApplyMouthOpen(float amount)
        {
            float clamped = Mathf.Clamp01(amount) * Mathf.Clamp(maxMouthOpen, 0.1f, 1f);

            if (faceRenderer != null)
            {
                if (_jawShapeIndex >= 0)
                {
                    faceRenderer.SetBlendShapeWeight(_jawShapeIndex, clamped * 100f * _shapeScale);
                }
                else if (_mouthShapeIndex >= 0)
                {
                    faceRenderer.SetBlendShapeWeight(_mouthShapeIndex, clamped * 100f * _shapeScale);
                }
            }

            if (_hasJawBone && jawBone != null && _jawShapeIndex < 0 && _mouthShapeIndex < 0)
            {
                Vector3 axis = jawOpenAxis.sqrMagnitude > 0.0001f ? jawOpenAxis.normalized : Vector3.right;
                jawBone.localRotation = _jawInitialRotation * Quaternion.AngleAxis(clamped * jawBoneMaxAngle, axis);
            }
        }

        /// <summary>Suelta los datos de frases anteriores a la que suena ahora.</summary>
        private void DiscardOlderThan(int utteranceId)
        {
            if (utteranceId < 0)
            {
                return;
            }

            _cleanupBuffer.Clear();
            foreach (KeyValuePair<int, List<VisemeFrame>> entry in _visemesByUtterance)
            {
                if (entry.Key < utteranceId)
                {
                    _cleanupBuffer.Add(entry.Key);
                }
            }

            for (int i = 0; i < _cleanupBuffer.Count; i++)
            {
                _visemesByUtterance.Remove(_cleanupBuffer[i]);
            }

            _cleanupBuffer.Clear();
            foreach (KeyValuePair<int, EnvelopeData> entry in _envelopesByUtterance)
            {
                if (entry.Key < utteranceId)
                {
                    _cleanupBuffer.Add(entry.Key);
                }
            }

            for (int i = 0; i < _cleanupBuffer.Count; i++)
            {
                _envelopesByUtterance.Remove(_cleanupBuffer[i]);
            }
        }

        private static int CompareByTime(VisemeFrame a, VisemeFrame b)
        {
            return a.T.CompareTo(b.T);
        }

        private sealed class EnvelopeData
        {
            public float IntervalSeconds;
            public float[] Values;
        }
    }
}
