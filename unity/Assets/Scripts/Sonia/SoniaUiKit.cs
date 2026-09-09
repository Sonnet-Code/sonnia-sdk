// Utilidades mínimas para construir paneles uGUI por código.
//
// Las usan el panel de ajuste (SoniaTuningUI) y el de animaciones
// (SoniaAnimationPreviewUI). Se construyen por código para no depender de
// prefabs ni de IMGUI, que con el Input System nuevo no siempre recibe el ratón.

using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Fábrica de imágenes, textos y botones uGUI, y un canvas superpuesto.</summary>
    public static class SoniaUiKit
    {
        /// <summary>Canvas Screen Space - Overlay escalado a 1080x1920.</summary>
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

        /// <summary>Botón pequeño anclado arriba a la derecha, desplazado <paramref name="slot"/> posiciones hacia abajo.</summary>
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
            Text text = MakeText(go.transform, "Texto", label, 22, TextAnchor.MiddleCenter);
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
            Text text = MakeText(go.transform, "Texto", label, 22, TextAnchor.MiddleCenter);
            Stretch(text.GetComponent<RectTransform>(), Vector2.zero, Vector2.one);
        }

    }
}
