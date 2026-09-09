// Expresiones faciales: cejas, párpados, sonrisa y mejillas.
//
// Una cara que solo mueve la boca parece un muñeco. Aquí se añaden, sobre los
// blendshapes ARKit del avatar (Ready Player Me los trae todos), los gestos
// pequeños que hace una persona sin darse cuenta:
//
//  - Cejas que suben con la energía de la voz (sílabas fuertes, énfasis) y un
//    "levantamiento" breve al empezar a hablar o al escuchar algo.
//  - Ceño leve al pensar, con los ojos entornados.
//  - Sonrisa de base distinta por estado (escuchar > reposo > hablar > pensar)
//    con las mejillas acompañando.
//  - Párpados: entornar un poco al sonreír y al hablar fuerte, abrir más en un
//    énfasis o al empezar a escuchar.
//  - Vaivén lento (ruido Perlin) en cejas y párpados para que nunca estén
//    clavados.
//
// Escribe solo blendshapes que no tocan ni el lip-sync (visemas, jawOpen) ni
// el parpadeo (eyeBlink*), así que no se pisan. Sin blendshapes ARKit (VRM
// antiguos) no hace nada.

using UnityEngine;

namespace Sonia
{
    /// <summary>Cejas, párpados, sonrisa y mejillas según el estado y la voz.</summary>
    [DefaultExecutionOrder(12050)]
    [DisallowMultipleComponent]
    public class FacialExpressionController : MonoBehaviour
    {
        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Malla con los blendshapes ARKit de la cara.")]
        private SkinnedMeshRenderer faceRenderer;

        [SerializeField]
        [Tooltip("Estado del avatar (para saber si escucha, piensa o habla).")]
        private AvatarStateController stateController;

        [SerializeField]
        [Tooltip("Lip-sync, para leer la apertura de boca y acompasar cejas y párpados a la voz.")]
        private LipSyncController lipSync;

        [Header("Sonrisa de base (0..1)")]
        [SerializeField, Range(0f, 1f)] public float smileIdle = 0.22f;
        [SerializeField, Range(0f, 1f)] public float smileListening = 0.30f;
        [SerializeField, Range(0f, 1f)] public float smileThinking = 0.08f;
        [SerializeField, Range(0f, 1f)] public float smileSpeaking = 0.14f;

        [Header("Cejas")]
        [SerializeField, Range(0f, 1f)]
        [Tooltip("Cuánto suben las cejas con la energía de la voz al hablar.")]
        public float browSpeechAmount = 0.45f;

        [SerializeField, Range(0f, 1f)]
        [Tooltip("Levantamiento breve de cejas al empezar a escuchar o a hablar.")]
        public float browFlashAmount = 0.5f;

        [SerializeField, Range(0f, 1f)]
        [Tooltip("Ceño al pensar.")]
        public float browThinkingFrown = 0.35f;

        [SerializeField, Range(0f, 1f)]
        [Tooltip("Vaivén aleatorio permanente de cejas.")]
        public float browIdleWander = 0.12f;

        [Header("Párpados")]
        [SerializeField, Range(0f, 1f)]
        [Tooltip("Cuánto se entornan los ojos al sonreír.")]
        public float squintWithSmile = 0.35f;

        [SerializeField, Range(0f, 1f)]
        [Tooltip("Cuánto se entornan los ojos en las sílabas fuertes.")]
        public float squintWithSpeech = 0.25f;

        [SerializeField, Range(0f, 1f)]
        [Tooltip("Cuánto se abren los ojos en un énfasis o al empezar a escuchar.")]
        public float wideOnEmphasis = 0.4f;

        [Header("Ritmo")]
        [SerializeField, Range(0.5f, 20f)]
        [Tooltip("Velocidad con la que las expresiones alcanzan su valor.")]
        public float smoothing = 6f;

        [SerializeField, Range(0f, 1f)]
        [Tooltip("Apertura de boca a partir de la cual una sílaba cuenta como énfasis.")]
        public float emphasisThreshold = 0.5f;

        private AvatarState _state = AvatarState.Idle;
        private float _scale = 1f;
        private float _noiseSeed;
        private float _flash;
        private float _emphasis;
        private float _energy;
        private bool _ready;

        // índices
        private int _browInnerUp, _browOuterUpL, _browOuterUpR, _browDownL, _browDownR;
        private int _smileL, _smileR, _cheekL, _cheekR, _squintL, _squintR, _wideL, _wideR, _mouthPress, _noseL, _noseR;

        // valores actuales (suavizados)
        private float _cBrowUp, _cBrowOuter, _cBrowDown, _cSmile, _cCheek, _cSquint, _cWide;

        /// <summary>Malla de la cara.</summary>
        public SkinnedMeshRenderer FaceRenderer
        {
            get { return faceRenderer; }
            set { faceRenderer = value; Bind(); }
        }

        private void Awake()
        {
            if (stateController == null)
            {
                stateController = GetComponentInChildren<AvatarStateController>(true);
            }

            if (lipSync == null)
            {
                lipSync = GetComponentInChildren<LipSyncController>(true);
            }

            _noiseSeed = Random.value * 100f;
            Bind();
        }

        /// <summary>Resuelve los blendshapes. Se llama sola; repetir si cambia la malla.</summary>
        public void Bind()
        {
            _ready = false;
            Mesh mesh = faceRenderer != null ? faceRenderer.sharedMesh : null;
            if (mesh == null)
            {
                return;
            }

            _scale = LipSyncController.BlendShapeScale(mesh);
            _browInnerUp = Find(mesh, "browInnerUp");
            _browOuterUpL = Find(mesh, "browOuterUpLeft");
            _browOuterUpR = Find(mesh, "browOuterUpRight");
            _browDownL = Find(mesh, "browDownLeft");
            _browDownR = Find(mesh, "browDownRight");
            _smileL = Find(mesh, "mouthSmileLeft");
            _smileR = Find(mesh, "mouthSmileRight");
            _cheekL = Find(mesh, "cheekSquintLeft");
            _cheekR = Find(mesh, "cheekSquintRight");
            _squintL = Find(mesh, "eyeSquintLeft");
            _squintR = Find(mesh, "eyeSquintRight");
            _wideL = Find(mesh, "eyeWideLeft");
            _wideR = Find(mesh, "eyeWideRight");
            _mouthPress = Find(mesh, "mouthPressLeft");
            _noseL = Find(mesh, "noseSneerLeft");
            _noseR = Find(mesh, "noseSneerRight");
            _ready = _browInnerUp >= 0 || _smileL >= 0 || _squintL >= 0;
        }

        private static int Find(Mesh mesh, string name)
        {
            int index = mesh.GetBlendShapeIndex(name);
            if (index >= 0)
            {
                return index;
            }

            for (int i = 0; i < mesh.blendShapeCount; i++)
            {
                string candidate = mesh.GetBlendShapeName(i);
                int dot = candidate.LastIndexOf('.');
                if (dot >= 0 && candidate.Substring(dot + 1) == name)
                {
                    return i;
                }
            }

            return -1;
        }

        private void LateUpdate()
        {
            if (!_ready || faceRenderer == null)
            {
                return;
            }

            float dt = Time.deltaTime;
            AvatarState state = stateController != null ? stateController.State : AvatarState.Idle;
            if (state != _state)
            {
                // Un levantamiento breve de cejas marca el cambio: "te escucho", "voy".
                if (state == AvatarState.Listening || state == AvatarState.Speaking)
                {
                    _flash = 1f;
                }

                _state = state;
            }

            _flash = Mathf.MoveTowards(_flash, 0f, dt * 1.6f);

            // La boca puede moverse en cualquier estado (frases del stand, bailes
            // cantados): las cejas y los párpados siguen a la voz siempre.
            float open = lipSync != null ? lipSync.MouthOpen : 0f;
            _energy = Mathf.Lerp(_energy, open, 1f - Mathf.Exp(-8f * dt));
            float emphasisTarget = open > emphasisThreshold ? 1f : 0f;
            _emphasis = Mathf.Lerp(_emphasis, emphasisTarget, 1f - Mathf.Exp(-(emphasisTarget > _emphasis ? 14f : 4f) * dt));

            float wander = (Mathf.PerlinNoise(_noiseSeed, Time.time * 0.23f) - 0.5f) * 2f;
            float wander2 = (Mathf.PerlinNoise(_noiseSeed + 47f, Time.time * 0.31f) - 0.5f) * 2f;

            float smile;
            switch (state)
            {
                case AvatarState.Listening: smile = smileListening; break;
                case AvatarState.Thinking: smile = smileThinking; break;
                case AvatarState.Speaking: smile = smileSpeaking; break;
                default: smile = smileIdle; break;
            }

            smile = Mathf.Clamp01(smile + wander2 * 0.05f);

            float browUp = Mathf.Clamp01(_energy * browSpeechAmount + _flash * browFlashAmount + Mathf.Max(0f, wander) * browIdleWander);
            float browOuter = Mathf.Clamp01(_emphasis * browSpeechAmount * 0.6f + _flash * browFlashAmount * 0.5f);
            float browDown = state == AvatarState.Thinking ? Mathf.Clamp01(browThinkingFrown + wander * 0.08f) : Mathf.Max(0f, -wander) * browIdleWander * 0.5f;
            float squint = Mathf.Clamp01(smile * squintWithSmile + _energy * squintWithSpeech + (state == AvatarState.Thinking ? 0.2f : 0f));
            float wide = Mathf.Clamp01(_emphasis * wideOnEmphasis * 0.5f + _flash * wideOnEmphasis);

            // Abrir los ojos y entornarlos a la vez no tiene sentido: gana el más fuerte.
            if (wide > squint) { squint *= 0.3f; } else { wide *= 0.3f; }

            float k = 1f - Mathf.Exp(-smoothing * dt);
            _cBrowUp = Mathf.Lerp(_cBrowUp, browUp, k);
            _cBrowOuter = Mathf.Lerp(_cBrowOuter, browOuter, k);
            _cBrowDown = Mathf.Lerp(_cBrowDown, browDown, k);
            _cSmile = Mathf.Lerp(_cSmile, smile, k);
            _cCheek = Mathf.Lerp(_cCheek, smile * 0.6f, k);
            _cSquint = Mathf.Lerp(_cSquint, squint, k);
            _cWide = Mathf.Lerp(_cWide, wide, k);

            Write(_browInnerUp, _cBrowUp);
            Write(_browOuterUpL, _cBrowOuter);
            Write(_browOuterUpR, _cBrowOuter * 0.9f);
            Write(_browDownL, _cBrowDown);
            Write(_browDownR, _cBrowDown * 0.9f);
            Write(_smileL, _cSmile);
            Write(_smileR, _cSmile * 0.95f);
            Write(_cheekL, _cCheek);
            Write(_cheekR, _cCheek);
            Write(_squintL, _cSquint);
            Write(_squintR, _cSquint);
            Write(_wideL, _cWide);
            Write(_wideR, _cWide);
            Write(_noseL, _emphasis * 0.08f);
            Write(_noseR, _emphasis * 0.08f);
        }

        private void Write(int index, float weight01)
        {
            if (index >= 0)
            {
                faceRenderer.SetBlendShapeWeight(index, Mathf.Clamp01(weight01) * 100f * _scale);
            }
        }
    }
}
