// Puente entre uLipSync (análisis de fonemas por MFCC) y el lip-sync de Sonia.
//
// El audio de la voz llega en streaming y no existe como AudioClip, así que
// uLipSync no puede analizar el AudioSource por su cuenta: aquí se le pasa cada
// bloque que AudioStreamPlayer va a reproducir (evento OnAudioFrame, en el hilo
// de audio, con el audio que sonará dentro de lipSyncLeadMs) y, en cada frame,
// se pasan sus proporciones de vocal (A/I/U/E/O) a LipSyncController, que solo
// las usa para la forma de la boca: cuánto abre lo mide él en el audio.
//
// uLipSync es MIT (github.com/hecomi/uLipSync). El perfil de fonemas se puede
// calibrar con la propia voz de Sonia desde su inspector.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Alimenta uLipSync con el audio en streaming y vuelca sus fonemas en el lip-sync.</summary>
    [DefaultExecutionOrder(11500)]
    [DisallowMultipleComponent]
    public class PhonemeLipSyncBridge : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Reproductor del audio en streaming. Si está vacío se busca en este objeto.")]
        private AudioStreamPlayer audioPlayer;

        [SerializeField]
        [Tooltip("Analizador de fonemas. Si está vacío se busca en este objeto.")]
        private uLipSync.uLipSync analyzer;

        [SerializeField]
        [Tooltip("Lip-sync que recibe los visemas. Si está vacío se busca en este objeto.")]
        private LipSyncController lipSync;

        private bool _subscribed;

        // El hilo de audio no puede tocar la API de Unity (ni siquiera
        // isActiveAndEnabled): el estado del analizador se cachea aquí desde el
        // hilo principal y el hilo de audio solo lee este campo.
        private volatile bool _analyzerReady;
        private uLipSync.uLipSync _analyzerForAudioThread;

        /// <summary>Último fonema dominante que devolvió el analizador.</summary>
        public string CurrentPhoneme { get; private set; }

        /// <summary>Último volumen normalizado del analizador (0..1), solo informativo.</summary>
        public float CurrentVolume { get; private set; }

        /// <summary>Último volumen bruto (RMS) del analizador, para calibrar el rango.</summary>
        public float CurrentRawVolume { get; private set; }

        private void Awake()
        {
            if (audioPlayer == null)
            {
                audioPlayer = GetComponent<AudioStreamPlayer>();
            }

            if (analyzer == null)
            {
                // El analizador vive en un objeto hijo, lejos del AudioSource: si
                // compartiera objeto, Unity le pasaría también la salida retardada.
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

        /// <summary>Hilo de audio: se le pasa el bloque al analizador.</summary>
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

            // Los perfiles de uLipSync nombran los fonemas A, I, U, E, O y "-"
            // (silencio). Al lip-sync solo le interesa qué vocal es: cuánto abre
            // la boca lo mide él sobre el audio.
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
