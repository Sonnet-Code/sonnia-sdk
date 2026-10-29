// WebSocket protocol between the orchestrator and Unity (version 1).
//
// This file is the C# mirror of docs/protocol.md and of the orchestrator's
// protocol module. When the protocol changes, all three change in the same
// commit.
//
// Nothing in this file touches the Unity API: it is safe to use from the
// socket thread.

using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Sonia
{
    /// <summary>Names of the protocol's JSON messages.</summary>
    public static class MessageTypes
    {
        // From the orchestrator to Unity.
        public const string Hello = "hello";
        public const string State = "state";
        public const string Transcript = "transcript";
        public const string SpeechStart = "speech_start";
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
        public const string SetSubtitles = "set_subtitles";
        public const string SetDisabledAnimations = "set_disabled_animations";
        public const string SetDebug = "set_debug";
        public const string SetTuning = "set_tuning";
        public const string SetAvatar = "set_avatar";
        public const string TriviaStart = "trivia_start";
        public const string TriviaQuestion = "trivia_question";
        public const string TriviaAnswer = "trivia_answer";
        public const string TriviaEnd = "trivia_end";
        public const string Activity = "activity";

        /// <summary>On-screen busy indicator (<see cref="BusyMessage"/>): drawn by <see cref="BusyIndicator"/>.</summary>
        public const string Busy = "busy";

        // From Unity to the orchestrator.
        public const string ClientHello = "client_hello";
        public const string Interrupt = "interrupt";
        public const string PlaybackDone = "playback_done";
        public const string TextInput = "text_input";
        public const string CameraFrame = "camera_frame";
        public const string Animations = "animations";
        public const string ListDevices = "list_devices";
        public const string SetDevice = "set_device";
        public const string AnimationPlaying = "animation_playing";

    }

    /// <summary>Possible values of the <c>state</c> field of the <c>state</c> message.</summary>
    public static class AvatarStateNames
    {
        public const string Idle = "idle";
        public const string Listening = "listening";
        public const string Thinking = "thinking";
        public const string Speaking = "speaking";
    }

    /// <summary>Possible values of the <c>source</c> field of <c>show_image</c>.</summary>
    public static class ImageSources
    {
        public const string Gallery = "gallery";
    }

    // ------------------------------------------------------------------
    // Incoming messages (orchestrator -> Unity)
    // ------------------------------------------------------------------

    /// <summary>First message after connecting: announces the audio format.</summary>
    [Serializable]
    public class HelloMessage
    {
        [JsonProperty("version")] public int Version = 1;
        [JsonProperty("sample_rate")] public int SampleRate = 24000;
        [JsonProperty("channels")] public int Channels = 1;
        [JsonProperty("format")] public string Format = "pcm_s16le";
    }

    /// <summary>Assistant state change: idle, listening, thinking or speaking.</summary>
    [Serializable]
    public class StateMessage
    {
        [JsonProperty("state")] public string State = AvatarStateNames.Idle;
    }

    /// <summary>Text from the user or from Sonnia, for subtitles and debugging.</summary>
    [Serializable]
    public class TranscriptMessage
    {
        [JsonProperty("role")] public string Role = "user";
        [JsonProperty("text")] public string Text = string.Empty;
        [JsonProperty("final")] public bool Final;
    }

    /// <summary>A synthesized utterance begins; binary frames follow.</summary>
    [Serializable]
    public class SpeechStartMessage
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
        [JsonProperty("text")] public string Text = string.Empty;

        /// <summary>
        /// Idle line (said on its own when nobody is around): the mouth moves but
        /// the avatar does not change state or interrupt the dance or idle.
        /// </summary>
        [JsonProperty("ambient")] public bool Ambient;
    }

    /// <summary>The orchestrator asks for an attention gesture (dance, fourth wall, soft, greeting).</summary>
    [Serializable]
    public class AttentionMessage
    {
        /// <summary>"dance", "fourth_wall", "soft" or "greeting" (wave).</summary>
        [JsonProperty("category")] public string Category = "soft";

        /// <summary>Specific clip name, optional.</summary>
        [JsonProperty("clip")] public string Clip;
    }

    /// <summary>
    /// The panel (or a move requested by voice) asks for a specific clip from the
    /// catalog Unity sent (<see cref="AnimationCatalog"/>).
    /// </summary>
    [Serializable]
    public class PlayAnimationMessage
    {
        /// <summary>Clip name, exactly as it appears in the <c>animations</c> message.</summary>
        [JsonProperty("clip")] public string Clip;

        /// <summary>
        /// Play it to the end even if Sonnia moves on to thinking or speaking (moves
        /// requested by voice). Without it, as from the panel, a state change cuts it.
        /// </summary>
        [JsonProperty("whole")] public bool Whole;
    }

    /// <summary>Subtitles on screen or not (panel, sticky message: re-sent after <c>hello</c>).</summary>
    [Serializable]
    public class SetSubtitlesMessage
    {
        [JsonProperty("enabled")] public bool Enabled = true;
    }

    /// <summary>Clips Sonnia does not use on her own (panel, sticky message). They still play with <c>play_animation</c>.</summary>
    [Serializable]
    public class SetDisabledAnimationsMessage
    {
        [JsonProperty("clips")] public List<string> Clips = new List<string>();
    }

    /// <summary>Panel debug mode (sticky message): the avatar does not trigger gestures, dances or variations on its own.</summary>
    [Serializable]
    public class SetDebugMessage
    {
        [JsonProperty("enabled")] public bool Enabled;
    }

    /// <summary>
    /// Settings from the panel's "Developer" section (sticky message): the mouth
    /// and idle movement as multipliers of what the scene provides, and the camera
    /// as offsets from its base shot. An older orchestrator does not send
    /// <c>idle</c>: it stays at 1 (unchanged).
    /// </summary>
    [Serializable]
    public class SetTuningMessage
    {
        [JsonProperty("mouth")] public MouthTuning Mouth = new MouthTuning();
        [JsonProperty("camera")] public CameraTuning Camera = new CameraTuning();
        [JsonProperty("idle")] public IdleTuning Idle = new IdleTuning();
    }

    /// <summary>
    /// Sonnia's look (sticky message): Genies avatar definition as JSON text, or
    /// null for the character the app ships with.
    /// </summary>
    [Serializable]
    public class SetAvatarMessage
    {
        [JsonProperty("definition")] public string Definition;
    }

    /// <summary>
    /// A trivia game starts: theme and scoreboard. Sticky while the game lasts
    /// (re-sent after <c>hello</c>).
    /// </summary>
    [Serializable]
    public class TriviaStartMessage
    {
        /// <summary>Questions in the game.</summary>
        [JsonProperty("total")] public int Total = 5;

        /// <summary>Correct answers needed to win.</summary>
        [JsonProperty("threshold")] public int Threshold = 3;

        /// <summary>Game level (easy, medium or hard); empty with old orchestrators.</summary>
        [JsonProperty("level")] public string Level = "";
    }

    /// <summary>A trivia question with its three options (A, B and C, in that order).</summary>
    [Serializable]
    public class TriviaQuestionMessage
    {
        /// <summary>Question number, from 1.</summary>
        [JsonProperty("number")] public int Number = 1;

        [JsonProperty("total")] public int Total = 5;

        [JsonProperty("question")] public string Question;

        [JsonProperty("options")] public string[] Options;

        /// <summary>Correct answers so far.</summary>
        [JsonProperty("score")] public int Score;
    }

    /// <summary>Result of a trivia question.</summary>
    [Serializable]
    public class TriviaAnswerMessage
    {
        [JsonProperty("number")] public int Number = 1;

        /// <summary>Chosen option (0 to 2), or -1 if the user did not know.</summary>
        [JsonProperty("chosen")] public int Chosen = -1;

        /// <summary>Correct option (0 to 2).</summary>
        [JsonProperty("correct")] public int Correct;

        [JsonProperty("is_correct")] public bool IsCorrect;

        [JsonProperty("score")] public int Score;
    }

    /// <summary>End of the trivia: <c>finished</c> (won or lost) or <c>cancelled</c>.</summary>
    [Serializable]
    public class TriviaEndMessage
    {
        [JsonProperty("score")] public int Score;

        [JsonProperty("total")] public int Total = 5;

        [JsonProperty("won")] public bool Won;

        [JsonProperty("reason")] public string Reason = "finished";
    }

    /// <summary>"Developer" mouth: LipSyncController multipliers (1 = unchanged).</summary>
    [Serializable]
    public class MouthTuning
    {
        /// <summary>Vowel and jaw opening.</summary>
        [JsonProperty("open")] public float Open = 1f;

        /// <summary>Extra jaw on stressed syllables (jawBoost).</summary>
        [JsonProperty("jaw")] public float Jaw = 1f;

        /// <summary>Lip closure on p, b and m (closureWeight).</summary>
        [JsonProperty("closure")] public float Closure = 1f;

        /// <summary>Mouth speed (mouthSpeed and closureSpeed).</summary>
        [JsonProperty("speed")] public float Speed = 1f;
    }

    /// <summary>"Developer" camera: offsets from the base shot, zoom and tilt.</summary>
    [Serializable]
    public class CameraTuning
    {
        /// <summary>Metros hacia arriba.</summary>
        [JsonProperty("height")] public float Height;

        /// <summary>Meters moving away from Sonnia (negative, closer).</summary>
        [JsonProperty("distance")] public float Distance;

        /// <summary>Meters toward the right of the screen.</summary>
        [JsonProperty("side")] public float Side;

        /// <summary>Above 1 zooms in (narrower field of view).</summary>
        [JsonProperty("zoom")] public float Zoom = 1f;

        /// <summary>Degrees; positive looks lower.</summary>
        [JsonProperty("tilt")] public float Tilt;
    }

    /// <summary>
    /// "Developer" idle movement: multipliers of
    /// AvatarStateController (1 = tal cual).
    /// </summary>
    [Serializable]
    public class IdleTuning
    {
        /// <summary>Breathing: chest, shoulders and head.</summary>
        [JsonProperty("breath")] public float Breath = 1f;

        /// <summary>Body accents on stressed syllables while speaking.</summary>
        [JsonProperty("accents")] public float Accents = 1f;

        /// <summary>Pace of breathing and of the idle loop.</summary>
        [JsonProperty("speed")] public float Speed = 1f;
    }

    /// <summary>
    /// Sonnia is on screen or has gone away (the panel's away mode). It is a
    /// sticky message: the orchestrator re-sends it after <c>hello</c> to each new client.
    /// </summary>
    [Serializable]
    public class PresenceMessage
    {
        /// <summary>False: she walks off and leaves the away sign. True: she returns to her place.</summary>
        [JsonProperty("present")] public bool Present = true;

        /// <summary>Text of the away sign while she is gone. Empty: the default.</summary>
        [JsonProperty("message")] public string Message;
    }

    /// <summary>
    /// Operating mode and whether Sonnia can hold a conversation right now (the
    /// realtime model is on). Sticky: re-sent after <c>hello</c>. The screen only
    /// invites people to talk with <see cref="Talk"/> true.
    /// </summary>
    [Serializable]
    public class StageModeMessage
    {
        /// <summary><c>conversation</c>, <c>greeter</c> (greeter mode) o <c>away</c> (away).</summary>
        [JsonProperty("mode")] public string Mode = "conversation";

        /// <summary>True if Sonnia would answer whoever speaks to her.</summary>
        [JsonProperty("talk")] public bool Talk = true;
    }

    /// <summary>Values of the <c>activity</c> field of the <c>activity</c> message.</summary>
    public static class ActivityNames
    {
        /// <summary>Nothing special: the usual particle effect.</summary>
        public const string None = "none";

        /// <summary>A task delegated to the backend is taking long (over 5 s).</summary>
        public const string Think = "think";

        /// <summary>The backend is searching the web: Matrix-style rain.</summary>
        public const string Search = "search";
    }

    /// <summary>
    /// What Sonnia is doing behind the scenes: with <c>search</c> the Matrix-style
    /// rain appears (StageParticles) and <c>think</c> marks a task that takes
    /// long. Not sticky: it arrives each time it changes.
    /// </summary>
    [Serializable]
    public class ActivityMessage
    {
        [JsonProperty("activity")] public string Activity = ActivityNames.None;
    }

    /// <summary>Values of the <c>kind</c> field of the <c>busy</c> message, from highest to lowest priority.</summary>
    public static class BusyKinds
    {
        /// <summary>The backend is searching the web.</summary>
        public const string Search = "search";

        /// <summary>A task is delegated to the backend.</summary>
        public const string Think = "think";
    }

    /// <summary>
    /// On-screen busy indicator: a pill with animated dots while Sonnia waits for
    /// something the user cannot see. It is the whole state, not a change: with
    /// <c>on</c> the <c>text</c> is shown (or replaced if already visible) and
    /// without it the pill is hidden. The orchestrator sends it only on change and
    /// re-sends it on reconnect.
    /// </summary>
    [Serializable]
    public class BusyMessage
    {
        [JsonProperty("on")] public bool On;

        /// <summary>Kind of wait (<see cref="BusyKinds"/>); empty with <c>on: false</c>.</summary>
        [JsonProperty("kind")] public string Kind = string.Empty;

        /// <summary>What the pill says ("Thinking…"); empty with <c>on: false</c>.</summary>
        [JsonProperty("text")] public string Text = string.Empty;
    }

    /// <summary>Volume of Sonnia's voice. Also sticky: re-sent after <c>hello</c>.</summary>
    [Serializable]
    public class SetVolumeMessage
    {
        /// <summary>From 0 to 1.5; 1 is normal volume.</summary>
        [JsonProperty("value")] public float Value = 1f;
    }

    /// <summary>A microphone on the machine where the orchestrator runs.</summary>
    [Serializable]
    public class MicrophoneInfo
    {
        [JsonProperty("name")] public string Name;
        [JsonProperty("default")] public bool IsDefault;
    }

    /// <summary>
    /// Microphones on the machine and the current choice, for the options menu.
    /// Unity lists the cameras (<c>WebCamTexture.devices</c>); <c>camera</c> is the
    /// index the orchestrator uses and <c>camera_source</c> where it takes photos from.
    /// </summary>
    [Serializable]
    public class DevicesMessage
    {
        [JsonProperty("microphones")] public MicrophoneInfo[] Microphones;
        /// <summary>The configured one; empty means the system default (<see cref="DefaultMicrophone"/>).</summary>
        [JsonProperty("microphone")] public string Microphone;
        [JsonProperty("default_microphone")] public string DefaultMicrophone;
        [JsonProperty("camera")] public int Camera;
        [JsonProperty("camera_source")] public string CameraSource;
    }

    /// <summary>No more audio for that utterance.</summary>
    [Serializable]
    public class SpeechEndMessage
    {
        [JsonProperty("utterance_id")] public int UtteranceId;
    }

    /// <summary>Interruption: drop the queued audio and stop the mouth.</summary>
    [Serializable]
    public class StopSpeakingMessage
    {
        [JsonProperty("reason")] public string Reason = "interrupted";
    }

    /// <summary>Image to show in the scene's image panel.</summary>
    [Serializable]
    public class ShowImageMessage
    {
        [JsonProperty("image_id")] public string ImageId = string.Empty;
        [JsonProperty("source")] public string Source = ImageSources.Gallery;
        [JsonProperty("mime")] public string Mime = "image/png";
        [JsonProperty("data_base64")] public string DataBase64 = string.Empty;
        [JsonProperty("caption")] public string Caption;
    }

    /// <summary>Hides the image panel.</summary>
    [Serializable]
    public class HideImageMessage
    {
    }

    /// <summary>Human-readable error sent by the orchestrator.</summary>
    [Serializable]
    public class ErrorMessage
    {
        [JsonProperty("message")] public string Message = string.Empty;
    }

    /// <summary>The orchestrator asks for a capture from Unity's camera.</summary>
    [Serializable]
    public class RequestFrameMessage
    {
    }

    /// <summary>An audio chunk already decoded to float samples in [-1, 1].</summary>
    public struct AudioFrame
    {
        /// <summary>Utterance the chunk belongs to.</summary>
        public int UtteranceId;

        /// <summary>True if it is the last chunk of the utterance (bit 0 of <c>flags</c>).</summary>
        public bool IsLast;

        /// <summary>Mono samples at the rate announced in <c>hello</c>.</summary>
        public float[] Samples;
    }

    /// <summary>
    /// Protocol encoding and decoding. Managed code only: it can be called from
    /// any thread.
    /// </summary>
    public static class Protocol
    {
        /// <summary>Protocol version this client understands.</summary>
        public const int Version = 1;

        /// <summary>Size of the header of binary audio frames.</summary>
        public const int AudioHeaderSize = 12;

        /// <summary>Bit 0 of <c>flags</c>: last chunk of the utterance.</summary>
        public const uint FlagLast = 1u;

        /// <summary>Default sample rate until <c>hello</c> arrives.</summary>
        public const int DefaultSampleRate = 24000;

        /// <summary>Name Unity identifies itself with in <c>client_hello</c>.</summary>
        public const string ClientName = "unity";

        /// <summary>Scale from int16 to float.</summary>
        private const float PcmScale = 1f / 32768f;

        // --------------------------------------------------------------
        // Binary audio frames
        // --------------------------------------------------------------

        /// <summary>
        /// Decodes a binary "SNIA" frame to float samples. Returns false if the
        /// frame is too short or the magic does not match (the protocol says such
        /// messages are silently ignored).
        /// </summary>
        /// <param name="data">Buffer holding the whole frame.</param>
        /// <param name="length">Valid bytes inside the buffer.</param>
        /// <param name="frame">Decoded frame.</param>
        public static bool TryDecodeAudioFrame(byte[] data, int length, out AudioFrame frame)
        {
            return TryDecodeFrame(data, length, out frame);
        }

        private static bool TryDecodeFrame(byte[] data, int length, out AudioFrame frame)
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
        // Reading text messages
        // --------------------------------------------------------------

        /// <summary>
        /// Parses a JSON message and extracts its <c>type</c> field. Returns false if
        /// it is not valid JSON, not an object, or has no string <c>type</c>.
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
        /// Converts an already parsed JSON object to the matching message type.
        /// Returns null if the content does not fit, so the client ignores it.
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
        // Outgoing message builders (Unity -> orchestrator)
        // --------------------------------------------------------------

        /// <summary>
        /// Identifies the client right after connecting. <c>features</c> is empty:
        /// this client announces no optional capabilities.
        /// </summary>
        public static string ClientHelloMessage(string client, string version)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.ClientHello,
                ["client"] = string.IsNullOrEmpty(client) ? ClientName : client,
                ["version"] = string.IsNullOrEmpty(version) ? "0.1.0" : version,
                ["features"] = new JArray()
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>The user has interrupted Sonnia.</summary>
        public static string InterruptMessage()
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.Interrupt
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Unity finished playing an utterance.</summary>
        public static string PlaybackDoneMessage(int utteranceId)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.PlaybackDone,
                ["utterance_id"] = utteranceId
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Text input instead of voice (for testing without a microphone).</summary>
        public static string TextInputMessage(string text)
        {
            JObject message = new JObject
            {
                ["type"] = MessageTypes.TextInput,
                ["text"] = text ?? string.Empty
            };
            return message.ToString(Formatting.None);
        }

        /// <summary>Capture from Unity's camera, JPEG-encoded.</summary>
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

        /// <summary>Catalog of animations the panel can trigger: (clip, group) pairs.</summary>
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

        /// <summary>Asks for the list of microphones and the current choice (options menu).</summary>
        public static string ListDevicesMessage()
        {
            JObject message = new JObject { ["type"] = MessageTypes.ListDevices };
            return message.ToString(Formatting.None);
        }

        /// <summary>Chooses a microphone (name; empty means the system default) from the options menu.</summary>
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

        /// <summary>Chooses a camera (index) from the options menu.</summary>
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


    }
}
