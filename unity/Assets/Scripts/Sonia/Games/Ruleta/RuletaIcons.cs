// Iconos y piezas de la ruleta de Sonnia, pintados por código (sin texturas en el
// proyecto): blancos sobre transparente, se tiñen con Image.color.
//
// - Disc: un disco de 512 px para las casillas (relleno radial), el borde, el buje y
//   los brillos: con el punto de 64 px del HUD el borde de una ruleta de 500 px salía
//   borroso.
// - Bolt (trivia relámpago), Mic (explica en 20 segundos), Crystal (futuro de la IA) y
//   Pointer (la lengüeta de arriba). La adivinanza usa un «?» de la fuente y el reto de
//   Sonnet Code, la estrella del HUD.

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia.Games.Ruleta
{
    /// <summary>Sprites de la ruleta, creados una vez y destruidos con el controlador.</summary>
    internal sealed class RuletaIcons
    {
        private const int IconSize = 128;
        private const int DiscSize = 512;
        private const int Samples = 4;

        private readonly List<Texture2D> _textures = new List<Texture2D>();
        private readonly List<Sprite> _sprites = new List<Sprite>();

        public Sprite Disc { get; private set; }

        public Sprite Bolt { get; private set; }

        public Sprite Mic { get; private set; }

        public Sprite Crystal { get; private set; }

        public Sprite Pointer { get; private set; }

        /// <summary>Brillo redondo que se difumina hacia fuera (halos).</summary>
        public Sprite Glow { get; private set; }

        public bool IsBuilt
        {
            get { return Disc != null; }
        }

        public void Build()
        {
            if (IsBuilt)
            {
                return;
            }

            Disc = PaintDisc();
            Glow = PaintGlow();

            // Rayo: zigzag de arriba a la derecha a la punta de abajo.
            Vector2[] bolt =
            {
                new Vector2(0.60f, 0.98f), new Vector2(0.20f, 0.44f), new Vector2(0.47f, 0.44f),
                new Vector2(0.36f, 0.02f), new Vector2(0.82f, 0.59f), new Vector2(0.55f, 0.59f),
                new Vector2(0.72f, 0.98f),
            };
            Bolt = Paint("RuletaBolt", (x, y) => InPolygon(bolt, x, y));

            // Micrófono: cápsula, el arco de abajo, el pie y la base.
            Mic = Paint("RuletaMic", (x, y) =>
                RoundBox(x, y, 0.5f, 0.68f, 0.14f, 0.27f, 0.14f)
                || (Band(x, y, 0.5f, 0.62f, 0.27f, 0.035f) && y <= 0.62f)
                || Box(x, y, 0.47f, 0.53f, 0.17f, 0.36f)
                || RoundBox(x, y, 0.5f, 0.15f, 0.18f, 0.035f, 0.035f));

            // Bola de cristal con su brillo y la peana.
            Vector2[] stand =
            {
                new Vector2(0.20f, 0.05f), new Vector2(0.80f, 0.05f), new Vector2(0.68f, 0.24f),
                new Vector2(0.32f, 0.24f),
            };
            Crystal = Paint("RuletaCrystal", (x, y) =>
            {
                bool ball = Circle(x, y, 0.5f, 0.61f, 0.36f);
                bool shine = Band(x, y, 0.5f, 0.61f, 0.25f, 0.035f) && x < 0.5f && y > 0.66f;
                return (ball && !shine) || InPolygon(stand, x, y);
            });

            // Lengüeta: triángulo con la punta hacia abajo (hacia la ruleta) y el eje
            // redondo arriba, en (0,5; 0,82).
            Vector2[] tip =
            {
                new Vector2(0.16f, 0.86f), new Vector2(0.84f, 0.86f), new Vector2(0.5f, 0.03f),
            };
            Pointer = Paint("RuletaPointer", (x, y) =>
                InPolygon(tip, x, y) || RoundBox(x, y, 0.5f, 0.86f, 0.34f, 0.1f, 0.1f));
        }

        public void Destroy()
        {
            foreach (Sprite sprite in _sprites)
            {
                if (sprite != null)
                {
                    UnityEngine.Object.Destroy(sprite);
                }
            }

            foreach (Texture2D texture in _textures)
            {
                if (texture != null)
                {
                    UnityEngine.Object.Destroy(texture);
                }
            }

            _sprites.Clear();
            _textures.Clear();
            Disc = null;
            Bolt = null;
            Mic = null;
            Crystal = null;
            Pointer = null;
            Glow = null;
        }

        private Sprite PaintGlow()
        {
            const int size = 256;
            Color32[] pixels = new Color32[size * size];
            float half = size * 0.5f;
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    float dx = (x + 0.5f - half) / half;
                    float dy = (y + 0.5f - half) / half;
                    float t = Mathf.Clamp01(1f - Mathf.Sqrt((dx * dx) + (dy * dy)));
                    float alpha = t * t * (3f - (2f * t));
                    pixels[(y * size) + x] = new Color32(255, 255, 255, (byte)Mathf.RoundToInt(alpha * 255f));
                }
            }

            return MakeSprite("RuletaGlow", size, pixels);
        }

        // ------------------------------------------------------------------
        // Pintado
        // ------------------------------------------------------------------

        private Sprite PaintDisc()
        {
            Color32[] pixels = new Color32[DiscSize * DiscSize];
            float half = DiscSize * 0.5f;
            for (int y = 0; y < DiscSize; y++)
            {
                for (int x = 0; x < DiscSize; x++)
                {
                    float dx = x + 0.5f - half;
                    float dy = y + 0.5f - half;
                    float alpha = Mathf.Clamp01(half - 1f - Mathf.Sqrt((dx * dx) + (dy * dy)) + 0.5f);
                    pixels[(y * DiscSize) + x] = new Color32(255, 255, 255, (byte)Mathf.RoundToInt(alpha * 255f));
                }
            }

            return MakeSprite("RuletaDisc", DiscSize, pixels);
        }

        /// <summary>Icono de <see cref="IconSize"/> px con <paramref name="inside"/> en coordenadas de 0 a 1 (y hacia arriba), con 4x4 muestras por píxel.</summary>
        private Sprite Paint(string name, Func<float, float, bool> inside)
        {
            Color32[] pixels = new Color32[IconSize * IconSize];
            float step = 1f / (IconSize * Samples);
            for (int y = 0; y < IconSize; y++)
            {
                for (int x = 0; x < IconSize; x++)
                {
                    int hits = 0;
                    for (int sy = 0; sy < Samples; sy++)
                    {
                        float v = ((y * Samples) + sy + 0.5f) * step;
                        for (int sx = 0; sx < Samples; sx++)
                        {
                            float u = ((x * Samples) + sx + 0.5f) * step;
                            if (inside(u, v))
                            {
                                hits++;
                            }
                        }
                    }

                    byte alpha = (byte)Mathf.RoundToInt(255f * hits / (Samples * Samples));
                    pixels[(y * IconSize) + x] = new Color32(255, 255, 255, alpha);
                }
            }

            return MakeSprite(name, IconSize, pixels);
        }

        private Sprite MakeSprite(string name, int size, Color32[] pixels)
        {
            Texture2D texture = new Texture2D(size, size, TextureFormat.RGBA32, true);
            texture.name = name;
            texture.wrapMode = TextureWrapMode.Clamp;
            texture.filterMode = FilterMode.Trilinear;
            texture.anisoLevel = 2;
            texture.SetPixels32(pixels);
            texture.Apply(true, true);
            _textures.Add(texture);
            Sprite sprite = Sprite.Create(texture, new Rect(0f, 0f, size, size), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
            sprite.name = name;
            _sprites.Add(sprite);
            return sprite;
        }

        // ------------------------------------------------------------------
        // Formas (coordenadas de 0 a 1)
        // ------------------------------------------------------------------

        private static bool Circle(float x, float y, float cx, float cy, float r)
        {
            float dx = x - cx;
            float dy = y - cy;
            return (dx * dx) + (dy * dy) <= r * r;
        }

        /// <summary>Anillo de radio <paramref name="r"/> y medio grosor <paramref name="halfWidth"/>.</summary>
        private static bool Band(float x, float y, float cx, float cy, float r, float halfWidth)
        {
            float dx = x - cx;
            float dy = y - cy;
            return Mathf.Abs(Mathf.Sqrt((dx * dx) + (dy * dy)) - r) <= halfWidth;
        }

        private static bool Box(float x, float y, float x0, float x1, float y0, float y1)
        {
            return x >= x0 && x <= x1 && y >= y0 && y <= y1;
        }

        /// <summary>Rectángulo de centro (cx, cy), medio tamaño (hx, hy) y esquinas de radio r.</summary>
        private static bool RoundBox(float x, float y, float cx, float cy, float hx, float hy, float r)
        {
            float qx = Mathf.Abs(x - cx) - (hx - r);
            float qy = Mathf.Abs(y - cy) - (hy - r);
            float outside = new Vector2(Mathf.Max(qx, 0f), Mathf.Max(qy, 0f)).magnitude;
            float inside = Mathf.Min(Mathf.Max(qx, qy), 0f);
            return outside + inside - r <= 0f;
        }

        /// <summary>Punto dentro de un polígono simple (regla par-impar).</summary>
        private static bool InPolygon(Vector2[] points, float x, float y)
        {
            bool inside = false;
            for (int i = 0, j = points.Length - 1; i < points.Length; j = i++)
            {
                Vector2 a = points[i];
                Vector2 b = points[j];
                if ((a.y > y) != (b.y > y) && x < ((b.x - a.x) * (y - a.y) / (b.y - a.y)) + a.x)
                {
                    inside = !inside;
                }
            }

            return inside;
        }
    }
}
