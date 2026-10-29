// "Microphone, camera and display" menu: opened from the options menu (Esc,
// SoniaOptionsMenu); Esc or "Back" returns to it.
//
// The microphone and camera are opened by the orchestrator: it sends the
// microphone list (devices message, requested when the menu opens) and the
// choice is sent back with set_device; it is saved on that machine
// (cache/devices.json) and overrides the .env. By default, the system
// ones. Unity lists the cameras (WebCamTexture.devices) in the same order
// OpenCV opens them. The resolution and display mode belong to the Unity
// window, and Unity remembers them from one launch to the next by itself.
//
// It works with the mouse or with the keyboard alone (↑↓ picks a row, ←→
// changes), like the graphics quality one.

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Microphone, camera, resolution and display mode of this machine.</summary>
    [DisallowMultipleComponent]
    public class StandSettingsMenu : MonoBehaviour
    {
        private static readonly Color PanelColor = new Color(0.02f, 0.03f, 0.08f, 0.94f);
        private static readonly Color ButtonColor = new Color(0.16f, 0.22f, 0.40f, 1f);
        private static readonly Color RowColor = new Color(1f, 1f, 1f, 0.04f);
        private static readonly Color SelectedRowColor = new Color(0.01f, 0.44f, 0.96f, 0.35f);
        private static readonly Color MutedText = new Color(0.72f, 0.77f, 0.88f, 1f);

        // Vertical 9:16 sizes on offer (those that fit on the screen, windowed).
        private static readonly Vector2Int[] Sizes =
        {
            new Vector2Int(540, 960),
            new Vector2Int(720, 1280),
            new Vector2Int(810, 1440),
            new Vector2Int(1080, 1920),
            new Vector2Int(1440, 2560),
            new Vector2Int(2160, 3840)
        };

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
        private SoniaClient _client;
        private DevicesMessage _devices;

        /// <summary>What "Back" does: set by the options menu to return to it.</summary>
        public Action BackRequested;

        /// <summary>True while the menu is open.</summary>
        public bool IsOpen
        {
            get { return _canvas != null && _canvas.activeSelf; }
        }

        private void OnDestroy()
        {
            if (_client != null)
            {
                _client.OnDevices -= HandleDevices;
            }
        }

        private void Update()
        {
            if (!IsOpen)
            {
                return;
            }

            Refresh();
            Keyboard keyboard = Keyboard.current;
            // SoniaOptionsMenu handles Esc; the key that opened it (3 or Enter) doesn't count here.
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
        }

        /// <summary>Opens or closes the menu. On opening, it asks the orchestrator for the microphone list.</summary>
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

                Bind();
                GraphicsQualityMenu.EnsureEventSystem();
                _cursorWasVisible = Cursor.visible;
                Cursor.visible = true;
                _canvas.SetActive(true);
                _openedFrame = Time.frameCount;
                if (_client != null && _client.IsConnected)
                {
                    _client.SendListDevices();
                }

                Refresh();
            }
            else
            {
                _canvas.SetActive(false);
                Cursor.visible = _cursorWasVisible;
            }
        }

        private void Bind()
        {
            if (_client != null)
            {
                return;
            }

            _client = FindAnyObjectByType<SoniaClient>();
            if (_client != null)
            {
                _client.OnDevices += HandleDevices;
            }
        }

        private void HandleDevices(DevicesMessage message)
        {
            _devices = message;
        }

        // ------------------------------------------------------------------
        // Microphone
        // ------------------------------------------------------------------

        /// <summary>Options: the system one ("") and each microphone on the machine.</summary>
        private List<string> MicrophoneOptions()
        {
            var options = new List<string> { string.Empty };
            if (_devices != null && _devices.Microphones != null)
            {
                foreach (MicrophoneInfo mic in _devices.Microphones)
                {
                    if (mic != null && !string.IsNullOrEmpty(mic.Name))
                    {
                        options.Add(mic.Name);
                    }
                }
            }

            return options;
        }

        /// <summary>The option matching what is configured (may be part of the name, as in the .env).</summary>
        private int MicrophoneIndex(List<string> options)
        {
            string chosen = _devices != null ? (_devices.Microphone ?? string.Empty).Trim() : string.Empty;
            if (chosen.Length == 0)
            {
                return 0;
            }

            for (int i = 1; i < options.Count; i++)
            {
                if (options[i].IndexOf(chosen, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return i;
                }
            }

            return -1;
        }

        private string MicrophoneLabel()
        {
            if (_client == null || !_client.IsConnected)
            {
                return "No orchestrator";
            }

            if (_devices == null)
            {
                return "Searching…";
            }

            List<string> options = MicrophoneOptions();
            int index = MicrophoneIndex(options);
            if (index == 0)
            {
                return string.IsNullOrEmpty(_devices.DefaultMicrophone)
                    ? "System default"
                    : "System default (" + _devices.DefaultMicrophone + ")";
            }

            return index > 0 ? options[index] : "\"" + _devices.Microphone + "\" not found: using system default";
        }

        private void StepMicrophone(int direction)
        {
            if (_client == null || _devices == null)
            {
                return;
            }

            List<string> options = MicrophoneOptions();
            int index = Mathf.Max(0, MicrophoneIndex(options));
            index = (index + direction + options.Count) % options.Count;
            _devices.Microphone = options[index];
            _client.SendSetMicrophone(options[index]);
        }

        // ------------------------------------------------------------------
        // Camera
        // ------------------------------------------------------------------

        private static WebCamDevice[] Cameras()
        {
            try
            {
                return WebCamTexture.devices ?? new WebCamDevice[0];
            }
            catch (Exception)
            {
                return new WebCamDevice[0];
            }
        }

        private bool CameraFromOrchestrator()
        {
            return _devices != null && _devices.CameraSource == "opencv";
        }

        private string CameraLabel()
        {
            if (_devices == null)
            {
                return _client == null || !_client.IsConnected ? "No orchestrator" : "Searching…";
            }

            if (!CameraFromOrchestrator())
            {
                return "Set by VISION_SOURCE=" + _devices.CameraSource;
            }

            WebCamDevice[] cameras = Cameras();
            int index = _devices.Camera;
            if (index >= 0 && index < cameras.Length)
            {
                return (index + 1) + ": " + cameras[index].name;
            }

            return "Camera " + (index + 1);
        }

        private void StepCamera(int direction)
        {
            if (_client == null || !CameraFromOrchestrator())
            {
                return;
            }

            int count = Mathf.Max(1, Cameras().Length);
            int index = ((_devices.Camera + direction) % count + count) % count;
            _devices.Camera = index;
            _client.SendSetCamera(index);
        }

        // ------------------------------------------------------------------
        // Display
        // ------------------------------------------------------------------

        private static bool Fullscreen
        {
            get { return Screen.fullScreenMode != FullScreenMode.Windowed; }
        }

        /// <summary>Sizes on offer: windowed, those that fit on the screen.</summary>
        private static List<Vector2Int> SizeOptions()
        {
            Resolution display = Screen.currentResolution;
            var options = new List<Vector2Int>();
            foreach (Vector2Int size in Sizes)
            {
                if (Fullscreen || display.height <= 0 || size.y <= display.height)
                {
                    options.Add(size);
                }
            }

            if (options.Count == 0)
            {
                options.Add(Sizes[0]);
            }

            return options;
        }

        private static string ResolutionLabel()
        {
            return Screen.width + " × " + Screen.height;
        }

        private static void StepResolution(int direction)
        {
            List<Vector2Int> options = SizeOptions();
            int current = 0;
            for (int i = 0; i < options.Count; i++)
            {
                if (options[i].y <= Screen.height)
                {
                    current = i;
                }
            }

            Vector2Int next = options[(current + direction + options.Count) % options.Count];
            Screen.SetResolution(next.x, next.y, Screen.fullScreenMode);
        }

        private static void ToggleFullscreen(int direction)
        {
            Screen.fullScreenMode = Fullscreen ? FullScreenMode.Windowed : FullScreenMode.FullScreenWindow;
        }

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        private void Build()
        {
            _canvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaDeviceSettingsMenu", 2000);

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

            Text title = SoniaUiKit.MakeText(panel.transform, "Title", "Microphone, camera and display", 46, TextAnchor.MiddleLeft);
            title.fontStyle = FontStyle.Bold;
            title.GetComponent<LayoutElement>().preferredHeight = 60f;

            Text hint = SoniaUiKit.MakeText(panel.transform, "Help",
                "By default, the system microphone and camera. What you pick here is saved on this machine and overrides the app configuration.",
                22, TextAnchor.MiddleLeft);
            hint.color = MutedText;
            hint.GetComponent<LayoutElement>().preferredHeight = 64f;

            AddOption(panel.transform, "Microphone", MicrophoneLabel, StepMicrophone);
            AddOption(panel.transform, "Camera", CameraLabel, StepCamera);
            AddOption(panel.transform, "Resolution", ResolutionLabel, StepResolution);
            AddOption(panel.transform, "Display", () => Fullscreen ? "Fullscreen" : "Windowed", ToggleFullscreen);

            _status = SoniaUiKit.MakeText(panel.transform, "Keys",
                "Esc back · ↑↓ pick · ←→ change. Microphone and camera change right away.",
                22, TextAnchor.MiddleLeft);
            _status.color = MutedText;
            _status.GetComponent<LayoutElement>().preferredHeight = 40f;

            GameObject backRow = new GameObject("Back", typeof(RectTransform));
            backRow.transform.SetParent(panel.transform, false);
            backRow.AddComponent<LayoutElement>().preferredHeight = 80f;
            HorizontalLayoutGroup layout = backRow.AddComponent<HorizontalLayoutGroup>();
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = true;
            MakeButton(backRow.transform, "Back", () =>
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
            row.AddComponent<LayoutElement>().preferredHeight = 78f;
            HorizontalLayoutGroup layout = row.AddComponent<HorizontalLayoutGroup>();
            layout.padding = new RectOffset(18, 10, 6, 6);
            layout.spacing = 10f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = false;
            layout.childForceExpandHeight = true;
            row.AddComponent<Button>().onClick.AddListener(() => Select(index));

            Text name = SoniaUiKit.MakeText(row.transform, "Name", label, 28, TextAnchor.MiddleLeft);
            name.GetComponent<LayoutElement>().preferredWidth = 170f;

            Image previous = MakeButton(row.transform, "◄", () => { Select(index); step(-1); });
            previous.GetComponent<LayoutElement>().preferredWidth = 66f;

            Text valueText = SoniaUiKit.MakeText(row.transform, "Value", string.Empty, 24, TextAnchor.MiddleCenter);
            valueText.GetComponent<LayoutElement>().flexibleWidth = 1f;

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
        }
    }
}
