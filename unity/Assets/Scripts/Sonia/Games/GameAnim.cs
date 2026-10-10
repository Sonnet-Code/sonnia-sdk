// Animaciones sencillas para las pantallas de los juegos: aparecer con rebote,
// temblar, latir, voltear (las fichas del Wordle), fundir y desplazar. Se lanzan
// con una línea y se apilan en un componente del propio objeto, sin corrutinas:
//
//   GameAnim.Pop(rect);                       // de 0 a su tamaño con rebote
//   GameAnim.Shake(rect);                     // la palabra no vale
//   GameAnim.Flip(rect, () => PaintTile(), 0.5f, 0.1f * column);
//   GameAnim.Fade(group, 0f, 0.3f);
//
// Van con Time.deltaTime, como el resto del HUD (y las capturas a paso fijo).

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Tweens mínimos sobre un RectTransform o un CanvasGroup.</summary>
    [DisallowMultipleComponent]
    public sealed class GameAnim : MonoBehaviour
    {
        private enum Kind
        {
            Pop,
            Shake,
            Pulse,
            Flip,
            Fade,
            Move
        }

        private sealed class Tween
        {
            public Kind Kind;
            public float Delay;
            public float Duration;
            public float Age;
            public float Amount;
            public float From;
            public float To;
            public Vector2 FromPosition;
            public Vector2 ToPosition;
            public Vector3 BaseScale;
            public Vector2 BasePosition;
            public bool Started;
            public bool MiddleDone;
            public Action Middle;
            public Action Done;
            public CanvasGroup Group;
        }

        private readonly List<Tween> _tweens = new List<Tween>();
        private RectTransform _rect;

        /// <summary>Cierto mientras queda alguna animación en marcha.</summary>
        public bool IsAnimating
        {
            get { return _tweens.Count > 0; }
        }

        /// <summary>Aparece de tamaño 0 a su escala con rebote. Mientras espera el retraso, no se ve.</summary>
        public static void Pop(RectTransform target, float duration = 0.45f, float delay = 0f, Action done = null)
        {
            GameAnim anim = For(target);
            if (anim == null)
            {
                return;
            }

            Tween tween = anim.Add(Kind.Pop, duration, delay, done);
            tween.BaseScale = Vector3.one;
            target.localScale = Vector3.zero;
        }

        /// <summary>Tiembla de lado a lado y vuelve a su sitio (respuesta que no vale).</summary>
        public static void Shake(RectTransform target, float duration = 0.55f, float amplitude = 16f)
        {
            GameAnim anim = For(target);
            if (anim == null)
            {
                return;
            }

            anim.Add(Kind.Shake, duration, 0f, null).Amount = amplitude;
        }

        /// <summary>Late una vez: crece un poco y vuelve.</summary>
        public static void Pulse(RectTransform target, float amount = 0.08f, float duration = 0.35f, float delay = 0f)
        {
            GameAnim anim = For(target);
            if (anim == null)
            {
                return;
            }

            anim.Add(Kind.Pulse, duration, delay, null).Amount = amount;
        }

        /// <summary>
        /// Se voltea en vertical: se aplasta hasta 0, llama a <paramref name="atMiddle"/>
        /// (cambiar color o letra) y vuelve a abrirse.
        /// </summary>
        public static void Flip(RectTransform target, Action atMiddle, float duration = 0.5f, float delay = 0f, Action done = null)
        {
            GameAnim anim = For(target);
            if (anim == null)
            {
                return;
            }

            anim.Add(Kind.Flip, duration, delay, done).Middle = atMiddle;
        }

        /// <summary>Lleva la opacidad del grupo a <paramref name="to"/>.</summary>
        public static void Fade(CanvasGroup group, float to, float duration = 0.3f, float delay = 0f, Action done = null)
        {
            if (group == null)
            {
                return;
            }

            GameAnim anim = For(group.transform as RectTransform);
            if (anim == null)
            {
                return;
            }

            Tween tween = anim.Add(Kind.Fade, duration, delay, done);
            tween.Group = group;
            tween.To = to;
        }

        /// <summary>Lleva <c>anchoredPosition</c> a <paramref name="to"/> con frenada suave.</summary>
        public static void Move(RectTransform target, Vector2 to, float duration = 0.4f, float delay = 0f, Action done = null)
        {
            GameAnim anim = For(target);
            if (anim == null)
            {
                return;
            }

            anim.Add(Kind.Move, duration, delay, done).ToPosition = to;
        }

        /// <summary>Corta las animaciones de un objeto y lo deja en su estado final.</summary>
        public static void Stop(Component target)
        {
            GameAnim anim = target != null ? target.GetComponent<GameAnim>() : null;
            if (anim != null)
            {
                anim.Finish();
            }
        }

        private static GameAnim For(RectTransform target)
        {
            if (target == null)
            {
                return null;
            }

            GameAnim anim = target.GetComponent<GameAnim>();
            if (anim == null)
            {
                anim = target.gameObject.AddComponent<GameAnim>();
            }

            anim._rect = target;
            anim.enabled = true;
            return anim;
        }

        private Tween Add(Kind kind, float duration, float delay, Action done)
        {
            // Una animación nueva del mismo tipo sustituye a la que hubiera.
            for (int i = _tweens.Count - 1; i >= 0; i--)
            {
                if (_tweens[i].Kind == kind)
                {
                    Complete(_tweens[i], false);
                    _tweens.RemoveAt(i);
                }
            }

            Tween tween = new Tween
            {
                Kind = kind,
                Duration = Mathf.Max(0.01f, duration),
                Delay = Mathf.Max(0f, delay),
                Done = done
            };
            _tweens.Add(tween);
            return tween;
        }

        private void Update()
        {
            if (_tweens.Count == 0)
            {
                enabled = false;
                return;
            }

            float dt = Time.deltaTime;
            for (int i = _tweens.Count - 1; i >= 0; i--)
            {
                if (i >= _tweens.Count)
                {
                    continue;
                }

                Tween tween = _tweens[i];
                if (tween.Delay > 0f)
                {
                    tween.Delay -= dt;
                    continue;
                }

                if (!tween.Started)
                {
                    Begin(tween);
                }

                tween.Age += dt;
                float t = Mathf.Clamp01(tween.Age / tween.Duration);
                Apply(tween, t);
                if (t >= 1f)
                {
                    _tweens.Remove(tween);
                    Complete(tween, true);
                }
            }
        }

        private void Begin(Tween tween)
        {
            tween.Started = true;
            if (_rect != null)
            {
                tween.BasePosition = _rect.anchoredPosition;
                tween.FromPosition = _rect.anchoredPosition;
                if (tween.Kind != Kind.Pop)
                {
                    tween.BaseScale = _rect.localScale;
                }
            }

            if (tween.Group != null)
            {
                tween.From = tween.Group.alpha;
            }
        }

        private void Apply(Tween tween, float t)
        {
            switch (tween.Kind)
            {
                case Kind.Pop:
                    if (_rect != null)
                    {
                        _rect.localScale = tween.BaseScale * GameUi.EaseOutBack(t);
                    }

                    break;
                case Kind.Shake:
                    if (_rect != null)
                    {
                        float offset = Mathf.Sin(tween.Age * 46f) * tween.Amount * (1f - t);
                        _rect.anchoredPosition = tween.BasePosition + new Vector2(t >= 1f ? 0f : offset, 0f);
                    }

                    break;
                case Kind.Pulse:
                    if (_rect != null)
                    {
                        _rect.localScale = tween.BaseScale * (1f + (tween.Amount * Mathf.Sin(t * Mathf.PI)));
                    }

                    break;
                case Kind.Flip:
                    if (_rect != null)
                    {
                        float y;
                        if (t < 0.5f)
                        {
                            y = 1f - GameUi.EaseInCubic(t * 2f);
                        }
                        else
                        {
                            if (!tween.MiddleDone)
                            {
                                tween.MiddleDone = true;
                                Invoke(tween.Middle);
                            }

                            y = GameUi.EaseOutCubic((t - 0.5f) * 2f);
                        }

                        Vector3 scale = tween.BaseScale;
                        _rect.localScale = new Vector3(scale.x, scale.y * y, scale.z);
                    }

                    break;
                case Kind.Fade:
                    if (tween.Group != null)
                    {
                        tween.Group.alpha = Mathf.Lerp(tween.From, tween.To, GameUi.EaseInOutSine(t));
                    }

                    break;
                case Kind.Move:
                    if (_rect != null)
                    {
                        _rect.anchoredPosition = Vector2.LerpUnclamped(tween.FromPosition, tween.ToPosition, GameUi.EaseOutCubic(t));
                    }

                    break;
            }
        }

        /// <summary>Deja el objeto en el estado final de la animación y avisa.</summary>
        private void Complete(Tween tween, bool natural)
        {
            if (!tween.Started)
            {
                Begin(tween);
            }

            if (!natural)
            {
                Apply(tween, 1f);
            }

            if (tween.Kind == Kind.Flip && !tween.MiddleDone)
            {
                tween.MiddleDone = true;
                Invoke(tween.Middle);
            }

            if (_rect != null)
            {
                if (tween.Kind == Kind.Shake)
                {
                    _rect.anchoredPosition = tween.BasePosition;
                }
                else if (tween.Kind == Kind.Pulse || tween.Kind == Kind.Flip || tween.Kind == Kind.Pop)
                {
                    _rect.localScale = tween.BaseScale;
                }
            }

            Invoke(tween.Done);
        }

        private void Finish()
        {
            List<Tween> pending = new List<Tween>(_tweens);
            _tweens.Clear();
            foreach (Tween tween in pending)
            {
                Complete(tween, false);
            }
        }

        private void Invoke(Action action)
        {
            if (action == null)
            {
                return;
            }

            try
            {
                action();
            }
            catch (Exception ex)
            {
                Debug.LogException(ex, this);
            }
        }
    }
}
