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
        public const string SetVolume = "set_volume";
        public const string PlayAnimation = "play_animation";

        // De Unity hacia el orquestador.
        public const string ClientHello = "client_hello";
        public const string Interrupt = "interrupt";
        public const string PlaybackDone = "playback_done";
        public const string TextInput = "text_input";
        public const string CameraFrame = "camera_frame";
        public const string Animations = "animations";
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
        public const string Camera = "camera";
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

    /// <summary>El panel pide un clip concreto del catálogo que mandó Unity (<see cref="AnimationCatalog"/>).</summary>
    [Serializable]
    public class PlayAnimationMessage
    {
        /// <summary>Nombre del clip, tal cual va en el mensaje <c>animations</c>.</summary>
        [JsonProperty("clip")] public string Clip;
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

    /// <summary>Volumen de la voz de Sonia. También fijo: se repite tras <c>hello</c>.</summary>
    [Serializable]
    public class SetVolumeMessage
    {
        /// <summary>De 0 a 1,5; 1 es el volumen normal.</summary>
        [JsonProperty("value")] public float Value = 1f;
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
            frame = default(AudioFrame);
            if (data == null || length < AudioHeaderSize || length > data.Length)
            {
                return false;
            }

            if (data[0] != (byte)'S' || data[1] != (byte)'N' || data[2] != (byte)'I' || data[3] != (byte)'A')
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
            JObject message = new JObject
            {
                ["type"] = MessageTypes.ClientHello,
                ["client"] = string.IsNullOrEmpty(client) ? ClientName : client,
                ["version"] = string.IsNullOrEmpty(version) ? "0.1.0" : version
            };
            return message.ToString(Formatting.None);
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
    }
}
