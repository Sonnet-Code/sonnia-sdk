// Base de los controladores de los juegos: lo que se repite en todos.
//
// - start: abre la pantalla común (GameHud.Open) con data.title (o DefaultTitle)
//   y llama a OnStart. Un start con el juego ya en pantalla es otra partida:
//   primero OnClosed, para dejarlo limpio.
// - El resto de eventos llegan a OnGameEvent, solo con la partida abierta.
// - end: OnFinish y la pantalla se retira. Si el juego no enseñó su resultado
//   final (GameHud.ShowResult) y es win o lose, sale uno genérico unos segundos;
//   con cancel se retira al momento. Al terminar de retirarse, OnClosed.
// - Ayudas: Send (game_event), ParseData (data a una clase propia), PlayReaction
//   y ShowEmotion (como la trivia), Content y Layer (lo del juego en la pantalla).
//
// Cada juego hereda de aquí en su carpeta (Games/<Juego>/), lee su data con sus
// propias clases y monta su pantalla dentro de Content o Layer.

using System;
using System.Collections;
using Newtonsoft.Json;
using UnityEngine;

namespace Sonia
{
    /// <summary>data del evento start (lo común; cada juego añade lo suyo en su clase).</summary>
    [Serializable]
    public class GameStartData
    {
        /// <summary>Título en pantalla («Wordle de tecnología»). Siempre lo manda el orquestador.</summary>
        [JsonProperty("title")] public string Title;
    }

    /// <summary>data del evento end (lo común).</summary>
    [Serializable]
    public class GameEndData
    {
        /// <summary>win, lose o cancel.</summary>
        [JsonProperty("result")] public string Result;
    }

    /// <summary>Controlador de un juego con lo común ya hecho. Heredar e implementar <see cref="OnGameEvent"/>.</summary>
    public abstract class GameControllerBase : MonoBehaviour, IGameController
    {
        [Header("Fin de la partida")]
        [SerializeField]
        [Range(0f, 15f)]
        [Tooltip("Segundos del resultado genérico si el juego no enseñó el suyo antes del end.")]
        private float defaultResultSeconds = 3.5f;

        [SerializeField]
        [Range(0f, 5f)]
        [Tooltip("Segundos que se queda la pantalla tras el end cuando el juego ya enseñó su resultado.")]
        private float lingerSeconds = 0.6f;

        [SerializeField]
        [Tooltip("Escribir en la consola los eventos del juego.")]
        private bool logEvents = true;

        private bool _active;
        private bool _ending;
        private Coroutine _closer;

        /// <summary>Id del juego en el protocolo.</summary>
        public abstract string Id { get; }

        /// <summary>Título si el start no trae data.title.</summary>
        protected virtual string DefaultTitle
        {
            get { return Id; }
        }

        /// <summary>Cierto desde el start hasta que la pantalla se retira (también durante el resultado).</summary>
        public bool IsActive
        {
            get { return _active; }
        }

        /// <summary>Cierto entre el end y que la pantalla termine de retirarse.</summary>
        protected bool IsEnding
        {
            get { return _ending; }
        }

        /// <summary>Título de la partida en curso.</summary>
        protected string Title { get; private set; }

        protected GameRouter Router { get; private set; }

        protected GameHud Hud { get; private set; }

        protected CameraPreviewPanel Preview { get; private set; }

        protected AvatarChoreographer Choreographer { get; private set; }

        protected FacialExpressionController Face { get; private set; }

        /// <summary>El contenedor de este juego en la tarjeta (bajo la cabecera). Ver <see cref="GameHud.ContentOf"/>.</summary>
        protected RectTransform Content
        {
            get { return Hud != null ? Hud.ContentOf(Id) : null; }
        }

        /// <summary>La capa a pantalla completa de este juego. Ver <see cref="GameHud.LayerOf"/>.</summary>
        protected RectTransform Layer
        {
            get { return Hud != null ? Hud.LayerOf(Id) : null; }
        }

        protected virtual void Awake()
        {
            Router = GetComponent<GameRouter>();
            Hud = GetComponent<GameHud>();
            Preview = GetComponent<CameraPreviewPanel>();
            Choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            Face = GetComponentInChildren<FacialExpressionController>(true);
        }

        // ------------------------------------------------------------------
        // IGameController (lo llama GameRouter)
        // ------------------------------------------------------------------

        /// <summary>Lo llama GameRouter. Los juegos implementan <see cref="OnStart"/> y <see cref="OnGameEvent"/>.</summary>
        public void OnEvent(string eventName, string dataJson)
        {
            if (eventName == GameEvents.Start)
            {
                if (_active)
                {
                    // Otra partida del mismo juego: se limpia lo de la anterior.
                    StopCloser();
                    SafeCall(OnClosed);
                }

                _active = true;
                _ending = false;
                GameStartData start = ParseData<GameStartData>(dataJson);
                Title = !string.IsNullOrEmpty(start.Title) ? start.Title : DefaultTitle;
                if (Hud != null)
                {
                    Hud.Open(Id, Title);
                }

                Log("empieza: " + Title);
                try
                {
                    OnStart(dataJson);
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex, this);
                }

                return;
            }

            if (!_active || _ending)
            {
                return;
            }

            OnGameEvent(eventName, dataJson);
        }

        /// <summary>Lo llama GameRouter con el end (o al cancelar Unity por su cuenta).</summary>
        public void OnEnd(string result, string dataJson)
        {
            if (!_active)
            {
                return;
            }

            bool cancel = result != GameResults.Win && result != GameResults.Lose;
            if (_ending)
            {
                // Ya enseñaba su final: otro juego pide la pantalla.
                if (cancel)
                {
                    CloseNow();
                }

                return;
            }

            _ending = true;
            Log("termina: " + result);
            try
            {
                OnFinish(result, string.IsNullOrEmpty(dataJson) ? "{}" : dataJson);
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }

            if (cancel || Hud == null)
            {
                CloseNow();
                return;
            }

            float wait = lingerSeconds;
            if (!Hud.IsResultShown)
            {
                try
                {
                    ShowDefaultResult(result, dataJson);
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex, this);
                }

                wait = defaultResultSeconds;
            }

            StopCloser();
            _closer = StartCoroutine(CloseLater(wait));
        }

        // ------------------------------------------------------------------
        // Lo que implementa cada juego
        // ------------------------------------------------------------------

        /// <summary>Empieza la partida: la tarjeta ya está abierta con el título. <paramref name="dataJson"/> es el data del start.</summary>
        protected virtual void OnStart(string dataJson)
        {
        }

        /// <summary>Un evento propio del juego, con la partida abierta.</summary>
        protected abstract void OnGameEvent(string eventName, string dataJson);

        /// <summary>
        /// Llega el end (win, lose o cancel). Si el juego quiere su propio final y aún
        /// no lo enseñó, este es el sitio (<see cref="GameHud.ShowResult"/>).
        /// </summary>
        protected virtual void OnFinish(string result, string dataJson)
        {
        }

        /// <summary>
        /// La pantalla se retiró (o empieza otra partida del mismo juego): dejarlo todo
        /// como al principio y apagar lo que el juego encendiera (vista en vivo,
        /// marcas, poses de Sonnia...).
        /// </summary>
        protected virtual void OnClosed()
        {
        }

        /// <summary>Resultado genérico si el juego no enseñó el suyo antes del end.</summary>
        protected virtual void ShowDefaultResult(string result, string dataJson)
        {
            if (result == GameResults.Win)
            {
                Hud.ShowResult("¡GANASTE!", null, "¡Eres un crack del DevFest!", true);
                PlayReaction("QuickAction_vibe", null);
                ShowEmotion(FacialExpressionController.Emotion.Joy, 4f);
            }
            else
            {
                Hud.ShowResult("¡CASI!", null, "¡Pídeme otra partida y lo intentas otra vez!", false);
                PlayReaction("emotions-0049-traitsKind", "Peace");
                ShowEmotion(FacialExpressionController.Emotion.Joy, 2f);
            }
        }

        // ------------------------------------------------------------------
        // Ayudas
        // ------------------------------------------------------------------

        /// <summary>Manda un evento de este juego al orquestador (<c>game_event</c>). <paramref name="data"/>: objeto, JObject o null.</summary>
        protected void Send(string eventName, object data = null)
        {
            if (Router != null)
            {
                Router.Send(Id, eventName, data);
            }
        }

        /// <summary>
        /// Lee el data de un evento a una clase propia (campos con [JsonProperty]).
        /// Nunca devuelve null: si no se puede leer, una instancia vacía y un aviso.
        /// </summary>
        public static T ParseData<T>(string dataJson) where T : class, new()
        {
            if (string.IsNullOrEmpty(dataJson))
            {
                return new T();
            }

            try
            {
                T value = JsonConvert.DeserializeObject<T>(dataJson);
                return value ?? new T();
            }
            catch (JsonException ex)
            {
                Debug.LogWarning("[Sonia] Juegos: data ilegible para " + typeof(T).Name + ": " + ex.Message);
                return new T();
            }
        }

        /// <summary>Lanza un clip del set de Sonnia como reacción (o el de respaldo si no está). Como la trivia.</summary>
        protected void PlayReaction(string clipName, string fallback)
        {
            if (Choreographer == null)
            {
                return;
            }

            SoniaMotionSet set = Choreographer.MotionSet;
            AnimationCatalog.Entry entry;
            if (!AnimationCatalog.TryFind(set, clipName, out entry) && !AnimationCatalog.TryFind(set, fallback, out entry))
            {
                return;
            }

            Choreographer.PlayReaction(entry.Clip);
        }

        /// <summary>Una emoción pasajera en la cara de Sonnia (alegría, pena, sorpresa).</summary>
        protected void ShowEmotion(FacialExpressionController.Emotion emotion, float seconds)
        {
            if (Face != null)
            {
                Face.ShowEmotion(emotion, seconds);
            }
        }

        protected void Log(string message)
        {
            if (logEvents)
            {
                Debug.Log("[Sonia] " + Id + ": " + message, this);
            }
        }

        private IEnumerator CloseLater(float seconds)
        {
            if (seconds > 0f)
            {
                yield return new WaitForSeconds(seconds);
            }

            _closer = null;
            CloseNow();
        }

        private void CloseNow()
        {
            StopCloser();
            if (!_active)
            {
                return;
            }

            _active = false;
            _ending = false;
            if (Hud != null)
            {
                Hud.Close(Id);
            }

            SafeCall(OnClosed);
        }

        private void StopCloser()
        {
            if (_closer != null)
            {
                StopCoroutine(_closer);
                _closer = null;
            }
        }

        private void SafeCall(Action action)
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }
    }
}
