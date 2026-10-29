// Graphics quality menu: opened from the options menu (Esc,
// SoniaOptionsMenu); Esc or "Back" returns to it.
//
// At the top the levels (High, Medium, Low, Custom) and the measured frames per
// second; below, each option with ◄ ►. Touching an option switches to
// Custom starting from what is shown. It works with the mouse or with the
// keyboard alone (↑↓ picks a row, ←→ changes the value, 1-4 the levels), in
// case there is no mouse. It also works without -dev-ui: it is for whoever
// sets up the machine, not for the public.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Graphics quality menu, inside the Esc options menu.</summary>
    [DisallowMultipleComponent]
    public class GraphicsQualityMenu : MonoBehaviour
    {
        private static readonly Color PanelColor = new Color(0.02f, 0.03f, 0.08f, 0.94f);
        private static readonly Color ButtonColor = new Color(0.16f, 0.22f, 0.40f, 1f);
        private static readonly Color ActiveColor = new Color(0.01f, 0.44f, 0.96f, 1f);
        private static readonly Color RowColor = new Color(1f, 1f, 1f, 0.04f);
        private static readonly Color SelectedRowColor = new Color(0.01f, 0.44f, 0.96f, 0.35f);
        private static readonly Color MutedText = new Color(0.72f, 0.77f, 0.88f, 1f);

        private sealed class Row
        {
            public Func<string> Value;
            public Action<int> Step;
            public Image Background;
            public Text ValueText;
        }

        private GraphicsQualityController _controller;
        private GameObject _canvas;
        private Text _fpsText;
        private readonly List<Image> _presetButtons = new List<Image>();
        private readonly List<Row> _rows = new List<Row>();
        private int _selected;
        private bool _cursorWasVisible;
        private float _nextFpsRefresh;
        private int _openedFrame = -1;

        /// <summary>What "Back" does: set by the options menu to return to it.</summary>
        public Action BackRequested;

        /// <summary>True while the menu is open.</summary>
        public bool IsOpen
        {
            get { return _canvas != null && _canvas.activeSelf; }
        }

        private void Start()
        {
            _controller = GetComponent<GraphicsQualityController>();
            if (_controller != null)
            {
                _controller.Changed += Refresh;
            }
        }

        private void OnDestroy()
        {
            if (_controller != null)
            {
                _controller.Changed -= Refresh;
            }
        }

        private void Update()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard == null || _controller == null)
            {
                return;
            }

            // SoniaOptionsMenu handles Esc: it closes this menu and returns to the options menu.
            // The key that opened it from the options menu (1 or Enter) doesn't count here.
            if (!IsOpen || Time.frameCount == _openedFrame)
            {
                return;
            }

            if (keyboard.digit1Key.wasPressedThisFrame || keyboard.numpad1Key.wasPressedThisFrame)
            {
                _controller.SetPreset(GraphicsPreset.High);
            }
            else if (keyboard.digit2Key.wasPressedThisFrame || keyboard.numpad2Key.wasPressedThisFrame)
            {
                _controller.SetPreset(GraphicsPreset.Medium);
            }
            else if (keyboard.digit3Key.wasPressedThisFrame || keyboard.numpad3Key.wasPressedThisFrame)
            {
                _controller.SetPreset(GraphicsPreset.Low);
            }
            else if (keyboard.digit4Key.wasPressedThisFrame || keyboard.numpad4Key.wasPressedThisFrame)
            {
                _controller.SetPreset(GraphicsPreset.Custom);
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

            if (Time.unscaledTime >= _nextFpsRefresh)
            {
                _nextFpsRefresh = Time.unscaledTime + 0.25f;
                RefreshFps();
            }
        }

        /// <summary>Opens or closes the menu.</summary>
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

                EnsureEventSystem();
                _cursorWasVisible = Cursor.visible;
                Cursor.visible = true;
                _canvas.SetActive(true);
                _openedFrame = Time.frameCount;
                Refresh();
            }
            else
            {
                _canvas.SetActive(false);
                Cursor.visible = _cursorWasVisible;
            }
        }

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        private void Build()
        {
            _canvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaGraphicsMenu", 2000);

            // Backdrop that darkens and swallows clicks meant for what is below.
            GameObject dim = SoniaUiKit.MakeImage(_canvas.transform, "Backdrop", new Color(0f, 0f, 0f, 0.5f));
            SoniaUiKit.Stretch(dim.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

            GameObject panel = SoniaUiKit.MakeImage(_canvas.transform, "Panel", PanelColor);
            RectTransform panelRect = panel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.5f, 0.5f);
            panelRect.anchorMax = new Vector2(0.5f, 0.5f);
            panelRect.pivot = new Vector2(0.5f, 0.5f);
            panelRect.sizeDelta = new Vector2(940f, 0f);
            VerticalLayoutGroup column = panel.AddComponent<VerticalLayoutGroup>();
            column.padding = new RectOffset(40, 40, 36, 36);
            column.spacing = 14f;
            column.childControlWidth = true;
            column.childControlHeight = true;
            column.childForceExpandWidth = true;
            column.childForceExpandHeight = false;
            panel.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            Text title = SoniaUiKit.MakeText(panel.transform, "Title", "Graphics quality", 46, TextAnchor.MiddleLeft);
            title.fontStyle = FontStyle.Bold;
            title.GetComponent<LayoutElement>().preferredHeight = 60f;

            _fpsText = SoniaUiKit.MakeText(panel.transform, "Fps", string.Empty, 28, TextAnchor.MiddleLeft);
            _fpsText.GetComponent<LayoutElement>().preferredHeight = 40f;

            GameObject presets = MakeRow(panel.transform, "Levels", 88f);
            AddPresetButton(presets.transform, GraphicsPreset.High);
            AddPresetButton(presets.transform, GraphicsPreset.Medium);
            AddPresetButton(presets.transform, GraphicsPreset.Low);
            AddPresetButton(presets.transform, GraphicsPreset.Custom);

            Text hint = SoniaUiKit.MakeText(panel.transform, "Help",
                "High is the scene as built; Medium and Low trim down from there. Changing any option switches to Custom.",
                22, TextAnchor.MiddleLeft);
            hint.color = MutedText;
            hint.GetComponent<LayoutElement>().preferredHeight = 64f;

            AddOption(panel.transform, "Resolution",
                () => Options.renderScalePercent + " %",
                dir => Edit(o => o.renderScalePercent = Cycle(GraphicsOptions.RenderScaleSteps, o.renderScalePercent, dir)));
            AddOption(panel.transform, "Upscaling",
                () => Options.renderScalePercent >= 100 ? "— (at 100 %)" : Options.sharpUpscaling ? "Sharp (FSR)" : "Soft",
                dir => Edit(o => o.sharpUpscaling = !o.sharpUpscaling));
            AddOption(panel.transform, "Edge smoothing",
                () => AntialiasLabel(Options.antialiasing),
                dir => Edit(o => o.antialiasing = (AntialiasLevel)CycleEnum((int)o.antialiasing, 4, -dir)));
            AddOption(panel.transform, "Shadows",
                () => ShadowLabel(Options.shadows),
                dir => Edit(o => o.shadows = (ShadowLevel)CycleEnum((int)o.shadows, 4, -dir)));
            AddOption(panel.transform, "Ambient occlusion",
                () => !_controller.HasAmbientOcclusion ? "Not in this scene" : Options.ambientOcclusion ? "Yes" : "No",
                dir => Edit(o => o.ambientOcclusion = !o.ambientOcclusion));
            AddOption(panel.transform, "Background blur",
                () => BlurLabel(Options.backgroundBlur),
                dir => Edit(o => o.backgroundBlur = (BlurLevel)CycleEnum((int)o.backgroundBlur, 3, -dir)));
            AddOption(panel.transform, "Glow (bloom)",
                () => BloomLabel(Options.bloom),
                dir => Edit(o => o.bloom = (BloomLevel)CycleEnum((int)o.bloom, 3, -dir)));
            AddOption(panel.transform, "Particles",
                () => Options.particles ? "Yes" : "No",
                dir => Edit(o => o.particles = !o.particles));
            AddOption(panel.transform, "Frames per second",
                () => Options.targetFrameRate.ToString(),
                dir => Edit(o => o.targetFrameRate = Cycle(GraphicsOptions.FrameRateSteps, o.targetFrameRate, dir)));

            Text keys = SoniaUiKit.MakeText(panel.transform, "Keys",
                "Esc back · ↑↓ pick · ←→ change · 1-4 levels. Saved on this machine; can be forced at launch with -quality high|medium|low.",
                22, TextAnchor.MiddleLeft);
            keys.color = MutedText;
            keys.GetComponent<LayoutElement>().preferredHeight = 64f;

            GameObject backRow = MakeRow(panel.transform, "Back", 80f);
            MakeButton(backRow.transform, "Back", () =>
            {
                SetOpen(false);
                BackRequested?.Invoke();
            });

            _canvas.SetActive(false);
            Select(0);
        }

        private static GameObject MakeRow(Transform parent, string name, float height)
        {
            GameObject row = new GameObject(name, typeof(RectTransform));
            row.transform.SetParent(parent, false);
            row.AddComponent<LayoutElement>().preferredHeight = height;
            HorizontalLayoutGroup layout = row.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = 12f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = true;
            return row;
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

        private void AddPresetButton(Transform parent, GraphicsPreset preset)
        {
            Image image = MakeButton(parent, GraphicsQualityStore.Label(preset), () => _controller.SetPreset(preset));
            _presetButtons.Add(image);
        }

        private void AddOption(Transform parent, string label, Func<string> value, Action<int> step)
        {
            int index = _rows.Count;
            GameObject row = SoniaUiKit.MakeImage(parent, label, RowColor);
            row.AddComponent<LayoutElement>().preferredHeight = 78f;
            HorizontalLayoutGroup layout = row.AddComponent<HorizontalLayoutGroup>();
            layout.padding = new RectOffset(18, 10, 6, 6);
            layout.spacing = 10f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = false;
            layout.childForceExpandHeight = true;
            // Clicking the row with the mouse selects it for the arrow keys.
            row.AddComponent<Button>().onClick.AddListener(() => Select(index));

            Text name = SoniaUiKit.MakeText(row.transform, "Name", label, 28, TextAnchor.MiddleLeft);
            name.GetComponent<LayoutElement>().flexibleWidth = 1f;

            Image previous = MakeButton(row.transform, "◄", () => { Select(index); step(-1); });
            previous.GetComponent<LayoutElement>().preferredWidth = 66f;

            Text valueText = SoniaUiKit.MakeText(row.transform, "Value", string.Empty, 28, TextAnchor.MiddleCenter);
            valueText.GetComponent<LayoutElement>().preferredWidth = 290f;

            Image next = MakeButton(row.transform, "►", () => { Select(index); step(1); });
            next.GetComponent<LayoutElement>().preferredWidth = 66f;

            _rows.Add(new Row { Value = value, Step = step, Background = row.GetComponent<Image>(), ValueText = valueText });
        }

        /// <summary>Creates an EventSystem if the scene has none, so the menus respond to the mouse.</summary>
        internal static void EnsureEventSystem()
        {
            if (EventSystem.current != null || FindAnyObjectByType<EventSystem>() != null)
            {
                return;
            }

            GameObject go = new GameObject("EventSystem", typeof(EventSystem), typeof(InputSystemUIInputModule));
            DontDestroyOnLoad(go);
        }

        // ------------------------------------------------------------------
        // State
        // ------------------------------------------------------------------

        private GraphicsOptions Options
        {
            get { return _controller.State.Effective; }
        }

        private void Edit(Action<GraphicsOptions> edit)
        {
            _controller.EditCustom(edit);
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
            if (_canvas == null || _controller == null)
            {
                return;
            }

            for (int i = 0; i < _presetButtons.Count; i++)
            {
                _presetButtons[i].color = (int)_controller.State.preset == i ? ActiveColor : ButtonColor;
            }

            foreach (Row row in _rows)
            {
                row.ValueText.text = row.Value();
            }

            RefreshFps();
        }

        private void RefreshFps()
        {
            if (_fpsText == null)
            {
                return;
            }

            float fps = _controller.Fps;
            int target = Options.targetFrameRate;
            _fpsText.text = "Now: " + Mathf.RoundToInt(fps) + " FPS (target " + target + ")";
            _fpsText.color = fps >= target * 0.9f
                ? new Color(0.45f, 0.9f, 0.55f)
                : fps >= target * 0.7f ? new Color(1f, 0.78f, 0.35f) : new Color(1f, 0.45f, 0.4f);
        }

        // ------------------------------------------------------------------
        // Values
        // ------------------------------------------------------------------

        /// <summary>Next value in the list (wrapping around).</summary>
        private static int Cycle(int[] steps, int current, int dir)
        {
            int index = Array.IndexOf(steps, current);
            if (index < 0)
            {
                index = 0;
            }

            return steps[((index + dir) % steps.Length + steps.Length) % steps.Length];
        }

        /// <summary>Next value of an enum from 0 to count-1 (wrapping around).</summary>
        private static int CycleEnum(int current, int count, int dir)
        {
            return ((current + dir) % count + count) % count;
        }

        private static string AntialiasLabel(AntialiasLevel level)
        {
            switch (level)
            {
                case AntialiasLevel.Off:
                    return "No smoothing";
                case AntialiasLevel.Fxaa:
                    return "FXAA";
                case AntialiasLevel.Smaa:
                    return "SMAA";
                default:
                    return "As built";
            }
        }

        private static string ShadowLabel(ShadowLevel level)
        {
            switch (level)
            {
                case ShadowLevel.Off:
                    return "No shadows";
                case ShadowLevel.Low:
                    return "Low";
                case ShadowLevel.Medium:
                    return "Medium";
                default:
                    return "As built";
            }
        }

        private static string BlurLabel(BlurLevel level)
        {
            switch (level)
            {
                case BlurLevel.Off:
                    return "No blur";
                case BlurLevel.Soft:
                    return "Soft";
                default:
                    return "As built";
            }
        }

        private static string BloomLabel(BloomLevel level)
        {
            switch (level)
            {
                case BloomLevel.Off:
                    return "No glow";
                case BloomLevel.Normal:
                    return "Normal";
                default:
                    return "As built";
            }
        }
    }
}
