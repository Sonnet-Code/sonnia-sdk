// Coreógrafo del avatar: decide qué clip suena en cada momento.
//
// Sustituye al Animator Controller y a los antiguos IdleAttentionController y
// SpeakingGestureController. Recibe el estado del orquestador (idle, listening,
// thinking, speaking) y las señales de cada frase, y reproduce clips a través
// de MotionPlayer con fundidos elegidos caso por caso:
//
//   idle       bucle base + variaciones de reposo cada pocos segundos + gestos
//              de atención (bailes, cuarta pared) con el ritmo de siempre
//   listening  bucle de escucha + asentimientos en la capa de torso
//   thinking   bucle de pensar + variaciones
//   speaking   clips de gesticulación encadenados sin bucle: cada uno termina
//              limpio y el siguiente entra fundido; una frase nueva cambia de
//              clip solo si el actual ya va avanzado
//   greeting   saludo con la mano; se deja terminar salvo que toque hablar
//
// Todo es opcional: sin MotionPlayer o sin set de clips no hace nada.

using UnityEngine;

namespace Sonia
{
    /// <summary>Reproduce el clip adecuado a cada estado con fundidos por código.</summary>
    [DefaultExecutionOrder(-50)]
    [DisallowMultipleComponent]
    public class AvatarChoreographer : MonoBehaviour
    {
        private enum Phase
        {
            Base,
            Variation,
            Attention,
            Greeting
        }

        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Reproductor de clips. Si está vacío se busca en este objeto o sus hijos.")]
        private MotionPlayer motionPlayer;

        [SerializeField]
        [Tooltip("Clips agrupados por estado. Se crea con Sonia > Crear set de animaciones.")]
        private SoniaMotionSet motionSet;

        [Header("Fundidos (segundos)")]
        [SerializeField]
        [Tooltip("Al cambiar entre estados principales (idle, escuchar, pensar).")]
        private float stateFade = 0.55f;

        [SerializeField]
        [Tooltip("Al empezar a hablar: más corto para que la respuesta se sienta inmediata.")]
        private float speakFade = 0.35f;

        [SerializeField]
        [Tooltip("Entre un clip de gesticulación y el siguiente mientras habla.")]
        private float talkingChainFade = 0.5f;

        [SerializeField]
        [Tooltip("Entrada y salida de las variaciones de reposo y de pensar.")]
        private float variationFade = 0.6f;

        [SerializeField]
        [Tooltip("Entrada de un gesto de atención (baile, cuarta pared).")]
        private float attentionFadeIn = 0.4f;

        [SerializeField]
        [Tooltip("Vuelta al reposo después de un gesto de atención o un saludo.")]
        private float attentionFadeOut = 0.7f;

        [SerializeField]
        [Tooltip("Asentimientos en la capa de torso.")]
        private float nodFade = 0.3f;

        [Header("Reposo")]
        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre variaciones de reposo.")]
        private Vector2 idleVariationInterval = new Vector2(7f, 16f);

        [SerializeField]
        [Tooltip("Segundos hasta el primer gesto de atención al entrar en idle.")]
        private float firstAttentionDelay = 6f;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre gestos de atención.")]
        private Vector2 attentionInterval = new Vector2(12f, 30f);

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de un gesto de cuarta pared: señalar, saludar, tocar la pantalla.")]
        private float fourthWallWeight = 0.45f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de un baile completo.")]
        private float danceWeight = 0.30f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de un gesto suave de relleno.")]
        private float softWeight = 0.25f;

        [Header("Escuchar y pensar")]
        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre asentimientos mientras escucha.")]
        private Vector2 nodInterval = new Vector2(4f, 8f);

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre variaciones mientras piensa.")]
        private Vector2 thinkingVariationInterval = new Vector2(4f, 8f);

        [Header("Hablar")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Progreso mínimo del clip actual para que una frase nueva cambie de gesto.")]
        private float speechChangeThreshold = 0.5f;

        [Header("Saludo")]
        [SerializeField]
        [Tooltip("Segundos que hay que llevar en idle para que el siguiente listening dispare un saludo.")]
        private float minIdleSecondsForGreeting = 25f;

        [SerializeField]
        [Tooltip("Segundos mínimos entre dos saludos.")]
        private float greetingCooldownSeconds = 20f;

        [Header("Registro")]
        [SerializeField]
        [Tooltip("Escribir en la consola cada clip que se lanza.")]
        private bool logEvents;

        private const float MaxTrackedSeconds = 3600f;

        private AvatarState _state = AvatarState.Idle;
        private Phase _phase = Phase.Base;
        private MotionPlayer.Handle _body;
        private MotionPlayer.Handle _upper;
        private AnimationClip _lastTalking;
        private AnimationClip _lastVariation;
        private int _lastAttention = -1;
        private float _stateSeconds;
        private float _lastIdleSeconds;
        private float _secondsSinceGreeting = MaxTrackedSeconds;
        private float _variationTimer;
        private float _attentionTimer;
        private float _nodTimer;
        private float _wideUntil = -1f;
        private bool _started;

        /// <summary>Estado que se le ha comunicado al coreógrafo.</summary>
        public AvatarState State
        {
            get { return _state; }
        }

        /// <summary>Segundos que lleva Sonia en el estado actual.</summary>
        public float SecondsInState
        {
            get { return _stateSeconds; }
        }

        /// <summary>
        /// Cierto mientras suena un gesto grande (baile, cuarta pared, saludo) y
        /// durante su fundido de salida: la cámara abre el plano.
        /// </summary>
        public bool IsWideShot
        {
            get { return _phase == Phase.Attention || _phase == Phase.Greeting || Time.time < _wideUntil; }
        }

        /// <summary>Set de clips en uso.</summary>
        public SoniaMotionSet MotionSet
        {
            get { return motionSet; }
            set { motionSet = value; }
        }

        private void Awake()
        {
            if (motionPlayer == null)
            {
                motionPlayer = GetComponentInChildren<MotionPlayer>(true);
            }
        }

        private void Start()
        {
            _started = true;
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            _attentionTimer = firstAttentionDelay;
            EnterState(_state, stateFade, true);
        }

        private bool Ready
        {
            get { return motionPlayer != null && motionPlayer.IsReady && motionSet != null; }
        }

        // ------------------------------------------------------------------
        // Entradas
        // ------------------------------------------------------------------

        /// <summary>Recibe el estado del orquestador.</summary>
        public void SetState(AvatarState state)
        {
            if (state == _state)
            {
                return;
            }

            if (_state == AvatarState.Idle)
            {
                _lastIdleSeconds = _stateSeconds;
            }

            AvatarState previous = _state;
            _state = state;
            _stateSeconds = 0f;

            if (!_started)
            {
                return;
            }

            // El saludo se deja terminar si solo cambia entre idle y escuchar;
            // pensar o hablar lo cortan.
            if (_phase == Phase.Greeting && (state == AvatarState.Idle || state == AvatarState.Listening))
            {
                return;
            }

            float fade = state == AvatarState.Speaking ? speakFade : stateFade;
            bool cutting = _phase == Phase.Attention || _phase == Phase.Greeting;
            EnterState(state, cutting ? Mathf.Max(fade, attentionFadeOut * 0.6f) : fade, false);

            if (previous == AvatarState.Listening && state != AvatarState.Listening && motionPlayer != null)
            {
                motionPlayer.FadeOut(MotionPlayer.UpperLayer, nodFade);
                _upper = null;
            }
        }

        /// <summary>
        /// Se llama en cada <c>speech_start</c>: si el gesto actual ya va avanzado,
        /// cambia a otro para que cada frase tenga su propia gesticulación.
        /// </summary>
        public void NotifySpeechStart()
        {
            if (!Ready || _state != AvatarState.Speaking)
            {
                return;
            }

            if (_body == null || !_body.IsAlive || _body.NormalizedTime >= speechChangeThreshold)
            {
                PlayNextTalking(talkingChainFade);
            }
        }

        /// <summary>
        /// Saluda con la mano si Sonia está en idle o escuchando, llevaba un buen
        /// rato sola y no acaba de saludar. Devuelve cierto si lanzó el saludo.
        /// </summary>
        public bool PlayGreeting()
        {
            if (!Ready || motionSet.greeting == null)
            {
                return false;
            }

            if (_state != AvatarState.Idle && _state != AvatarState.Listening)
            {
                return false;
            }

            float idleSeconds = _state == AvatarState.Idle ? _stateSeconds : _lastIdleSeconds;
            if (idleSeconds < minIdleSecondsForGreeting || _secondsSinceGreeting < greetingCooldownSeconds)
            {
                return false;
            }

            _secondsSinceGreeting = 0f;
            _phase = Phase.Greeting;
            _body = motionPlayer.Play(motionSet.greeting, MotionPlayer.BodyLayer, attentionFadeIn);
            _attentionTimer = Random.Range(attentionInterval.x, attentionInterval.y);
            Log("saludo tras " + Mathf.RoundToInt(idleSeconds) + " s en idle");
            return true;
        }

        /// <summary>
        /// Previsualiza un clip del set (panel de animaciones). Un bucle base se
        /// convierte en el bucle activo; cualquier otro clip se reproduce una vez
        /// sobre el cuerpo (o sobre el torso, si es un asentimiento) y se vuelve a
        /// la base del estado actual.
        /// </summary>
        public void Preview(AnimationClip clip, bool upperBody = false)
        {
            if (!Ready || clip == null)
            {
                return;
            }

            if (upperBody)
            {
                _upper = motionPlayer.Play(clip, MotionPlayer.UpperLayer, nodFade);
                return;
            }

            if (clip.isLooping)
            {
                _phase = Phase.Base;
                PlayLoop(clip, stateFade);
                return;
            }

            bool attentionLike = System.Array.Exists(
                motionSet.attention, m => m != null && m.clip == clip) || clip == motionSet.greeting;
            _phase = attentionLike ? Phase.Attention : Phase.Variation;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, attentionLike ? attentionFadeIn : variationFade);
            Log("previsualización: " + clip.name);
        }

        /// <summary>Lanza un gesto de atención al azar (según los pesos). Solo en idle.</summary>
        public void PlayRandomAttention()
        {
            if (_state != AvatarState.Idle)
            {
                return;
            }

            PlayAttention(PickAttention());
        }

        /// <summary>
        /// Lanza un gesto de atención de una categoría (o un clip concreto por
        /// nombre, si existe). Lo usa el orquestador para los bailes cantados.
        /// Solo en idle.
        /// </summary>
        public void PlayAttention(AttentionCategory category, string clipName = null)
        {
            if (!Ready || _state != AvatarState.Idle)
            {
                return;
            }

            if (!string.IsNullOrEmpty(clipName))
            {
                for (int i = 0; i < motionSet.attention.Length; i++)
                {
                    AttentionMotion motion = motionSet.attention[i];
                    if (motion != null && motion.clip != null && motion.clip.name == clipName)
                    {
                        PlayAttention(i);
                        return;
                    }
                }
            }

            int count = motionSet.CountInCategory(category);
            if (count == 0)
            {
                PlayAttention(PickAttention());
                return;
            }

            for (int attempt = 0; attempt < 12; attempt++)
            {
                int index = Random.Range(0, motionSet.attention.Length);
                AttentionMotion motion = motionSet.attention[index];
                if (motion == null || motion.clip == null || motion.category != category)
                {
                    continue;
                }

                if (index != _lastAttention || count == 1)
                {
                    PlayAttention(index);
                    return;
                }
            }

            for (int i = 0; i < motionSet.attention.Length; i++)
            {
                if (motionSet.attention[i] != null && motionSet.attention[i].clip != null
                    && motionSet.attention[i].category == category)
                {
                    PlayAttention(i);
                    return;
                }
            }
        }

        /// <summary>Lanza el gesto de atención con ese índice del set. Solo en idle.</summary>
        public void PlayAttention(int index)
        {
            if (!Ready || _state != AvatarState.Idle || index < 0 || index >= motionSet.attention.Length)
            {
                return;
            }

            AttentionMotion motion = motionSet.attention[index];
            if (motion == null || motion.clip == null)
            {
                return;
            }

            _phase = Phase.Attention;
            _lastAttention = index;
            _body = motionPlayer.Play(motion.clip, MotionPlayer.BodyLayer, attentionFadeIn);
            _attentionTimer = Random.Range(attentionInterval.x, attentionInterval.y);
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            Log("atención " + motion.category + ": " + motion.clip.name);
        }

        // ------------------------------------------------------------------
        // Bucle
        // ------------------------------------------------------------------

        private void Update()
        {
            float dt = Time.deltaTime;
            _stateSeconds = Mathf.Min(MaxTrackedSeconds, _stateSeconds + dt);
            _secondsSinceGreeting = Mathf.Min(MaxTrackedSeconds, _secondsSinceGreeting + dt);

            if (!Ready)
            {
                return;
            }

            // Un gesto de una sola vez ha terminado (o casi): vuelta a la base.
            if (_phase != Phase.Base)
            {
                if (_body == null || !_body.IsAlive || _body.Remaining <= FadeForReturn())
                {
                    EndOneShot();
                }

                return;
            }

            switch (_state)
            {
                case AvatarState.Idle:
                    UpdateIdle(dt);
                    break;
                case AvatarState.Listening:
                    UpdateListening(dt);
                    break;
                case AvatarState.Thinking:
                    UpdateThinking(dt);
                    break;
                case AvatarState.Speaking:
                    UpdateSpeaking();
                    break;
            }
        }

        private float FadeForReturn()
        {
            return _phase == Phase.Variation ? variationFade : attentionFadeOut;
        }

        private void EndOneShot()
        {
            bool wasWide = _phase == Phase.Attention || _phase == Phase.Greeting;
            _phase = Phase.Base;
            if (wasWide)
            {
                _wideUntil = Time.time + attentionFadeOut;
            }

            EnterState(_state, wasWide ? attentionFadeOut : variationFade, false);
        }

        private void UpdateIdle(float dt)
        {
            EnsureLoop(motionSet.idleLoop, stateFade);

            _attentionTimer -= dt;
            if (_attentionTimer <= 0f)
            {
                int index = PickAttention();
                if (index >= 0)
                {
                    PlayAttention(index);
                    return;
                }

                _attentionTimer = Random.Range(attentionInterval.x, attentionInterval.y);
            }

            _variationTimer -= dt;
            if (_variationTimer <= 0f)
            {
                _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                AnimationClip clip = PickDifferent(motionSet.idleVariations, _lastVariation);
                if (clip != null)
                {
                    _lastVariation = clip;
                    _phase = Phase.Variation;
                    _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, variationFade);
                    Log("variación de reposo: " + clip.name);
                }
            }
        }

        private void UpdateListening(float dt)
        {
            EnsureLoop(motionSet.listeningLoop, stateFade);

            if (_upper != null && _upper.IsAlive)
            {
                if (_upper.Remaining <= nodFade)
                {
                    motionPlayer.FadeOut(MotionPlayer.UpperLayer, nodFade);
                    _upper = null;
                }

                return;
            }

            _nodTimer -= dt;
            if (_nodTimer <= 0f)
            {
                _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                AnimationClip nod = PickDifferent(motionSet.nods, null);
                if (nod != null)
                {
                    _upper = motionPlayer.Play(nod, MotionPlayer.UpperLayer, nodFade);
                    Log("asentimiento: " + nod.name);
                }
            }
        }

        private void UpdateThinking(float dt)
        {
            EnsureLoop(motionSet.thinkingLoop, stateFade);

            _variationTimer -= dt;
            if (_variationTimer <= 0f)
            {
                _variationTimer = Random.Range(thinkingVariationInterval.x, thinkingVariationInterval.y);
                AnimationClip clip = PickDifferent(motionSet.thinkingVariations, _lastVariation);
                if (clip != null)
                {
                    _lastVariation = clip;
                    _phase = Phase.Variation;
                    _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, variationFade);
                    Log("variación de pensar: " + clip.name);
                }
            }
        }

        private void UpdateSpeaking()
        {
            if (_body == null || !_body.IsAlive || _body.Remaining <= talkingChainFade)
            {
                PlayNextTalking(_body == null || !_body.IsAlive ? speakFade : talkingChainFade);
            }
        }

        // ------------------------------------------------------------------
        // Reproducción
        // ------------------------------------------------------------------

        /// <summary>Arranca el movimiento base de un estado.</summary>
        private void EnterState(AvatarState state, float fade, bool initial)
        {
            if (!Ready)
            {
                return;
            }

            _phase = Phase.Base;
            switch (state)
            {
                case AvatarState.Idle:
                    _attentionTimer = initial ? firstAttentionDelay : Mathf.Max(_attentionTimer, firstAttentionDelay);
                    _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                    PlayLoop(motionSet.idleLoop, fade);
                    break;
                case AvatarState.Listening:
                    _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                    PlayLoop(motionSet.listeningLoop, fade);
                    break;
                case AvatarState.Thinking:
                    _variationTimer = Random.Range(thinkingVariationInterval.x, thinkingVariationInterval.y);
                    PlayLoop(motionSet.thinkingLoop, fade);
                    break;
                case AvatarState.Speaking:
                    PlayNextTalking(fade);
                    break;
            }
        }

        /// <summary>Si el bucle base no está sonando (o suena otro clip), lo lanza.</summary>
        private void EnsureLoop(AnimationClip loop, float fade)
        {
            if (loop == null)
            {
                return;
            }

            if (_body != null && _body.IsCurrent && _body.Clip == loop)
            {
                return;
            }

            PlayLoop(loop, fade);
        }

        private void PlayLoop(AnimationClip loop, float fade)
        {
            if (loop == null)
            {
                return;
            }

            // Se entra en un punto aleatorio del bucle para que dos vueltas al
            // mismo estado no arranquen siempre con la misma pose.
            float start = loop.isLooping ? Random.Range(0f, Mathf.Max(0f, loop.length - 0.5f)) : 0f;
            _body = motionPlayer.Play(loop, MotionPlayer.BodyLayer, fade, 1f, start);
        }

        private void PlayNextTalking(float fade)
        {
            AnimationClip clip = PickDifferent(motionSet.talking, _lastTalking);
            if (clip == null)
            {
                EnsureLoop(motionSet.idleLoop, fade);
                return;
            }

            _lastTalking = clip;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, fade);
            Log("gesto al hablar: " + clip.name);
        }

        // ------------------------------------------------------------------
        // Elección
        // ------------------------------------------------------------------

        private static AnimationClip PickDifferent(AnimationClip[] clips, AnimationClip last)
        {
            if (clips == null || clips.Length == 0)
            {
                return null;
            }

            int valid = 0;
            for (int i = 0; i < clips.Length; i++)
            {
                if (clips[i] != null)
                {
                    valid++;
                }
            }

            if (valid == 0)
            {
                return null;
            }

            for (int attempt = 0; attempt < 8; attempt++)
            {
                AnimationClip candidate = clips[Random.Range(0, clips.Length)];
                if (candidate != null && (candidate != last || valid == 1))
                {
                    return candidate;
                }
            }

            for (int i = 0; i < clips.Length; i++)
            {
                if (clips[i] != null)
                {
                    return clips[i];
                }
            }

            return null;
        }

        private int PickAttention()
        {
            if (motionSet == null || motionSet.attention.Length == 0)
            {
                return -1;
            }

            AttentionCategory category = PickCategory();
            int count = motionSet.CountInCategory(category);
            if (count == 0)
            {
                // Sin clips de esa categoría se coge cualquiera.
                count = 0;
                for (int i = 0; i < motionSet.attention.Length; i++)
                {
                    if (motionSet.attention[i] != null && motionSet.attention[i].clip != null)
                    {
                        count++;
                    }
                }

                if (count == 0)
                {
                    return -1;
                }
            }

            for (int attempt = 0; attempt < 12; attempt++)
            {
                int index = Random.Range(0, motionSet.attention.Length);
                AttentionMotion motion = motionSet.attention[index];
                if (motion == null || motion.clip == null)
                {
                    continue;
                }

                bool categoryOk = motion.category == category || motionSet.CountInCategory(category) == 0;
                if (categoryOk && (index != _lastAttention || count == 1))
                {
                    return index;
                }
            }

            for (int i = 0; i < motionSet.attention.Length; i++)
            {
                if (motionSet.attention[i] != null && motionSet.attention[i].clip != null)
                {
                    return i;
                }
            }

            return -1;
        }

        private AttentionCategory PickCategory()
        {
            float fourth = Mathf.Max(0f, fourthWallWeight);
            float dance = Mathf.Max(0f, danceWeight);
            float soft = Mathf.Max(0f, softWeight);
            float total = fourth + dance + soft;
            if (total <= 0f)
            {
                return AttentionCategory.Soft;
            }

            float roll = Random.value * total;
            if (roll < fourth)
            {
                return AttentionCategory.FourthWall;
            }

            return roll < fourth + dance ? AttentionCategory.Dance : AttentionCategory.Soft;
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] " + message, this);
            }
        }
    }
}
