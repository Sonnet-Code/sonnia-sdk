// Reparte los mensajes de los juegos (docs/plan-juegos.md, 4.2 y 4.3).
//
// - El sobre común "game" va al controlador cuyo Id coincide con "game". "start"
//   abre la partida; "end" la cierra (IGameController.OnEnd); el resto son
//   eventos propios de cada juego y solo llegan con la partida abierta.
// - Tras reconectar, el orquestador repite sus mensajes fijos (el start de la
//   partida y el último estado) con su seq original: lo ya visto de la partida en
//   marcha se ignora. Si en replayGraceSeconds tras el hello no vuelve a llegar
//   nada de ella, la partida terminó mientras no había conexión y se cancela,
//   como hace la trivia.
// - Un start de otro juego con una partida abierta la cancela en pantalla: el
//   orquestador solo lleva un juego cada vez.
// - camera_preview y los frames "SNCV" van a la vista en vivo (CameraPreviewPanel).
// - Los controladores de GameRegistry se añaden por código a este mismo objeto en
//   Awake y sus ids se anuncian en client_hello (games), junto con la vista en
//   vivo (features), antes de que el cliente conecte.
// - Mientras hay partida, Sonia no saluda sola (como en la trivia).

using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Sonia
{
    /// <summary>Recibe los mensajes de los juegos y los reparte entre sus controladores.</summary>
    [DisallowMultipleComponent]
    public class GameRouter : MonoBehaviour
    {
        [SerializeField]
        [Range(0.5f, 10f)]
        [Tooltip("Tras reconectar, si en este tiempo no vuelve a llegar la partida en marcha, ya no existe y se retira.")]
        private float replayGraceSeconds = 2.5f;

        [SerializeField]
        [Tooltip("Escribir en la consola los eventos de los juegos.")]
        private bool logEvents = true;

        private SoniaClient _client;
        private GameHud _hud;
        private CameraPreviewPanel _preview;
        private AvatarChoreographer _choreographer;
        private TriviaController _trivia;

        private readonly Dictionary<string, IGameController> _controllers = new Dictionary<string, IGameController>();
        private readonly List<string> _ids = new List<string>();
        private readonly HashSet<string> _warned = new HashSet<string>();

        // Partida en marcha según el orquestador y los seq ya vistos de ella.
        private IGameController _running;
        private readonly HashSet<long> _seen = new HashSet<long>();
        private float _awaitReplayUntil = -1f;

        /// <summary>Ids de los juegos registrados (los que se anuncian en client_hello).</summary>
        public IReadOnlyList<string> GameIds
        {
            get { return _ids; }
        }

        /// <summary>La partida en marcha, o null. Un juego que enseña su resultado tras <c>end</c> ya no cuenta.</summary>
        public IGameController Running
        {
            get { return _running; }
        }

        /// <summary>Cierto si algún juego tiene algo en pantalla.</summary>
        public bool AnyActive
        {
            get
            {
                foreach (IGameController controller in _controllers.Values)
                {
                    if (controller.IsActive)
                    {
                        return true;
                    }
                }

                return false;
            }
        }

        /// <summary>Lo común de pantalla de los juegos.</summary>
        public GameHud Hud
        {
            get { return _hud; }
        }

        /// <summary>La vista en vivo de la cámara.</summary>
        public CameraPreviewPanel Preview
        {
            get { return _preview; }
        }

        /// <summary>Empieza una partida (tras su <c>start</c>).</summary>
        public event Action<IGameController> GameStarted;

        /// <summary>Termina una partida, con su resultado (win, lose o cancel).</summary>
        public event Action<IGameController, string> GameEnded;

        private void Awake()
        {
            _client = GetComponentInChildren<SoniaClient>(true);
            _choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            _hud = GetComponent<GameHud>();
            if (_hud == null)
            {
                _hud = gameObject.AddComponent<GameHud>();
            }

            _preview = GetComponent<CameraPreviewPanel>();
            if (_preview == null)
            {
                _preview = gameObject.AddComponent<CameraPreviewPanel>();
            }

            foreach (Type type in GameRegistry.Controllers)
            {
                if (type == null || !typeof(MonoBehaviour).IsAssignableFrom(type) || !typeof(IGameController).IsAssignableFrom(type))
                {
                    Debug.LogWarning("[Sonia] GameRegistry: " + type + " no es un controlador de juego.", this);
                    continue;
                }

                Component component = GetComponent(type);
                if (component == null)
                {
                    component = gameObject.AddComponent(type);
                }

                Register((IGameController)component);
            }

            Announce();
        }

        private void OnEnable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnHello += HandleHello;
            _client.OnGame += HandleGame;
            _client.OnCameraPreview += HandleCameraPreview;
            _client.OnCameraPreviewFrame += HandleCameraPreviewFrame;
        }

        private void OnDisable()
        {
            if (_client == null)
            {
                return;
            }

            _client.OnHello -= HandleHello;
            _client.OnGame -= HandleGame;
            _client.OnCameraPreview -= HandleCameraPreview;
            _client.OnCameraPreviewFrame -= HandleCameraPreviewFrame;
        }

        private void Start()
        {
            _trivia = GetComponent<TriviaController>();
        }

        /// <summary>
        /// Registra un controlador. Los de <see cref="GameRegistry"/> se registran
        /// solos; uno de fuera tiene que hacerlo en su Awake, antes de conectar, para
        /// salir en client_hello.
        /// </summary>
        public void Register(IGameController controller)
        {
            if (controller == null || string.IsNullOrEmpty(controller.Id))
            {
                return;
            }

            if (!Protocol.IsValidGameName(controller.Id))
            {
                Debug.LogWarning("[Sonia] Id de juego inválido: " + controller.Id, this);
                return;
            }

            if (!_controllers.ContainsKey(controller.Id))
            {
                _ids.Add(controller.Id);
            }

            _controllers[controller.Id] = controller;
            Announce();
        }

        /// <summary>El controlador de un juego, o null.</summary>
        public IGameController Find(string gameId)
        {
            IGameController controller;
            return gameId != null && _controllers.TryGetValue(gameId, out controller) ? controller : null;
        }

        /// <summary>Manda un evento de un juego al orquestador (<c>game_event</c>). <paramref name="data"/> puede ser null.</summary>
        public void Send(string gameId, string eventName, JObject data)
        {
            if (_client == null)
            {
                return;
            }

            _client.SendGameEvent(gameId, eventName, data ?? new JObject());
            Log(gameId + " → " + eventName);
        }

        /// <summary>Como <see cref="Send(string, string, JObject)"/> con un objeto cualquiera (se serializa con Newtonsoft).</summary>
        public void Send(string gameId, string eventName, object data)
        {
            JObject json = null;
            if (data is JObject asObject)
            {
                json = asObject;
            }
            else if (data != null)
            {
                try
                {
                    json = JObject.FromObject(data);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning("[Sonia] game_event " + gameId + "/" + eventName + ": data no es un objeto JSON (" + ex.Message + ")", this);
                    return;
                }
            }

            Send(gameId, eventName, json);
        }

        private void Announce()
        {
            if (_client != null)
            {
                _client.SetAnnouncement(_ids, new[] { ClientFeatures.CameraPreview });
            }
        }

        // ------------------------------------------------------------------
        // Mensajes
        // ------------------------------------------------------------------

        private void HandleHello(HelloMessage message)
        {
            // Si la partida terminó sin conexión, el orquestador no repetirá sus fijos.
            if (_running != null)
            {
                _awaitReplayUntil = Time.unscaledTime + replayGraceSeconds;
            }

            if (_preview != null)
            {
                _preview.HandleReconnect();
            }
        }

        private void HandleGame(GameMessage message)
        {
            if (message == null)
            {
                return;
            }

            IGameController controller = Find(message.Game);
            if (controller == null)
            {
                if (_warned.Add(message.Game ?? string.Empty))
                {
                    Debug.LogWarning("[Sonia] Juego desconocido en esta Unity: " + message.Game, this);
                }

                return;
            }

            bool running = ReferenceEquals(controller, _running);
            if (running && message.Seq > 0 && _seen.Contains(message.Seq))
            {
                // Un fijo repetido tras reconectar: la partida sigue, ya está pintado.
                _awaitReplayUntil = -1f;
                return;
            }

            if (message.Event == GameEvents.End)
            {
                if (running || controller.IsActive)
                {
                    Log(message.Game + ": end " + ResultOf(message.DataJson));
                    Finish(controller, ResultOf(message.DataJson), message.DataJson);
                }

                return;
            }

            if (message.Event == GameEvents.Start)
            {
                // Otro juego en pantalla (en marcha o enseñando su resultado): fuera.
                CancelOthers(controller);
                _running = controller;
                _seen.Clear();
                _awaitReplayUntil = -1f;
                if (message.Seq > 0)
                {
                    _seen.Add(message.Seq);
                }

                SetGreetingSuppressed(true);
                Log(message.Game + ": start");
                Deliver(controller, message.Event, message.DataJson);
                Raise(GameStarted, controller);
                return;
            }

            if (!running)
            {
                // Sin su start no hay partida (el orquestador siempre lo manda antes).
                Log(message.Game + ": " + message.Event + " sin partida abierta, se ignora");
                return;
            }

            _awaitReplayUntil = -1f;
            if (message.Seq > 0)
            {
                _seen.Add(message.Seq);
            }

            Deliver(controller, message.Event, message.DataJson);
        }

        private void HandleCameraPreview(CameraPreviewMessage message)
        {
            if (_preview != null && message != null)
            {
                _preview.HandleSwitch(message);
            }
        }

        private void HandleCameraPreviewFrame(PreviewFrame frame)
        {
            if (_preview != null && frame != null)
            {
                _preview.HandleFrame(frame);
            }
        }

        private void Update()
        {
            if (_awaitReplayUntil > 0f && Time.unscaledTime > _awaitReplayUntil)
            {
                _awaitReplayUntil = -1f;
                if (_running != null)
                {
                    Log("tras reconectar no volvió " + _running.Id + ": se cancela");
                    Finish(_running, GameResults.Cancel, "{}");
                }
            }
        }

        // ------------------------------------------------------------------
        // Partidas
        // ------------------------------------------------------------------

        private void CancelOthers(IGameController keep)
        {
            foreach (IGameController other in _controllers.Values)
            {
                if (!ReferenceEquals(other, keep) && (ReferenceEquals(other, _running) || other.IsActive))
                {
                    Finish(other, GameResults.Cancel, "{}");
                }
            }
        }

        private void Finish(IGameController controller, string result, string dataJson)
        {
            if (ReferenceEquals(controller, _running))
            {
                _running = null;
                _seen.Clear();
                _awaitReplayUntil = -1f;
                SetGreetingSuppressed(false);
            }

            try
            {
                controller.OnEnd(result, string.IsNullOrEmpty(dataJson) ? "{}" : dataJson);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }

            Raise(GameEnded, controller, result);
        }

        private void Deliver(IGameController controller, string eventName, string dataJson)
        {
            try
            {
                controller.OnEvent(eventName, string.IsNullOrEmpty(dataJson) ? "{}" : dataJson);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void SetGreetingSuppressed(bool suppressed)
        {
            if (_choreographer == null)
            {
                return;
            }

            // La trivia también lo pide; no se suelta si sigue en marcha.
            if (!suppressed && _trivia != null && _trivia.IsActive)
            {
                return;
            }

            _choreographer.GreetingSuppressed = suppressed;
        }

        /// <summary><c>data.result</c> del evento end: win, lose o cancel (cualquier otra cosa cuenta como cancel).</summary>
        public static string ResultOf(string dataJson)
        {
            try
            {
                JObject data = string.IsNullOrEmpty(dataJson) ? null : JObject.Parse(dataJson);
                string result = data != null ? data.Value<string>("result") : null;
                if (result == GameResults.Win || result == GameResults.Lose)
                {
                    return result;
                }
            }
            catch (JsonException)
            {
                // Mal formado: se cancela.
            }

            return GameResults.Cancel;
        }

        private void Raise(Action<IGameController> handler, IGameController controller)
        {
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(controller);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void Raise(Action<IGameController, string> handler, IGameController controller, string result)
        {
            if (handler == null)
            {
                return;
            }

            try
            {
                handler(controller, result);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }

        private void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] Juegos: " + message, this);
            }
        }
    }
}
