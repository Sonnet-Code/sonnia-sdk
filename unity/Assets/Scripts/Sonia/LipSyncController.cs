// Avatar lip-sync from the voice that is playing.
//
// Every frame the mouth is composed of three things measured on the audio:
//
//  1. How wide it opens: the syllable envelope (SpeechAnalyzer, 5 ms windows and
//     gain control). It is what is most noticeable from afar and what can never
//     be off-beat, so it is taken from the audio itself with a small lead: the
//     mouth gets ready a little before the syllable sounds, like in a person.
//  2. What shape: the vowel recognized by uLipSync (A, E, I, O, U) through
//     PhonemeLipSyncBridge, smoothed and blended with a neutral shape depending
//     on how sure it is, because a wrong "o" is more visible than an extra "a".
//  3. The visible consonants: lip closure in the deep valleys between
//     syllables (p, b, m and the rest of the plosives) and teeth together on "s".
//
// The mouth is written to the FaceRig channels (viseme_aa, viseme_PP...,
// jawOpen), which translates them to the avatar's shapes: on Genies avatars, to
// the FACS recipes. Visemes are used almost at full weight (at 0.2 the mouth
// barely opened) and the jaw is added on strong syllables. Everything goes
// through critically damped springs.
//
// When the voice stops, the mouth does not snap shut: if there is no voice
// ahead, the remaining opening closes with a smooth curve over closeSeconds
// (like the Genies MouthCloser). On an interruption, the same but faster.
//
// It also dispatches the prosody: the analyzer's syllable and phrase events
// go out through OnSpeechEvent when their moment arrives, so head, eyebrows and
// blinking go with the voice.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Moves the mouth with the voice that is playing and dispatches the prosody events.</summary>
    [DefaultExecutionOrder(12000)]
    [DisallowMultipleComponent]
    public class LipSyncController : MonoBehaviour
    {
        [Header("References")]
        [SerializeField]
        [Tooltip("Avatar face: the mouth is written to its viseme and jawOpen channels.")]
        private FaceRig faceRig;

        [SerializeField]
        [Tooltip("Streaming audio player: the voice that is analyzed comes from it.")]
        private AudioStreamPlayer audioPlayer;

        [Header("Sync")]
        [SerializeField]
        [Range(40f, 200f)]
        [Tooltip("Voice delay relative to the analysis (ms). It is how far ahead the face can see: mouth lead, closures before the p and gestures that precede the syllable. Applied to AudioStreamPlayer on start if its own is lower.")]
        public float voiceDelayMs = 100f;

        [SerializeField]
        [Range(-60f, 120f)]
        [Tooltip("How far the mouth leads what is heard (ms). Positive: the mouth goes first, like in real speech.")]
        public float mouthLeadMs = 35f;

        [SerializeField]
        [Range(0f, 160f)]
        [Tooltip("How far gestures (head, eyebrows, blink) lead their syllable (ms).")]
        public float gestureLeadMs = 70f;

        [SerializeField]
        [Range(-1f, 200f)]
        [Tooltip("Audio output latency in ms (how long the block takes to play). -1: one DSP buffer.")]
        public float outputLatencyMs = -1f;

        [Header("Mouth")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Weight of the vowel viseme on a strong syllable. At 1 the mouth makes the full viseme shape.")]
        public float vowelWeight = 0.85f;

        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("Opening intensity: multiplies vowels and jaw (1 = as is). Adjusted from the control panel.")]
        public float openScale = 1f;

        [SerializeField]
        [Range(0.3f, 1.5f)]
        [Tooltip("Opening curve: below 1 opens sooner with a weak voice.")]
        public float openCurve = 1f;

        [SerializeField]
        [Range(0f, 0.6f)]
        [Tooltip("Extra jaw (jawOpen) on the strongest syllables with an open vowel.")]
        public float jawBoost = 0.18f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("How much the recognized vowel counts versus a neutral shape (a, e).")]
        public float vowelTrust = 0.75f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Lip closure (viseme_PP) in the valleys between syllables: p, b, m and other plosives.")]
        public float closureWeight = 0.85f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Teeth together (viseme_SS) on the s.")]
        public float sibilantWeight = 0.5f;

        [SerializeField]
        [Range(2f, 20f)]
        [Tooltip("Mouth speed (spring Hz). Higher is crisper; lower is softer.")]
        public float mouthSpeed = 10f;

        [SerializeField]
        [Range(2f, 30f)]
        [Tooltip("Lip closure speed (spring Hz). A slow closure is not visible.")]
        public float closureSpeed = 16f;

        [SerializeField]
        [Range(0.01f, 0.2f)]
        [Tooltip("Time constant (s) of the recognized vowel smoothing. Too low: the shape jitters.")]
        public float vowelSmoothing = 0.05f;

        [Header("Closing when voice stops")]
        [SerializeField]
        [Range(0f, 2f)]
        [Tooltip("When the voice stops, the mouth finishes closing in this time with a smooth curve (like the Genies MouthCloser). Almost all of the closing happens in the first 40 %. 0: with the spring, abruptly.")]
        public float closeSeconds = 1f;

        [SerializeField]
        [Range(0.02f, 0.12f)]
        [Tooltip("Silence that must be seen ahead (s) to close slowly. Shorter pauses (consonants, between words) close with the spring.")]
        public float closeLookahead = 0.06f;

        [SerializeField]
        [Range(0.05f, 1f)]
        [Tooltip("Closing time when the voice is cut (interruption): fast, but without snapping to a closed mouth.")]
        public float interruptCloseSeconds = 0.25f;

        /// <summary>Prosody event when its moment arrives (see gestureLeadMs). Main thread.</summary>
        public event Action<SpeechAnalyzer.SpeechEvent> OnSpeechEvent;

        // Vowels in the order of the mouth channels.
        private const int VA = 0, VE = 1, VI = 2, VO = 3, VU = 4;
        private static readonly string[] VowelChannels = { "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U" };

        // Neutral shape of a syllable when the vowel is unknown: open and relaxed.
        private static readonly float[] NeutralMix = { 0.6f, 0.3f, 0.1f, 0f, 0f };

        private struct VowelSample
        {
            public long Sample;
            public float A, E, I, O, U;
        }

        private SpeechAnalyzer _analyzer;
        private readonly List<SpeechAnalyzer.SpeechEvent> _eventBuffer = new List<SpeechAnalyzer.SpeechEvent>();
        private readonly VowelSample[] _vowels = new VowelSample[64];
        private int _vowelCount;
        private int _vowelHead;
        private long _writtenLastFrame;
        private bool _subscribed;

        private bool _hasVisemeShapes;
        private readonly int[] _vowelChannels = { -1, -1, -1, -1, -1 };
        private int _ppChannel = -1;
        private int _ssChannel = -1;
        private int _jawChannel = -1;

        private double _clock;
        private bool _clockReady;
        private readonly float[] _mix = { 0.6f, 0.3f, 0.1f, 0f, 0f };
        private Spring _open;
        private Spring _closure;
        private Spring _sibilant;
        private Spring _jaw;
        private readonly Spring[] _vowelSprings = new Spring[5];
        private float _roundness;
        private bool _active;

        // Smooth closing when voice stops: starting opening, elapsed time and duration.
        private bool _closing;
        private float _closeFrom;
        private float _closeElapsed;
        private float _closeDuration;

        // Scene values before the control panel multipliers.
        private bool _tuningBaseCaptured;
        private float _baseJawBoost;
        private float _baseClosureWeight;
        private float _baseMouthSpeed;
        private float _baseClosureSpeed;

        /// <summary>True if the face has usable viseme channels.</summary>
        public bool HasVisemeShapes
        {
            get { return _hasVisemeShapes; }
        }

        /// <summary>Current mouth opening, 0..1. Useful to pace gestures to the voice.</summary>
        public float MouthOpen
        {
            get { return Mathf.Clamp01(_open.Value); }
        }

        /// <summary>How much the lips are rounded now (o, u), 0..1: with a round mouth a wide smile does not fit.</summary>
        public float Roundness
        {
            get { return _roundness; }
        }

        /// <summary>True while there is voice in the mouth (syllables sounding or about to sound).</summary>
        public bool IsTalking
        {
            get { return _active; }
        }

        /// <summary>True while the vowel comes from the real-time phoneme analysis.</summary>
        public bool UsingPhonemes
        {
            get { return _vowelCount > 0; }
        }

        /// <summary>Voice analyzer (level, bands, prosody). May be null without a player.</summary>
        public SpeechAnalyzer Analyzer
        {
            get { return _analyzer; }
        }

        /// <summary>Sample (analysis clock) that is playing right now.</summary>
        public double AudibleSample
        {
            get { return _clock; }
        }

        /// <summary>Output latency samples being assumed.</summary>
        public int OutputLatencySamples
        {
            get { return LatencySamples(); }
        }

        /// <summary>Avatar face. When changed the channels are resolved again.</summary>
        public FaceRig FaceRig
        {
            get { return faceRig; }
            set
            {
                if (faceRig != null)
                {
                    faceRig.Rebuilt -= RebindBlendShapes;
                }

                faceRig = value;
                if (faceRig != null && isActiveAndEnabled)
                {
                    faceRig.Rebuilt += RebindBlendShapes;
                }

                RebindBlendShapes();
            }
        }

        private void Awake()
        {
            if (audioPlayer == null)
            {
                audioPlayer = GetComponentInParent<AudioStreamPlayer>();
            }

            if (audioPlayer != null)
            {
                _analyzer = new SpeechAnalyzer(audioPlayer.OutputSampleRate);
                if (audioPlayer.LipSyncLeadMs < voiceDelayMs)
                {
                    audioPlayer.LipSyncLeadMs = voiceDelayMs;
                }
            }

            RebindBlendShapes();
        }

        private void OnEnable()
        {
            if (audioPlayer != null && _analyzer != null && !_subscribed)
            {
                audioPlayer.OnAudioFrame += _analyzer.Push;
                _subscribed = true;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RebindBlendShapes;
                faceRig.Rebuilt += RebindBlendShapes;
            }
        }

        private void OnDisable()
        {
            if (audioPlayer != null && _analyzer != null && _subscribed)
            {
                audioPlayer.OnAudioFrame -= _analyzer.Push;
                _subscribed = false;
            }

            if (faceRig != null)
            {
                faceRig.Rebuilt -= RebindBlendShapes;
            }
        }

        /// <summary>Resolves the mouth channels on the face. Called automatically and when the avatar changes.</summary>
        public void RebindBlendShapes()
        {
            _hasVisemeShapes = false;
            for (int v = 0; v < VowelChannels.Length; v++)
            {
                _vowelChannels[v] = faceRig != null ? faceRig.Channel(VowelChannels[v]) : -1;
                _hasVisemeShapes |= _vowelChannels[v] >= 0;
            }

            _ppChannel = faceRig != null ? faceRig.Channel("viseme_PP") : -1;
            _ssChannel = faceRig != null ? faceRig.Channel("viseme_SS") : -1;
            _jawChannel = faceRig != null ? faceRig.Channel("jawOpen") : -1;
            if (_jawChannel < 0 && faceRig != null)
            {
                _jawChannel = faceRig.Channel("mouthOpen");
            }
        }

        /// <summary>
        /// Factor that converts a 0..100 weight to the mesh's real scale: 1 for
        /// meshes whose blendshape frames are at 100 and 0.01 for those whose
        /// frames are at 1.
        /// </summary>
        public static float BlendShapeScale(Mesh mesh)
        {
            if (mesh == null || mesh.blendShapeCount == 0)
            {
                return 1f;
            }

            int frames = mesh.GetBlendShapeFrameCount(0);
            float full = frames > 0 ? mesh.GetBlendShapeFrameWeight(0, frames - 1) : 100f;
            return full > 0.0001f ? full / 100f : 1f;
        }

        /// <summary>Finds a blendshape by name, case-insensitive and accepting a dotted prefix.</summary>
        public static int FindBlendShape(Mesh mesh, string name)
        {
            if (mesh == null || string.IsNullOrEmpty(name))
            {
                return -1;
            }

            int direct = mesh.GetBlendShapeIndex(name);
            if (direct >= 0)
            {
                return direct;
            }

            int total = mesh.blendShapeCount;
            for (int i = 0; i < total; i++)
            {
                string candidate = mesh.GetBlendShapeName(i);
                if (string.IsNullOrEmpty(candidate))
                {
                    continue;
                }

                if (string.Equals(candidate, name, StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }

                int dot = candidate.LastIndexOf('.');
                if (dot >= 0 && dot + 1 < candidate.Length
                    && string.Equals(candidate.Substring(dot + 1), name, StringComparison.OrdinalIgnoreCase))
                {
                    return i;
                }
            }

            return -1;
        }

        // ------------------------------------------------------------------
        // Inputs
        // ------------------------------------------------------------------

        /// <summary>
        /// Vowel proportions recognized by uLipSync (PhonemeLipSyncBridge),
        /// computed over a window of <paramref name="windowSamples"/> samples
        /// that ends at the last audio the analyzer saw.
        /// </summary>
        public void PushVowelRatios(float a, float i, float u, float e, float o, int windowSamples)
        {
            float sum = a + i + u + e + o;
            if (sum <= 0.0001f)
            {
                return;
            }

            VowelSample sample = new VowelSample
            {
                // This frame's phoneme analysis used the audio available when the
                // previous one ended; the window is dated at its center.
                Sample = _writtenLastFrame - (windowSamples / 2),
                A = a / sum,
                E = e / sum,
                I = i / sum,
                O = o / sum,
                U = u / sum
            };
            _vowelHead = (_vowelHead + 1) % _vowels.Length;
            _vowels[_vowelHead] = sample;
            _vowelCount = Mathf.Min(_vowelCount + 1, _vowels.Length);
        }

        /// <summary>An utterance finished playing. Nothing to release: everything is measured on the fly.</summary>
        public void NotifyUtteranceFinished(int utteranceId)
        {
        }

        /// <summary>
        /// Interruption: pending voice is forgotten and the mouth closes now, in
        /// interruptCloseSeconds and with the same smooth curve as at the end of
        /// an utterance (snapping to a closed mouth in one frame looks like a cut).
        /// </summary>
        public void StopAndClose()
        {
            if (_analyzer != null)
            {
                _analyzer.ClearEvents();
            }

            _closure.Reset();
            _sibilant.Reset();
            _vowelCount = 0;
            _active = false;
            _closing = true;
            _closeFrom = Mathf.Max(0f, _open.Value);
            _closeElapsed = 0f;
            _closeDuration = Mathf.Max(0.05f, interruptCloseSeconds);
        }

        /// <summary>Internal state as text, for debugging from the editor or the HUD.</summary>
        public string DebugInfo()
        {
            return "face=" + (faceRig != null && faceRig.PrimaryRenderer != null ? faceRig.PrimaryRenderer.name : "null")
                   + " visemes=" + _hasVisemeShapes
                   + " clock=" + _clock.ToString("F0")
                   + " open=" + _open.Value.ToString("F2")
                   + " closure=" + _closure.Value.ToString("F2")
                   + " s=" + _sibilant.Value.ToString("F2")
                   + " vowel=[" + _mix[VA].ToString("F2") + " " + _mix[VE].ToString("F2") + " " + _mix[VI].ToString("F2")
                   + " " + _mix[VO].ToString("F2") + " " + _mix[VU].ToString("F2") + "]";
        }

        // ------------------------------------------------------------------
        // Animation
        // ------------------------------------------------------------------

        private void Update()
        {
            if (_analyzer == null)
            {
                return;
            }

            // Whatever arrived from the audio thread is analyzed before anyone
            // (face, head) queries it in LateUpdate.
            _writtenLastFrame = _analyzer.Written;
            _analyzer.Process();
            AdvanceClock(Time.deltaTime);
            DispatchEvents();
        }

        private int LatencySamples()
        {
            int rate = _analyzer != null ? _analyzer.SampleRate : 48000;
            if (outputLatencyMs >= 0f)
            {
                return Mathf.RoundToInt(outputLatencyMs / 1000f * rate);
            }

            int length;
            int buffers;
            AudioSettings.GetDSPBufferSize(out length, out buffers);
            return Mathf.Max(0, length);
        }

        /// <summary>
        /// Clock of what is playing: the latest the analysis saw minus the voice
        /// delay and the output latency. Audio blocks arrive in jumps (21 ms with
        /// 1024 samples at 48 kHz), so the clock advances with game time and is
        /// gradually corrected toward the measurement.
        /// </summary>
        private void AdvanceClock(float dt)
        {
            int rate = _analyzer.SampleRate;
            float delayMs = audioPlayer != null ? audioPlayer.LipSyncLeadMs : 0f;
            double measured = _analyzer.Written - (delayMs / 1000.0 * rate) - LatencySamples();
            if (!_clockReady || Math.Abs(measured - _clock) > rate * 0.1)
            {
                _clock = measured;
                _clockReady = true;
                return;
            }

            _clock += dt * rate;
            _clock += (measured - _clock) * Mathf.Clamp01(dt * 6f);
        }

        private void DispatchEvents()
        {
            _eventBuffer.Clear();
            double horizon = _clock + gestureLeadMs / 1000.0 * _analyzer.SampleRate;
            _analyzer.TakeEvents((long)horizon, _eventBuffer);
            Action<SpeechAnalyzer.SpeechEvent> handler = OnSpeechEvent;
            for (int i = 0; i < _eventBuffer.Count; i++)
            {
                if (handler != null)
                {
                    handler(_eventBuffer[i]);
                }
            }
        }

        private void LateUpdate()
        {
            float dt = Time.deltaTime;
            if (_analyzer == null)
            {
                return;
            }

            int rate = _analyzer.SampleRate;
            double at = _clock + mouthLeadMs / 1000.0 * rate;
            SpeechAnalyzer.Features f = _analyzer.Sample(at);
            float closure = _analyzer.ClosureAt(at, 0.07f);
            float nasal = f.Nasality * 0.5f;
            closure = Mathf.Max(closure, nasal);

            // Opening: the syllable envelope with its curve, reduced by the lip
            // closure and by the s (teeth together).
            float open = Mathf.Pow(Mathf.Clamp01(f.Syllable), openCurve);
            float sib = f.Sibilance;
            float openTarget = open * (1f - closure) * (1f - 0.6f * sib);
            _active = f.Voiced || openTarget > 0.05f;

            UpdateVowelMix(at, dt);
            UpdateOpening(f, openTarget, at, dt);
            _closure.Step(closure * closureWeight, closureSpeed, closureSpeed * 0.7f, dt);
            _sibilant.Step(sib * sibilantWeight * (1f - closure), mouthSpeed, dt);

            float a = Mathf.Clamp01(_open.Value);
            for (int v = 0; v < _vowelSprings.Length; v++)
            {
                _vowelSprings[v].Step(a * vowelWeight * _mix[v], mouthSpeed * 1.4f, mouthSpeed, dt);
            }

            float jawTarget = jawBoost * Mathf.Clamp01((a - 0.5f) / 0.5f) * (_mix[VA] + 0.6f * _mix[VO] + 0.3f * _mix[VE]);
            _jaw.Step(jawTarget, mouthSpeed, dt);
            _roundness = Mathf.Clamp01((_mix[VO] + _mix[VU]) * a * 1.6f);
            Apply(a);
        }

        /// <summary>
        /// Mouth opening. With voice, the usual spring. When the voice stops (no
        /// voice now nor within closeLookahead ahead), what remains open closes
        /// over closeSeconds with a curve that slows at the end (cubic), without
        /// the spring's snap. If voice returns, the spring continues from wherever
        /// it is.
        /// </summary>
        private void UpdateOpening(SpeechAnalyzer.Features f, float openTarget, double at, float dt)
        {
            bool quiet = !f.Voiced && openTarget < 0.05f;
            bool interrupting = _closing && _closeDuration < closeSeconds;
            if (quiet && closeSeconds > 0.01f && (interrupting || SilentAhead(at, closeLookahead)))
            {
                if (!_closing)
                {
                    _closing = true;
                    _closeFrom = Mathf.Max(0f, _open.Value);
                    _closeElapsed = 0f;
                    _closeDuration = closeSeconds;
                }

                _closeElapsed += dt;
                float x = Mathf.Clamp01(_closeElapsed / Mathf.Max(0.05f, _closeDuration));
                float left = 1f - x;
                _open.Value = _closeFrom * left * left * left;
                _open.Velocity = 0f;
                return;
            }

            _closing = false;
            _open.Step(openTarget, mouthSpeed * 1.4f, mouthSpeed, dt);
        }

        /// <summary>
        /// True if there is no voice in the <paramref name="seconds"/> following
        /// <paramref name="at"/>. Only what is already analyzed is looked at (it
        /// runs about 100 ms ahead of what is heard); with less than 30 ms in
        /// view nothing is decided.
        /// </summary>
        private bool SilentAhead(double at, float seconds)
        {
            int rate = _analyzer.SampleRate;
            double end = Math.Min(at + seconds * rate, _analyzer.AnalyzedUpTo - 1);
            if (end - at < 0.03 * rate)
            {
                return false;
            }

            double step = Math.Max(1.0, 0.005 * rate);
            for (double s = at + step; s <= end; s += step)
            {
                if (_analyzer.Sample(s).Voiced)
                {
                    return false;
                }
            }

            return true;
        }

        /// <summary>
        /// Control panel tuning: multipliers over what the scene provides
        /// (1 = as is) for the opening, the extra jaw, the lip closure and the
        /// speed. The scene values are stored the first time.
        /// </summary>
        public void ApplyTuning(float open, float jaw, float closure, float speed)
        {
            if (!_tuningBaseCaptured)
            {
                _baseJawBoost = jawBoost;
                _baseClosureWeight = closureWeight;
                _baseMouthSpeed = mouthSpeed;
                _baseClosureSpeed = closureSpeed;
                _tuningBaseCaptured = true;
            }

            float pace = Mathf.Clamp(speed, 0.25f, 4f);
            openScale = Mathf.Clamp(open, 0f, 2f);
            jawBoost = Mathf.Clamp01(_baseJawBoost * Mathf.Max(0f, jaw));
            closureWeight = Mathf.Clamp01(_baseClosureWeight * Mathf.Max(0f, closure));
            mouthSpeed = Mathf.Clamp(_baseMouthSpeed * pace, 1f, 40f);
            closureSpeed = Mathf.Clamp(_baseClosureSpeed * pace, 1f, 60f);
        }

        /// <summary>Vowel mix at the requested instant: the classifier's, smoothed and weighted by confidence.</summary>
        private void UpdateVowelMix(double at, float dt)
        {
            float a, e, i, o, u;
            if (!SampleVowels(at, out a, out e, out i, out o, out u))
            {
                // No classifier: neutral shape.
                a = NeutralMix[VA];
                e = NeutralMix[VE];
                i = NeutralMix[VI];
                o = NeutralMix[VO];
                u = NeutralMix[VU];
            }

            // The distribution is sharpened (a clear vowel rules) and the
            // confidence is measured: with 0.2 on each vowel nothing is known;
            // with 0.6 on one, it is.
            float sa = a * a, se = e * e, si = i * i, so = o * o, su = u * u;
            float sum = Mathf.Max(0.0001f, sa + se + si + so + su);
            float max = Mathf.Max(Mathf.Max(a, e), Mathf.Max(Mathf.Max(i, o), u));
            float trust = Mathf.Clamp01((max - 0.3f) / 0.35f) * vowelTrust;
            float k = 1f - Mathf.Exp(-dt / Mathf.Max(0.005f, vowelSmoothing));
            _mix[VA] = Mathf.Lerp(_mix[VA], Mathf.Lerp(NeutralMix[VA], sa / sum, trust), k);
            _mix[VE] = Mathf.Lerp(_mix[VE], Mathf.Lerp(NeutralMix[VE], se / sum, trust), k);
            _mix[VI] = Mathf.Lerp(_mix[VI], Mathf.Lerp(NeutralMix[VI], si / sum, trust), k);
            _mix[VO] = Mathf.Lerp(_mix[VO], Mathf.Lerp(NeutralMix[VO], so / sum, trust), k);
            _mix[VU] = Mathf.Lerp(_mix[VU], Mathf.Lerp(NeutralMix[VU], su / sum, trust), k);
        }

        private bool SampleVowels(double at, out float a, out float e, out float i, out float o, out float u)
        {
            a = e = i = o = u = 0f;
            if (_vowelCount == 0)
            {
                return false;
            }

            // The sample closest to the requested instant (there is one every frame).
            int best = -1;
            double bestDistance = double.MaxValue;
            for (int n = 0; n < _vowelCount; n++)
            {
                int index = (_vowelHead - n + _vowels.Length) % _vowels.Length;
                double distance = Math.Abs(_vowels[index].Sample - at);
                if (distance < bestDistance)
                {
                    bestDistance = distance;
                    best = index;
                }
            }

            if (best < 0 || bestDistance > _analyzer.SampleRate * 0.25)
            {
                return false;
            }

            VowelSample s = _vowels[best];
            a = s.A;
            e = s.E;
            i = s.I;
            o = s.O;
            u = s.U;
            return true;
        }

        private void Apply(float open)
        {
            if (faceRig == null)
            {
                return;
            }

            // FaceRig sums everyone's contribution and writes once: several
            // channels share shapes (on Genies almost all vowels carry JAW_DROP).
            // The control panel intensity scales what opens (vowels and jaw), not
            // the closures: a p still brings the lips together the same.
            float keep = 1f - Mathf.Clamp01(_closure.Value);
            float scale = Mathf.Max(0f, openScale);
            for (int v = 0; v < _vowelChannels.Length; v++)
            {
                faceRig.Add(_vowelChannels[v], _vowelSprings[v].Value * keep * scale);
            }

            faceRig.Add(_ppChannel, _closure.Value);
            faceRig.Add(_ssChannel, _sibilant.Value);

            // Without visemes (avatars with only jawOpen), the jaw does all the work.
            float jaw = (_hasVisemeShapes ? _jaw.Value * keep : open * 0.5f * keep) * scale;
            faceRig.Add(_jawChannel, Mathf.Clamp01(jaw));
        }
    }
}
