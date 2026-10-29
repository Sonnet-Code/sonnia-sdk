// Analysis of Sonnia's voice for the face: level, bands and prosody.
//
// Lip-sync and expressions cannot depend only on the vowel classifier
// (uLipSync works with 64 ms windows, which blur exactly what is most visible:
// the hit of each syllable and the lip closure on p, b and m).
// Here the voice is analyzed with 5 ms windows:
//
//  - Level in dB with automatic gain control: 0..1 relative to the recent
//    peak, so the mouth opens the same with a quieter or louder session.
//  - Energy per band (low 100-500 Hz, mid 500-1500, high 1500-3500 and
//    sibilants 4-10 kHz) to tell open vowels, front vowels, nasals
//    and the "s".
//  - Prosody events: syllable onset with its strength (to nod, raise the
//    eyebrows or blink with the voice), phrase start and end.
//
// Threads: the audio thread only copies samples (Push) into a ring; all the
// computation runs on the main thread (Process), with the audio running
// ahead of what is heard thanks to the delay line of AudioStreamPlayer.
// Each datum carries its "fresh" sample index (the analysis clock); whoever
// queries asks for the instant it wants (what plays now plus a lead).

using System;
using System.Collections.Generic;
using System.Threading;
using UnityEngine;

namespace Sonia
{
    /// <summary>Level, bands and prosody events of the voice, with 5 ms windows.</summary>
    public sealed class SpeechAnalyzer
    {
        /// <summary>What is known about the voice at one instant.</summary>
        public struct Features
        {
            /// <summary>Level 0..1 relative to the recent peak (0 = silence, 1 = strong syllable).</summary>
            public float Level;

            /// <summary>Level smoothed at 25 ms (the "syllable", without the grain of each period).</summary>
            public float Syllable;

            /// <summary>Vowel openness 0..1: strong mids versus lows (a versus i, u).</summary>
            public float Openness;

            /// <summary>Front vowel 0..1: highs versus mids (i, e).</summary>
            public float Frontness;

            /// <summary>Sibilant 0..1 (s, z, ch, j): energy above 4 kHz without lows.</summary>
            public float Sibilance;

            /// <summary>Nasal or murmur 0..1 (m, n): lows without mids or highs.</summary>
            public float Nasality;

            /// <summary>There is voice (level above the threshold).</summary>
            public bool Voiced;
        }

        /// <summary>Kind of prosody event.</summary>
        public enum EventKind
        {
            /// <summary>A syllable starts; Strength is its strength 0..1 (stressed ones exceed 0.7).</summary>
            Syllable,

            /// <summary>Starts speaking after a pause.</summary>
            PhraseStart,

            /// <summary>Goes quiet: a pause longer than PauseSeconds.</summary>
            PhraseEnd
        }

        /// <summary>Prosody event with its instant in fresh samples.</summary>
        public struct SpeechEvent
        {
            public EventKind Kind;
            public long Sample;
            public float Strength;
        }

        private struct Frame
        {
            public float Db;
            public float LowDb;
            public float MidDb;
            public float HighDb;
            public float SibDb;
            public float RefDb;
            public float Fast;
        }

        /// <summary>Biquad filter (transposed direct form II).</summary>
        private struct Biquad
        {
            private float _b0, _b1, _b2, _a1, _a2, _z1, _z2;

            public static Biquad LowPass(float rate, float freq)
            {
                return Make(rate, freq, 0.7071f, false);
            }

            public static Biquad HighPass(float rate, float freq)
            {
                return Make(rate, freq, 0.7071f, true);
            }

            private static Biquad Make(float rate, float freq, float q, bool high)
            {
                float w0 = 2f * Mathf.PI * Mathf.Clamp(freq, 10f, rate * 0.45f) / rate;
                float cos = Mathf.Cos(w0);
                float alpha = Mathf.Sin(w0) / (2f * q);
                float a0 = 1f + alpha;
                Biquad b = new Biquad();
                if (high)
                {
                    b._b0 = (1f + cos) / 2f / a0;
                    b._b1 = -(1f + cos) / a0;
                    b._b2 = (1f + cos) / 2f / a0;
                }
                else
                {
                    b._b0 = (1f - cos) / 2f / a0;
                    b._b1 = (1f - cos) / a0;
                    b._b2 = (1f - cos) / 2f / a0;
                }

                b._a1 = -2f * cos / a0;
                b._a2 = (1f - alpha) / a0;
                return b;
            }

            public float Run(float x)
            {
                float y = (_b0 * x) + _z1;
                _z1 = (_b1 * x) - (_a1 * y) + _z2;
                _z2 = (_b2 * x) - (_a2 * y);
                return y;
            }

            public void Reset()
            {
                _z1 = 0f;
                _z2 = 0f;
            }
        }

        // ------------------------------------------------------------------
        // Parameters
        // ------------------------------------------------------------------

        /// <summary>Dynamic range in dB that goes from level 0 to level 1.</summary>
        public float RangeDb = 30f;

        /// <summary>The reference peak never drops below this (dBFS): weak voice is not amplified endlessly.</summary>
        public float MinReferenceDb = -32f;

        /// <summary>Decay of the reference peak in dB per second.</summary>
        public float ReferenceDecayDbPerSecond = 4f;

        /// <summary>Level below which there is no voice.</summary>
        public float VoiceThreshold = 0.12f;

        /// <summary>Seconds of silence that close a phrase.</summary>
        public float PauseSeconds = 0.22f;

        /// <summary>Minimum level rise (0..1) to count a new syllable.</summary>
        public float SyllableProminence = 0.14f;

        // ------------------------------------------------------------------
        // State
        // ------------------------------------------------------------------

        private const int RingSize = 1 << 17;
        private const int HistorySize = 2048;

        private readonly float[] _ring = new float[RingSize];
        private long _written;

        private readonly Frame[] _history = new Frame[HistorySize];
        private long _frames;
        private long _processed;
        private long _historyBase;

        private int _rate;
        private int _hop;
        private Biquad _dc;
        private Biquad _lowHp, _lowLp, _midHp, _midLp, _highHp, _highLp, _sibHp, _sibLp;
        private double _accTotal, _accLow, _accMid, _accHigh, _accSib;
        private int _accCount;
        private float _refDb = -26f;
        private float _fast;

        // Syllable and pause detection (over the Fast series).
        private float _valley = 1f;
        private long _valleyHop;
        private bool _rising;
        private float _peak;
        private int _silentHops;
        private bool _inPhrase;
        private long _lastVoicedHop;

        private readonly Queue<SpeechEvent> _events = new Queue<SpeechEvent>();

        /// <summary>Samples per analysis window.</summary>
        public int HopSamples
        {
            get { return _hop; }
        }

        /// <summary>Sample rate of the analysis.</summary>
        public int SampleRate
        {
            get { return _rate; }
        }

        /// <summary>Fresh samples received from the audio thread (analysis clock).</summary>
        public long Written
        {
            get { return Volatile.Read(ref _written); }
        }

        /// <summary>Samples already analyzed.</summary>
        public long Processed
        {
            get { return _processed; }
        }

        public SpeechAnalyzer(int sampleRate)
        {
            Configure(sampleRate);
        }

        /// <summary>Prepares the filters for a sample rate. Main thread.</summary>
        public void Configure(int sampleRate)
        {
            _rate = Mathf.Max(8000, sampleRate);
            _hop = Mathf.Max(32, Mathf.RoundToInt(_rate * 0.005f));
            _dc = Biquad.HighPass(_rate, 70f);
            _lowHp = Biquad.HighPass(_rate, 100f);
            _lowLp = Biquad.LowPass(_rate, 500f);
            _midHp = Biquad.HighPass(_rate, 500f);
            _midLp = Biquad.LowPass(_rate, 1500f);
            _highHp = Biquad.HighPass(_rate, 1500f);
            _highLp = Biquad.LowPass(_rate, 3500f);
            _sibHp = Biquad.HighPass(_rate, 4000f);
            _sibLp = Biquad.LowPass(_rate, Mathf.Min(10000f, _rate * 0.45f));
        }

        // ------------------------------------------------------------------
        // Audio thread
        // ------------------------------------------------------------------

        /// <summary>Copies a (interleaved) block into the ring. Audio thread: no Unity API.</summary>
        public void Push(float[] data, int channels)
        {
            if (data == null || channels <= 0)
            {
                return;
            }

            int frames = data.Length / channels;
            long w = _written;
            for (int i = 0; i < frames; i++)
            {
                _ring[(int)((w + i) & (RingSize - 1))] = data[i * channels];
            }

            Volatile.Write(ref _written, w + frames);
        }

        // ------------------------------------------------------------------
        // Main thread
        // ------------------------------------------------------------------

        /// <summary>Analyzes whatever arrived since the last call. Main thread, once per frame.</summary>
        public void Process()
        {
            long written = Volatile.Read(ref _written);
            if (written - _processed > RingSize / 2)
            {
                // Too far behind (the editor was paused): skip to the
                // present. Each window starts at a multiple of _hop, so the
                // window index and the sample index still line up.
                long target = written - _hop * 8;
                _processed = target - (target % _hop);
                _frames = _processed / _hop;
                _historyBase = _frames;
                ResetFilters();
            }

            while (_processed < written)
            {
                float x = _dc.Run(_ring[(int)(_processed & (RingSize - 1))]);
                float low = _lowLp.Run(_lowHp.Run(x));
                float mid = _midLp.Run(_midHp.Run(x));
                float high = _highLp.Run(_highHp.Run(x));
                float sib = _sibLp.Run(_sibHp.Run(x));
                _accTotal += x * x;
                _accLow += low * low;
                _accMid += mid * mid;
                _accHigh += high * high;
                _accSib += sib * sib;
                _processed++;
                if (++_accCount >= _hop)
                {
                    EmitFrame();
                }
            }
        }

        private void ResetFilters()
        {
            _dc.Reset();
            _lowHp.Reset();
            _lowLp.Reset();
            _midHp.Reset();
            _midLp.Reset();
            _highHp.Reset();
            _highLp.Reset();
            _sibHp.Reset();
            _sibLp.Reset();
            _accTotal = _accLow = _accMid = _accHigh = _accSib = 0.0;
            _accCount = 0;
        }

        private static float ToDb(double sumSquares, int count)
        {
            double rms = Math.Sqrt(sumSquares / Math.Max(1, count));
            return (float)(20.0 * Math.Log10(rms + 1e-7));
        }

        private void EmitFrame()
        {
            Frame f = new Frame
            {
                Db = ToDb(_accTotal, _accCount),
                LowDb = ToDb(_accLow, _accCount),
                MidDb = ToDb(_accMid, _accCount),
                HighDb = ToDb(_accHigh, _accCount),
                SibDb = ToDb(_accSib, _accCount)
            };
            _accTotal = _accLow = _accMid = _accHigh = _accSib = 0.0;
            _accCount = 0;

            // Reference peak: rises instantly, falls slowly and never below the
            // minimum (otherwise background noise would open the mouth).
            float hopSeconds = _hop / (float)_rate;
            _refDb = Mathf.Max(MinReferenceDb, Mathf.Max(f.Db, _refDb - ReferenceDecayDbPerSecond * hopSeconds));
            f.RefDb = _refDb;

            float level = LevelOf(f);
            // Syllable envelope: 10 ms attack and 35 ms decay.
            float k = level > _fast ? 1f - Mathf.Exp(-hopSeconds / 0.010f) : 1f - Mathf.Exp(-hopSeconds / 0.035f);
            _fast += (level - _fast) * k;
            f.Fast = _fast;

            long hop = _frames;
            if (_frames - _historyBase >= HistorySize)
            {
                _historyBase++;
            }

            _history[(int)(hop % HistorySize)] = f;
            _frames++;
            DetectEvents(hop, _fast);
        }

        private float LevelOf(Frame f)
        {
            return Mathf.Clamp01((f.Db - (f.RefDb - RangeDb)) / Mathf.Max(1f, RangeDb));
        }

        private void DetectEvents(long hop, float fast)
        {
            long sample = hop * _hop;
            bool voiced = fast > VoiceThreshold;
            if (voiced)
            {
                if (!_inPhrase)
                {
                    _inPhrase = true;
                    _events.Enqueue(new SpeechEvent { Kind = EventKind.PhraseStart, Sample = sample, Strength = 1f });
                }

                _silentHops = 0;
                _lastVoicedHop = hop;
            }
            else if (_inPhrase)
            {
                _silentHops++;
                if (_silentHops * _hop >= PauseSeconds * _rate)
                {
                    _inPhrase = false;
                    _events.Enqueue(new SpeechEvent { Kind = EventKind.PhraseEnd, Sample = (_lastVoicedHop + 1) * _hop, Strength = 1f });
                }
            }

            // Syllables: a valley followed by a rise of at least SyllableProminence.
            // The event is dated at the valley (where the syllable starts) and its
            // strength is the peak it reaches.
            if (!_rising)
            {
                if (fast < _valley)
                {
                    _valley = fast;
                    _valleyHop = hop;
                }
                else if (fast - _valley >= SyllableProminence && fast > VoiceThreshold)
                {
                    _rising = true;
                    _peak = fast;
                }
            }
            else
            {
                if (fast > _peak)
                {
                    _peak = fast;
                }
                else if (_peak - fast >= SyllableProminence * 0.5f || fast < VoiceThreshold)
                {
                    _events.Enqueue(new SpeechEvent { Kind = EventKind.Syllable, Sample = _valleyHop * _hop, Strength = _peak });
                    _rising = false;
                    _valley = fast;
                    _valleyHop = hop;
                }
            }

            while (_events.Count > 256)
            {
                _events.Dequeue();
            }
        }

        // ------------------------------------------------------------------
        // Queries
        // ------------------------------------------------------------------

        /// <summary>Pops the events dated up to <paramref name="upToSample"/> (inclusive).</summary>
        public void TakeEvents(long upToSample, List<SpeechEvent> into)
        {
            while (_events.Count > 0 && _events.Peek().Sample <= upToSample)
            {
                into.Add(_events.Dequeue());
            }
        }

        /// <summary>Discards the pending events (interruption).</summary>
        public void ClearEvents()
        {
            _events.Clear();
        }

        /// <summary>Voice features at instant <paramref name="sample"/> (fresh samples), interpolated.</summary>
        public Features Sample(double sample)
        {
            Features result = new Features();
            double hopPos = sample / _hop;
            long h0 = (long)Math.Floor(hopPos);
            if (_frames == 0 || h0 < _historyBase || h0 >= _frames)
            {
                return result;
            }

            long h1 = Math.Min(h0 + 1, _frames - 1);
            float t = (float)(hopPos - h0);
            Frame a = _history[(int)(h0 % HistorySize)];
            Frame b = _history[(int)(h1 % HistorySize)];
            float level = Mathf.Lerp(LevelOf(a), LevelOf(b), t);
            result.Level = level;
            result.Syllable = Mathf.Lerp(a.Fast, b.Fast, t);
            result.Voiced = result.Syllable > VoiceThreshold;

            float low = Mathf.Lerp(a.LowDb, b.LowDb, t);
            float mid = Mathf.Lerp(a.MidDb, b.MidDb, t);
            float high = Mathf.Lerp(a.HighDb, b.HighDb, t);
            float sib = Mathf.Lerp(a.SibDb, b.SibDb, t);
            float loudest = Mathf.Max(low, mid);

            // Measured with Sonnia's voice: in vowels the lows are 10-20 dB
            // above the mids (the a, closer); in the s the sibilants
            // exceed the lows and mids by 10-30 dB.
            result.Openness = Mathf.Clamp01((mid - low + 16f) / 14f);
            result.Frontness = Mathf.Clamp01((high - mid + 12f) / 14f);
            result.Sibilance = Mathf.Clamp01((sib - loudest + 2f) / 14f) * Mathf.Clamp01(level * 3f);
            result.Nasality = Mathf.Clamp01((low - Mathf.Max(mid, high) - 18f) / 8f) * (result.Voiced ? 1f : 0f);
            return result;
        }

        /// <summary>
        /// Lip closure 0..1 at <paramref name="sample"/>: a deep valley in the
        /// level between two voiced stretches (the plosives p, b, t, d, k, g and
        /// the m). Looks <paramref name="windowSeconds"/> on each side.
        /// </summary>
        public float ClosureAt(double sample, float windowSeconds)
        {
            Features here = Sample(sample);
            if (here.Syllable > 0.55f)
            {
                return 0f;
            }

            int span = Mathf.Max(1, Mathf.RoundToInt(windowSeconds * _rate / _hop));
            long center = (long)Math.Floor(sample / _hop);
            float before = 0f;
            float after = 0f;
            for (int i = 1; i <= span; i++)
            {
                before = Mathf.Max(before, FastAt(center - i));
                after = Mathf.Max(after, FastAt(center + i));
            }

            // Voice is needed on both sides: a long silence is not a consonant
            // closure but rest, and the level takes care of that.
            float sides = Mathf.Min(before, after);
            float depth = sides - here.Syllable;
            return Mathf.Clamp01((depth - 0.18f) / 0.3f) * Mathf.Clamp01(sides / 0.4f);
        }

        private float FastAt(long hop)
        {
            if (hop < _historyBase || hop >= _frames || hop < 0)
            {
                return 0f;
            }

            return _history[(int)(hop % HistorySize)].Fast;
        }

        /// <summary>First fresh sample not yet analyzed (there is data up to here).</summary>
        public long AnalyzedUpTo
        {
            get { return _frames * _hop; }
        }
    }
}
