// Puente entre uLipSync (análisis de fonemas por MFCC) y el lip-sync de Sonia.
//
// El audio de la voz llega en streaming y no existe como AudioClip, así que
// uLipSync no puede analizar el AudioSource por su cuenta: aquí se le pasa cada
// bloque que AudioStreamPlayer va a reproducir (evento OnAudioFrame, en el hilo
// de audio, con el audio que sonará dentro de lipSyncLeadMs) y, en cada frame,
// se traduce su resultado (fonema dominante, proporciones A/I/U/E/O/silencio y
// volumen) a los visemas del protocolo, que LipSyncController convierte en
// blendshapes con su suavizado.
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

        [SerializeField]
        [Tooltip("Volumen bruto (RMS) que se considera silencio y volumen bruto al que la boca abre del todo. Se mide con la voz real.")]
        private Vector2 rawVolumeRange = new Vector2(0.01f, 0.30f);

        [SerializeField]
        [Range(0.3f, 2f)]
        [Tooltip("Curva de apertura: 1 lineal, menos de 1 abre antes con poco volumen.")]
        private float volumeCurve = 0.7f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Apertura mínima cuando hay voz, para que las sílabas flojas no cierren la boca del todo.")]
        private float minOpenWhileVoiced = 0.18f;

        private bool _subscribed;

        // El hilo de audio no puede tocar la API de Unity (ni siquiera
        // isActiveAndEnabled): el estado del analizador se cachea aquí desde el
        // hilo principal y el hilo de audio solo lee este campo.
        private volatile bool _analyzerReady;
        private uLipSync.uLipSync _analyzerForAudioThread;

        /// <summary>Último fonema dominante que devolvió el analizador.</summary>
        public string CurrentPhoneme { get; private set; }

        /// <summary>Última apertura derivada del volumen (0..1).</summary>
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
            if (lipSync != null)
            {
                lipSync.ClearPhonemeFrame();
            }
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

            // Volumen bruto -> apertura 0..1 con una curva suave: así las sílabas
            // flojas abren un poco y las fuertes no clavan la boca al máximo.
            float lo = Mathf.Max(0.00001f, rawVolumeRange.x);
            float hi = Mathf.Max(lo * 1.5f, rawVolumeRange.y);
            float t = Mathf.Clamp01((info.rawVolume - lo) / (hi - lo));
            float volume = t > 0f ? Mathf.Lerp(minOpenWhileVoiced, 1f, Mathf.Pow(t, volumeCurve)) : 0f;
            CurrentPhoneme = info.phoneme;
            CurrentVolume = volume;

            if (ratios == null || volume <= 0f || string.IsNullOrEmpty(info.phoneme) || info.phoneme == "-")
            {
                lipSync.SetPhonemeFrame(0f, 0f, 0f, 0f, 0f, 0f);
                return;
            }

            // Los perfiles de uLipSync nombran los fonemas A, I, U, E, O y "-"
            // (silencio); también se aceptan minúsculas y "N" (nasal, boca casi cerrada).
            float a = Ratio(ratios, "A", "a");
            float i = Ratio(ratios, "I", "i");
            float u = Ratio(ratios, "U", "u");
            float e = Ratio(ratios, "E", "e");
            float o = Ratio(ratios, "O", "o");
            float n = Ratio(ratios, "N", "n");
            lipSync.SetPhonemeFrame(a * volume, i * volume, u * volume, e * volume, o * volume, n * volume);
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
