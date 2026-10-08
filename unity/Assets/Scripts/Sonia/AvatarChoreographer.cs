// Coreógrafo del avatar: decide qué clip suena en cada momento.
//
// Sustituye al Animator Controller y a los antiguos IdleAttentionController y
// SpeakingGestureController. Recibe el estado del orquestador (idle, listening,
// thinking, speaking) y las señales de cada frase, y reproduce clips a través
// de MotionPlayer con fundidos elegidos caso por caso:
//
//   idle       bucle base; con el stand en calma (sin conversación desde hace
//              attentionQuietDelay) gestos de atención (bailes, cuarta pared)
//              espaciados 15 ± 5 s, como el aburrimiento de Genies
//   listening, thinking, speaking
//              con singleConversationLoop (por defecto), un solo reposo largo:
//              el mismo bucle de idle, sin reiniciarlo ni cambiar de clip entre
//              estados y sin variaciones ni gestos, como Mia. Apagado, cada
//              estado lleva su bucle, asentimientos, variaciones de pensar y
//              clips de gesticulación encadenados
//   greeting   saludo con la mano; se deja terminar salvo que toque hablar
//
// Los gestos entran y salen en gestureFade (0,8 s) y MotionPlayer los funde con
// curva suave, como Genies.
//
// Mientras Sonia sale o entra caminando (modo "Fuera", PresenceController) el
// coreógrafo queda suspendido: apunta el estado que le llega pero no lanza
// ningún clip, ni gestos ni bailes, hasta que se le devuelve el cuerpo.
//
// Con un set de Genies con reposos (GeniesGestureLayer, el de Sage) el cuerpo
// lo llevan sus clips, como en el chat de Genies (genieBody): reposo base en
// bucle (baseIdle, elegido por frecuencia en cada vuelta), escuchar y pensar con
// los suyos, aburrimiento cada 15 ± 5 s con el stand en calma, saludo y gestos
// hacia el público. Lo que el personaje no tiene (bailar, caminar, señalar una
// imagen, las reacciones de la trivia) sigue en MotionPlayer y el reposo de
// Genies se aparta con fundido mientras suena (al señalar, solo el brazo).
// Si una tarea delegada tarda (activity think del orquestador), al pensar se
// lleva la mano a la barbilla (touchBeard de Sage, sostenido) hasta que acaba.
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
            Greeting,
            // Reacción de la trivia: suena entera aunque cambie el estado.
            Reaction,
            // Mano en la barbilla mientras una tarea tarda (acción de Genies sostenida).
            Ponder
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
        [Range(0.1f, 2f)]
        [Tooltip("Entrada y salida de los gestos (atención, saludo y variaciones), con la curva suave de MotionPlayer. Genies usa 0,8 s.")]
        private float gestureFade = 0.8f;

        [SerializeField]
        [Range(0.1f, 1.5f)]
        [Tooltip("Entrada y salida del gesto de presentar una imagen (brazo derecho).")]
        private float presentFade = 0.5f;

        [SerializeField]
        [Tooltip("Asentimientos en la capa de torso.")]
        private float nodFade = 0.3f;

        [Header("Conversación")]
        [SerializeField]
        [Tooltip("En conversación (escuchar, pensar, hablar) suena un solo reposo largo, el de idle, sin cambiar de clip entre estados y sin variaciones, asentimientos ni gestos de hablar, como Mia. Apagado: cada estado con su bucle y sus variaciones.")]
        private bool singleConversationLoop = true;

        [Header("Cuerpo de Genies")]
        [SerializeField]
        [Tooltip("El cuerpo lo llevan los clips de Genies del set de GeniesGestureLayer (reposo, escuchar, pensar, aburrimiento, saludo y gestos hacia el público). Lo que el personaje no tiene (bailar, caminar, señalar una imagen, la trivia) sigue con MotionPlayer.")]
        private bool genieBody = true;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre aburrimientos con el stand en calma (BoredTimeBase de Genies: 15 ± 5).")]
        private Vector2 boredInterval = new Vector2(10f, 20f);

        [SerializeField]
        [Tooltip("Al hablar, encadena gestos neutros de relleno (lista talk del set) mientras el director no pide otro: así no habla con los brazos quietos.")]
        private bool talkFillers = true;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Probabilidad de dejar un respiro sin gesto entre dos rellenos.")]
        private float talkFillerRestChance = 0.25f;

        [Header("Reposo")]
        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre variaciones de reposo (solo con el stand en calma).")]
        private Vector2 idleVariationInterval = new Vector2(7f, 16f);

        [SerializeField]
        [Tooltip("Segundos en idle sin conversación antes del primer gesto de atención: con alguien delante (entre turnos el estado también es idle) no se baila.")]
        private float attentionQuietDelay = 25f;

        [SerializeField]
        [Tooltip("Segundos mínimo y máximo entre gestos de atención con el stand en calma (15 ± 5, como el aburrimiento de Genies).")]
        private Vector2 attentionSpacing = new Vector2(10f, 20f);

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

        [SerializeField]
        [Tooltip("Gesto de Genies del set con el que se lleva la mano a la barbilla mientras una tarea tarda (activity think del orquestador). Vacío: no lo hace.")]
        private string ponderGesture = "touchBeard";

        [SerializeField]
        [Tooltip("Tramo del gesto, en segundos, con la mano en la barbilla: entra ahí directamente (antes, la mano de touchBeard le tapa la boca) y va y viene en él mientras dure la tarea.")]
        private Vector2 ponderHold = new Vector2(1.75f, 3.2f);

        [SerializeField]
        [Range(0.1f, 1f)]
        [Tooltip("Velocidad del vaivén con la mano en la barbilla (1: la del clip).")]
        private float ponderSpeed = 0.5f;

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

        // Gesto de presentar (imagen): mano arriba congelada en el punto álgido.
        private MotionPlayer.Handle _present;
        private bool _presentHolding;
        private bool _presentReleasing;
        private AnimationClip _lastTalking;
        private bool _speechPaused;
        // Clips de Genies: reposo, acciones y gestos al hablar (los pide el director de gestos del orquestador).
        private GeniesGestureLayer _gestures;
        // El gesto de una vez en curso es una acción de Genies (no un clip de MotionPlayer).
        private bool _genieAction;
        private string _lastGenieAction;
        private string _lastFiller;
        private float _nextFillerAt;
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
        private bool _suspended;

        // El orquestador dice que una tarea tarda (activity think): mano en la barbilla al pensar.
        private bool _ponderWanted;

        // Segundos en idle desde la última conversación (escuchar, pensar o hablar).
        private float _quietSeconds;
        private bool _quietArmed;

        // Velocidad de los bucles base (ajuste «Movimiento en reposo»).
        private float _loopSpeed = 1f;

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
            get
            {
                return !_suspended
                       && (_phase == Phase.Attention || _phase == Phase.Greeting || Time.time < _wideUntil);
            }
        }

        /// <summary>Set de clips en uso.</summary>
        public SoniaMotionSet MotionSet
        {
            get { return motionSet; }
            set { motionSet = value; }
        }

        /// <summary>Reproductor de clips que usa el coreógrafo.</summary>
        public MotionPlayer Player
        {
            get { return motionPlayer; }
        }

        /// <summary>Cierto mientras otro componente manda en el cuerpo (salida y entrada caminando).</summary>
        public bool IsSuspended
        {
            get { return _suspended; }
        }

        /// <summary>
        /// Cierto mientras suena un clip de una sola vez sobre el cuerpo (gesto,
        /// saludo, baile, reacción o variación) en lugar del bucle base: los gestos
        /// de manos al hablar (AvatarStateController) esperan a que acabe.
        /// </summary>
        public bool IsPlayingOneShot
        {
            get { return !_suspended && _phase != Phase.Base; }
        }

        /// <summary>Cierto si el cuerpo lo llevan los clips de Genies (reposo y acciones).</summary>
        public bool GenieBody
        {
            get { return genieBody && _gestures != null && _gestures.HasRest && _gestures.IsReady; }
        }

        /// <summary>
        /// Cierto si ahora puede sonar un gesto de Genies al hablar (director de
        /// gestos, <see cref="GeniesGestureLayer"/>): hablando y con voz, sin
        /// imagen, saludo, reacción, baile ni salida caminando.
        /// </summary>
        public bool CanTalkGesture
        {
            get
            {
                return Ready && _started && !_suspended && _state == AvatarState.Speaking
                       && _phase == Phase.Base && !_speechPaused && !IsPresenting;
            }
        }

        /// <summary>Segundos en idle desde la última conversación: con poco, alguien sigue delante.</summary>
        public float QuietSeconds
        {
            get { return _quietSeconds; }
        }

        /// <summary>
        /// Velocidad de los bucles base (1 = la del clip). Más lenta, el traspaso
        /// de peso del reposo va más despacio. Lo ajusta «Movimiento en reposo».
        /// </summary>
        public void SetLoopSpeed(float speed)
        {
            _loopSpeed = Mathf.Clamp(speed, 0.25f, 3f);
            if (_body != null && _body.IsAlive && _body.Clip != null && _body.Clip.isLooping)
            {
                _body.SetSpeed(_loopSpeed);
            }
        }

        private void Awake()
        {
            if (motionPlayer == null)
            {
                motionPlayer = GetComponentInChildren<MotionPlayer>(true);
            }

            _gestures = GetComponent<GeniesGestureLayer>();
        }

        // Funde hacia fuera el gesto de Genies que suene: otro clip o estado manda en el cuerpo.
        private void StopTalkGesture()
        {
            if (_gestures != null && _gestures.IsActive)
            {
                _gestures.Stop();
            }
        }

        // Reposo de Genies del estado actual: la lista que toca, otro de ella por
        // frecuencia al acabar cada vuelta, y el brazo derecho libre mientras señala.
        private void EnsureGenieRest(float fade)
        {
            if (!GenieBody)
            {
                return;
            }

            GeniesGestureSet set = _gestures.Set;
            string[] list = RestListOf(_state, set);
            string current = _gestures.CurrentRest;
            _gestures.MaskRightArm(IsPresenting);
            if (current == null || System.Array.IndexOf(list, current) < 0)
            {
                _gestures.PlayRest(set.Pick(list, null), Mathf.Max(fade, set.transitionSeconds));
            }
            else if (_gestures.ConsumeRestLoopEnd(set.transitionSeconds))
            {
                string next = set.Pick(list, null);
                if (next != null && next != current)
                {
                    _gestures.PlayRest(next, set.transitionSeconds);
                    Log("reposo de Genies: " + next);
                }
            }

            _gestures.SetRestWeight(1f, fade);
        }

        private static string[] RestListOf(AvatarState state, GeniesGestureSet set)
        {
            string[] list = state == AvatarState.Listening ? set.restListen
                : state == AvatarState.Thinking ? set.restThink
                : set.restIdle;
            return set.Pick(list, null) != null ? list : set.restIdle;
        }

        // Un clip de MotionPlayer manda en el cuerpo: el reposo y las acciones de Genies se apartan.
        private void HideGenieBody(float fade)
        {
            if (_gestures == null)
            {
                return;
            }

            _gestures.SetRestWeight(0f, fade);
            _gestures.StopActions(fade);
            _genieAction = false;
        }

        // Lanza una acción de Genies (cuerpo entero, sobre el reposo) como gesto de una vez.
        private bool StartGenieAction(string name, Phase phase, string why)
        {
            if (!GenieBody || string.IsNullOrEmpty(name) || !_gestures.PlayAction(name))
            {
                return false;
            }

            _phase = phase;
            _genieAction = true;
            _lastGenieAction = name;
            _gestures.SetRestWeight(1f, gestureFade);
            Log(why + ": " + name);
            return true;
        }

        // Relleno al hablar: cuando no suena gesto (o el que suena va de salida) entra
        // otro neutro de la lista talk, con fundido cruzado; a veces, un respiro.
        // Un gesto pedido por el director entra encima y manda.
        private void UpdateTalkFillers()
        {
            if (!talkFillers || _gestures == null || !CanTalkGesture || !_gestures.IsReady || Time.time < _nextFillerAt)
            {
                return;
            }

            GeniesGestureSet set = _gestures.Set;
            if (_gestures.IsActive && _gestures.GestureRemaining > set.transitionSeconds * 0.6f)
            {
                return;
            }

            if (!_gestures.IsActive && Random.value < talkFillerRestChance)
            {
                _nextFillerAt = Time.time + Random.Range(0.4f, 1.2f);
                return;
            }

            string name = set.Pick(set.talk, _lastFiller);
            if (name != null && _gestures.Play(name))
            {
                _lastFiller = name;
            }

            _nextFillerAt = Time.time + 0.5f;
        }

        /// <summary>
        /// Vista previa de un clip de Genies del set (panel): suena de cuerpo entero
        /// sobre el reposo y se vuelve a lo que tocaba. Falso si no se pudo.
        /// </summary>
        public bool PreviewGenie(string name)
        {
            if (!Ready || _suspended || !GenieBody)
            {
                return false;
            }

            return StartGenieAction(name, Phase.Variation, "vista previa de Genies");
        }

        /// <summary>
        /// Movimiento de Genies pedido de viva voz: como <see cref="PlayReaction"/>,
        /// suena entero aunque cambie el estado. Falso si no se pudo.
        /// </summary>
        public bool PlayGenieReaction(string name)
        {
            if (!Ready || _suspended || !GenieBody)
            {
                return false;
            }

            return StartGenieAction(name, Phase.Reaction, "movimiento de Genies");
        }

        /// <summary>
        /// El orquestador dice si una tarea delegada tarda (<c>activity</c>
        /// <c>think</c>). Mientras tanto, pensando y sin otra cosa en el cuerpo,
        /// Sonia se lleva la mano a la barbilla (<see cref="ponderGesture"/>) y la
        /// deja ahí hasta que acaba la tarea o cambia de estado.
        /// </summary>
        public void SetPondering(bool pondering)
        {
            _ponderWanted = pondering;
            if (!pondering && _phase == Phase.Ponder)
            {
                // La mano baja con el final del clip; EndOneShot vuelve a la base.
                ReleasePonder();
            }
        }

        /// <summary>Cierto mientras la mano está en la barbilla (sostenida o bajando).</summary>
        public bool IsPondering
        {
            get { return !_suspended && _phase == Phase.Ponder; }
        }

        private bool TryStartPonder()
        {
            if (!_ponderWanted || _state != AvatarState.Thinking || IsPresenting || !GenieBody
                || string.IsNullOrEmpty(ponderGesture) || _gestures.CurrentAction == ponderGesture)
            {
                return false;
            }

            StopTalkGesture();
            if (!_gestures.PlayHeldAction(ponderGesture, ponderHold.x, ponderHold.y, ponderSpeed, gestureFade))
            {
                return false;
            }

            _phase = Phase.Ponder;
            _genieAction = true;
            _lastGenieAction = ponderGesture;
            _gestures.SetRestWeight(1f, gestureFade);
            Log("mano en la barbilla: " + ponderGesture);
            return true;
        }

        private void ReleasePonder()
        {
            if (_gestures != null)
            {
                _gestures.ReleaseHold();
            }
        }

        private void Start()
        {
            _started = true;
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            _attentionTimer = RandomSpacing();
            EnterState(_state, stateFade, true);
        }

        /// <summary>Cierto cuando hay reproductor con grafo y set de clips: ya puede mover al avatar.</summary>
        public bool Ready
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
            _speechPaused = false;
            if (state != AvatarState.Speaking)
            {
                StopTalkGesture();
            }
            if (state != AvatarState.Idle)
            {
                // Hay conversación: el stand no está en calma.
                _quietSeconds = 0f;
                _quietArmed = false;
            }

            // Suspendido (fuera de pantalla o caminando): se apunta el estado y
            // se aplica al devolverle el cuerpo (Resume).
            if (!_started || _suspended)
            {
                return;
            }

            // Deja de pensar con la mano en la barbilla: la mano baja con el final
            // del clip mientras entra el estado nuevo (sin cortarla de golpe).
            if (_phase == Phase.Ponder)
            {
                ReleasePonder();
                _genieAction = false;
                _phase = Phase.Base;
            }

            // El saludo se deja terminar si solo cambia entre idle y escuchar;
            // pensar o hablar lo cortan.
            if (_phase == Phase.Greeting && (state == AvatarState.Idle || state == AvatarState.Listening))
            {
                return;
            }

            // Una reacción (acierto, fallo o final de la trivia) no se corta: el
            // estado nuevo se aplica al terminar (EndOneShot).
            if (_phase == Phase.Reaction)
            {
                return;
            }

            float fade = state == AvatarState.Speaking ? speakFade : stateFade;
            bool cutting = _phase == Phase.Attention || _phase == Phase.Greeting;
            EnterState(state, cutting ? Mathf.Max(fade, gestureFade * 0.6f) : fade, false);

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
            if (!Ready || _suspended || _state != AvatarState.Speaking)
            {
                return;
            }

            if (_speechPaused)
            {
                SetSpeechPaused(false);
                return;
            }

            if (IsPresenting || _phase == Phase.Reaction)
            {
                return;
            }

            if (_body == null || !_body.IsAlive || _body.NormalizedTime >= speechChangeThreshold)
            {
                PlayNextTalking(talkingChainFade);
            }
        }

        /// <summary>Cierto mientras los gestos de hablar están en pausa por falta de audio.</summary>
        public bool SpeechPaused
        {
            get { return _speechPaused; }
        }

        /// <summary>
        /// En mitad de una respuesta el modelo puede tardar en dar la frase
        /// siguiente y Sonia se queda sin voz unos segundos: gesticular con la
        /// boca cerrada queda raro. En pausa se pasa al bucle de escuchar (una
        /// espera atenta) sin salir de "hablando"; al volver el audio se retoma la
        /// gesticulación.
        /// </summary>
        public void SetSpeechPaused(bool paused)
        {
            if (paused == _speechPaused)
            {
                return;
            }

            _speechPaused = paused;
            if (paused)
            {
                // Sin voz, el gesto se queda a medias: se deja ir, como Genies al acabar de hablar.
                StopTalkGesture();
            }

            if (!Ready || _suspended || _state != AvatarState.Speaking || _phase != Phase.Base)
            {
                return;
            }

            if (singleConversationLoop)
            {
                // Un solo reposo: la pausa no cambia de clip.
                return;
            }

            if (paused)
            {
                PlayLoop(motionSet.listeningLoop != null ? motionSet.listeningLoop : motionSet.idleLoop, speakFade);
                Log("gestos de hablar en pausa: sin audio");
            }
            else if (!IsPresenting)
            {
                PlayNextTalking(speakFade);
            }
        }

        /// <summary>
        /// Saluda con la mano si Sonia está en idle o escuchando, llevaba un buen
        /// rato sola y no acaba de saludar. Devuelve cierto si lanzó el saludo.
        /// </summary>
        public bool PlayGreeting()
        {
            if (GreetingSuppressed || !CanGreet())
            {
                return false;
            }

            float idleSeconds = _state == AvatarState.Idle ? _stateSeconds : _lastIdleSeconds;
            if (idleSeconds < minIdleSecondsForGreeting || _secondsSinceGreeting < greetingCooldownSeconds)
            {
                return false;
            }

            StartGreeting("saludo tras " + Mathf.RoundToInt(idleSeconds) + " s en idle");
            return true;
        }

        /// <summary>
        /// Saluda con la mano ya, sin las condiciones del saludo automático
        /// (rato sola, enfriamiento). Lo pide el orquestador con
        /// <c>attention</c> y <c>category: "greeting"</c> (botón del panel, modo
        /// saludos). Solo en idle o escuchando, sin una imagen puesta (el brazo
        /// que saluda es el que señala) y sin repetir uno que ya esté en marcha.
        /// </summary>
        public bool PlayGreetingNow()
        {
            if (!CanGreet() || IsPresenting || _phase == Phase.Greeting)
            {
                return false;
            }

            StartGreeting("saludo pedido por el orquestador");
            return true;
        }

        private bool CanGreet()
        {
            return Ready
                   && !_suspended
                   && motionSet.greeting != null
                   && _phase != Phase.Reaction
                   && (_state == AvatarState.Idle || _state == AvatarState.Listening);
        }

        /// <summary>
        /// Sin saludo automático al acercarse alguien (lo apaga la trivia: con la
        /// partida en marcha, cada respuesta del visitante lo dispararía).
        /// </summary>
        public bool GreetingSuppressed { get; set; }

        private void StartGreeting(string why)
        {
            StopTalkGesture();
            _secondsSinceGreeting = 0f;
            if (!GenieBody || !StartGenieAction(_gestures.Set.Pick(_gestures.Set.greeting, _lastGenieAction), Phase.Greeting, why))
            {
                HideGenieBody(gestureFade);
                _phase = Phase.Greeting;
                _body = motionPlayer.Play(motionSet.greeting, MotionPlayer.BodyLayer, gestureFade);
            }

            _attentionTimer = RandomSpacing();
            _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
            if (!_genieAction)
            {
                Log(why);
            }
        }

        /// <summary>
        /// Otro componente toma el cuerpo (salida y entrada caminando): se cortan
        /// la presentación de imagen y los asentimientos, y hasta
        /// <see cref="Resume"/> no se lanza ningún clip (ni variaciones, ni
        /// gestos de atención, ni bailes, ni gestos de habla). El estado que
        /// llegue mientras tanto se apunta.
        /// </summary>
        public void Suspend()
        {
            if (_suspended)
            {
                return;
            }

            _suspended = true;
            StopTalkGesture();
            HideGenieBody(0.3f);
            _phase = Phase.Base;
            _wideUntil = -1f;
            _speechPaused = false;
            _present = null;
            _presentHolding = false;
            _presentReleasing = false;
            _upper = null;
            if (motionPlayer != null && motionPlayer.IsReady)
            {
                motionPlayer.FadeOut(MotionPlayer.UpperLayer, nodFade);
                motionPlayer.FadeOut(MotionPlayer.RightArmLayer, presentFade);
            }

            Log("coreografía suspendida");
        }

        /// <summary>
        /// Devuelve el cuerpo al coreógrafo. Si <paramref name="body"/> ya está
        /// sonando el bucle base del estado actual (Sonia acaba de llegar en
        /// reposo), se adopta tal cual para no reiniciarlo; si no, se entra en el
        /// estado con un fundido de <paramref name="fade"/> segundos. El primer
        /// gesto de atención espera lo de siempre, para que no se ponga a bailar
        /// nada más volver.
        /// </summary>
        public void Resume(MotionPlayer.Handle body, float fade)
        {
            if (!_suspended)
            {
                return;
            }

            _suspended = false;
            _stateSeconds = 0f;
            _attentionTimer = RandomSpacing();
            if (!Ready)
            {
                return;
            }

            AnimationClip loop = BaseLoopOf(_state);
            if (body != null && body.IsCurrent && loop != null && body.Clip == loop)
            {
                _body = body;
                _phase = Phase.Base;
                _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                Log("coreografía de vuelta, sigue el bucle " + loop.name);
                return;
            }

            EnterState(_state, Mathf.Max(0.05f, fade), false);
            Log("coreografía de vuelta en " + _state);
        }

        private AnimationClip BaseLoopOf(AvatarState state)
        {
            if (motionSet == null)
            {
                return null;
            }

            switch (state)
            {
                case AvatarState.Idle:
                    return motionSet.idleLoop;
                case AvatarState.Listening:
                    return ConversationLoop(motionSet.listeningLoop);
                case AvatarState.Thinking:
                    return ConversationLoop(motionSet.thinkingLoop);
                default:
                    return singleConversationLoop ? motionSet.idleLoop : null;
            }
        }

        /// <summary>Bucle de un estado de conversación: el reposo de idle con un solo reposo largo, si no el suyo.</summary>
        private AnimationClip ConversationLoop(AnimationClip own)
        {
            if (singleConversationLoop || own == null)
            {
                return motionSet.idleLoop;
            }

            return own;
        }

        /// <summary>
        /// Empieza a presentar una imagen: levanta la mano y señala con el índice
        /// (capa de torso, así sigue hablando o en reposo con las piernas y el
        /// resto). El gesto se congela al llegar arriba y se sostiene hasta
        /// <see cref="EndPresent"/>. Devuelve falso si no hay clip.
        /// </summary>
        public bool BeginPresent()
        {
            if (!Ready || _suspended || motionSet.present == null)
            {
                return false;
            }

            _presentHolding = false;
            _presentReleasing = false;
            StopTalkGesture();
            // Solo el brazo derecho: el torso, la cabeza y el otro brazo siguen el
            // bucle base del estado, que además se queda sin variaciones ni
            // gestos mientras dure la presentación (ver UpdateIdle/UpdateSpeaking).
            _present = motionPlayer.Play(motionSet.present, MotionPlayer.RightArmLayer, presentFade);
            if (_phase != Phase.Base && _phase != Phase.Greeting)
            {
                // Una variación o un gesto de atención a medias se corta: el cuerpo
                // vuelve a la base para no bailar mientras señala.
                EndOneShot();
            }

            Log("presenta una imagen: " + motionSet.present.name);
            return true;
        }

        /// <summary>Suelta el gesto de presentar: la mano termina de bajar y la capa de torso se apaga.</summary>
        public void EndPresent()
        {
            if (_present == null)
            {
                return;
            }

            if (_present.IsAlive)
            {
                _present.SetSpeed(1f);
                _presentReleasing = true;
            }
            else
            {
                _present = null;
            }

            _presentHolding = false;
        }

        /// <summary>Cierto mientras la mano está arriba, congelada señalando.</summary>
        public bool IsPresentHolding
        {
            get { return _presentHolding && _present != null && _present.IsAlive; }
        }

        /// <summary>Cierto mientras dura el gesto de presentar (subiendo, sostenido o bajando).</summary>
        public bool IsPresenting
        {
            get { return _present != null && _present.IsAlive; }
        }

        /// <summary>Animator humano que mueve el reproductor (para huesos de referencia).</summary>
        public Animator MotionPlayerAnimator
        {
            get { return motionPlayer != null ? motionPlayer.Animator : null; }
        }

        /// <summary>Punta del índice de la mano que presenta, o null si no hay Animator humano.</summary>
        public Transform PresentAnchor
        {
            get
            {
                Animator animator = motionPlayer != null ? motionPlayer.Animator : null;
                if (animator == null || !animator.isHuman)
                {
                    return null;
                }

                Transform tip = animator.GetBoneTransform(HumanBodyBones.RightIndexDistal);
                return tip != null ? tip : animator.GetBoneTransform(HumanBodyBones.RightHand);
            }
        }

        private void UpdatePresent()
        {
            if (_present == null)
            {
                return;
            }

            if (!_present.IsAlive)
            {
                _present = null;
                _presentHolding = false;
                _presentReleasing = false;
                return;
            }

            if (_presentReleasing)
            {
                if (_present.Remaining <= presentFade)
                {
                    motionPlayer.FadeOut(MotionPlayer.RightArmLayer, presentFade);
                    _present = null;
                    _presentReleasing = false;
                }

                return;
            }

            if (!_presentHolding && _present.Time >= SoniaAnimations.PresentHoldTime)
            {
                _present.SetSpeed(0f);
                _presentHolding = true;
            }
        }

        /// <summary>
        /// Gesto de reacción (trivia: celebrar un acierto, lamentar un fallo,
        /// bailar al ganar). Como <see cref="Preview"/>, pero suena entero aunque
        /// Sonia pase a pensar o a hablar mientras tanto; al terminar, vuelve al
        /// estado que toque.
        /// </summary>
        public void PlayReaction(AnimationClip clip)
        {
            if (!Ready || _suspended || clip == null || clip.isLooping)
            {
                return;
            }

            StopTalkGesture();
            HideGenieBody(gestureFade);
            _phase = Phase.Reaction;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
            Log("reacción: " + clip.name);
        }

        /// <summary>
        /// Previsualiza un clip del set (panel de animaciones). Un bucle base se
        /// convierte en el bucle activo; cualquier otro clip se reproduce una vez
        /// sobre el cuerpo (o sobre el torso, si es un asentimiento) y se vuelve a
        /// la base del estado actual.
        /// </summary>
        public void Preview(AnimationClip clip, bool upperBody = false)
        {
            if (!Ready || _suspended || clip == null)
            {
                return;
            }

            if (upperBody)
            {
                _upper = motionPlayer.Play(clip, MotionPlayer.UpperLayer, nodFade);
                return;
            }

            StopTalkGesture();
            HideGenieBody(gestureFade);
            if (clip.isLooping)
            {
                _phase = Phase.Base;
                PlayLoop(clip, stateFade);
                return;
            }

            bool attentionLike = System.Array.Exists(
                motionSet.attention, m => m != null && m.clip == clip) || clip == motionSet.greeting;
            _phase = attentionLike ? Phase.Attention : Phase.Variation;
            _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
            Log("previsualización: " + clip.name);
        }

        /// <summary>Lanza un gesto de atención al azar (según los pesos). Solo en idle.</summary>
        public void PlayRandomAttention()
        {
            if (_suspended || _state != AvatarState.Idle)
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
            if (!Ready || _suspended || _state != AvatarState.Idle)
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
            if (!Ready || _suspended || _state != AvatarState.Idle || index < 0 || index >= motionSet.attention.Length)
            {
                return;
            }

            AttentionMotion motion = motionSet.attention[index];
            if (motion == null || motion.clip == null)
            {
                return;
            }

            StopTalkGesture();
            _lastAttention = index;
            _attentionTimer = RandomSpacing();
            if (GenieBody && motion.category != AttentionCategory.Dance)
            {
                GeniesGestureSet set = _gestures.Set;
                string[] list = motion.category == AttentionCategory.FourthWall ? set.fourthWall : set.bored;
                if (StartGenieAction(set.Pick(list, _lastGenieAction), Phase.Attention, "atención " + motion.category))
                {
                    _variationTimer = Random.Range(boredInterval.x, boredInterval.y);
                    return;
                }
            }

            HideGenieBody(gestureFade);
            _phase = Phase.Attention;
            _body = motionPlayer.Play(motion.clip, MotionPlayer.BodyLayer, gestureFade);
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
            if (_state == AvatarState.Idle)
            {
                _quietSeconds = Mathf.Min(MaxTrackedSeconds, _quietSeconds + dt);
            }

            if (!Ready || _suspended)
            {
                return;
            }

            UpdatePresent();

            // Un gesto de una sola vez ha terminado (o casi): vuelta a la base.
            if (_phase != Phase.Base)
            {
                bool done = _genieAction
                    ? _gestures == null || !_gestures.IsActionPlaying || _gestures.ActionRemaining <= gestureFade
                    : _body == null || !_body.IsAlive || _body.Remaining <= FadeForReturn();
                if (done)
                {
                    EndOneShot();
                }

                return;
            }

            EnsureGenieRest(stateFade);
            if (TryStartPonder())
            {
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
            return gestureFade;
        }

        private void EndOneShot()
        {
            bool wasWide = _phase == Phase.Attention || _phase == Phase.Greeting;
            _phase = Phase.Base;
            // La acción de Genies termina sola con su fundido sobre el reposo.
            _genieAction = false;
            if (wasWide)
            {
                _wideUntil = Time.time + gestureFade;
            }

            EnterState(_state, gestureFade, false);
        }

        private float RandomSpacing()
        {
            return Random.Range(Mathf.Min(attentionSpacing.x, attentionSpacing.y), Mathf.Max(attentionSpacing.x, attentionSpacing.y));
        }

        private void UpdateIdle(float dt)
        {
            EnsureLoop(motionSet.idleLoop, stateFade);

            if (IsPresenting)
            {
                // Presentando una imagen: solo el bucle base, sin variaciones ni
                // gestos de atención, que con el brazo señalando quedan absurdos.
                return;
            }

            // Entre turnos el estado también es idle: hasta que el stand lleva un
            // rato en calma no hay gestos ni variaciones (con alguien delante,
            // Sonia no se pone a bailar). El primero llega poco después.
            if (_quietSeconds < attentionQuietDelay)
            {
                return;
            }

            if (!_quietArmed)
            {
                _quietArmed = true;
                _attentionTimer = Random.Range(0f, Mathf.Max(0.1f, Mathf.Min(attentionSpacing.x, attentionSpacing.y) * 0.5f));
            }

            _attentionTimer -= dt;
            if (_attentionTimer <= 0f)
            {
                int index = PickAttention();
                if (index >= 0)
                {
                    PlayAttention(index);
                    return;
                }

                _attentionTimer = RandomSpacing();
            }

            _variationTimer -= dt;
            if (_variationTimer <= 0f && GenieBody)
            {
                // Aburrimiento de Genies: otra pose de reposo un rato, sobre el reposo base.
                _variationTimer = Random.Range(boredInterval.x, boredInterval.y);
                StartGenieAction(_gestures.Set.Pick(_gestures.Set.bored, _lastGenieAction), Phase.Variation, "aburrimiento de Genies");
                return;
            }

            if (_variationTimer <= 0f)
            {
                _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                AnimationClip clip = PickDifferent(motionSet.idleVariations, _lastVariation);
                if (clip != null)
                {
                    _lastVariation = clip;
                    _phase = Phase.Variation;
                    _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
                    Log("variación de reposo: " + clip.name);
                }
            }
        }

        private void UpdateListening(float dt)
        {
            EnsureLoop(ConversationLoop(motionSet.listeningLoop), stateFade);

            if (IsPresenting || singleConversationLoop)
            {
                // Presentando una imagen, o con un solo reposo largo: sin asentimientos
                // de clip (la cabeza asiente por código en AvatarStateController).
                return;
            }

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
            EnsureLoop(ConversationLoop(motionSet.thinkingLoop), stateFade);
            if (IsPresenting || singleConversationLoop)
            {
                return;
            }

            _variationTimer -= dt;
            if (_variationTimer <= 0f)
            {
                _variationTimer = Random.Range(thinkingVariationInterval.x, thinkingVariationInterval.y);
                AnimationClip clip = PickDifferent(motionSet.thinkingVariations, _lastVariation);
                if (clip != null)
                {
                    _lastVariation = clip;
                    _phase = Phase.Variation;
                    _body = motionPlayer.Play(clip, MotionPlayer.BodyLayer, gestureFade);
                    Log("variación de pensar: " + clip.name);
                }
            }
        }

        private void UpdateSpeaking()
        {
            UpdateTalkFillers();

            if (singleConversationLoop)
            {
                // Un solo reposo largo: se habla desde él, sin gesticulación de clip.
                EnsureLoop(motionSet.idleLoop, speakFade);
                return;
            }

            if (_speechPaused || IsPresenting)
            {
                // Sin audio, o señalando una imagen: espera atenta en vez de gesticular.
                EnsureLoop(motionSet.listeningLoop != null ? motionSet.listeningLoop : motionSet.idleLoop, speakFade);
                return;
            }

            if (_body == null || !_body.IsAlive || _body.Remaining <= talkingChainFade)
            {
                PlayNextTalking(_body == null || !_body.IsAlive ? speakFade : talkingChainFade);
            }
        }

        // ------------------------------------------------------------------
        // Reproducción
        // ------------------------------------------------------------------

        /// <summary>
        /// Arranca el movimiento base de un estado. Si el bucle del estado nuevo
        /// es el que ya suena (pensar y hablar comparten reposo con idle), sigue
        /// donde iba: un fundido del mismo clip consigo mismo en otro punto
        /// mezclaría dos fases del traspaso de peso.
        /// </summary>
        private void EnterState(AvatarState state, float fade, bool initial)
        {
            if (!Ready)
            {
                return;
            }

            _phase = Phase.Base;
            if (_genieAction && _gestures != null)
            {
                _gestures.StopActions(fade);
            }

            _genieAction = false;
            EnsureGenieRest(fade);
            switch (state)
            {
                case AvatarState.Idle:
                    _attentionTimer = initial ? RandomSpacing() : Mathf.Max(_attentionTimer, 0.5f);
                    _variationTimer = Random.Range(idleVariationInterval.x, idleVariationInterval.y);
                    EnsureLoop(motionSet.idleLoop, fade);
                    break;
                case AvatarState.Listening:
                    _nodTimer = Random.Range(nodInterval.x, nodInterval.y);
                    EnsureLoop(ConversationLoop(motionSet.listeningLoop), fade);
                    break;
                case AvatarState.Thinking:
                    _variationTimer = Random.Range(thinkingVariationInterval.x, thinkingVariationInterval.y);
                    EnsureLoop(ConversationLoop(motionSet.thinkingLoop), fade);
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
            _body = motionPlayer.Play(loop, MotionPlayer.BodyLayer, fade, loop.isLooping ? _loopSpeed : 1f, start);
        }

        private void PlayNextTalking(float fade)
        {
            AnimationClip clip = singleConversationLoop ? null : PickDifferent(motionSet.talking, _lastTalking);
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
