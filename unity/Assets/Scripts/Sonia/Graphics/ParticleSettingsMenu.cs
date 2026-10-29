// "Particles" menu: opened from the options menu (Esc, SoniaOptionsMenu);
// Esc or "Back" returns to it.
//
// At the top the effect is chosen (Ambient, Trivia or Matrix) and shown at once:
// while the menu is open, StageParticles shows that effect no matter what
// (for trivia, with a correct-answer burst every few seconds). Below it:
// amount, speed, size and brightness of that effect, and automatic switching
// (whether effects change by themselves depending on what is happening). The
// panel sits at the bottom and the backdrop barely darkens, so the effect
// shows on top. Saved on this machine (ParticleSettings).
//
// It works with the mouse or with the keyboard alone (↑↓ picks a row, ←→
// changes, R resets the effect), like the other menus.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Stage particle settings, inside the Esc options menu.</summary>
    [DisallowMultipleComponent]
    public class ParticleSettingsMenu : MonoBehaviour
    {
        private static readonly Color PanelColor = new Color(0.02f, 0.03f, 0.08f, 0.94f);
        private static readonly Color ButtonColor = new Color(0.16f, 0.22f, 0.40f, 1f);
        private static readonly Color RowColor = new Color(1f, 1f, 1f, 0.04f);
        private static readonly Color SelectedRowColor = new Color(0.01f, 0.44f, 0.96f, 0.35f);
        private static readonly Color MutedText = new Color(0.72f, 0.77f, 0.88f, 1f);
        private static readonly Color WarningText = new Color(1f, 0.78f, 0.35f, 1f);

        private sealed class Row
        {
            public Func<string> Value;
            public Action<int> Step;
            public Image Background;
            public Text ValueText;
        }

        private GameObject _canvas;
        private Text _status;
        private readonly List<Row> _rows = new List<Row>();
        private int _selected;
        private bool _cursorWasVisible;
        private int _openedFrame = -1;
        private StageEffect _effect = StageEffect.Ambient;

        /// <summary>What "Back" does: set by the options menu to return to it.</summary>
        public Action BackRequested;

        /// <summary>True while the menu is open.</summary>
        public bool IsOpen
        {
            get { return _canvas != null && _canvas.activeSelf; }
        }

        private static StageParticles Particles
        {
            get { return StageParticles.Instance; }
        }

        private void Update()
        {
            if (!IsOpen)
            {
                return;
            }

            Refresh();
            Keyboard keyboard = Keyboard.current;
            // SoniaOptionsMenu handles Esc; the key that opened it (4 or Enter) doesn't count here.
            if (keyboard == null || Time.frameCount == _openedFrame)
            {
                return;
            }

            if (keyboard.downArrowKey.wasPressedThisFrame)
            {
                Select(_selected + 1);
            }
            else if (keyboard.upArrowKey.wasPressedThisFrame)
            {
                Select(_selected - 1);
            }
            else if (keyboard.rightArrowKey.wasPressedThisFrame)
            {
                _rows[_selected].Step(1);
            }
            else if (keyboard.leftArrowKey.wasPressedThisFrame)
            {
                _rows[_selected].Step(-1);
            }
            else if (keyboard.rKey.wasPressedThisFrame)
            {
                ResetEffect();
            }
        }

        private void OnDisable()
        {
            if (Particles != null)
            {
                Particles.Preview = null;
            }
        }

        /// <summary>Opens or closes the menu. While open, the stage shows the chosen effect.</summary>
        public void SetOpen(bool open)
        {
            if (open == IsOpen)
            {
                return;
            }

            if (open)
            {
                if (_canvas == null)
                {
                    Build();
                }

                GraphicsQualityMenu.EnsureEventSystem();
                _cursorWasVisible = Cursor.visible;
                Cursor.visible = true;
                _canvas.SetActive(true);
                _openedFrame = Time.frameCount;
                if (Particles != null)
                {
                    // Opens on the effect currently showing.
                    _effect = Particles.Showing;
                    Particles.Preview = _effect;
                }

                Refresh();
            }
            else
            {
                _canvas.SetActive(false);
                Cursor.visible = _cursorWasVisible;
                if (Particles != null)
                {
                    Particles.Preview = null;
                }
            }
        }

        // ------------------------------------------------------------------
        // Values
        // ------------------------------------------------------------------

        private EffectTuning Tuning
        {
            get { return Particles != null ? Particles.Settings.For(_effect) : null; }
        }

        private void StepEffect(int direction)
        {
            _effect = (StageEffect)(((int)_effect + direction + 3) % 3);
            if (Particles != null)
            {
                Particles.Preview = _effect;
            }
        }

        private void Edit(Action<EffectTuning> edit)
        {
            if (Particles != null)
            {
                StageEffect effect = _effect;
                Particles.EditSettings(s => edit(s.For(effect)));
            }
        }

        private void ResetEffect()
        {
            if (Particles != null)
            {
                StageEffect effect = _effect;
                Particles.EditSettings(s => s.Reset(effect));
            }
        }

        private void ToggleContextual(int direction)
        {
            if (Particles != null)
            {
                Particles.EditSettings(s => s.contextual = !s.contextual);
            }
        }

        private string Percent(Func<EffectTuning, int> read, string zero)
        {
            EffectTuning tuning = Tuning;
            if (tuning == null)
            {
                return "—";
            }

            int value = read(tuning);
            return value == 0 && zero != null ? zero : value + " %";
        }

        private string EffectLabel()
        {
            return ParticleSettings.Label(_effect);
        }

        private string ContextualLabel()
        {
            if (Particles == null)
            {
                return "—";
            }

            return Particles.Settings.contextual ? "Yes: trivia and searches" : "No: always ambient";
        }

        private string StatusText(out bool warning)
        {
            warning = true;
            if (Particles == null)
            {
                return "There are no particles in this scene.";
            }

            if (!StageParticles.QualityAllows)
            {
                return "Particles are off in Graphics quality (\"Particles: No\"): turn them on there to see them.";
            }

            if (Tuning != null && Tuning.amount == 0)
            {
                return ParticleSettings.Label(_effect) + " is off (amount 0 %): ambient shows instead.";
            }

            warning = false;
            switch (_effect)
            {
                case StageEffect.Trivia:
                    return "Trivia preview, with a correct-answer burst every few seconds. Shows by itself during trivia.";
                case StageEffect.Matrix:
                    return "Matrix preview. Shows by itself when Sonnia searches the internet.";
                default:
                    return "Ambient preview: the usual motes.";
            }
        }

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        private void Build()
        {
            _canvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaParticleMenu", 2000);

            // Almost transparent backdrop: the effect has to show above the panel.
            GameObject dim = SoniaUiKit.MakeImage(_canvas.transform, "Backdrop", new Color(0f, 0f, 0f, 0.12f));
            SoniaUiKit.Stretch(dim.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

            GameObject panel = SoniaUiKit.MakeImage(_canvas.transform, "Panel", PanelColor);
            RectTransform panelRect = panel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.5f, 0f);
            panelRect.anchorMax = new Vector2(0.5f, 0f);
            panelRect.pivot = new Vector2(0.5f, 0f);
            panelRect.anchoredPosition = new Vector2(0f, 40f);
            panelRect.sizeDelta = new Vector2(940f, 0f);
            VerticalLayoutGroup column = panel.AddComponent<VerticalLayoutGroup>();
            column.padding = new RectOffset(40, 40, 30, 30);
            column.spacing = 12f;
            column.childControlWidth = true;
            column.childControlHeight = true;
            column.childForceExpandWidth = true;
            column.childForceExpandHeight = false;
            panel.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            Text title = SoniaUiKit.MakeText(panel.transform, "Title", "Particles", 46, TextAnchor.MiddleLeft);
            title.fontStyle = FontStyle.Bold;
            title.GetComponent<LayoutElement>().preferredHeight = 60f;

            _status = SoniaUiKit.MakeText(panel.transform, "Status", string.Empty, 22, TextAnchor.MiddleLeft);
            _status.GetComponent<LayoutElement>().preferredHeight = 64f;

            AddOption(panel.transform, "Effect", EffectLabel, StepEffect);
            AddOption(panel.transform, "Amount",
                () => Percent(t => t.amount, "Off"),
                dir => Edit(t => t.amount = Cycle(ParticleSettings.AmountSteps, t.amount, dir)));
            AddOption(panel.transform, "Speed",
                () => Percent(t => t.speed, null),
                dir => Edit(t => t.speed = Cycle(ParticleSettings.SpeedSteps, t.speed, dir)));
            AddOption(panel.transform, "Size",
                () => Percent(t => t.size, null),
                dir => Edit(t => t.size = Cycle(ParticleSettings.SizeSteps, t.size, dir)));
            AddOption(panel.transform, "Brightness",
                () => Percent(t => t.brightness, null),
                dir => Edit(t => t.brightness = Cycle(ParticleSettings.BrightnessSteps, t.brightness, dir)));
            AddOption(panel.transform, "Auto switch", ContextualLabel, ToggleContextual);

            Text keys = SoniaUiKit.MakeText(panel.transform, "Keys",
                "Esc back · ↑↓ pick · ←→ change · R reset this effect. Saved on this machine.",
                22, TextAnchor.MiddleLeft);
            keys.color = MutedText;
            keys.GetComponent<LayoutElement>().preferredHeight = 64f;

            GameObject buttons = new GameObject("Buttons", typeof(RectTransform));
            buttons.transform.SetParent(panel.transform, false);
            buttons.AddComponent<LayoutElement>().preferredHeight = 80f;
            HorizontalLayoutGroup layout = buttons.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = 12f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = true;
            MakeButton(buttons.transform, "Reset this effect", ResetEffect);
            MakeButton(buttons.transform, "Back", () =>
            {
                SetOpen(false);
                BackRequested?.Invoke();
            });

            _canvas.SetActive(false);
            Select(0);
        }

        private Image MakeButton(Transform parent, string label, UnityEngine.Events.UnityAction action)
        {
            GameObject go = SoniaUiKit.MakeImage(parent, label, ButtonColor);
            go.AddComponent<LayoutElement>();
            go.AddComponent<Button>().onClick.AddListener(action);
            Text text = SoniaUiKit.MakeText(go.transform, "Text", label, 28, TextAnchor.MiddleCenter);
            text.fontStyle = FontStyle.Bold;
            SoniaUiKit.Stretch(text.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
            return go.GetComponent<Image>();
        }

        private void AddOption(Transform parent, string label, Func<string> value, Action<int> step)
        {
            int index = _rows.Count;
            GameObject row = SoniaUiKit.MakeImage(parent, label, RowColor);
            row.AddComponent<LayoutElement>().preferredHeight = 74f;
            HorizontalLayoutGroup layout = row.AddComponent<HorizontalLayoutGroup>();
            layout.padding = new RectOffset(18, 10, 6, 6);
            layout.spacing = 10f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = false;
            layout.childForceExpandHeight = true;
            row.AddComponent<Button>().onClick.AddListener(() => Select(index));

            Text name = SoniaUiKit.MakeText(row.transform, "Name", label, 28, TextAnchor.MiddleLeft);
            name.GetComponent<LayoutElement>().flexibleWidth = 1f;

            Image previous = MakeButton(row.transform, "◄", () => { Select(index); step(-1); });
            previous.GetComponent<LayoutElement>().preferredWidth = 66f;

            Text valueText = SoniaUiKit.MakeText(row.transform, "Value", string.Empty, 26, TextAnchor.MiddleCenter);
            valueText.GetComponent<LayoutElement>().preferredWidth = 330f;

            Image next = MakeButton(row.transform, "►", () => { Select(index); step(1); });
            next.GetComponent<LayoutElement>().preferredWidth = 66f;

            _rows.Add(new Row { Value = value, Step = step, Background = row.GetComponent<Image>(), ValueText = valueText });
        }

        private void Select(int index)
        {
            if (_rows.Count == 0)
            {
                return;
            }

            _selected = (index % _rows.Count + _rows.Count) % _rows.Count;
            for (int i = 0; i < _rows.Count; i++)
            {
                _rows[i].Background.color = i == _selected ? SelectedRowColor : RowColor;
            }
        }

        private void Refresh()
        {
            foreach (Row row in _rows)
            {
                string text = row.Value();
                if (row.ValueText.text != text)
                {
                    row.ValueText.text = text;
                }
            }

            bool warning;
            string status = StatusText(out warning);
            if (_status.text != status)
            {
                _status.text = status;
            }

            _status.color = warning ? WarningText : MutedText;
        }

        /// <summary>Next value in the list (wrapping around).</summary>
        private static int Cycle(int[] steps, int current, int dir)
        {
            int index = Array.IndexOf(steps, current);
            if (index < 0)
            {
                index = Array.IndexOf(steps, 100);
            }

            return steps[((index + dir) % steps.Length + steps.Length) % steps.Length];
        }
    }
}
