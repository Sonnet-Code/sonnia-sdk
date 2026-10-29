// Runtime tuning panel ("Settings" button at the top right, or F2).
//
// To find gaze, head and expression settings that look natural you have to
// tweak values while the avatar talks and moves, not in the inspector with the
// game stopped. This panel lists sliders for the [Range] fields of
// EyeGazeController, AvatarStateController, FacialExpressionController and
// LipSyncController (and a few more by name), and saves the values to a JSON
// in Application.persistentDataPath, which is applied again at startup.
// "Print" writes the values to the console so they can be copied into the scene.
//
// It is built with uGUI from code (own Canvas, Screen Space - Overlay) to avoid
// depending on IMGUI, which with the new Input System does not always get the mouse.

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Panel with sliders to tune facial and gaze animation live.</summary>
    [DisallowMultipleComponent]
    public class SoniaTuningUI : MonoBehaviour
    {
        [Serializable]
        private class Entry
        {
            public string component;
            public string field;
            public float value;
        }

        [Serializable]
        private class SaveFile
        {
            public List<Entry> entries = new List<Entry>();
        }

        private sealed class Binding
        {
            public Component Target;
            public FieldInfo Field;
            public float Min;
            public float Max;
            public Slider Slider;
            public Text Label;
            public float Default;
        }

        [SerializeField]
        [Tooltip("Apply the values saved on disk at startup.")]
        private bool loadOnStart = true;

        [SerializeField]
        [Tooltip("Name of the values file inside Application.persistentDataPath.")]
        private string fileName = "sonia-tuning.json";

        // Private fields that are also worth exposing, per component.
        private static readonly Dictionary<Type, string[]> ExtraFields = new Dictionary<Type, string[]>
        {
            {
                typeof(EyeGazeController),
                new[]
                {
                    "gazeGain", "convergenceDegrees", "yawLimit", "pitchLimit", "minFocusDistance", "excursionLimit", "wideShotLiveliness",
                    "speed", "jitterDegrees", "saccadeInterval", "saccadeAmplitude"
                }
            },
            {
                typeof(AvatarStateController),
                new[]
                {
                    "headFollow", "speakingHeadFollow", "wideShotLookWeight", "maxLookAngle", "lookSmoothing", "headSwayDegrees",
                    "blinkEvery", "blinkSeconds", "listenNodEvery"
                }
            },
            {
                typeof(FacialExpressionController),
                new[] { "microInterval" }
            }
        };

        // [NonSerialized] on purpose: Unity keeps private fields across the domain
        // reload after recompiling in Play, but the slider bindings (reflection,
        // listeners) do not survive. When these references are lost, Update
        // rebuilds the whole panel.
        private readonly List<Binding> _bindings = new List<Binding>();

        [NonSerialized]
        private GameObject _canvas;

        [NonSerialized]
        private GameObject _toggleCanvas;

        [NonSerialized]
        private bool _built;

        private string SavePath
        {
            get { return Path.Combine(Application.persistentDataPath, fileName); }
        }

        private void Start()
        {
            if (loadOnStart)
            {
                Load();
            }

            // In normal operation there are no buttons on screen: the saved
            // values are applied anyway, but the panel is not offered.
            if (!SoniaDevMode.Enabled)
            {
                return;
            }

            BuildToggleButton();
        }

        /// <summary>Small, always visible button to open the panel without a keyboard.</summary>
        private void BuildToggleButton()
        {
            DestroyStale("SoniaTuningToggle");
            _toggleCanvas = new GameObject("SoniaTuningToggle");
            _toggleCanvas.transform.SetParent(transform, false);
            Canvas canvas = _toggleCanvas.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 499;
            CanvasScaler scaler = _toggleCanvas.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;
            _toggleCanvas.AddComponent<GraphicRaycaster>();

            GameObject go = SoniaUiKit.MakeImage(_toggleCanvas.transform, "Settings", new Color(0.2f, 0.35f, 0.7f, 0.85f));
            RectTransform rect = go.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(1f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(1f, 1f);
            rect.anchoredPosition = new Vector2(-20f, -20f);
            rect.sizeDelta = new Vector2(150f, 56f);
            Button button = go.AddComponent<Button>();
            button.onClick.AddListener(Toggle);
            Text text = SoniaUiKit.MakeText(go.transform, "Text", "Settings", 22, TextAnchor.MiddleCenter);
            SoniaUiKit.Stretch(text.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
        }

        private void Update()
        {
            if (!SoniaDevMode.Enabled)
            {
                return;
            }

            // After a recompile in Play, objects created from code survive but this
            // component loses its references and the buttons their listeners:
            // everything is rebuilt.
            if (_toggleCanvas == null)
            {
                bool wasOpen = false;
                for (int i = 0; i < transform.childCount; i++)
                {
                    Transform child = transform.GetChild(i);
                    if (child.name == "SoniaTuning" && child.gameObject.activeSelf)
                    {
                        wasOpen = true;
                    }
                }

                DestroyStale("SoniaTuningToggle");
                DestroyStale("SoniaTuning");
                _built = false;
                _canvas = null;
                BuildToggleButton();
                if (wasOpen)
                {
                    Toggle();
                }
            }

            Keyboard keyboard = Keyboard.current;
            if (keyboard != null && keyboard.f2Key.wasPressedThisFrame)
            {
                Toggle();
            }
        }

        private void DestroyStale(string childName)
        {
            for (int i = transform.childCount - 1; i >= 0; i--)
            {
                Transform child = transform.GetChild(i);
                if (child.name == childName)
                {
                    Destroy(child.gameObject);
                }
            }
        }

        /// <summary>Shows or hides the panel.</summary>
        public void Toggle()
        {
            if (!_built)
            {
                Build();
            }

            _canvas.SetActive(!_canvas.activeSelf);
            if (_canvas.activeSelf)
            {
                RefreshSliders();
            }
        }

        // ------------------------------------------------------------------
        // Construction
        // ------------------------------------------------------------------

        private void Build()
        {
            DestroyStale("SoniaTuning");
            _built = true;
            _canvas = new GameObject("SoniaTuning");
            _canvas.transform.SetParent(transform, false);
            Canvas canvas = _canvas.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 500;
            CanvasScaler scaler = _canvas.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;
            _canvas.AddComponent<GraphicRaycaster>();

            GameObject panel = SoniaUiKit.MakeImage(_canvas.transform, "Panel", new Color(0.02f, 0.03f, 0.08f, 0.92f));
            RectTransform panelRect = panel.GetComponent<RectTransform>();
            // Lower half of the screen: the face stays visible while tuning.
            panelRect.anchorMin = new Vector2(0.03f, 0.07f);
            panelRect.anchorMax = new Vector2(0.97f, 0.55f);
            panelRect.offsetMin = Vector2.zero;
            panelRect.offsetMax = Vector2.zero;

            Text title = SoniaUiKit.MakeText(panel.transform, "Title", "Sonnia settings. Save writes " + fileName + " to " + Application.persistentDataPath + " and it is applied at startup; Print sends them to the console.", 18, TextAnchor.UpperLeft);
            RectTransform titleRect = title.GetComponent<RectTransform>();
            titleRect.anchorMin = new Vector2(0f, 1f);
            titleRect.anchorMax = new Vector2(1f, 1f);
            titleRect.pivot = new Vector2(0.5f, 1f);
            titleRect.anchoredPosition = new Vector2(0f, -10f);
            titleRect.sizeDelta = new Vector2(-30f, 60f);

            // Buttons
            GameObject buttons = new GameObject("Buttons", typeof(RectTransform));
            buttons.transform.SetParent(panel.transform, false);
            RectTransform buttonsRect = buttons.GetComponent<RectTransform>();
            buttonsRect.anchorMin = new Vector2(0f, 1f);
            buttonsRect.anchorMax = new Vector2(1f, 1f);
            buttonsRect.pivot = new Vector2(0.5f, 1f);
            buttonsRect.anchoredPosition = new Vector2(0f, -72f);
            buttonsRect.sizeDelta = new Vector2(-30f, 52f);
            HorizontalLayoutGroup row = buttons.AddComponent<HorizontalLayoutGroup>();
            row.spacing = 12f;
            row.childForceExpandWidth = true;
            row.childForceExpandHeight = true;
            SoniaUiKit.MakeButton(buttons.transform, "Save", Save);
            SoniaUiKit.MakeButton(buttons.transform, "Load", Load);
            SoniaUiKit.MakeButton(buttons.transform, "Reset", ResetDefaults);
            SoniaUiKit.MakeButton(buttons.transform, "Print", Print);

            // Scrolling list
            GameObject scrollGo = new GameObject("Scroll", typeof(RectTransform));
            scrollGo.transform.SetParent(panel.transform, false);
            RectTransform scrollRect = scrollGo.GetComponent<RectTransform>();
            scrollRect.anchorMin = new Vector2(0f, 0f);
            scrollRect.anchorMax = new Vector2(1f, 1f);
            scrollRect.offsetMin = new Vector2(15f, 15f);
            scrollRect.offsetMax = new Vector2(-15f, -135f);
            ScrollRect scroll = scrollGo.AddComponent<ScrollRect>();
            scroll.horizontal = false;
            scroll.scrollSensitivity = 40f;
            Image mask = scrollGo.AddComponent<Image>();
            mask.color = new Color(0f, 0f, 0f, 0.15f);
            scrollGo.AddComponent<Mask>().showMaskGraphic = true;

            GameObject content = new GameObject("Content", typeof(RectTransform));
            content.transform.SetParent(scrollGo.transform, false);
            RectTransform contentRect = content.GetComponent<RectTransform>();
            contentRect.anchorMin = new Vector2(0f, 1f);
            contentRect.anchorMax = new Vector2(1f, 1f);
            contentRect.pivot = new Vector2(0.5f, 1f);
            contentRect.anchoredPosition = Vector2.zero;
            contentRect.sizeDelta = Vector2.zero; // otherwise it starts 100 px wider than the window and clips the texts
            VerticalLayoutGroup column = content.AddComponent<VerticalLayoutGroup>();
            column.spacing = 4f;
            column.padding = new RectOffset(8, 8, 8, 8);
            column.childForceExpandWidth = true;
            column.childForceExpandHeight = false;
            column.childControlHeight = true;
            column.childControlWidth = true;
            content.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            scroll.content = contentRect;
            scroll.viewport = scrollRect;

            _bindings.Clear();
            AddComponentSection<EyeGazeController>(content.transform, "Eyes");
            AddComponentSection<AvatarStateController>(content.transform, "Head and blinking");
            AddComponentSection<FacialExpressionController>(content.transform, "Expressions");
            AddComponentSection<LipSyncController>(content.transform, "Mouth");

            // Starts closed: the first Toggle opens it.
            _canvas.SetActive(false);
        }

        private void AddComponentSection<T>(Transform parent, string title) where T : Component
        {
            T target = GetComponentInChildren<T>(true);
            if (target == null)
            {
                return;
            }

            Text header = SoniaUiKit.MakeText(parent, "Section", title, 24, TextAnchor.MiddleLeft);
            header.fontStyle = FontStyle.Bold;
            header.GetComponent<LayoutElement>().preferredHeight = 44f;

            HashSet<string> wanted = new HashSet<string>();
            string[] extra;
            if (ExtraFields.TryGetValue(typeof(T), out extra))
            {
                for (int i = 0; i < extra.Length; i++)
                {
                    wanted.Add(extra[i]);
                }
            }

            FieldInfo[] fields = typeof(T).GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            for (int i = 0; i < fields.Length; i++)
            {
                FieldInfo field = fields[i];
                bool listed = wanted.Contains(field.Name);
                RangeAttribute range = field.GetCustomAttribute<RangeAttribute>();
                bool serialized = field.IsPublic || field.GetCustomAttribute<SerializeField>() != null;
                if (!serialized || (!listed && range == null))
                {
                    continue;
                }

                if (field.FieldType == typeof(float))
                {
                    float min = range != null ? range.min : 0f;
                    float max = range != null ? range.max : GuessMax((float)field.GetValue(target));
                    AddSlider(parent, target, field, -1, min, max);
                }
                else if (field.FieldType == typeof(Vector2))
                {
                    Vector2 v = (Vector2)field.GetValue(target);
                    float max = GuessMax(Mathf.Max(v.x, v.y));
                    AddSlider(parent, target, field, 0, 0f, max);
                    AddSlider(parent, target, field, 1, 0f, max);
                }
            }
        }

        private static float GuessMax(float current)
        {
            float magnitude = Mathf.Abs(current);
            if (magnitude <= 1f) return 1f;
            if (magnitude <= 10f) return 20f;
            if (magnitude <= 60f) return 100f;
            return magnitude * 3f;
        }

        private void AddSlider(Transform parent, Component target, FieldInfo field, int axis, float min, float max)
        {
            GameObject row = new GameObject(field.Name, typeof(RectTransform));
            row.transform.SetParent(parent, false);
            row.AddComponent<LayoutElement>().preferredHeight = 46f;
            HorizontalLayoutGroup layout = row.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = 10f;
            layout.childForceExpandHeight = true;
            layout.childForceExpandWidth = false;
            layout.childControlWidth = true;
            layout.childControlHeight = true;

            string suffix = axis == 0 ? " (min)" : axis == 1 ? " (max)" : "";
            Text label = SoniaUiKit.MakeText(row.transform, "Label", field.Name + suffix, 20, TextAnchor.MiddleLeft);
            label.horizontalOverflow = HorizontalWrapMode.Overflow;
            LayoutElement labelLayout = label.GetComponent<LayoutElement>();
            labelLayout.preferredWidth = 360f;
            labelLayout.minWidth = 360f;

            GameObject sliderGo = new GameObject("Slider", typeof(RectTransform));
            sliderGo.transform.SetParent(row.transform, false);
            sliderGo.AddComponent<LayoutElement>().flexibleWidth = 1f;
            Slider slider = sliderGo.AddComponent<Slider>();
            GameObject bg = SoniaUiKit.MakeImage(sliderGo.transform, "Background", new Color(1f, 1f, 1f, 0.15f));
            SoniaUiKit.Stretch(bg.GetComponent<RectTransform>(), new Vector2(0f, 0.35f), new Vector2(1f, 0.65f));
            GameObject fillArea = new GameObject("FillArea", typeof(RectTransform));
            fillArea.transform.SetParent(sliderGo.transform, false);
            SoniaUiKit.Stretch(fillArea.GetComponent<RectTransform>(), new Vector2(0f, 0.35f), new Vector2(1f, 0.65f));
            GameObject fill = SoniaUiKit.MakeImage(fillArea.transform, "Fill", new Color(0.35f, 0.6f, 1f, 0.9f));
            SoniaUiKit.Stretch(fill.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
            GameObject handleArea = new GameObject("HandleArea", typeof(RectTransform));
            handleArea.transform.SetParent(sliderGo.transform, false);
            SoniaUiKit.Stretch(handleArea.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
            GameObject handle = SoniaUiKit.MakeImage(handleArea.transform, "Handle", Color.white);
            RectTransform handleRect = handle.GetComponent<RectTransform>();
            handleRect.sizeDelta = new Vector2(28f, 0f);
            slider.fillRect = fill.GetComponent<RectTransform>();
            slider.handleRect = handleRect;
            slider.targetGraphic = handle.GetComponent<Image>();
            slider.direction = Slider.Direction.LeftToRight;
            slider.minValue = min;
            slider.maxValue = max;

            Text value = SoniaUiKit.MakeText(row.transform, "Value", "", 20, TextAnchor.MiddleRight);
            LayoutElement valueLayout = value.GetComponent<LayoutElement>();
            valueLayout.preferredWidth = 90f;
            valueLayout.minWidth = 90f;

            Binding binding = new Binding
            {
                Target = target, Field = field, Min = min, Max = max, Slider = slider, Label = value,
                Default = ReadValue(target, field, axis)
            };
            int capturedAxis = axis;
            slider.onValueChanged.AddListener(v =>
            {
                WriteValue(target, field, capturedAxis, v);
                value.text = v.ToString("F2");
            });
            binding.Slider.name = field.Name + ":" + axis;
            _bindings.Add(binding);
        }

        // ------------------------------------------------------------------
        // Values
        // ------------------------------------------------------------------

        private static float ReadValue(Component target, FieldInfo field, int axis)
        {
            object raw = field.GetValue(target);
            if (raw is Vector2)
            {
                Vector2 v = (Vector2)raw;
                return axis == 0 ? v.x : v.y;
            }

            return raw is float ? (float)raw : 0f;
        }

        private static void WriteValue(Component target, FieldInfo field, int axis, float value)
        {
            if (field.FieldType == typeof(Vector2))
            {
                Vector2 v = (Vector2)field.GetValue(target);
                if (axis == 0) v.x = value; else v.y = value;
                field.SetValue(target, v);
            }
            else
            {
                field.SetValue(target, value);
            }
        }

        private void RefreshSliders()
        {
            for (int i = 0; i < _bindings.Count; i++)
            {
                Binding b = _bindings[i];
                int axis = b.Slider.name.EndsWith(":0") ? 0 : b.Slider.name.EndsWith(":1") ? 1 : -1;
                float v = ReadValue(b.Target, b.Field, axis);
                b.Slider.SetValueWithoutNotify(Mathf.Clamp(v, b.Min, b.Max));
                b.Label.text = v.ToString("F2");
            }
        }

        private string KeyOf(Binding b)
        {
            return b.Target.GetType().Name + "." + b.Field.Name + (b.Slider.name.EndsWith(":0") ? ".x" : b.Slider.name.EndsWith(":1") ? ".y" : "");
        }

        /// <summary>Saves the current values to disk.</summary>
        public void Save()
        {
            if (!_built)
            {
                Build();
            }

            SaveFile file = new SaveFile();
            for (int i = 0; i < _bindings.Count; i++)
            {
                Binding b = _bindings[i];
                int axis = b.Slider.name.EndsWith(":0") ? 0 : b.Slider.name.EndsWith(":1") ? 1 : -1;
                file.entries.Add(new Entry { component = b.Target.GetType().Name, field = b.Field.Name + (axis == 0 ? ".x" : axis == 1 ? ".y" : ""), value = ReadValue(b.Target, b.Field, axis) });
            }

            File.WriteAllText(SavePath, JsonUtility.ToJson(file, true));
            Debug.Log("[Sonnia] Settings saved to " + SavePath);
        }

        /// <summary>Applies the values saved on disk, if any.</summary>
        public void Load()
        {
            if (!File.Exists(SavePath))
            {
                return;
            }

            SaveFile file;
            try
            {
                file = JsonUtility.FromJson<SaveFile>(File.ReadAllText(SavePath));
            }
            catch (Exception)
            {
                return;
            }

            if (file == null || file.entries == null)
            {
                return;
            }

            Component[] all = GetComponentsInChildren<Component>(true);
            for (int i = 0; i < file.entries.Count; i++)
            {
                Entry entry = file.entries[i];
                string fieldName = entry.field;
                int axis = -1;
                if (fieldName.EndsWith(".x")) { axis = 0; fieldName = fieldName.Substring(0, fieldName.Length - 2); }
                else if (fieldName.EndsWith(".y")) { axis = 1; fieldName = fieldName.Substring(0, fieldName.Length - 2); }

                for (int c = 0; c < all.Length; c++)
                {
                    if (all[c] == null || all[c].GetType().Name != entry.component)
                    {
                        continue;
                    }

                    FieldInfo field = all[c].GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    if (field != null)
                    {
                        WriteValue(all[c], field, axis, entry.value);
                    }
                }
            }

            if (_built)
            {
                RefreshSliders();
            }

            Debug.Log("[Sonnia] Settings loaded from " + SavePath);
        }

        /// <summary>Goes back to the values the scene had at startup and deletes the file.</summary>
        public void ResetDefaults()
        {
            for (int i = 0; i < _bindings.Count; i++)
            {
                Binding b = _bindings[i];
                int axis = b.Slider.name.EndsWith(":0") ? 0 : b.Slider.name.EndsWith(":1") ? 1 : -1;
                WriteValue(b.Target, b.Field, axis, b.Default);
            }

            if (File.Exists(SavePath))
            {
                File.Delete(SavePath);
            }

            RefreshSliders();
        }

        /// <summary>Writes the current values to the console.</summary>
        public void Print()
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder("[Sonnia] Current settings:\n");
            for (int i = 0; i < _bindings.Count; i++)
            {
                Binding b = _bindings[i];
                int axis = b.Slider.name.EndsWith(":0") ? 0 : b.Slider.name.EndsWith(":1") ? 1 : -1;
                sb.Append(KeyOf(b)).Append(" = ").Append(ReadValue(b.Target, b.Field, axis).ToString("F3")).Append('\n');
            }

            Debug.Log(sb.ToString());
        }
    }
}
