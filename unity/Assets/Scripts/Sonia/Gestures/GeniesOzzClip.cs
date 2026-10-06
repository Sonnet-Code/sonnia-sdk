// Lector de los clips OZZ de Genies (el `runtimeOzz` de cada gesto del chat de
// Genies), el mismo formato que lee scripts/gestos_genies/ozz_genies.py.
//
// Cada archivo es un archivo binario de ozz-animation 0.15 (biblioteca libre,
// MIT) dentro de un envoltorio de Genies, little endian:
//
//   u8    endianness (1)
//   tag   "genies-animation-clip", u32 versión (3)
//   str   nombre de la toma ("Take 001"), f32 duración
//   tag   "ozz-animation", u32 versión (7)    huesos, por índice
//   u32   nº de FloatTrack, u32 versión (1)   pistas float con nombre (curvas de
//         cara FACS como Root-EYES_CLOSED_L y atributos de Maya del nodo Root)
//   4×u32 pistas float2/float3/float4/quat (0)
//   list  nombres de los huesos, en el orden de las pistas de la animación
//   list  nombres cortos de las pistas float
//   4×u32 (0)
//   tag   "genies-pose-mask" y lo demás (máscara, bloque NAFM y una segunda
//         animación "motion-data-v1" para el retarget nativo de Genies): no
//         hacen falta y no se leen.
//
// Los huesos no guardan la pose absoluta sino la diferencia con la pose de
// enlace del cuerpo: el motor de Genies hace local = enlace · clip (y suma la
// traslación de la cadera). Las coordenadas van en mano derecha con Y arriba,
// como three.js; a Unity se pasan con cuaternión (x, -y, -z, w) y posición
// (-x, y, z) (ToUnity). Detalle y validación en gestos-genies/README.md.
//
// Las claves de ozz 0.15 no guardan su pista: van ordenadas por tiempo y cada
// una apunta a la anterior de su pista (previouses); las primeras N son la
// primera clave de cada pista. Las rotaciones van cuantizadas en 3 componentes
// de 15 bits (la cuarta, la mayor, se reconstruye) y traslaciones y escalas en
// medios floats.

using System;
using System.Text;
using UnityEngine;

namespace Sonia
{
    /// <summary>Un clip OZZ de Genies ya decodificado: claves por hueso y pistas float.</summary>
    public sealed class GeniesOzzClip
    {
        /// <summary>Pista float de ozz con nombre: claves por ratio (0..1) y bits de escalón.</summary>
        public sealed class FloatTrack
        {
            public string Name;
            public float[] Ratios;
            public float[] Values;
            public byte[] Steps;

            /// <summary>Cierto si la pista cambia de valor a lo largo del clip.</summary>
            public bool IsAnimated
            {
                get
                {
                    for (int i = 1; i < Values.Length; i++)
                    {
                        if (Values[i] != Values[0])
                        {
                            return true;
                        }
                    }

                    return false;
                }
            }

            /// <summary>Valor en <paramref name="ratio"/> (0..1 de la duración del clip).</summary>
            public float Sample(float ratio)
            {
                int n = Ratios.Length;
                if (n == 0)
                {
                    return 0f;
                }

                if (ratio <= Ratios[0])
                {
                    return Values[0];
                }

                if (ratio >= Ratios[n - 1])
                {
                    return Values[n - 1];
                }

                int i = Upper(Ratios, ratio);
                int k = i - 1;
                if (((Steps[k >> 3] >> (k & 7)) & 1) != 0)
                {
                    return Values[k];
                }

                float t = (ratio - Ratios[k]) / (Ratios[i] - Ratios[k]);
                return Values[k] + (Values[i] - Values[k]) * t;
            }
        }

        /// <summary>Claves de un hueso (diferencias con el enlace, en mano derecha).</summary>
        public sealed class JointTrack
        {
            public float[] TranslationRatios;
            public Vector3[] Translations;
            public float[] RotationRatios;
            public Quaternion[] Rotations;

            /// <summary>Cierto si la rotación cambia a lo largo del clip.</summary>
            public bool HasRotation
            {
                get { return Rotations.Length > 2 || (Rotations.Length > 0 && Quaternion.Angle(Rotations[0], Quaternion.identity) > 0.05f); }
            }
        }

        /// <summary>Nombre de la toma ("Take 001").</summary>
        public string Take { get; private set; }

        /// <summary>Duración en segundos.</summary>
        public float Duration { get; private set; }

        /// <summary>Nombres de los huesos, en el orden de <see cref="Joints"/>.</summary>
        public string[] JointNames { get; private set; }

        /// <summary>Claves de cada hueso.</summary>
        public JointTrack[] Joints { get; private set; }

        /// <summary>Pistas float con nombre ("Root-EYES_CLOSED_L"...).</summary>
        public FloatTrack[] FloatTracks { get; private set; }

        /// <summary>Índice del hueso con ese nombre, o -1.</summary>
        public int JointIndex(string name)
        {
            return Array.IndexOf(JointNames, name);
        }

        /// <summary>Ratio (0..1) que corresponde a un instante del clip.</summary>
        public float RatioAt(float seconds)
        {
            return Duration > 0f ? Mathf.Clamp01(seconds / Duration) : 0f;
        }

        /// <summary>Diferencia de rotación del hueso con su enlace, en mano derecha.</summary>
        public Quaternion SampleRotation(int joint, float ratio)
        {
            JointTrack track = Joints[joint];
            float[] ratios = track.RotationRatios;
            Quaternion[] values = track.Rotations;
            int n = ratios.Length;
            if (ratio <= ratios[0])
            {
                return values[0];
            }

            if (ratio >= ratios[n - 1])
            {
                return values[n - 1];
            }

            int i = Upper(ratios, ratio);
            float t = (ratio - ratios[i - 1]) / (ratios[i] - ratios[i - 1]);
            // Igual que ozz: nlerp sin buscar el camino corto (ya viene resuelto al exportar).
            Quaternion a = values[i - 1];
            Quaternion b = values[i];
            Quaternion q = new Quaternion(
                a.x + (b.x - a.x) * t,
                a.y + (b.y - a.y) * t,
                a.z + (b.z - a.z) * t,
                a.w + (b.w - a.w) * t);
            return Normalize(q);
        }

        /// <summary>Diferencia de traslación del hueso con su enlace, en mano derecha.</summary>
        public Vector3 SampleTranslation(int joint, float ratio)
        {
            JointTrack track = Joints[joint];
            float[] ratios = track.TranslationRatios;
            Vector3[] values = track.Translations;
            int n = ratios.Length;
            if (ratio <= ratios[0])
            {
                return values[0];
            }

            if (ratio >= ratios[n - 1])
            {
                return values[n - 1];
            }

            int i = Upper(ratios, ratio);
            float t = (ratio - ratios[i - 1]) / (ratios[i] - ratios[i - 1]);
            return Vector3.LerpUnclamped(values[i - 1], values[i], t);
        }

        /// <summary>Cuaternión de mano derecha (three.js, el de los OZZ) a Unity.</summary>
        public static Quaternion ToUnity(Quaternion q)
        {
            return new Quaternion(q.x, -q.y, -q.z, q.w);
        }

        /// <summary>Posición de mano derecha (three.js, la de los OZZ) a Unity.</summary>
        public static Vector3 ToUnity(Vector3 v)
        {
            return new Vector3(-v.x, v.y, v.z);
        }

        // ------------------------------------------------------------------
        // Lectura
        // ------------------------------------------------------------------

        private static readonly float QuatScale = Mathf.Sqrt(2f) / ((1 << 15) - 1);
        private static readonly float QuatOffset = -Mathf.Sqrt(2f) / 2f;

        // Qué valor guardado va en cada componente según cuál era la mayor (ozz).
        private static readonly int[][] ComponentMapping =
        {
            new[] { 0, 0, 1, 2 },
            new[] { 0, 0, 1, 2 },
            new[] { 0, 1, 0, 2 },
            new[] { 0, 1, 2, 0 }
        };

        /// <summary>Decodifica un archivo OZZ de Genies. Lanza <see cref="FormatException"/> si no lo es.</summary>
        public static GeniesOzzClip Parse(byte[] data)
        {
            if (data == null || data.Length < 2)
            {
                throw new FormatException("OZZ vacío");
            }

            Reader r = new Reader(data);
            if (r.U8() != 1)
            {
                throw new FormatException("Solo se leen OZZ little endian");
            }

            r.ExpectTag("genies-animation-clip");
            GeniesOzzClip clip = new GeniesOzzClip();
            clip.Take = r.String((int)r.U32());
            r.F32(); // duración del envoltorio, la misma que la de la animación

            float duration;
            JointTrack[] joints = ReadAnimation(r, out duration);
            clip.Duration = duration;
            clip.Joints = joints;
            clip.FloatTracks = ReadFloatTracks(r);
            for (int i = 0; i < 4; i++)
            {
                if (r.U32() != 0)
                {
                    throw new FormatException("El clip trae pistas float2/float3/float4/quat, que no se leen");
                }
            }

            clip.JointNames = ReadStringList(r);
            if (clip.JointNames.Length != joints.Length)
            {
                throw new FormatException(clip.JointNames.Length + " nombres para " + joints.Length + " huesos");
            }

            return clip;
        }

        private static JointTrack[] ReadAnimation(Reader r, out float duration)
        {
            uint version = r.ExpectTag("ozz-animation");
            if (version != 7)
            {
                throw new FormatException("Versión de ozz-animation no soportada: " + version);
            }

            duration = r.F32();
            int numTracks = (int)r.U32();
            int nameLength = (int)r.U32();
            int timepointCount = (int)r.U32();
            int tCount = (int)r.U32();
            int rCount = (int)r.U32();
            int sCount = (int)r.U32();
            int tIfEntries = (int)r.U32();
            int tIfDesc = (int)r.U32();
            int rIfEntries = (int)r.U32();
            int rIfDesc = (int)r.U32();
            int sIfEntries = (int)r.U32();
            int sIfDesc = (int)r.U32();
            r.Skip(nameLength);
            float[] timepoints = new float[timepointCount];
            for (int i = 0; i < timepointCount; i++)
            {
                timepoints[i] = r.F32();
            }

            int soaTracks = (numTracks + 3) / 4;
            int padded = soaTracks * 4;

            float[] tRatios;
            int[] tTracks;
            ushort[] tValues;
            ReadKeyframes(r, tCount, timepoints, tIfEntries, tIfDesc, padded, out tRatios, out tTracks, out tValues);
            float[] rRatios;
            int[] rTracks;
            ushort[] rValues;
            ReadKeyframes(r, rCount, timepoints, rIfEntries, rIfDesc, padded, out rRatios, out rTracks, out rValues);
            float[] sRatios;
            int[] sTracks;
            ushort[] sValues;
            ReadKeyframes(r, sCount, timepoints, sIfEntries, sIfDesc, padded, out sRatios, out sTracks, out sValues);

            // Las escalas no se usan (en los gestos de Genies valen 1).
            int[] tPerTrack = CountPerTrack(tTracks, padded);
            int[] rPerTrack = CountPerTrack(rTracks, padded);
            JointTrack[] joints = new JointTrack[numTracks];
            for (int j = 0; j < numTracks; j++)
            {
                joints[j] = new JointTrack
                {
                    TranslationRatios = new float[tPerTrack[j]],
                    Translations = new Vector3[tPerTrack[j]],
                    RotationRatios = new float[rPerTrack[j]],
                    Rotations = new Quaternion[rPerTrack[j]]
                };
            }

            int[] fill = new int[padded];
            for (int k = 0; k < tCount; k++)
            {
                int track = tTracks[k];
                if (track >= numTracks)
                {
                    continue;
                }

                int at = fill[track]++;
                joints[track].TranslationRatios[at] = tRatios[k];
                joints[track].Translations[at] = new Vector3(
                    Mathf.HalfToFloat(tValues[k * 3]),
                    Mathf.HalfToFloat(tValues[k * 3 + 1]),
                    Mathf.HalfToFloat(tValues[k * 3 + 2]));
            }

            Array.Clear(fill, 0, fill.Length);
            for (int k = 0; k < rCount; k++)
            {
                int track = rTracks[k];
                if (track >= numTracks)
                {
                    continue;
                }

                int at = fill[track]++;
                joints[track].RotationRatios[at] = rRatios[k];
                joints[track].Rotations[at] = DecodeQuaternion(rValues[k * 3], rValues[k * 3 + 1], rValues[k * 3 + 2]);
            }

            for (int j = 0; j < numTracks; j++)
            {
                if (joints[j].RotationRatios.Length == 0 || joints[j].TranslationRatios.Length == 0)
                {
                    throw new FormatException("El hueso " + j + " no tiene claves");
                }
            }

            return joints;
        }

        private static void ReadKeyframes(
            Reader r,
            int count,
            float[] timepoints,
            int iframeEntries,
            int iframeDesc,
            int paddedTracks,
            out float[] ratios,
            out int[] tracks,
            out ushort[] values)
        {
            ratios = new float[count];
            if (timepoints.Length <= 255)
            {
                for (int i = 0; i < count; i++)
                {
                    ratios[i] = timepoints[r.U8()];
                }
            }
            else
            {
                for (int i = 0; i < count; i++)
                {
                    ratios[i] = timepoints[r.U16()];
                }
            }

            ushort[] previous = new ushort[count];
            for (int i = 0; i < count; i++)
            {
                previous[i] = r.U16();
            }

            // Las iframes solo aceleran la búsqueda en ozz; aquí no hacen falta.
            r.Skip(iframeEntries);
            r.Skip(4 * iframeDesc);
            r.F32();

            values = new ushort[count * 3];
            for (int i = 0; i < values.Length; i++)
            {
                values[i] = r.U16();
            }

            // Pista de cada clave: las primeras N van en orden; el resto, por su anterior.
            tracks = new int[count];
            for (int i = 0; i < count; i++)
            {
                tracks[i] = i < paddedTracks ? i : tracks[i - previous[i]];
            }
        }

        private static int[] CountPerTrack(int[] tracks, int padded)
        {
            int[] counts = new int[padded];
            for (int i = 0; i < tracks.Length; i++)
            {
                counts[tracks[i]]++;
            }

            return counts;
        }

        private static Quaternion DecodeQuaternion(ushort v0, ushort v1, ushort v2)
        {
            int largest = v0 & 0x3;
            int sign = (v0 >> 2) & 0x1;
            uint packed = ((uint)v0 >> 3) | ((uint)v1 << 13) | ((uint)v2 << 29);
            int c0 = (int)(packed & 0x7fff);
            int c1 = (int)((packed >> 15) & 0x7fff);
            int c2 = v2 >> 1;
            int[] mapping = ComponentMapping[largest];
            float[] stored = { c0, c1, c2 };
            float[] cpnt = new float[4];
            float dot = 0f;
            for (int i = 0; i < 4; i++)
            {
                cpnt[i] = i == largest ? 0f : stored[mapping[i]] * QuatScale + QuatOffset;
                dot += cpnt[i] * cpnt[i];
            }

            float w = Mathf.Sqrt(Mathf.Max(0f, 1f - dot));
            cpnt[largest] = sign != 0 ? -w : w;
            return new Quaternion(cpnt[0], cpnt[1], cpnt[2], cpnt[3]);
        }

        private static FloatTrack[] ReadFloatTracks(Reader r)
        {
            int count = (int)r.U32();
            uint version = r.U32();
            if (version != 1)
            {
                throw new FormatException("Versión de FloatTrack no soportada: " + version);
            }

            FloatTrack[] tracks = new FloatTrack[count];
            for (int t = 0; t < count; t++)
            {
                int keys = (int)r.U32();
                int nameLength = (int)r.U32();
                FloatTrack track = new FloatTrack
                {
                    Ratios = new float[keys],
                    Values = new float[keys]
                };
                for (int i = 0; i < keys; i++)
                {
                    track.Ratios[i] = r.F32();
                }

                for (int i = 0; i < keys; i++)
                {
                    track.Values[i] = r.F32();
                }

                track.Steps = r.Bytes((keys + 7) / 8);
                track.Name = r.String(nameLength);
                tracks[t] = track;
            }

            return tracks;
        }

        private static string[] ReadStringList(Reader r)
        {
            int count = (int)r.U32();
            string[] items = new string[count];
            for (int i = 0; i < count; i++)
            {
                items[i] = r.String((int)r.U32());
            }

            return items;
        }

        // Primer índice con valor mayor que x (búsqueda binaria; los ratios crecen).
        private static int Upper(float[] values, float x)
        {
            int lo = 0;
            int hi = values.Length;
            while (lo < hi)
            {
                int mid = (lo + hi) >> 1;
                if (values[mid] <= x)
                {
                    lo = mid + 1;
                }
                else
                {
                    hi = mid;
                }
            }

            return Mathf.Clamp(lo, 1, values.Length - 1);
        }

        private static Quaternion Normalize(Quaternion q)
        {
            float n = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            return n > 1e-8f ? new Quaternion(q.x / n, q.y / n, q.z / n, q.w / n) : Quaternion.identity;
        }

        private sealed class Reader
        {
            private readonly byte[] _data;
            private int _pos;

            public Reader(byte[] data)
            {
                _data = data;
            }

            private void Need(int n)
            {
                if (_pos + n > _data.Length)
                {
                    throw new FormatException("OZZ truncado");
                }
            }

            public byte U8()
            {
                Need(1);
                return _data[_pos++];
            }

            public ushort U16()
            {
                Need(2);
                ushort v = (ushort)(_data[_pos] | (_data[_pos + 1] << 8));
                _pos += 2;
                return v;
            }

            public uint U32()
            {
                Need(4);
                uint v = (uint)(_data[_pos] | (_data[_pos + 1] << 8) | (_data[_pos + 2] << 16) | (_data[_pos + 3] << 24));
                _pos += 4;
                return v;
            }

            public float F32()
            {
                Need(4);
                float v = BitConverter.ToSingle(_data, _pos);
                _pos += 4;
                return v;
            }

            public byte[] Bytes(int n)
            {
                Need(n);
                byte[] chunk = new byte[n];
                Buffer.BlockCopy(_data, _pos, chunk, 0, n);
                _pos += n;
                return chunk;
            }

            public string String(int n)
            {
                Need(n);
                string s = Encoding.UTF8.GetString(_data, _pos, n);
                _pos += n;
                return s;
            }

            public void Skip(int n)
            {
                Need(n);
                _pos += n;
            }

            public uint ExpectTag(string expected)
            {
                int end = Array.IndexOf(_data, (byte)0, _pos);
                if (end < 0)
                {
                    throw new FormatException("Falta la etiqueta " + expected);
                }

                string found = Encoding.ASCII.GetString(_data, _pos, end - _pos);
                if (found != expected)
                {
                    throw new FormatException("Esperaba la etiqueta " + expected + " y encontré " + found);
                }

                _pos = end + 1;
                return U32();
            }
        }
    }
}
