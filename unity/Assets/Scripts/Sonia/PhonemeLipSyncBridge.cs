// Bridge between uLipSync (MFCC phoneme analysis) and Sonnia's lip-sync.
//
// The voice audio arrives as a stream and never exists as an AudioClip, so
// uLipSync cannot analyze the AudioSource by itself: this bridge feeds it each
// block that AudioStreamPlayer is about to play (OnAudioFrame event, on the
// audio thread, with the audio that will sound in lipSyncLeadMs) and, every
// frame, passes its vowel ratios (A/I/U/E/O) to LipSyncController, which only
// uses them for the mouth shape: how wide it opens is measured on the audio.
//
// uLipSync is MIT (github.com/hecomi/uLipSync). The phoneme profile can be
// calibrated with Sonnia's own voice from its inspector.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Feeds uLipSync with the streamed audio and pushes its phonemes into the lip-sync.</summary>
    [DefaultExecutionOrder(11500)]
    [DisallowMultipleComponent]
    public class PhonemeLipSyncBridge : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Streaming audio player. If empty, it is looked up on this object.")]
        private AudioStreamPlayer audioPlayer;

        [SerializeField]
        [Tooltip("Phoneme analyzer. If empty, it is looked up on this object.")]
        private uLipSync.uLipSync analyzer;

        [SerializeField]
        [Tooltip("Lip-sync that receives the visemes. If empty, it is looked up on this object.")]
        private LipSyncController lipSync;

        private bool _subscribed;

        // The audio thread cannot touch the Unity API (not even
        // isActiveAndEnabled): the analyzer state is cached here from the
        // main thread and the audio thread only reads this field.
        private volatile bool _analyzerReady;
        private uLipSync.uLipSync _analyzerForAudioThread;

        /// <summary>Last dominant phoneme returned by the analyzer.</summary>
        public string CurrentPhoneme { get; private set; }

        /// <summary>Last normalized analyzer volume (0..1), informational only.</summary>
        public float CurrentVolume { get; private set; }

        /// <summary>Last raw (RMS) analyzer volume, for calibrating the range.</summary>
        public float CurrentRawVolume { get; private set; }

        private void Awake()
        {
            if (audioPlayer == null)
            {
                audioPlayer = GetComponent<AudioStreamPlayer>();
            }

            if (analyzer == null)
            {
                // The analyzer lives on a child object, away from the AudioSource: if
                // it shared the object, Unity would also feed it the delayed output.
                analyzer = GetComponentInChildren<uLipSync.uLipSync>(true);
            }

            if (lipSync == null)
            {
                lipSync = GetComponent<LipSyncController>();
            }
        }

        private void OnEnable()
        {
            if (audioPlayer != null && !_subscribed)
            {
                audioPlayer.OnAudioFrame += HandleAudioFrame;
                _subscribed = true;
            }
        }

        private void OnDisable()
        {
            if (audioPlayer != null && _subscribed)
            {
                audioPlayer.OnAudioFrame -= HandleAudioFrame;
                _subscribed = false;
            }

            _analyzerReady = false;
            _analyzerForAudioThread = null;
        }

        /// <summary>Audio thread: hands the block to the analyzer.</summary>
        private void HandleAudioFrame(float[] data, int channels)
        {
            uLipSync.uLipSync target = _analyzerForAudioThread;
            if (_analyzerReady && target != null)
            {
                target.OnDataReceived(data, channels);
            }
        }

        private void Update()
        {
            bool ready = analyzer != null && analyzer.isActiveAndEnabled && analyzer.profile != null;
            _analyzerForAudioThread = ready ? analyzer : null;
            _analyzerReady = ready;
            if (!ready || lipSync == null)
            {
                return;
            }

            uLipSync.LipSyncInfo info = analyzer.result;
            Dictionary<string, float> ratios = info.phonemeRatios;
            CurrentRawVolume = info.rawVolume;
            CurrentPhoneme = info.phoneme;
            CurrentVolume = info.volume;
            if (ratios == null || ratios.Count == 0)
            {
                return;
            }

            // uLipSync profiles name the phonemes A, I, U, E, O and "-"
            // (silence). The lip-sync only cares which vowel it is: how wide
            // the mouth opens is measured by it on the audio.
            float a = Ratio(ratios, "A", "a");
            float i = Ratio(ratios, "I", "i");
            float u = Ratio(ratios, "U", "u");
            float e = Ratio(ratios, "E", "e");
            float o = Ratio(ratios, "O", "o");
            int rate = AudioSettings.outputSampleRate > 0 ? AudioSettings.outputSampleRate : 48000;
            int window = Mathf.RoundToInt(analyzer.profile.sampleCount * (rate / (float)Mathf.Max(1, analyzer.profile.targetSampleRate)));
            lipSync.PushVowelRatios(a, i, u, e, o, window);
        }

        private static float Ratio(Dictionary<string, float> ratios, string upper, string lower)
        {
            float value;
            if (ratios.TryGetValue(upper, out value))
            {
                return value;
            }

            return ratios.TryGetValue(lower, out value) ? value : 0f;
        }
    }
}
