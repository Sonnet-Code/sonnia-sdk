// Menú de opciones: Esc en la ventana de Sonia lo abre y lo cierra.
//
// Desde aquí se va a la calidad gráfica (GraphicsQualityMenu, que con Esc vuelve
// a este menú), al editor de personaje de Sonia (AvatarEditorLauncher; el de
// Jean solo se abre desde el panel), a micrófono, cámara y pantalla
// (StandSettingsMenu) y a las partículas del escenario (ParticleSettingsMenu).
// Se maneja con el ratón o solo con el teclado (↑↓ elige, Intro abre, 1-4
// atajos), por si en el stand no hay ratón.
// Con el editor de personaje en pantalla, Esc no hace nada: el editor tiene sus
// propios botones de guardar y salir.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Menú de opciones que se abre con Esc.</summary>
    [DisallowMultipleComponent]
    public class SoniaOptionsMenu : MonoBehaviour
    {
        private static readonly Color PanelColor = new Color(0.02f, 0.03f, 0.08f, 0.94f);
        private static readonly Color ItemColor = new Color(0.16f, 0.22f, 0.40f, 1f);
        private static readonly Color SelectedColor = new Color(0.01f, 0.44f, 0.96f, 1f);
        private static readonly Color MutedText = new Color(0.72f, 0.77f, 0.88f, 1f);

        private GraphicsQualityMenu _graphics;
        private StandSettingsMenu _stand;
        private ParticleSettingsMenu _particles;
        private GameObject _canvas;
        private readonly List<Image> _items = new List<Image>();
        private readonly List<UnityAction> _actions = new List<UnityAction>();
        private int _selected;
        private bool _cursorWasVisible;

        /// <summary>Cierto mientras el menú está abierto.</summary>
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

            if (AvatarEditorSession.IsOpen)
            {
                SetOpen(false);
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
            else if (keyboard.digit4Key.wasPressedThisFrame || keyboard.numpad4Key.wasPressedThisFrame)
            {
                _actions[3]();
            }
        }

        /// <summary>Abre o cierra el menú.</summary>
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

        private void OpenStandSettings()
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

        private void OpenSoniaEditor()
        {
            AvatarEditorLauncher launcher = FindAnyObjectByType<AvatarEditorLauncher>();
            if (launcher == null)
            {
                Debug.LogWarning("[Sonia] No hay AvatarEditorLauncher en la escena: no se puede editar a Sonia.", this);
                return;
            }

            SetOpen(false);
            launcher.Open(AvatarRole.Sonia);
        }

        // ------------------------------------------------------------------
        // Construcción
        // ------------------------------------------------------------------

        private void Build()
        {
            _canvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaOptionsMenu", 2000);

            // Fondo que oscurece y se come los clics a lo de debajo.
            GameObject dim = SoniaUiKit.MakeImage(_canvas.transform, "Fondo", new Color(0f, 0f, 0f, 0.5f));
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

            Text title = SoniaUiKit.MakeText(panel.transform, "Titulo", "Opciones", 46, TextAnchor.MiddleLeft);
            title.fontStyle = FontStyle.Bold;
            title.GetComponent<LayoutElement>().preferredHeight = 64f;

            AddItem(panel.transform, "Calidad gráfica",
                "Resolución, sombras, efectos y fotogramas por segundo de este equipo.", OpenGraphics);
            AddItem(panel.transform, "Editar a Sonnia",
                "Abre el editor de personaje. Al guardar, el nuevo aspecto llega a todas las Sonnias.", OpenSoniaEditor);
            AddItem(panel.transform, "Micrófono, cámara y pantalla",
                "Qué micrófono y qué cámara usa este equipo, la resolución y ventana o pantalla completa.", OpenStandSettings);
            AddItem(panel.transform, "Partículas",
                "Cantidad, velocidad, tamaño y brillo de las partículas, y los efectos de la trivia y de cuando Sonnia busca en internet.",
                OpenParticles);
            AddItem(panel.transform, "Cerrar", null, () => SetOpen(false));

            Text keys = SoniaUiKit.MakeText(panel.transform, "Teclas",
                "Esc cierra · ↑↓ elige · Intro abre · 1 calidad · 2 editar a Sonnia · 3 micro, cámara y pantalla · 4 partículas",
                22, TextAnchor.MiddleLeft);
            keys.color = MutedText;
            keys.GetComponent<LayoutElement>().preferredHeight = 64f;

            _canvas.SetActive(false);
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

            Text name = SoniaUiKit.MakeText(item.transform, "Nombre", label, 34, TextAnchor.MiddleLeft);
            name.fontStyle = FontStyle.Bold;
            if (description != null)
            {
                Text detail = SoniaUiKit.MakeText(item.transform, "Detalle", description, 22, TextAnchor.UpperLeft);
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
