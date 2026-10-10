// Protocolo WebSocket entre el orquestador y Unity (versión 1).
//
// Este archivo es el espejo en C# de server/sonia/ws/protocol.py y de
// docs/protocolo.md. Si cambia el protocolo, se actualizan los tres a la vez.
//
// Nada de este archivo toca la API de Unity: se puede usar sin problema desde
// el hilo del socket.

using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Sonia
{
    /// <summary>Nombres de los mensajes JSON del protocolo.</summary>
    public static class MessageTypes
    {
        // Del orquestador hacia Unity.
        public const string Hello = "hello";
        public const string State = "state";
        public const string Transcript = "transcript";
        public const string SpeechStart = "speech_start";
        public const string Visemes = "visemes";
        public const string Envelope = "envelope";
        public const string SpeechEnd = "speech_end";
        public const string StopSpeaking = "stop_speaking";
        public const string ShowImage = "show_image";
        public const string HideImage = "hide_image";
        public const string Error = "error";
        public const string RequestFrame = "request_frame";
        public const string Attention = "attention";
        public const string Presence = "presence";
        public const string StageMode = "stage_mode";
        public const string SetVolume = "set_volume";
        public const string Devices = "devices";
        public const string PlayAnimation = "play_animation";
        public const string Gesture = "gesture";
        public const string SetSubtitles = "set_subtitles";
        public const string SetDisabledAnimations = "set_disabled_animations";
        public const string SetDebug = "set_debug";
        public const string SetTuning = "set_tuning";
        public const string SetAvatar = "set_avatar";
        public const string OpenAvatarEditor = "open_avatar_editor";
        public const string CloseAvatarEditor = "close_avatar_editor";
        public const string SetGuestAvatar = "set_guest_avatar";
        public const string GuestMode = "guest_mode";
        public const string GuestAnimation = "guest_animation";
        public const string TriviaStart = "trivia_start";
        public const string TriviaQuestion = "trivia_question";
        public const string TriviaAnswer = "trivia_answer";
        public const string TriviaEnd = "trivia_end";
        public const string Activity = "activity";

        /// <summary>Aviso de espera en pantalla (<see cref="BusyMessage"/>): lo pinta <see cref="BusyIndicator"/>.</summary>
        public const string Busy = "busy";

        /// <summary>Sobre común de los juegos (docs/plan-juegos.md): lo reparte <see cref="GameRouter"/>.</summary>
        public const string Game = "game";

        /// <summary>Enciende o apaga la vista en vivo de la cámara (frames binarios "SNCV").</summary>
        public const string CameraPreview = "camera_preview";

        /// <summary>
        /// Solo del orquestador falso de las pruebas (scripts/juegos_demo.py): la
        /// herramienta de capturas en batch guarda una captura con ese nombre.
        /// </summary>
        public const string DevCapture = "dev_capture";

        /// <summary>Solo del orquestador falso: la herramienta de capturas en batch termina.</summary>
        public const string DevDone = "dev_done";

        // De Unity hacia el orquestador.
        public const string ClientHello = "client_hello";
        public const string Interrupt = "interrupt";
        public const string PlaybackDone = "playback_done";
        public const string TextInput = "text_input";
        public const string CameraFrame = "camera_frame";
        public const string Animations = "animations";
        public const string GestureCatalog = "gesture_catalog";
        public const string ListDevices = "list_devices";
        public const string SetDevice = "set_device";
        public const string AnimationPlaying = "animation_playing";
        public const string AvatarEditor = "avatar_editor";
        public const string AvatarSaved = "avatar_saved";
        public const string GuestState = "guest_state";

        /// <summary>Un evento de un juego hacia el orquestador (la ruleta se paró...).</summary>
        public const string GameEvent = "game_event";
    }

    /// <summary>Capacidades que Unity anuncia en <c>client_hello.features</c>.</summary>
    public static class ClientFeatures
    {
        /// <summary>Sabe mostrar la vista en vivo de la cámara (<c>camera_preview</c> y frames "SNCV").</summary>
        public const string CameraPreview = "camera_preview";
    }

    /// <summary>Eventos comunes a todos los juegos dentro del sobre <c>game</c>.</summary>
    public static class GameEvents
    {
        /// <summary>Empieza la partida: monta la pantalla del juego. Lleva <c>data.title</c>.</summary>
        public const string Start = "start";

        /// <summary>Fin de la partida: <c>data.result</c> vale win, lose o cancel. Retira la pantalla.</summary>
        public const string End = "end";
    }

    /// <summary>Valores de <c>data.result</c> en el evento <c>end</c>.</summary>
    public static class GameResults
    {
        public const string Win = "win";
        public const string Lose = "lose";
        public const string Cancel = "cancel";
    }

    /// <summary>Valores posibles del campo <c>state</c> del mensaje <c>state</c>.</summary>
    public static class AvatarStateNames
    {
        public const string Idle = "idle";
        public const string Listening = "listening";
        public const string Thinking = "thinking";
        public const string Speaking = "speaking";
    }

    /// <summary>
    /// Identificadores de visema del protocolo (conjunto Oculus, compatible con
    /// Ready Player Me). Son los mismos que produce <c>server/sonia/visemes.py</c>.
    /// </summary>
    public static class VisemeIds
    {
        public const string Sil = "sil";
        public const string PP = "PP";
        public const string FF = "FF";
        public const string TH = "TH";
        public const string DD = "DD";
        public const string KK = "kk";
        public const string CH = "CH";
        public const string SS = "SS";
        public const string NN = "nn";
        public const string RR = "RR";
        public const string AA = "aa";
        public const string E = "E";
        public const string IH = "ih";
        public const string OH = "oh";
        public const string OU = "ou";

        /// <summary>Todos los identificadores, en el orden del documento del protocolo.</summary>
        public static readonly string[] All =
        {
            Sil, PP, FF, TH, DD, KK, CH, SS, NN, RR, AA, E, IH, OH, OU
        };
    }

    /// <summary>Valores posibles del campo <c>source</c> de <c>show_image</c>.</summary>
    public static class ImageSources
    {
        public const string Gallery = "gallery";
    }

    // ------------------------------------------------------------------
    // Mensajes entrantes (orquestador -> Unity)
    // ------------------------------------------------------------------

    /// <summary>Primer mensaje tras conectar: anuncia el formato del audio.</summary>
    [Serializable]
    public class HelloMessage
    {
        [JsonProperty("version")] public int Version = 1;
        [JsonProperty("sample_rate")] public int SampleRate = 24000;
        [JsonProperty("channels")] public int Channels = 1;
        [JsonProperty("format")] public string Format = "pcm_s16le";
    }

    /// <summary>Cambio de estado del asistente: idle, listening, thinking o speaking.</summary>
    [Serializable]
    public class StateMessage
    {
        [JsonProperty("state")] public string State = AvatarStateNames.Idle;
    }

    /// <summary>Texto del usuario o de Sonia, para subtítulos y depuración.</summary>
    [Serializable]
    public class TranscriptMessage
    {
        [JsonProperty("role")] public string Role = "user";
        [JsonProperty("text")] public string Text = string.Empty;
        [JsonProperty("final")] public bool Final;
    }

    /// <summary>Empieza una frase sintetizada; a partir de aquí llegan frames binarios.</summary>
    [Serializable]
    public class SpeechStartMessage
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
        [JsonProperty("text")] public string Text = string.Empty;

        /// <summary>
        /// Frase de la animación de stand: se mueve la boca pero el avatar no
        /// cambia de estado ni interrumpe el baile o el idle.
        /// </summary>
        [JsonProperty("ambient")] public bool Ambient;
    }

    /// <summary>El orquestador pide un gesto de atención (baile, cuarta pared, suave, saludo).</summary>
    [Serializable]
    public class AttentionMessage
    {
        /// <summary>"dance", "fourth_wall", "soft" o "greeting" (saludo con la mano).</summary>
        [JsonProperty("category")] public string Category = "soft";

        /// <summary>Nombre de clip concreto, opcional.</summary>
        [JsonProperty("clip")] public string Clip;
    }

    /// <summary>
    /// El director de gestos del orquestador pide un gesto de Genies
    /// (<see cref="GeniesGestureSet"/>) para acompañar una frase de Sonia.
    /// </summary>
    [Serializable]
    public class GestureMessage
    {
        /// <summary>Nombre del gesto, tal cual va en <c>gesture_catalog</c>.</summary>
        [JsonProperty("name")] public string Name;

        /// <summary>
        /// Frase (<c>speech_start</c>) que acompaña: si ya terminó, se descarta.
        /// Null: para la próxima frase (el gesto de apertura, elegido con lo que
        /// dijo el visitante); se guarda unos segundos.
        /// </summary>
        [JsonProperty("utterance_id")] public int? UtteranceId;
    }

    /// <summary>
    /// El panel (o un movimiento pedido de viva voz) pide un clip concreto del
    /// catálogo que mandó Unity (<see cref="AnimationCatalog"/>).
    /// </summary>
    [Serializable]
    public class PlayAnimationMessage
    {
        /// <summary>Nombre del clip, tal cual va en el mensaje <c>animations</c>.</summary>
        [JsonProperty("clip")] public string Clip;

        /// <summary>
        /// Que suene entero aunque Sonia pase a pensar o a hablar (movimientos por
        /// voz). Sin él, como desde el panel, el cambio de estado lo corta.
        /// </summary>
        [JsonProperty("whole")] public bool Whole;
    }

    /// <summary>Subtítulos en pantalla sí o no (panel, mensaje fijo: se repite tras <c>hello</c>).</summary>
    [Serializable]
    public class SetSubtitlesMessage
    {
        [JsonProperty("enabled")] public bool Enabled = true;
    }

    /// <summary>Clips que Sonia no usa por su cuenta (panel, mensaje fijo). Con <c>play_animation</c> sí suenan.</summary>
    [Serializable]
    public class SetDisabledAnimationsMessage
    {
        [JsonProperty("clips")] public List<string> Clips = new List<string>();
    }

    /// <summary>Modo debug del panel (mensaje fijo): el avatar no lanza gestos, bailes ni variaciones por su cuenta.</summary>
    [Serializable]
    public class SetDebugMessage
    {
        [JsonProperty("enabled")] public bool Enabled;
    }

    /// <summary>
    /// Ajustes de la sección «Developer» del panel (mensaje fijo; se guardan en
    /// la nube y valen para todas las Sonias): la boca y el movimiento en reposo
    /// en multiplicadores de lo que trae la escena y la cámara sobre su plano base.
    /// Un orquestador anterior no manda <c>idle</c>: queda en 1 (tal cual).
    /// </summary>
    [Serializable]
    public class SetTuningMessage
    {
        [JsonProperty("mouth")] public MouthTuning Mouth = new MouthTuning();
        [JsonProperty("camera")] public CameraTuning Camera = new CameraTuning();
        [JsonProperty("idle")] public IdleTuning Idle = new IdleTuning();
    }

    /// <summary>
    /// Aspecto de Sonia (mensaje fijo; se guarda en la nube y vale para todas
    /// las Sonias): definición del avatar de Genies en texto JSON, o null para
    /// el personaje que trae la app.
    /// </summary>
    [Serializable]
    public class SetAvatarMessage
    {
        [JsonProperty("definition")] public string Definition;
    }

    /// <summary>
    /// Aspecto del invitado del Modo Jean (mensaje fijo; ajuste compartido
    /// <c>guest_avatar</c> en la nube): definición de Genies en texto JSON, o null
    /// para el avatar de prueba que trae la app.
    /// </summary>
    [Serializable]
    public class SetGuestAvatarMessage
    {
        [JsonProperty("definition")] public string Definition;
    }

    /// <summary>
    /// Modo Jean: entra el invitado (Sonia lo presenta, se dan la mano y ella se
    /// va) o se despide (vuelve Sonia). Mensaje fijo. Su voz llega en frames
    /// "SNGU" a <see cref="SampleRate"/>.
    /// </summary>
    [Serializable]
    public class GuestModeMessage
    {
        /// <summary>"enter" o "leave".</summary>
        [JsonProperty("phase")] public string Phase;

        /// <summary>Nombre del invitado (para los registros).</summary>
        [JsonProperty("name")] public string Name;

        /// <summary>Tasa de la voz del invitado.</summary>
        [JsonProperty("sample_rate")] public int SampleRate = Protocol.DefaultSampleRate;
    }

    /// <summary>Un clip de una sola vez en el avatar del invitado (lo lanza Jean desde su modal).</summary>
    [Serializable]
    public class GuestAnimationMessage
    {
        [JsonProperty("clip")] public string Clip;
    }

    /// <summary>
    /// Empieza una trivia: gorro de fiesta, tema y marcador. Fijo mientras dura
    /// la partida (se repite tras <c>hello</c>).
    /// </summary>
    [Serializable]
    public class TriviaStartMessage
    {
        /// <summary>Preguntas de la partida.</summary>
        [JsonProperty("total")] public int Total = 5;

        /// <summary>Aciertos que hacen falta para ganar.</summary>
        [JsonProperty("threshold")] public int Threshold = 3;

        /// <summary>Nivel de la partida (fácil, intermedio o difícil); vacío en orquestadores viejos.</summary>
        [JsonProperty("level")] public string Level = "";
    }

    /// <summary>Una pregunta de la trivia con sus tres opciones (A, B y C, en este orden).</summary>
    [Serializable]
    public class TriviaQuestionMessage
    {
        /// <summary>Número de la pregunta, desde 1.</summary>
        [JsonProperty("number")] public int Number = 1;

        [JsonProperty("total")] public int Total = 5;

        [JsonProperty("question")] public string Question;

        [JsonProperty("options")] public string[] Options;

        /// <summary>Aciertos que lleva el visitante.</summary>
        [JsonProperty("score")] public int Score;
    }

    /// <summary>Resultado de una pregunta de la trivia.</summary>
    [Serializable]
    public class TriviaAnswerMessage
    {
        [JsonProperty("number")] public int Number = 1;

        /// <summary>Opción elegida (0 a 2) o -1 si el visitante no la sabía.</summary>
        [JsonProperty("chosen")] public int Chosen = -1;

        /// <summary>Opción correcta (0 a 2).</summary>
        [JsonProperty("correct")] public int Correct;

        [JsonProperty("is_correct")] public bool IsCorrect;

        [JsonProperty("score")] public int Score;
    }

    /// <summary>Fin de la trivia: <c>finished</c> (ganada o perdida) o <c>cancelled</c>.</summary>
    [Serializable]
    public class TriviaEndMessage
    {
        [JsonProperty("score")] public int Score;

        [JsonProperty("total")] public int Total = 5;

        [JsonProperty("won")] public bool Won;

        [JsonProperty("reason")] public string Reason = "finished";
    }

    /// <summary>Un trozo de la voz del invitado (frame binario "SNGU"), envuelto para la cola del cliente.</summary>
    public sealed class GuestAudioFrame
    {
        public AudioFrame Frame;
    }

    /// <summary>
    /// Sobre común de los juegos (orquestador → Unity):
    /// <c>{"type":"game","game":"wordle","event":"guess","seq":7,"data":{...}}</c>.
    /// <see cref="GameRouter"/> lo reparte por <see cref="Game"/> y el controlador
    /// de cada juego deserializa <see cref="DataJson"/> con sus propias clases.
    /// </summary>
    public sealed class GameMessage
    {
        /// <summary>Id del juego ("ruleta", "wordle"...).</summary>
        public string Game;

        /// <summary>Evento: <see cref="GameEvents.Start"/>, <see cref="GameEvents.End"/> o uno propio del juego.</summary>
        public string Event;

        /// <summary>Contador global del orquestador: sube en cada mensaje de juego y vuelve a 1 si se reinicia.</summary>
        public long Seq;

        /// <summary>El objeto <c>data</c> en JSON compacto; "{}" si no venía.</summary>
        public string DataJson = "{}";
    }

    /// <summary>
    /// Enciende o apaga la vista en vivo de la cámara encima de Sonia, durante los
    /// juegos que la usan. La imagen llega en frames binarios "SNCV".
    /// </summary>
    [Serializable]
    public class CameraPreviewMessage
    {
        [JsonProperty("on")] public bool On;

        /// <summary>Que se vea en espejo (si el frame no viene ya en espejo, Unity lo voltea).</summary>
        [JsonProperty("mirror")] public bool Mirror = true;
    }

    /// <summary>Herramienta de capturas en batch: guarda una captura 1080x1920 con este nombre.</summary>
    [Serializable]
    public class DevCaptureMessage
    {
        [JsonProperty("name")] public string Name;
    }

    /// <summary>Herramienta de capturas en batch: se acabó la secuencia, Unity sale.</summary>
    [Serializable]
    public class DevDoneMessage
    {
    }

    /// <summary>Un frame de la vista en vivo (binario "SNCV") con su JPEG ya separado de la cabecera.</summary>
    public sealed class PreviewFrame
    {
        /// <summary>Sube en cada frame; Unity descarta los que llegan con uno menor.</summary>
        public uint Seq;

        /// <summary>Píxeles del JPEG que anuncia la cabecera.</summary>
        public int Width;

        public int Height;

        /// <summary>Bit 0 de los flags: la imagen ya viene en espejo.</summary>
        public bool Mirrored;

        /// <summary>La imagen, con los esqueletos y las marcas del juego ya dibujados.</summary>
        public byte[] Jpeg;
    }

    /// <summary>
    /// El panel pide pasar a la escena de editar personaje. <see cref="Target"/>
    /// dice de quién: "sonia" (por defecto, también si falta) o "guest", el
    /// invitado del Modo Jean.
    /// </summary>
    [Serializable]
    public class OpenAvatarEditorMessage
    {
        [JsonProperty("target")] public string Target;

        /// <summary>De quién es el personaje que se edita.</summary>
        public AvatarRole Role
        {
            get { return Protocol.ParseAvatarTarget(Target); }
        }
    }

    /// <summary>El panel pide salir del editor de personaje sin guardar.</summary>
    [Serializable]
    public class CloseAvatarEditorMessage
    {
    }

    /// <summary>Boca de «Developer»: multiplicadores de LipSyncController (1 = tal cual).</summary>
    [Serializable]
    public class MouthTuning
    {
        /// <summary>Apertura de vocales y mandíbula.</summary>
        [JsonProperty("open")] public float Open = 1f;

        /// <summary>Mandíbula extra en las sílabas fuertes (jawBoost).</summary>
        [JsonProperty("jaw")] public float Jaw = 1f;

        /// <summary>Cierre de labios en p, b y m (closureWeight).</summary>
        [JsonProperty("closure")] public float Closure = 1f;

        /// <summary>Rapidez de la boca (mouthSpeed y closureSpeed).</summary>
        [JsonProperty("speed")] public float Speed = 1f;
    }

    /// <summary>Cámara de «Developer»: desplazamientos sobre el plano base, zoom e inclinación.</summary>
    [Serializable]
    public class CameraTuning
    {
        /// <summary>Metros hacia arriba.</summary>
        [JsonProperty("height")] public float Height;

        /// <summary>Metros alejándose de Sonia (negativo, más cerca).</summary>
        [JsonProperty("distance")] public float Distance;

        /// <summary>Metros hacia la derecha de la pantalla.</summary>
        [JsonProperty("side")] public float Side;

        /// <summary>Más de 1 acerca (campo de visión más estrecho).</summary>
        [JsonProperty("zoom")] public float Zoom = 1f;

        /// <summary>Grados; positivo mira más abajo.</summary>
        [JsonProperty("tilt")] public float Tilt;
    }

    /// <summary>
    /// Movimiento en reposo de «Developer»: multiplicadores de
    /// AvatarStateController (1 = tal cual).
    /// </summary>
    [Serializable]
    public class IdleTuning
    {
        /// <summary>Respiración: pecho, hombros y cabeza.</summary>
        [JsonProperty("breath")] public float Breath = 1f;

        /// <summary>Acentos del cuerpo en las sílabas fuertes al hablar.</summary>
        [JsonProperty("accents")] public float Accents = 1f;

        /// <summary>Ritmo de la respiración y del bucle de reposo.</summary>
        [JsonProperty("speed")] public float Speed = 1f;
    }

    /// <summary>
    /// Sonia está en pantalla o se ha ido (modo "Fuera" del panel). Es un mensaje
    /// fijo: el orquestador lo repite tras <c>hello</c> a cada cliente nuevo.
    /// </summary>
    [Serializable]
    public class PresenceMessage
    {
        /// <summary>Falso: sale caminando y deja el letrero. Cierto: vuelve a su sitio.</summary>
        [JsonProperty("present")] public bool Present = true;

        /// <summary>Texto del letrero mientras está fuera. Vacío: el de por defecto.</summary>
        [JsonProperty("message")] public string Message;
    }

    /// <summary>
    /// Modo del stand y si Sonia puede conversar ahora (GPT-Live encendida). Es
    /// fijo: se repite tras <c>hello</c>. La pantalla solo invita a hablar con
    /// <see cref="Talk"/> cierto.
    /// </summary>
    [Serializable]
    public class StageModeMessage
    {
        /// <summary><c>conversation</c>, <c>greeter</c> (solo saludos) o <c>away</c> (fuera).</summary>
        [JsonProperty("mode")] public string Mode = "conversation";

        /// <summary>Cierto si Sonia contestaría a quien le hable.</summary>
        [JsonProperty("talk")] public bool Talk = true;
    }

    /// <summary>Valores del campo <c>activity</c> del mensaje <c>activity</c>.</summary>
    public static class ActivityNames
    {
        /// <summary>Nada especial: el efecto de partículas de siempre.</summary>
        public const string None = "none";

        /// <summary>Una tarea delegada en el backend tarda (más de 5 s): Sonia piensa con la mano en la barbilla.</summary>
        public const string Think = "think";

        /// <summary>El backend está buscando en internet: la lluvia estilo Matrix.</summary>
        public const string Search = "search";
    }

    /// <summary>
    /// Qué está haciendo Sonia por detrás: con <c>search</c> sale la lluvia
    /// estilo Matrix (StageParticles) y con <c>think</c> se lleva la mano a la
    /// barbilla mientras piensa (AvatarChoreographer). No es fijo: llega cada vez
    /// que cambia.
    /// </summary>
    [Serializable]
    public class ActivityMessage
    {
        [JsonProperty("activity")] public string Activity = ActivityNames.None;
    }

    /// <summary>Valores del campo <c>kind</c> del mensaje <c>busy</c>, de más a menos prioridad.</summary>
    public static class BusyKinds
    {
        /// <summary>El juez de un juego mira la foto de la ronda.</summary>
        public const string Judge = "judge";

        /// <summary>La cámara de un juego arranca, hasta su primer frame.</summary>
        public const string Camera = "camera";

        /// <summary>Un juego se prepara, hasta su primera pantalla.</summary>
        public const string Game = "game";

        /// <summary>El backend busca en internet.</summary>
        public const string Search = "search";

        /// <summary>Hay una tarea delegada en el backend.</summary>
        public const string Think = "think";
    }

    /// <summary>
    /// Aviso de espera en pantalla («la gente se desespera», Jean, 10 de octubre
    /// de 2026): una pastilla con puntos animados mientras Sonia espera algo que
    /// el visitante no ve. Es el estado entero, no un cambio: con <c>on</c> se
    /// enseña <c>text</c> (o se cambia si ya estaba) y sin él se quita. El
    /// orquestador lo manda solo al cambiar y lo repite al reconectarse.
    /// </summary>
    [Serializable]
    public class BusyMessage
    {
        [JsonProperty("on")] public bool On;

        /// <summary>Tipo de espera (<see cref="BusyKinds"/>); vacío con <c>on: false</c>.</summary>
        [JsonProperty("kind")] public string Kind = string.Empty;

        /// <summary>Lo que dice la pastilla («Pensando…»); vacío con <c>on: false</c>.</summary>
        [JsonProperty("text")] public string Text = string.Empty;
    }

    /// <summary>Volumen de la voz de Sonia. También fijo: se repite tras <c>hello</c>.</summary>
    [Serializable]
    public class SetVolumeMessage
    {
        /// <summary>De 0 a 1,5; 1 es el volumen normal.</summary>
        [JsonProperty("value")] public float Value = 1f;
    }

    /// <summary>Un micrófono del equipo donde corre el orquestador.</summary>
    [Serializable]
    public class MicrophoneInfo
    {
        [JsonProperty("name")] public string Name;
        [JsonProperty("default")] public bool IsDefault;
    }

    /// <summary>
    /// Micrófonos del equipo y lo elegido, para el menú de opciones. Las cámaras
    /// las lista Unity (<c>WebCamTexture.devices</c>); <c>camera</c> es el índice
    /// que usa el orquestador y <c>camera_source</c> de dónde saca las fotos.
    /// </summary>
    [Serializable]
    public class DevicesMessage
    {
        [JsonProperty("microphones")] public MicrophoneInfo[] Microphones;
        /// <summary>Lo configurado; vacío es el del sistema (<see cref="DefaultMicrophone"/>).</summary>
        [JsonProperty("microphone")] public string Microphone;
        [JsonProperty("default_microphone")] public string DefaultMicrophone;
        [JsonProperty("camera")] public int Camera;
        [JsonProperty("camera_source")] public string CameraSource;
    }

    /// <summary>Un visema con su instante de inicio relativo al <c>speech_start</c>.</summary>
    [Serializable]
    public class VisemeFrame
    {
        /// <summary>Instante de inicio en segundos, relativo al comienzo de la frase.</summary>
        [JsonProperty("t")] public float T;

        /// <summary>Identificador del visema (ver <see cref="VisemeIds"/>).</summary>
        [JsonProperty("v")] public string V = VisemeIds.Sil;

        /// <summary>Peso entre 0 y 1.</summary>
        [JsonProperty("w")] public float W = 1f;
    }

    /// <summary>Lista completa de visemas de una frase.</summary>
    [Serializable]
    public class VisemesMessage
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
        [JsonProperty("frames")] public List<VisemeFrame> Frames = new List<VisemeFrame>();
    }

    /// <summary>Envolvente de amplitud de la frase: un valor de 0 a 1 cada <c>interval_ms</c>.</summary>
    [Serializable]
    public class EnvelopeMessage
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
        [JsonProperty("interval_ms")] public int IntervalMs = 20;
        [JsonProperty("values")] public List<float> Values = new List<float>();
    }

    /// <summary>No habrá más audio de esa frase.</summary>
    [Serializable]
    public class SpeechEndMessage
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
    }

    /// <summary>Interrupción: hay que descartar el audio en cola y parar la boca.</summary>
    [Serializable]
    public class StopSpeakingMessage
    {
        [JsonProperty("reason")] public string Reason = "interrupted";
    }

    /// <summary>Imagen a mostrar en el panel de la escena.</summary>
    [Serializable]
    public class ShowImageMessage
    {
        [JsonProperty("image_id")] public string ImageId = string.Empty;
        [JsonProperty("source")] public string Source = ImageSources.Gallery;
        [JsonProperty("mime")] public string Mime = "image/png";
        [JsonProperty("data_base64")] public string DataBase64 = string.Empty;
        [JsonProperty("caption")] public string Caption;
    }

    /// <summary>Retira el panel de imágenes.</summary>
    [Serializable]
    public class HideImageMessage
    {
    }

    /// <summary>Error legible enviado por el orquestador.</summary>
    [Serializable]
    public class ErrorMessage
    {
        [JsonProperty("message")] public string Message = string.Empty;
    }

    /// <summary>El orquestador pide una captura de la cámara de Unity.</summary>
    [Serializable]
    public class RequestFrameMessage
    {
    }

    /// <summary>Un chunk de audio ya decodificado a muestras float en [-1, 1].</summary>
    public struct AudioFrame
    {
        /// <summary>Frase a la que pertenece el chunk.</summary>
        public int UtteranceId;

        /// <summary>Cierto si es el último chunk de la frase (bit 0 de <c>flags</c>).</summary>
        public bool IsLast;

        /// <summary>Muestras mono a la tasa anunciada en <c>hello</c>.</summary>
        public float[] Samples;
    }

    /// <summary>
    /// Codificación y decodificación del protocolo. Solo código gestionado: se
    /// puede llamar desde cualquier hilo.
    /// </summary>
    public static class Protocol
    {
        /// <summary>Versión del protocolo que entiende este cliente.</summary>
        public const int Version = 1;

        /// <summary>Tamaño de la cabecera de los frames binarios de audio.</summary>
        public const int AudioHeaderSize = 12;

        /// <summary>Bit 0 de <c>flags</c>: último chunk de la frase.</summary>
        public const uint FlagLast = 1u;

        /// <summary>Tasa de muestreo por defecto mientras no llega el <c>hello</c>.</summary>
        public const int DefaultSampleRate = 24000;

        /// <summary>Nombre con el que Unity se identifica en <c>client_hello</c>.</summary>
        public const string ClientName = "unity";

        /// <summary>Escala de int16 a float.</summary>
        private const float PcmScale = 1f / 32768f;

        /// <summary>Cabecera de los frames de la vista en vivo: magic, seq, ancho, alto y flags.</summary>
        public const int PreviewHeaderSize = 16;

        /// <summary>Bit 0 de los flags de la vista en vivo: la imagen ya va en espejo.</summary>
        public const uint PreviewFlagMirrored = 1u;

        // --------------------------------------------------------------
        // Frames binarios de audio
        // --------------------------------------------------------------

        /// <summary>
        /// Decodifica un frame binario "SNIA" a muestras float. Devuelve false si
        /// el frame es demasiado corto o la marca no coincide (el protocolo dice
        /// que esos mensajes se ignoran en silencio).
        /// </summary>
        /// <param name="data">Buffer que contiene el frame completo.</param>
        /// <param name="length">Bytes válidos dentro del buffer.</param>
        /// <param name="frame">Frame decodificado.</param>
        public static bool TryDecodeAudioFrame(byte[] data, int length, out AudioFrame frame)
        {
            return TryDecodeFrame(data, length, 'I', 'A', out frame);
        }

        /// <summary>
        /// Como <see cref="TryDecodeAudioFrame"/> pero con la voz del invitado del
        /// Modo Jean (marca "SNGU", misma cabecera).
        /// </summary>
        public static bool TryDecodeGuestAudioFrame(byte[] data, int length, out AudioFrame frame)
        {
            return TryDecodeFrame(data, length, 'G', 'U', out frame);
        }

        private static bool TryDecodeFrame(byte[] data, int length, char third, char fourth, out AudioFrame frame)
        {
            frame = default(AudioFrame);
            if (data == null || length < AudioHeaderSize || length > data.Length)
            {
                return false;
            }

            if (data[0] != (byte)'S' || data[1] != (byte)'N' || data[2] != (byte)third || data[3] != (byte)fourth)
            {
                return false;
            }

            uint utteranceId = data[4]
                               | ((uint)data[5] << 8)
                               | ((uint)data[6] << 16)
                               | ((uint)data[7] << 24);
            uint flags = data[8]
                         | ((uint)data[9] << 8)
                         | ((uint)data[10] << 16)
                         | ((uint)data[11] << 24);

            int sampleCount = (length - AudioHeaderSize) / 2;
            float[] samples = new float[sampleCount];
            int offset = AudioHeaderSize;
            for (int i = 0; i < sampleCount; i++)
            {
                short value = (short)(data[offset] | (data[offset + 1] << 8));
                samples[i] = value * PcmScale;
                offset += 2;
            }

            frame.UtteranceId = unchecked((int)utteranceId);
            frame.IsLast = (flags & FlagLast) != 0u;
            frame.Samples = samples;
            return true;
        }

        /// <summary>
        /// Decodifica un frame de la vista en vivo ("SNCV": magic, seq uint32, ancho
        /// y alto uint16, flags uint32, little endian, y el JPEG detrás). Devuelve
        /// false si es demasiado corto, si la marca no coincide o si no trae imagen.
        /// </summary>
        public static bool TryDecodePreviewFrame(byte[] data, int length, out PreviewFrame frame)
        {
            frame = null;
            if (data == null || length <= PreviewHeaderSize || length > data.Length)
            {
                return false;
            }

            if (data[0] != (byte)'S' || data[1] != (byte)'N' || data[2] != (byte)'C' || data[3] != (byte)'V')
            {
                return false;
            }

            uint seq = data[4] | ((uint)data[5] << 8) | ((uint)data[6] << 16) | ((uint)data[7] << 24);
            int width = data[8] | (data[9] << 8);
            int height = data[10] | (data[11] << 8);
            uint flags = data[12] | ((uint)data[13] << 8) | ((uint)data[14] << 16) | ((uint)data[15] << 24);
            byte[] jpeg = new byte[length - PreviewHeaderSize];
            Buffer.BlockCopy(data, PreviewHeaderSize, jpeg, 0, jpeg.Length);
            frame = new PreviewFrame
            {
                Seq = seq,
                Width = width,
                Height = height,
                Mirrored = (flags & PreviewFlagMirrored) != 0u,
                Jpeg = jpeg
            };
            return true;
        }

        /// <summary>
        /// Lee el sobre <c>game</c>. Devuelve null si falta el juego o el evento;
        /// <c>data</c> se pasa tal cual, en texto, para que lo lea cada juego.
        /// </summary>
        public static GameMessage ParseGameMessage(JObject payload)
        {
            if (payload == null)
            {
                return null;
            }

            string game = payload.Value<string>("game");
            string eventName = payload.Value<string>("event");
            if (string.IsNullOrEmpty(game) || string.IsNullOrEmpty(eventName))
            {
                return null;
            }

            long seq = 0;
            JToken seqToken = payload["seq"];
            if (seqToken != null && (seqToken.Type == JTokenType.Integer || seqToken.Type == JTokenType.Float))
            {
                seq = seqToken.Value<long>();
            }

            JObject data = payload["data"] as JObject;
            return new GameMessage
            {
                Game = game,
                Event = eventName,
                Seq = seq,
                DataJson = data != null ? data.ToString(Formatting.None) : "{}"
            };
        }

        // --------------------------------------------------------------
        // Lectura de mensajes de texto
        // --------------------------------------------------------------

        /// <summary>
        /// Parsea un mensaje JSON y saca su campo <c>type</c>. Devuelve false si no
        /// es JSON válido, si no es un objeto o si no trae un <c>type</c> de texto.
        /// </summary>
        public static bool TryParse(string json, out string type, out JObject payload)
        {
            type = null;
            payload = null;
            if (string.IsNullOrEmpty(json))
            {
                return false;
            }

            JObject parsed;
            try
            {
                parsed = JObject.Parse(json);
            }
            catch (JsonException)
            {
                return false;
            }

            JToken typeToken = parsed["type"];
            if (typeToken == null || typeToken.Type != JTokenType.String)
            {
                return false;
            }

            type = typeToken.Value<string>();
            payload = parsed;
            return !string.IsNullOrEmpty(type);
        }

        /// <summary>
        /// Convierte un objeto JSON ya parseado al tipo de mensaje correspondiente.
        /// Devuelve null si el contenido no encaja, para que el cliente lo ignore.
        /// </summary>
        public static T Deserialize<T>(JObject payload) where T : class
        {
            if (payload == null)
            {
                return null;
            }

            try
            {
                return payload.ToObject<T>();
            }
            catch (JsonException)
            {
                return null;
            }
            catch (ArgumentException)
            {
                return null;
            }
        }

        // --------------------------------------------------------------
        // Constructores de mensajes salientes (Unity -> orquestador)
        // --------------------------------------------------------------

        /// <summary>Identifica al cliente justo después de conectar.</summary>
        public static string ClientHelloMessage(string client, string version)
        {
            return ClientHelloMessage(client, version, null, null);
        }

        /// <summary>
        /// Identifica al cliente y anuncia los juegos que sabe pintar
        /// (<c>games</c>, los ids de los controladores registrados) y sus
        /// capacidades (<c>features</c>, como <see cref="ClientFeatures.CameraPreview"/>).
        /// Un orquestador anterior ignora los dos campos.
        /// </summary>
        public static string ClientHelloMessage(string client, string version, IList<string> games, IList<string> features)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.ClientHello,
                ["client"] = string.IsNullOrEmpty(client) ? ClientName : client,
                ["version"] = string.IsNullOrEmpty(version) ? "0.1.0" : version
            };

            if (games != null)
            {
                message["games"] = new JArray(games);
            }

            if (features != null)
            {
                message["features"] = new JArray(features);
            }

            return message.ToString(Formatting.None);
        }

        /// <summary>
        /// Evento de un juego hacia el orquestador:
        /// <c>{"type":"game_event","game":"ruleta","event":"wheel_stopped","data":{...}}</c>.
        /// </summary>
        public static string GameEventMessage(string game, string eventName, JObject data)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.GameEvent,
                ["game"] = game ?? string.Empty,
                ["event"] = eventName ?? string.Empty,
                ["data"] = data ?? new JObject()
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>
        /// Ids de juego y nombres de evento válidos (los mismos que acepta el
        /// orquestador): minúscula inicial y luego minúsculas, cifras o "_", hasta 40.
        /// </summary>
        public static bool IsValidGameName(string name)
        {
            if (string.IsNullOrEmpty(name) || name.Length > 40 || name[0] < 'a' || name[0] > 'z')
            {
                return false;
            }

            for (int i = 1; i < name.Length; i++)
            {
                char c = name[i];
                if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'))
                {
                    return false;
                }
            }

            return true;
        }

        /// <summary>El usuario ha interrumpido a Sonia.</summary>
        public static string InterruptMessage()
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.Interrupt
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Unity terminó de reproducir una frase.</summary>
        public static string PlaybackDoneMessage(int utteranceId)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.PlaybackDone,
                ["utterance_id"] = utteranceId
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Entrada de texto en lugar de voz (para probar sin micrófono).</summary>
        public static string TextInputMessage(string text)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.TextInput,
                ["text"] = text ?? string.Empty
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Captura de la cámara de Unity, codificada en JPEG.</summary>
        public static string CameraFrameMessage(byte[] jpeg)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.CameraFrame,
                ["mime"] = "image/jpeg",
                ["data_base64"] = jpeg == null ? string.Empty : Convert.ToBase64String(jpeg)
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Catálogo de animaciones que el panel puede lanzar: pares (clip, grupo).</summary>
        public static string AnimationsMessage(IList<KeyValuePair<string, string>> clips)
        {
            JArray list = new JArray();
            if (clips != null)
            {
                foreach (KeyValuePair<string, string> item in clips)
                {
                    list.Add(new JObject { ["clip"] = item.Key, ["group"] = item.Value });
                }
            }

            JObject message = new JObject
            {
                ["type"] = MessageTypes.Animations,
                ["animations"] = list
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>
        /// Gestos de Genies que Unity puede reproducir, con la ficha que el
        /// director de gestos del orquestador le pasa a su modelo (docs/gestos.md).
        /// </summary>
        public static string GestureCatalogMessage(GeniesGestureSet set)
        {
            JArray list = new JArray();
            if (set != null && set.gestures != null)
            {
                foreach (GeniesGestureSet.Gesture g in set.gestures)
                {
                    if (g == null || g.clip == null || string.IsNullOrEmpty(g.name))
                    {
                        continue;
                    }

                    list.Add(new JObject
                    {
                        ["name"] = g.name,
                        ["lists"] = new JArray(g.lists ?? new string[0]),
                        ["duration"] = Math.Round(g.duration, 3),
                        ["core_start"] = Math.Round(g.coreStart, 3),
                        ["core_stop"] = Math.Round(g.coreStop, 3),
                        ["critical_beat"] = g.criticalBeat >= 0f ? new JValue(Math.Round(g.criticalBeat, 3)) : JValue.CreateNull(),
                        ["held"] = g.held,
                        ["min_duration"] = g.minDuration >= 0f ? new JValue(Math.Round(g.minDuration, 3)) : JValue.CreateNull(),
                        ["frequency"] = g.frequency ?? "Standard",
                        ["timing"] = g.timing ?? "Short",
                        ["impact"] = g.impact ?? "",
                        ["intensity"] = g.intensity,
                        ["special"] = g.special,
                        ["description"] = g.description ?? "",
                        ["intents"] = new JArray(g.intents ?? new string[0]),
                        ["intent_description"] = g.intentDescription ?? "",
                        ["tags"] = new JArray(g.tags ?? new string[0])
                    });
                }
            }

            JObject message = new JObject
            {
                ["type"] = MessageTypes.GestureCatalog,
                ["character"] = set != null ? set.character : "",
                ["transition_s"] = set != null ? Math.Round(set.transitionSeconds, 3) : 0.8,
                ["gestures"] = list
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Clip del catálogo que suena ahora en el avatar, o null si ninguno.</summary>
        /// <summary>Pide la lista de micrófonos y lo elegido (menú de opciones).</summary>
        public static string ListDevicesMessage()
        {
            JObject message = new JObject { ["type"] = MessageTypes.ListDevices };
            return message.ToString(Formatting.None);
        }

        /// <summary>Elige micrófono (nombre; vacío es el del sistema) desde el menú de opciones.</summary>
        public static string SetMicrophoneMessage(string name)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.SetDevice,
                ["kind"] = "microphone",
                ["value"] = name ?? string.Empty
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Elige cámara (índice) desde el menú de opciones.</summary>
        public static string SetCameraMessage(int index)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.SetDevice,
                ["kind"] = "camera",
                ["value"] = Math.Max(0, index)
            };
            return message.ToString(Formatting.None);
        }

        public static string AnimationPlayingMessage(string clip)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.AnimationPlaying,
                ["clip"] = string.IsNullOrEmpty(clip) ? JValue.CreateNull() : new JValue(clip)
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Fase del Modo Jean en la pantalla: entering, live, leaving u off.</summary>
        public static string GuestStateMessage(string phase)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.GuestState,
                ["phase"] = phase ?? "off"
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>La escena de editar personaje se abrió o se cerró.</summary>
        public static string AvatarEditorMessage(bool open, AvatarRole role = AvatarRole.Sonia)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.AvatarEditor,
                ["open"] = open,
                ["target"] = AvatarTarget(role)
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Se guardó un personaje en el editor: su definición de Genies en texto JSON y de quién es.</summary>
        public static string AvatarSavedMessage(string definition, AvatarRole role = AvatarRole.Sonia)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.AvatarSaved,
                ["definition"] = definition ?? string.Empty,
                ["target"] = AvatarTarget(role)
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Valor de <c>target</c> en los mensajes del editor de personaje.</summary>
        public static string AvatarTarget(AvatarRole role)
        {
            return role == AvatarRole.Guest ? "guest" : "sonia";
        }

        /// <summary><c>target</c> de <c>open_avatar_editor</c>: "guest" es el invitado; cualquier otra cosa, Sonia.</summary>
        public static AvatarRole ParseAvatarTarget(string target)
        {
            return target == "guest" ? AvatarRole.Guest : AvatarRole.Sonia;
        }
    }
}
