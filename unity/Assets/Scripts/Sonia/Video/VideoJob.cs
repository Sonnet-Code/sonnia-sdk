// Trabajo del renderizador de vídeos: lo que manda sonnia-video (Python) por HTTP.
// El contrato completo está en docs/video.md, «Contrato con Unity».

using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Sonia.Video
{
    /// <summary>Un vídeo (o una vista previa) que hay que renderizar.</summary>
    public sealed class VideoJob
    {
        [JsonProperty("id")] public string Id = "video";

        /// <summary>"video" o "still" (una sola imagen tras el calentamiento).</summary>
        [JsonProperty("kind")] public string Kind = "video";

        [JsonProperty("output_dir")] public string OutputDir;
        [JsonProperty("width")] public int Width = 1080;
        [JsonProperty("height")] public int Height = 1920;
        [JsonProperty("fps")] public int Fps = 30;
        [JsonProperty("supersample")] public int Supersample = 2;
        [JsonProperty("subframes")] public int Subframes = 1;
        [JsonProperty("shutter")] public float Shutter = 0.5f;
        [JsonProperty("duration_s")] public float DurationSeconds = 5f;
        [JsonProperty("warmup_s")] public float WarmupSeconds = 2f;
        [JsonProperty("audio_sample_rate")] public int AudioSampleRate = 24000;
        [JsonProperty("timeline")] public List<TimelineEntry> Timeline = new List<TimelineEntry>();
        [JsonProperty("scene")] public VideoScene Scene = new VideoScene();
        [JsonProperty("encoder")] public VideoEncoder Encoder;
        [JsonProperty("still_path")] public string StillPath;

        /// <summary>Fotos (kind "still"): un PNG en cada instante de la línea de tiempo.</summary>
        [JsonProperty("stills")] public List<VideoStill> Stills = new List<VideoStill>();

        public bool IsStill
        {
            get { return Kind == "still"; }
        }
    }

    /// <summary>Una foto: el PNG que se guarda en el segundo t de la línea de tiempo.</summary>
    public sealed class VideoStill
    {
        [JsonProperty("t")] public float Time;
        [JsonProperty("path")] public string Path;
    }

    /// <summary>Lo que pasa en un instante del vídeo: un mensaje, una voz o un gesto suelto.</summary>
    public sealed class TimelineEntry
    {
        [JsonProperty("t")] public float Time;

        /// <summary>Mensaje del protocolo del stand, despachado como si llegara del orquestador.</summary>
        [JsonProperty("message")] public JObject Message;

        [JsonProperty("audio")] public TimelineAudio Audio;
        [JsonProperty("action")] public TimelineAction Action;
    }

    /// <summary>Voz de una frase: un WAV PCM 16 bit mono que se manda en trozos de 100 ms.</summary>
    public sealed class TimelineAudio
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
        [JsonProperty("wav")] public string Wav;
    }

    /// <summary>Un gesto de Sage lanzado a esa hora en el canal de acciones.</summary>
    public sealed class TimelineAction
    {
        [JsonProperty("name")] public string Name;
        [JsonProperty("mirror")] public bool Mirror;
    }

    public sealed class VideoEncoder
    {
        [JsonProperty("ffmpeg")] public string Ffmpeg;
        [JsonProperty("args")] public List<string> Args = new List<string>();
        [JsonProperty("path")] public string Path;
    }

    /// <summary>Aspecto de la escena: fondo, luz, encuadre y vestuario. Sin HUD: los vídeos no llevan logo, QR ni subtítulos.</summary>
    public sealed class VideoScene
    {
        [JsonProperty("background")] public VideoBackground Background = new VideoBackground();

        /// <summary>Las motas del escenario detrás de Sonnia (no salen con fondo transparente).</summary>
        [JsonProperty("particles")] public bool Particles = true;
        [JsonProperty("lighting")] public VideoLighting Lighting = new VideoLighting();
        [JsonProperty("framing")] public VideoFraming Framing = new VideoFraming();

        /// <summary>"staff" o "plain". Va en el arranque de la app (la camiseta se pone al cargar el avatar).</summary>
        [JsonProperty("outfit")] public string Outfit = "staff";

        [JsonProperty("cap")] public bool Cap;

        /// <summary>"joy" o "neutral".</summary>
        [JsonProperty("emotion")] public string Emotion = "joy";
    }

    public sealed class VideoBackground
    {
        /// <summary>"stand", "color", "gradient", "image" o "transparent" (alfa, solo Sonnia).</summary>
        [JsonProperty("mode")] public string Mode = "stand";

        [JsonProperty("color")] public string Color = "#142752";
        [JsonProperty("color2")] public string Color2 = "#0B1322";
        [JsonProperty("image")] public string Image = string.Empty;
    }

    public sealed class VideoLighting
    {
        /// <summary>"stand", "studio", "soft", "warm", "cool" o "dramatic".</summary>
        [JsonProperty("preset")] public string Preset = "stand";

        [JsonProperty("key")] public float Key = 1f;
        [JsonProperty("ambient")] public float Ambient = 1f;
        [JsonProperty("rim_color")] public string RimColor = string.Empty;
        [JsonProperty("rim_intensity")] public float RimIntensity;
        [JsonProperty("exposure")] public float Exposure;
    }

    public sealed class VideoFraming
    {
        /// <summary>"stand", "close", "medium", "cowboy" o "full".</summary>
        [JsonProperty("preset")] public string Preset = "stand";

        [JsonProperty("zoom")] public float Zoom = 1f;
        [JsonProperty("offset_x")] public float OffsetX;
        [JsonProperty("offset_y")] public float OffsetY;
    }
}
