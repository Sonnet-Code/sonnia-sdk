// Minimal helpers to build uGUI panels from code.
//
// Used by the tuning panel (SoniaTuningUI) and the animations panel
// (SoniaAnimationPreviewUI). They are built from code to avoid depending on
// prefabs or on IMGUI, which with the new Input System does not always get the mouse.

using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Factory for uGUI images, texts and buttons, and an overlay canvas.</summary>
    public static class SoniaUiKit
    {
        /// <summary>Screen Space - Overlay canvas scaled to 1080x1920.</summary>
        public static GameObject MakeOverlayCanvas(Transform parent, string name, int sortingOrder)
        {
            GameObject go = new GameObject(name);
            go.transform.SetParent(parent, false);
            Canvas canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = sortingOrder;
            CanvasScaler scaler = go.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;
            go.AddComponent<GraphicRaycaster>();
            return go;
        }

        /// <summary>Small button anchored top right, shifted <paramref name="slot"/> positions down.</summary>
        public static GameObject MakeCornerButton(Transform parent, string label, int slot, UnityEngine.Events.UnityAction action)
        {
            GameObject go = MakeImage(parent, label, new Color(0.2f, 0.35f, 0.7f, 0.85f));
            RectTransform rect = go.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(1f, 1f);
            rect.anchorMax = new Vector2(1f, 1f);
            rect.pivot = new Vector2(1f, 1f);
            rect.anchoredPosition = new Vector2(-20f, -20f - slot * 66f);
            rect.sizeDelta = new Vector2(170f, 56f);
            Button button = go.AddComponent<Button>();
            button.onClick.AddListener(action);
            Text text = MakeText(go.transform, "Text", label, 22, TextAnchor.MiddleCenter);
            Stretch(text.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
            return go;
        }

        public static void Stretch(RectTransform rect, Vector2 min, Vector2 max)
        {
            rect.anchorMin = min;
            rect.anchorMax = max;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
        }

        public static GameObject MakeImage(Transform parent, string name, Color color)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            Image image = go.AddComponent<Image>();
            image.color = color;
            return go;
        }

        public static Text MakeText(Transform parent, string name, string content, int size, TextAnchor anchor)
        {
            GameObject go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            Text text = go.AddComponent<Text>();
            text.text = content;
            text.fontSize = size;
            text.alignment = anchor;
            text.color = Color.white;
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            go.AddComponent<LayoutElement>();
            return text;
        }

        public static void MakeButton(Transform parent, string label, UnityEngine.Events.UnityAction action)
        {
            GameObject go = MakeImage(parent, label, new Color(0.2f, 0.35f, 0.7f, 1f));
            Button button = go.AddComponent<Button>();
            button.onClick.AddListener(action);
            Text text = MakeText(go.transform, "Text", label, 22, TextAnchor.MiddleCenter);
            Stretch(text.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
        }

    }
}
