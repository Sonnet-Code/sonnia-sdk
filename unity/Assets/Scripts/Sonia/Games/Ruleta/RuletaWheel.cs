// La ruleta de cinco casillas (docs/juegos/ruleta.md): la monta y la anima
// RuletaController dentro de su contenido de la tarjeta.
//
// - Cinco casillas en los colores de Google (azul, rojo, amarillo y verde) y la de
//   Sonnet Code en blanco, cada una con su icono y su texto, derechos cuando la casilla
//   pasa por arriba.
// - Una lengüeta arriba que «hace clic» (salta y vuelve) cada vez que pasa una
//   clavija, como una ruleta de feria.
// - El giro: un pequeño impulso hacia atrás y varias vueltas que frenan poco a poco
//   (curva de cuarto grado) hasta la casilla que eligió el orquestador, con un desvío
//   al azar dentro de la casilla para que no pare siempre en el centro. Al parar, la
//   casilla brilla y las demás se apagan un poco.
//
// Ángulos: la ruleta gira en z (positivo, antihorario, como Unity). La casilla i va
// de 72·i a 72·(i+1) grados medidos en sentido horario desde arriba, así que con la
// ruleta girada R grados queda bajo la lengüeta la casilla floor(R mod 360 / 72).

using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Random = UnityEngine.Random;

namespace Sonia.Games.Ruleta
{
    /// <summary>La ruleta en pantalla: casillas, lengüeta, giro con frenada y casilla ganadora.</summary>
    internal sealed class RuletaWheel
    {
        public const int Count = 5;
        private const float Step = 360f / Count;

        /// <summary>Vueltas enteras como mínimo en cada giro.</summary>
        private const int MinTurns = 4;

        /// <summary>Retroceso del impulso inicial (grados) y lo que dura.</summary>
        private const float WindUp = 7f;
        private const float WindUpSeconds = 0.22f;

        /// <summary>Lo que se puede desviar del centro de la casilla al parar (grados).</summary>
        private const float LandJitter = 20f;

        /// <summary>Salto de la lengüeta en cada clic (grados).</summary>
        private const float KickAngle = 22f;

        /// <summary>Altura del eje de la lengüeta en su sprite (fracción, desde abajo).</summary>
        private const float PointerPivot = 0.86f;

        /// <summary>Colores de las casillas, en el orden del protocolo, y de lo que va encima.</summary>
        public static readonly Color[] Fill =
        {
            GameColors.Blue,
            GameColors.Red,
            GameColors.Yellow,
            GameColors.Green,
            new Color(0.95f, 0.96f, 0.99f, 1f),
        };

        public static readonly Color[] Ink =
        {
            Color.white,
            Color.white,
            GameColors.Navy,
            Color.white,
            GameColors.Navy,
        };

        private readonly Image[] _wedges = new Image[Count];
        private readonly Image[] _glows = new Image[Count];
        private readonly RectTransform[] _faces = new RectTransform[Count];
        private readonly TextMeshProUGUI[] _labels = new TextMeshProUGUI[Count];
        private readonly Image[] _icons = new Image[Count];
        private readonly TextMeshProUGUI[] _glyphs = new TextMeshProUGUI[Count];
        private readonly Image[] _pegs = new Image[Count];
        private readonly float[] _pegFlash = new float[Count];
        private readonly bool[] _off = new bool[Count];

        private RectTransform _root;
        private RectTransform _spinner;
        private RectTransform _pointer;
        private Image _hubDot;
        private float _diameter;

        private float _angle;
        private bool _spinning;
        private float _spinAt;
        private float _spinFrom;
        private float _spinTo;
        private float _spinSeconds;
        private int _target = -1;
        private int _landed = -1;
        private float _landedAt = -1f;
        private int _underPointer = -1;
        private float _kick;
        private float _clock;

        /// <summary>Al parar en una casilla (la del orquestador) tras un giro.</summary>
        public event Action<int> Stopped;

        public RectTransform Root
        {
            get { return _root; }
        }

        public bool IsBuilt
        {
            get { return _root != null; }
        }

        public bool IsSpinning
        {
            get { return _spinning; }
        }

        /// <summary>La casilla en la que paró la última vez (-1 si aún no paró).</summary>
        public int Landed
        {
            get { return _landed; }
        }

        /// <summary>Monta la ruleta de <paramref name="diameter"/> px en <paramref name="parent"/>, con el centro en <paramref name="center"/> (posición anclada arriba en el centro).</summary>
        public void Build(GameHud hud, RuletaIcons icons, RectTransform parent, Vector2 center, float diameter)
        {
            _diameter = diameter;
            float radius = diameter * 0.5f;
            _root = hud.NewRect("Ruleta", parent);
            _root.anchorMin = new Vector2(0.5f, 1f);
            _root.anchorMax = _root.anchorMin;
            _root.pivot = new Vector2(0.5f, 0.5f);
            _root.anchoredPosition = center;
            _root.sizeDelta = new Vector2(diameter, diameter);

            // Sombra y aro exterior (quietos).
            Image shadow = hud.NewImage("Sombra", _root, icons.Disc, new Color(0f, 0f, 0f, 0.4f));
            Place(shadow.rectTransform, new Vector2(0f, -10f), diameter + 16f);
            Image halo = hud.NewImage("Halo", _root, icons.Glow, GameUi.WithAlpha(GameColors.Brand, 0.55f));
            Place(halo.rectTransform, Vector2.zero, diameter * 1.35f);
            Image rim = hud.NewImage("Aro", _root, icons.Disc, GameColors.Navy);
            Place(rim.rectTransform, Vector2.zero, diameter);
            Image rimLine = hud.NewImage("AroLuz", _root, hud.RingSprite, GameUi.WithAlpha(Color.white, 0.85f));
            Place(rimLine.rectTransform, Vector2.zero, diameter - 6f);

            // Lo que gira.
            _spinner = hud.NewRect("Giro", _root);
            Place(_spinner, Vector2.zero, diameter);
            float wedgeDiameter = diameter - 34f;
            for (int i = 0; i < Count; i++)
            {
                Image wedge = hud.NewImage("Casilla" + i, _spinner, icons.Disc, Fill[i]);
                MakeWedge(wedge);
                Place(wedge.rectTransform, Vector2.zero, wedgeDiameter);
                wedge.rectTransform.localRotation = Quaternion.Euler(0f, 0f, -Step * i);
                _wedges[i] = wedge;

                Image glow = hud.NewImage("Brillo" + i, _spinner, icons.Disc, new Color(1f, 1f, 1f, 0f));
                MakeWedge(glow);
                Place(glow.rectTransform, Vector2.zero, wedgeDiameter);
                glow.rectTransform.localRotation = wedge.rectTransform.localRotation;
                _glows[i] = glow;
            }

            // Separadores entre casillas.
            for (int i = 0; i < Count; i++)
            {
                Image line = hud.NewImage("Separador" + i, _spinner, null, GameUi.WithAlpha(Color.white, 0.9f));
                RectTransform rect = line.rectTransform;
                rect.anchorMin = new Vector2(0.5f, 0.5f);
                rect.anchorMax = rect.anchorMin;
                rect.pivot = new Vector2(0.5f, 0f);
                rect.anchoredPosition = Vector2.zero;
                rect.sizeDelta = new Vector2(5f, (wedgeDiameter * 0.5f) - 2f);
                rect.localRotation = Quaternion.Euler(0f, 0f, -Step * i);
            }

            // Icono y texto de cada casilla, en la bisectriz y derechos arriba.
            for (int i = 0; i < Count; i++)
            {
                RectTransform face = hud.NewRect("Cara" + i, _spinner);
                face.anchorMin = new Vector2(0.5f, 0.5f);
                face.anchorMax = face.anchorMin;
                face.pivot = new Vector2(0.5f, 0.5f);
                face.anchoredPosition = Vector2.zero;
                face.sizeDelta = Vector2.zero;
                face.localRotation = Quaternion.Euler(0f, 0f, -((Step * i) + (Step * 0.5f)));
                _faces[i] = face;

                float iconSize = diameter * 0.12f;
                Image icon = hud.NewImage("Icono", face, null, Ink[i]);
                icon.preserveAspect = true;
                RectTransform iconRect = icon.rectTransform;
                iconRect.anchorMin = new Vector2(0.5f, 0.5f);
                iconRect.anchorMax = iconRect.anchorMin;
                iconRect.pivot = new Vector2(0.5f, 0.5f);
                iconRect.anchoredPosition = new Vector2(0f, radius * 0.76f);
                iconRect.sizeDelta = new Vector2(iconSize, iconSize);
                _icons[i] = icon;

                TextMeshProUGUI glyph = hud.NewText("Signo", face, "?", iconSize * 1.05f, Ink[i], TextAlignmentOptions.Center, hud.DisplayFont);
                RectTransform glyphRect = glyph.rectTransform;
                glyphRect.anchorMin = new Vector2(0.5f, 0.5f);
                glyphRect.anchorMax = glyphRect.anchorMin;
                glyphRect.pivot = new Vector2(0.5f, 0.5f);
                glyphRect.anchoredPosition = new Vector2(0f, radius * 0.76f);
                glyphRect.sizeDelta = new Vector2(iconSize * 1.4f, iconSize * 1.4f);
                glyph.textWrappingMode = TextWrappingModes.NoWrap;
                glyph.gameObject.SetActive(false);
                _glyphs[i] = glyph;

                // El texto, en una caja estrecha: la casilla se estrecha hacia el centro y
                // el autoajuste lo encoge hasta que la línea de dentro cabe.
                TextMeshProUGUI label = hud.NewText("Texto", face, string.Empty, diameter * 0.046f, Ink[i], TextAlignmentOptions.Center, hud.DisplayFont);
                label.enableAutoSizing = true;
                label.fontSizeMin = diameter * 0.03f;
                label.fontSizeMax = diameter * 0.046f;
                label.lineSpacing = -12f;
                label.verticalAlignment = VerticalAlignmentOptions.Middle;
                RectTransform labelRect = label.rectTransform;
                labelRect.anchorMin = new Vector2(0.5f, 0.5f);
                labelRect.anchorMax = labelRect.anchorMin;
                labelRect.pivot = new Vector2(0.5f, 0.5f);
                labelRect.anchoredPosition = new Vector2(0f, radius * 0.48f);
                labelRect.sizeDelta = new Vector2(radius * 0.5f, radius * 0.28f);
                _labels[i] = label;
            }

            // Clavijas en el borde, una por separador: con ellas «hace clic» la lengüeta.
            for (int i = 0; i < Count; i++)
            {
                Image peg = hud.NewImage("Clavija" + i, _spinner, icons.Disc, Color.white);
                float angle = Step * i * Mathf.Deg2Rad;
                float pegRadius = (wedgeDiameter * 0.5f) + 6f;
                Place(peg.rectTransform, new Vector2(Mathf.Sin(angle) * pegRadius, Mathf.Cos(angle) * pegRadius), 18f);
                _pegs[i] = peg;
            }

            // Buje.
            Image hubShadow = hud.NewImage("BujeSombra", _spinner, icons.Disc, new Color(0f, 0f, 0f, 0.35f));
            Place(hubShadow.rectTransform, new Vector2(0f, -4f), diameter * 0.25f);
            Image hub = hud.NewImage("Buje", _spinner, icons.Disc, GameColors.Navy);
            Place(hub.rectTransform, Vector2.zero, diameter * 0.23f);
            Image hubRing = hud.NewImage("BujeAro", _spinner, hud.RingSprite, Color.white);
            Place(hubRing.rectTransform, Vector2.zero, diameter * 0.23f);
            _hubDot = hud.NewImage("BujePunto", _spinner, hud.StarSprite, GameColors.Yellow);
            Place(_hubDot.rectTransform, Vector2.zero, diameter * 0.11f);

            // Lengüeta (quieta, arriba, con el eje arriba): la punta toca el borde de las
            // casillas.
            _pointer = hud.NewRect("Lengueta", _root);
            _pointer.anchorMin = new Vector2(0.5f, 0.5f);
            _pointer.anchorMax = _pointer.anchorMin;
            _pointer.pivot = new Vector2(0.5f, PointerPivot);
            float pointerSize = diameter * 0.15f;
            _pointer.sizeDelta = new Vector2(pointerSize, pointerSize);
            float tip = (wedgeDiameter * 0.5f) - 2f;
            _pointer.anchoredPosition = new Vector2(0f, tip + (pointerSize * (PointerPivot - 0.03f)));
            Image pointerShadow = hud.NewImage("Sombra", _pointer, icons.Pointer, new Color(0f, 0f, 0f, 0.45f));
            GameUi.Stretch(pointerShadow.rectTransform);
            pointerShadow.rectTransform.anchoredPosition = new Vector2(0f, -6f);
            Image pointerBody = hud.NewImage("Cuerpo", _pointer, icons.Pointer, Color.white);
            GameUi.Stretch(pointerBody.rectTransform);
            Image pointerInner = hud.NewImage("Punta", _pointer, icons.Pointer, GameColors.Red);
            GameUi.Stretch(pointerInner.rectTransform);
            pointerInner.rectTransform.offsetMin = new Vector2(pointerSize * 0.2f, pointerSize * 0.22f);
            pointerInner.rectTransform.offsetMax = new Vector2(-pointerSize * 0.2f, -pointerSize * 0.06f);
            Image pointerPin = hud.NewImage("Eje", _pointer, icons.Disc, Color.white);
            RectTransform pin = pointerPin.rectTransform;
            pin.anchorMin = new Vector2(0.5f, PointerPivot);
            pin.anchorMax = pin.anchorMin;
            pin.pivot = new Vector2(0.5f, 0.5f);
            pin.anchoredPosition = Vector2.zero;
            pin.sizeDelta = new Vector2(pointerSize * 0.16f, pointerSize * 0.16f);
        }

        /// <summary>Pone las casillas que mandó el orquestador (las que falten, por defecto).</summary>
        public void SetSegments(GameHud hud, RuletaIcons icons, IList<SegmentInfo> segments)
        {
            for (int i = 0; i < Count; i++)
            {
                SegmentInfo info = segments != null && i < segments.Count && segments[i] != null ? segments[i] : RuletaController.DefaultSegment(i);
                _labels[i].text = GameUi.Plain(WheelLabel(info.Label));
                Sprite sprite = IconFor(hud, icons, info.Icon);
                bool glyph = sprite == null;
                _icons[i].sprite = sprite;
                _icons[i].gameObject.SetActive(!glyph);
                _glyphs[i].gameObject.SetActive(glyph);
                _off[i] = info.Off;
            }

            ApplyColors();
        }

        /// <summary>El icono de una casilla (null: el «?» de la fuente).</summary>
        public static Sprite IconFor(GameHud hud, RuletaIcons icons, string icon)
        {
            switch (icon)
            {
                case "bolt":
                    return icons.Bolt;
                case "mic":
                    return icons.Mic;
                case "crystal":
                    return icons.Crystal;
                case "star":
                    return hud.StarSprite;
                default:
                    return null;
            }
        }

        /// <summary>«Trivia relámpago» en dos líneas para que quepa en la casilla.</summary>
        private static string WheelLabel(string label)
        {
            string text = (label ?? string.Empty).Trim();
            int space = text.IndexOf(' ');
            if (space <= 0)
            {
                return text;
            }

            // Corta por el espacio más cercano al centro.
            int best = space;
            for (int i = space; i >= 0 && i < text.Length; i = text.IndexOf(' ', i + 1))
            {
                if (Mathf.Abs(i - (text.Length / 2)) < Mathf.Abs(best - (text.Length / 2)))
                {
                    best = i;
                }
            }

            return text.Substring(0, best) + "\n" + text.Substring(best + 1);
        }

        /// <summary>Quieta, sin casilla ganadora y con la casilla <paramref name="segment"/> arriba (o como estaba).</summary>
        public void ResetIdle(int segment = -1)
        {
            _spinning = false;
            _target = -1;
            _landed = -1;
            _landedAt = -1f;
            _kick = 0f;
            if (segment >= 0)
            {
                _angle = CenterOf(segment);
            }

            _underPointer = IndexAt(_angle);
            for (int i = 0; i < Count; i++)
            {
                _pegFlash[i] = 0f;
            }

            Apply();
            ApplyColors();
        }

        /// <summary>Gira y para en <paramref name="segment"/> en <paramref name="seconds"/> segundos.</summary>
        public void Spin(int segment, float seconds)
        {
            segment = Mathf.Clamp(segment, 0, Count - 1);
            _angle = Mod360(_angle);
            float stop = CenterOf(segment) + Random.Range(-LandJitter, LandJitter);
            float turns = Mathf.Floor((_angle - (MinTurns * 360f) - stop) / 360f);
            _spinFrom = _angle;
            _spinTo = stop + (turns * 360f);
            _spinAt = _clock;
            _spinSeconds = Mathf.Max(1.5f, seconds);
            _spinning = true;
            _target = segment;
            _landed = -1;
            _landedAt = -1f;
            _underPointer = IndexAt(_angle);
            ApplyColors();
        }

        /// <summary>Para ya en <paramref name="segment"/>, sin animación (reconexión o un reto que llega antes).</summary>
        public void SnapTo(int segment)
        {
            segment = Mathf.Clamp(segment, 0, Count - 1);
            _spinning = false;
            _target = segment;
            _angle = CenterOf(segment);
            _underPointer = segment;
            Land(segment, false);
            Apply();
        }

        public void Tick(float dt)
        {
            if (_root == null)
            {
                return;
            }

            _clock += dt;
            if (_spinning)
            {
                float t = _clock - _spinAt;
                if (t < WindUpSeconds)
                {
                    // Impulso: un poco hacia atrás antes de salir disparada.
                    _angle = _spinFrom + (WindUp * Mathf.Sin(t / WindUpSeconds * Mathf.PI * 0.5f));
                }
                else
                {
                    float u = Mathf.Clamp01((t - WindUpSeconds) / Mathf.Max(0.1f, _spinSeconds - WindUpSeconds));
                    float eased = 1f - Mathf.Pow(1f - u, 4f);
                    float from = _spinFrom + WindUp;
                    _angle = from + ((_spinTo - from) * eased);
                    if (u >= 1f)
                    {
                        _angle = _spinTo;
                        _spinning = false;
                        Land(_target, true);
                    }
                }

                int under = IndexAt(_angle);
                if (under != _underPointer)
                {
                    // Pasa una clavija: clic de la lengüeta.
                    int peg = PegBetween(_underPointer, under);
                    _underPointer = under;
                    _kick = 1f;
                    if (peg >= 0)
                    {
                        _pegFlash[peg] = 1f;
                    }
                }
            }

            _kick = Mathf.MoveTowards(_kick, 0f, dt * 7f);
            for (int i = 0; i < Count; i++)
            {
                _pegFlash[i] = Mathf.MoveTowards(_pegFlash[i], 0f, dt * 5f);
                float size = 18f + (8f * _pegFlash[i]);
                _pegs[i].rectTransform.sizeDelta = new Vector2(size, size);
                _pegs[i].color = Color.Lerp(Color.white, GameColors.Yellow, _pegFlash[i]);
            }

            Apply();
            AnimateLanded();
        }

        // ------------------------------------------------------------------
        // Internas
        // ------------------------------------------------------------------

        private void Land(int segment, bool raise)
        {
            _landed = segment;
            _landedAt = _clock;
            _kick = 0.6f;
            ApplyColors();
            if (raise)
            {
                try
                {
                    Action<int> handler = Stopped;
                    if (handler != null)
                    {
                        handler(segment);
                    }
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex);
                }
            }
        }

        private void Apply()
        {
            if (_spinner != null)
            {
                _spinner.localRotation = Quaternion.Euler(0f, 0f, _angle);
            }

            if (_pointer != null)
            {
                // El clic: salta hacia el lado al que empuja la clavija y vuelve.
                float kick = KickAngle * Mathf.Sin(Mathf.Clamp01(_kick) * Mathf.PI * 0.5f);
                _pointer.localRotation = Quaternion.Euler(0f, 0f, kick);
            }
        }

        private void AnimateLanded()
        {
            for (int i = 0; i < Count; i++)
            {
                float glow = 0f;
                if (_landed == i && _landedAt >= 0f)
                {
                    float s = _clock - _landedAt;
                    glow = (0.06f + (0.14f * (0.5f + (0.5f * Mathf.Sin(s * 7f))))) * Mathf.Clamp01(1.6f - (s * 0.15f));
                    float pop = s < 0.45f ? 1f + (0.08f * Mathf.Sin(s / 0.45f * Mathf.PI)) : 1f;
                    _faces[i].localScale = new Vector3(pop, pop, 1f);
                }
                else
                {
                    _faces[i].localScale = Vector3.one;
                }

                Color color = _glows[i].color;
                color.a = glow;
                _glows[i].color = color;
            }

            if (_hubDot != null)
            {
                // La estrella del buje late mientras gira.
                float spin = _spinning ? 1f : 0f;
                float beat = 1f + (0.08f * spin * Mathf.Sin(_clock * 18f));
                _hubDot.rectTransform.localScale = new Vector3(beat, beat, 1f);
            }
        }

        private void ApplyColors()
        {
            for (int i = 0; i < Count; i++)
            {
                bool dim = _off[i] || (_landed >= 0 && _landed != i);
                float alpha = _off[i] ? 0.4f : dim ? 0.72f : 1f;
                Color fill = Fill[i];
                _wedges[i].color = new Color(fill.r * alpha, fill.g * alpha, fill.b * alpha, 1f);
                Color ink = Ink[i];
                ink.a = _off[i] ? 0.5f : dim ? 0.75f : 1f;
                _labels[i].color = ink;
                _icons[i].color = ink;
                _glyphs[i].color = ink;
            }
        }

        private static void MakeWedge(Image image)
        {
            image.type = Image.Type.Filled;
            image.fillMethod = Image.FillMethod.Radial360;
            image.fillOrigin = (int)Image.Origin360.Top;
            image.fillClockwise = true;
            image.fillAmount = 1f / Count;
        }

        private static void Place(RectTransform rect, Vector2 position, float size)
        {
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = rect.anchorMin;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = new Vector2(size, size);
        }

        /// <summary>Ángulo de la ruleta con el centro de la casilla bajo la lengüeta.</summary>
        private static float CenterOf(int segment)
        {
            return (Step * segment) + (Step * 0.5f);
        }

        private static int IndexAt(float angle)
        {
            return Mathf.Clamp(Mathf.FloorToInt(Mod360(angle) / Step), 0, Count - 1);
        }

        /// <summary>La clavija entre dos casillas vecinas (la de la casilla de mayor índice, o la 0 al dar la vuelta).</summary>
        private static int PegBetween(int from, int to)
        {
            if (from < 0 || to < 0)
            {
                return -1;
            }

            if ((from + 1) % Count == to)
            {
                return to;
            }

            if ((to + 1) % Count == from)
            {
                return from;
            }

            return -1;
        }

        private static float Mod360(float angle)
        {
            float m = angle % 360f;
            return m < 0f ? m + 360f : m;
        }
    }
}
