// Options menu: Esc in the Sonnia window opens and closes it.
//
// From here you go to graphics quality (GraphicsQualityMenu, which returns to
// this menu with Esc), to microphone, camera and display (StandSettingsMenu)
// and to the stage particles (ParticleSettingsMenu).
// It works with the mouse or with the keyboard alone (↑↓ picks, Enter opens,
// 1-3 shortcuts), in case there is no mouse.
// At the top right it shows the app version (Application.version), to
// know which build each machine has.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Options menu opened with Esc.</summary>
    [DisallowMultipleComponent]
    public class SoniaOptionsMenu : MonoBehaviour
    {
        private static readonly Color PanelColor = new Color(0.02f, 0.03f, 0.08f, 0.94f);
        private static readonly Color ItemColor = new Color(0.16f, 0.22f, 0.40f, 1f);
        private static readonly Color SelectedColor = new Color(0.30f, 0.36f, 0.83f, 1f);
        private static readonly Color MutedText = new Color(0.72f, 0.77f, 0.88f, 1f);

        private GraphicsQualityMenu _graphics;
        private StandSettingsMenu _stand;
        private ParticleSettingsMenu _particles;
        private GameObject _canvas;
        private readonly List<Image> _items = new List<Image>();
        private readonly List<UnityAction> _actions = new List<UnityAction>();
        private int _selected;
        private bool _cursorWasVisible;

        /// <summary>True while the menu is open.</summary>
        public bool IsOpen
        {
            get { return _canvas != null && _canvas.activeSelf; }
        }

        private void Start()
        {
            _graphics = GetComponent<GraphicsQualityMenu>();
            if (_graphics != null)
            {
                _graphics.BackRequested = () => SetOpen(true);
            }

            _stand = GetComponent<StandSettingsMenu>();
            if (_stand == null)
            {
                _stand = gameObject.AddComponent<StandSettingsMenu>();
            }

            _stand.BackRequested = () => SetOpen(true);

            _particles = GetComponent<ParticleSettingsMenu>();
            if (_particles == null)
            {
                _particles = gameObject.AddComponent<ParticleSettingsMenu>();
            }

            _particles.BackRequested = () => SetOpen(true);
        }

        private void Update()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard == null)
            {
                return;
            }

            if (keyboard.escapeKey.wasPressedThisFrame)
            {
                if (_graphics != null && _graphics.IsOpen)
                {
                    _graphics.SetOpen(false);
                    SetOpen(true);
                }
                else if (_stand != null && _stand.IsOpen)
                {
                    _stand.SetOpen(false);
                    SetOpen(true);
                }
                else if (_particles != null && _particles.IsOpen)
                {
                    _particles.SetOpen(false);
                    SetOpen(true);
                }
                else
                {
                    SetOpen(!IsOpen);
                }

                return;
            }

            if (!IsOpen)
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
            else if (keyboard.enterKey.wasPressedThisFrame || keyboard.numpadEnterKey.wasPressedThisFrame
                                                           || keyboard.spaceKey.wasPressedThisFrame)
            {
                _actions[_selected]();
            }
            else if (keyboard.digit1Key.wasPressedThisFrame || keyboard.numpad1Key.wasPressedThisFrame)
            {
                _actions[0]();
            }
            else if (keyboard.digit2Key.wasPressedThisFrame || keyboard.numpad2Key.wasPressedThisFrame)
            {
                _actions[1]();
            }
            else if (keyboard.digit3Key.wasPressedThisFrame || keyboard.numpad3Key.wasPressedThisFrame)
            {
                _actions[2]();
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

                GraphicsQualityMenu.EnsureEventSystem();
                _cursorWasVisible = Cursor.visible;
                Cursor.visible = true;
                _canvas.SetActive(true);
                Select(0);
            }
            else
            {
                _canvas.SetActive(false);
                Cursor.visible = _cursorWasVisible;
            }
        }

        private void OpenGraphics()
        {
            SetOpen(false);
            if (_graphics != null)
            {
                _graphics.SetOpen(true);
            }
        }

        private void OpenDeviceSettings()
        {
            SetOpen(false);
            if (_stand != null)
            {
                _stand.SetOpen(true);
            }
        }

        private void OpenParticles()
        {
            SetOpen(false);
            if (_particles != null)
            {
                _particles.SetOpen(true);
            }
        }

        // ------------------------------------------------------------------
        // Build
        // ------------------------------------------------------------------

        private void Build()
        {
            _canvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaOptionsMenu", 2000);

            // Backdrop that darkens and swallows clicks meant for what is below.
            GameObject dim = SoniaUiKit.MakeImage(_canvas.transform, "Backdrop", new Color(0f, 0f, 0f, 0.5f));
            SoniaUiKit.Stretch(dim.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);

            GameObject panel = SoniaUiKit.MakeImage(_canvas.transform, "Panel", PanelColor);
            RectTransform panelRect = panel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.5f, 0.5f);
            panelRect.anchorMax = new Vector2(0.5f, 0.5f);
            panelRect.pivot = new Vector2(0.5f, 0.5f);
            panelRect.sizeDelta = new Vector2(820f, 0f);
            VerticalLayoutGroup column = panel.AddComponent<VerticalLayoutGroup>();
            column.padding = new RectOffset(40, 40, 36, 36);
            column.spacing = 18f;
            column.childControlWidth = true;
            column.childControlHeight = true;
            column.childForceExpandWidth = true;
            column.childForceExpandHeight = false;
            panel.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            Text title = SoniaUiKit.MakeText(panel.transform, "Title", "Options", 46, TextAnchor.MiddleLeft);
            title.fontStyle = FontStyle.Bold;
            title.GetComponent<LayoutElement>().preferredHeight = 64f;

            // The version, level with the title and outside the column.
            Text version = SoniaUiKit.MakeText(panel.transform, "Version", VersionLabel(), 26, TextAnchor.MiddleRight);
            version.color = MutedText;
            version.GetComponent<LayoutElement>().ignoreLayout = true;
            RectTransform versionRect = version.rectTransform;
            versionRect.anchorMin = new Vector2(1f, 1f);
            versionRect.anchorMax = new Vector2(1f, 1f);
            versionRect.pivot = new Vector2(1f, 1f);
            versionRect.sizeDelta = new Vector2(420f, 64f);
            versionRect.anchoredPosition = new Vector2(-40f, -36f);

            AddItem(panel.transform, "Graphics quality",
                "Resolution, shadows, effects and frames per second on this machine.", OpenGraphics);
            AddItem(panel.transform, "Microphone, camera and display",
                "Which microphone and camera this machine uses, the resolution, and windowed or fullscreen.", OpenDeviceSettings);
            AddItem(panel.transform, "Particles",
                "Amount, speed, size and brightness of the particles, and the trivia and web-search effects.",
                OpenParticles);
            AddItem(panel.transform, "Close", null, () => SetOpen(false));

            Text keys = SoniaUiKit.MakeText(panel.transform, "Keys",
                "Esc close · ↑↓ pick · Enter open · 1 quality · 2 mic, camera and display · 3 particles",
                22, TextAnchor.MiddleLeft);
            keys.color = MutedText;
            keys.GetComponent<LayoutElement>().preferredHeight = 64f;

            _canvas.SetActive(false);
        }

        /// <summary>"Version 1.0.179"; in the editor, with "(editor)" after it, because it isn't any build's.</summary>
        private static string VersionLabel()
        {
            return "Version " + Application.version + (Application.isEditor ? " (editor)" : string.Empty);
        }

        private void AddItem(Transform parent, string label, string description, UnityAction action)
        {
            int index = _items.Count;
            GameObject item = SoniaUiKit.MakeImage(parent, label, ItemColor);
            item.AddComponent<LayoutElement>().preferredHeight = description == null ? 84f : 124f;
            VerticalLayoutGroup layout = item.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(28, 28, 14, 14);
            layout.spacing = 4f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = true;
            item.AddComponent<Button>().onClick.AddListener(() =>
            {
                Select(index);
                action();
            });

            Text name = SoniaUiKit.MakeText(item.transform, "Name", label, 34, TextAnchor.MiddleLeft);
            name.fontStyle = FontStyle.Bold;
            if (description != null)
            {
                Text detail = SoniaUiKit.MakeText(item.transform, "Detail", description, 22, TextAnchor.UpperLeft);
                detail.color = MutedText;
            }

            _items.Add(item.GetComponent<Image>());
            _actions.Add(action);
        }

        private void Select(int index)
        {
            if (_items.Count == 0)
            {
                return;
            }

            _selected = (index % _items.Count + _items.Count) % _items.Count;
            for (int i = 0; i < _items.Count; i++)
            {
                _items[i].color = i == _selected ? SelectedColor : ItemColor;
            }
        }
    }
}
