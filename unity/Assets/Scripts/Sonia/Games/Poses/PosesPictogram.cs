// Pictograma de la pose en «Simón dice con poses»: un monigote blanco hecho con
// la UI (líneas y puntos), visto de frente como se ve a Sonnia en la pantalla.
// El brazo de la izquierda de la pantalla es el derecho de Sonnia. Cambia de
// pose con una transición corta.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia.Games.Poses
{
    /// <summary>Monigote blanco que dibuja cada pose del juego.</summary>
    public sealed class PosesPictogram
    {
        // Articulaciones en coordenadas del dibujo: -1 a 1, y hacia arriba.
        private struct Figure
        {
            public Vector2 ElbowA;
            public Vector2 HandA;
            public Vector2 ElbowB;
            public Vector2 HandB;
            public bool FistA;
            public bool FistB;
        }

        private static readonly Vector2 Head = new Vector2(0f, 0.6f);
        private const float HeadRadius = 0.17f;
        private static readonly Vector2 Neck = new Vector2(0f, 0.4f);
        private static readonly Vector2 ShoulderA = new Vector2(-0.2f, 0.34f);
        private static readonly Vector2 ShoulderB = new Vector2(0.2f, 0.34f);
        private static readonly Vector2 Hips = new Vector2(0f, -0.2f);
        private static readonly Vector2 FootA = new Vector2(-0.2f, -0.94f);
        private static readonly Vector2 FootB = new Vector2(0.2f, -0.94f);

        private static readonly Dictionary<string, Figure> Figures = new Dictionary<string, Figure>
        {
            { "reposo", Make(-0.3f, 0.02f, -0.34f, -0.3f, false, false, false) },
            { "brazos_arriba", Make(-0.36f, 0.66f, -0.5f, 0.95f, false, false, true) },
            { "un_brazo", new Figure { ElbowA = new Vector2(-0.26f, 0.68f), HandA = new Vector2(-0.3f, 1.0f), ElbowB = new Vector2(0.3f, 0.02f), HandB = new Vector2(0.34f, -0.3f) } },
            { "pose_t", Make(-0.54f, 0.36f, -0.86f, 0.38f, false, false, true) },
            { "manos_cabeza", Make(-0.52f, 0.6f, -0.2f, 0.68f, false, false, true) },
            { "biceps", Make(-0.54f, 0.38f, -0.5f, 0.74f, true, true, true) },
            { "barbilla", new Figure { ElbowA = new Vector2(-0.2f, 0.02f), HandA = new Vector2(-0.04f, 0.4f), FistA = true, ElbowB = new Vector2(0.3f, 0.02f), HandB = new Vector2(0.34f, -0.3f) } }
        };

        private readonly RectTransform _root;
        private readonly float _half;
        private readonly float _thickness;
        private readonly Image _head;
        private readonly Image[] _lines = new Image[9];
        private readonly Image[] _dots = new Image[8];

        private Figure _from;
        private Figure _to;
        private float _t = 1f;

        /// <summary>Monta el monigote en <paramref name="parent"/>, de <paramref name="size"/> píxeles de alto.</summary>
        public PosesPictogram(GameHud hud, RectTransform parent, float size, Color color)
        {
            _root = hud.NewRect("Monigote", parent);
            GameUi.PlaceCenter(_root, Vector2.zero, new Vector2(size, size));
            _half = size * 0.5f;
            _thickness = Mathf.Max(6f, size * 0.075f);
            for (int i = 0; i < _lines.Length; i++)
            {
                _lines[i] = hud.NewImage("Trazo" + i, _root, null, color);
                RectTransform rect = _lines[i].rectTransform;
                rect.anchorMin = new Vector2(0.5f, 0.5f);
                rect.anchorMax = rect.anchorMin;
                rect.pivot = new Vector2(0f, 0.5f);
            }

            for (int i = 0; i < _dots.Length; i++)
            {
                _dots[i] = hud.NewImage("Punto" + i, _root, hud.DotSprite, color);
                RectTransform rect = _dots[i].rectTransform;
                rect.anchorMin = new Vector2(0.5f, 0.5f);
                rect.anchorMax = rect.anchorMin;
                rect.pivot = new Vector2(0.5f, 0.5f);
            }

            _head = hud.NewImage("Cabeza", _root, hud.DotSprite, color);
            RectTransform headRect = _head.rectTransform;
            headRect.anchorMin = new Vector2(0.5f, 0.5f);
            headRect.anchorMax = headRect.anchorMin;
            headRect.pivot = new Vector2(0.5f, 0.5f);
            headRect.anchoredPosition = Head * _half;
            headRect.sizeDelta = Vector2.one * (HeadRadius * 2f * _half);

            _from = Figures["reposo"];
            _to = _from;
            Draw(_to);
        }

        public RectTransform Root
        {
            get { return _root; }
        }

        /// <summary>Cambia a la pose <paramref name="pose"/> (desconocida: de pie, en reposo).</summary>
        public void SetPose(string pose, bool instant)
        {
            Figure figure;
            if (string.IsNullOrEmpty(pose) || !Figures.TryGetValue(pose, out figure))
            {
                figure = Figures["reposo"];
            }

            _from = instant ? figure : Current();
            _to = figure;
            _t = instant ? 1f : 0f;
            Draw(instant ? _to : _from);
        }

        /// <summary>Avanza la transición (llamar cada fotograma).</summary>
        public void Tick(float dt)
        {
            if (_t >= 1f)
            {
                return;
            }

            _t = Mathf.Min(1f, _t + (dt / 0.35f));
            Draw(Current());
        }

        private Figure Current()
        {
            float k = GameUi.EaseOutCubic(Mathf.Clamp01(_t));
            return new Figure
            {
                ElbowA = Vector2.Lerp(_from.ElbowA, _to.ElbowA, k),
                HandA = Vector2.Lerp(_from.HandA, _to.HandA, k),
                ElbowB = Vector2.Lerp(_from.ElbowB, _to.ElbowB, k),
                HandB = Vector2.Lerp(_from.HandB, _to.HandB, k),
                FistA = k > 0.5f ? _to.FistA : _from.FistA,
                FistB = k > 0.5f ? _to.FistB : _from.FistB
            };
        }

        private void Draw(Figure f)
        {
            Line(0, Neck, Hips);
            Line(1, ShoulderA, ShoulderB);
            Line(2, Hips, FootA);
            Line(3, Hips, FootB);
            Line(4, ShoulderA, f.ElbowA);
            Line(5, f.ElbowA, f.HandA);
            Line(6, ShoulderB, f.ElbowB);
            Line(7, f.ElbowB, f.HandB);
            Line(8, Neck, Head - new Vector2(0f, HeadRadius * 0.6f));
            Dot(0, ShoulderA, 1f);
            Dot(1, ShoulderB, 1f);
            Dot(2, f.ElbowA, 1f);
            Dot(3, f.ElbowB, 1f);
            Dot(4, f.HandA, f.FistA ? 2.1f : 1.6f);
            Dot(5, f.HandB, f.FistB ? 2.1f : 1.6f);
            Dot(6, FootA, 1f);
            Dot(7, FootB, 1f);
        }

        private void Line(int index, Vector2 a, Vector2 b)
        {
            RectTransform rect = _lines[index].rectTransform;
            Vector2 pa = a * _half;
            Vector2 pb = b * _half;
            Vector2 d = pb - pa;
            rect.anchoredPosition = pa;
            rect.sizeDelta = new Vector2(d.magnitude, _thickness);
            rect.localRotation = Quaternion.Euler(0f, 0f, Mathf.Atan2(d.y, d.x) * Mathf.Rad2Deg);
        }

        private void Dot(int index, Vector2 at, float scale)
        {
            RectTransform rect = _dots[index].rectTransform;
            rect.anchoredPosition = at * _half;
            rect.sizeDelta = Vector2.one * (_thickness * scale);
        }

        /// <summary>Un monigote simétrico: el brazo A (izquierda de la pantalla) y su espejo.</summary>
        private static Figure Make(float ex, float ey, float hx, float hy, bool fistA, bool fistB, bool mirror)
        {
            Figure f = new Figure
            {
                ElbowA = new Vector2(ex, ey),
                HandA = new Vector2(hx, hy),
                FistA = fistA,
                FistB = fistB
            };
            f.ElbowB = mirror ? new Vector2(-ex, ey) : new Vector2(0.3f, 0.02f);
            f.HandB = mirror ? new Vector2(-hx, hy) : new Vector2(0.34f, -0.3f);
            return f;
        }
    }
}
