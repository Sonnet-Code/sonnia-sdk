// Los data de los eventos de la ruleta (docs/protocolo.md, eventos de «ruleta»). Los
// lee RuletaController con GameControllerBase.ParseData: lo que falte se queda con el
// valor de aquí.

using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace Sonia.Games.Ruleta
{
    /// <summary>Una casilla (data.segments del start).</summary>
    [Serializable]
    internal sealed class SegmentInfo
    {
        /// <summary>trivia, adivinanza, explica, futuro o sonnet.</summary>
        [JsonProperty("id")] public string Id = string.Empty;

        /// <summary>Lo que pone en la ruleta («Trivia relámpago»).</summary>
        [JsonProperty("label")] public string Label = string.Empty;

        /// <summary>El título de la tarjeta del reto («TRIVIA RELÁMPAGO»).</summary>
        [JsonProperty("title")] public string Title = string.Empty;

        /// <summary>bolt, riddle, mic, crystal o star.</summary>
        [JsonProperty("icon")] public string Icon = string.Empty;

        /// <summary>Sin reto esta partida: sale apagada.</summary>
        [JsonProperty("off")] public bool Off;

        public SegmentInfo()
        {
        }

        public SegmentInfo(string id, string label, string title, string icon)
        {
            Id = id;
            Label = label;
            Title = title;
            Icon = icon;
        }
    }

    [Serializable]
    internal sealed class RuletaStartData
    {
        [JsonProperty("segments")] public List<SegmentInfo> Segments;
    }

    /// <summary>spin: la casilla de destino y lo que dura el giro.</summary>
    [Serializable]
    internal sealed class SpinData
    {
        [JsonProperty("spin")] public int Spin;
        [JsonProperty("segment")] public int Segment;
        [JsonProperty("duration_s")] public float Duration = 4.6f;
        [JsonProperty("wins")] public int Wins;
    }

    [Serializable]
    internal sealed class TimerData
    {
        [JsonProperty("seconds")] public float Seconds;
        [JsonProperty("running")] public bool Running;
    }

    /// <summary>challenge (el reto en juego) y result (el mismo estado más cómo acabó).</summary>
    [Serializable]
    internal sealed class ChallengeData
    {
        [JsonProperty("spin")] public int Spin;
        [JsonProperty("segment")] public int Segment;
        [JsonProperty("kind")] public string Kind = string.Empty;
        [JsonProperty("title")] public string Title = string.Empty;
        [JsonProperty("prompt")] public string Prompt = string.Empty;
        [JsonProperty("wins")] public int Wins;
        [JsonProperty("options")] public List<string> Options;
        [JsonProperty("tries")] public int Tries;
        [JsonProperty("misses")] public int Misses;
        [JsonProperty("hint")] public string Hint = string.Empty;
        [JsonProperty("task")] public bool Task;
        [JsonProperty("timer")] public TimerData Timer;
        [JsonProperty("time_up")] public bool TimeUp;

        // Solo en result.
        [JsonProperty("outcome")] public string Outcome = string.Empty;
        [JsonProperty("chosen")] public int Chosen = -1;
        [JsonProperty("correct")] public int Correct = -1;
        [JsonProperty("answer")] public string Answer = string.Empty;
        [JsonProperty("score")] public int Score;
        [JsonProperty("prediction")] public string Prediction = string.Empty;
        [JsonProperty("probability")] public int Probability = -1;
    }
}
