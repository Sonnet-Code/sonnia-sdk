// Panel de animaciones (botón "Animaciones" arriba a la derecha).
//
// Lista todos los clips del set por categoría y los reproduce al pulsar, más
// botones para forzar el estado (idle, escuchar, pensar, hablar) sin necesidad
// del orquestador. Sirve para revisar cada clip en la escena real y decidir
// cuáles se quedan.

using System;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Botones para reproducir cualquier clip del set y forzar estados.</summary>
    [DisallowMultipleComponent]
    public class SoniaAnimationPreviewUI : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Coreógrafo del avatar. Si está vacío se busca en este objeto.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Estado del avatar (para forzar estados desde el panel).")]
        private AvatarStateController stateController;

        [NonSerialized]
        private GameObject _canvas;

        [NonSerialized]
        private GameObject _toggleCanvas;

        private void Awake()
        {
            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (stateController == null)
            {
                stateController = GetComponentInChildren<AvatarStateController>(true);
            }
        }

        private void Update()
        {
            if (!SoniaDevMode.Enabled)
            {
                return;
            }

            if (_toggleCanvas == null)
            {
                DestroyStale("SoniaAnimToggle");
                DestroyStale("SoniaAnim");
                _canvas = null;
                _toggleCanvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaAnimToggle", 499);
                SoniaUiKit.MakeCornerButton(_toggleCanvas.transform, "Animaciones", 1, Toggle);
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

        /// <summary>Muestra u oculta el panel.</summary>
        public void Toggle()
        {
            if (_canvas == null)
            {
                Build();
            }

            _canvas.SetActive(!_canvas.activeSelf);
        }

        private void Build()
        {
            DestroyStale("SoniaAnim");
            _canvas = SoniaUiKit.MakeOverlayCanvas(transform, "SoniaAnim", 500);

            GameObject panel = SoniaUiKit.MakeImage(_canvas.transform, "Panel", new Color(0.02f, 0.03f, 0.08f, 0.92f));
            RectTransform panelRect = panel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.03f, 0.07f);
            panelRect.anchorMax = new Vector2(0.97f, 0.55f);
            panelRect.offsetMin = Vector2.zero;
            panelRect.offsetMax = Vector2.zero;

            Text title = SoniaUiKit.MakeText(panel.transform, "Titulo",
                "Animaciones del set. Los bucles (idle, escuchar, pensar) se quedan; el resto se reproduce una vez y vuelve.",
                18, TextAnchor.UpperLeft);
            RectTransform titleRect = title.GetComponent<RectTransform>();
            titleRect.anchorMin = new Vector2(0f, 1f);
            titleRect.anchorMax = new Vector2(1f, 1f);
            titleRect.pivot = new Vector2(0.5f, 1f);
            titleRect.anchoredPosition = new Vector2(0f, -10f);
            titleRect.sizeDelta = new Vector2(-30f, 50f);

            // Estados
            GameObject states = new GameObject("Estados", typeof(RectTransform));
            states.transform.SetParent(panel.transform, false);
            RectTransform statesRect = states.GetComponent<RectTransform>();
            statesRect.anchorMin = new Vector2(0f, 1f);
            statesRect.anchorMax = new Vector2(1f, 1f);
            statesRect.pivot = new Vector2(0.5f, 1f);
            statesRect.anchoredPosition = new Vector2(0f, -62f);
            statesRect.sizeDelta = new Vector2(-30f, 52f);
            HorizontalLayoutGroup row = states.AddComponent<HorizontalLayoutGroup>();
            row.spacing = 10f;
            row.childForceExpandWidth = true;
            row.childForceExpandHeight = true;
            SoniaUiKit.MakeButton(states.transform, "Idle", () => ForceState(AvatarState.Idle));
            SoniaUiKit.MakeButton(states.transform, "Escuchar", () => ForceState(AvatarState.Listening));
            SoniaUiKit.MakeButton(states.transform, "Pensar", () => ForceState(AvatarState.Thinking));
            SoniaUiKit.MakeButton(states.transform, "Hablar", () => ForceState(AvatarState.Speaking));
            SoniaUiKit.MakeButton(states.transform, "Saludo", () =>
            {
                if (choreographer != null && choreographer.MotionSet != null)
                {
                    choreographer.Preview(choreographer.MotionSet.greeting);
                }
            });

            // Modo Fuera sin orquestador: sale caminando y deja el letrero, o vuelve.
            SoniaUiKit.MakeButton(states.transform, "Salir/Volver", () =>
            {
                PresenceController presence = GetComponentInParent<PresenceController>();
                if (presence == null)
                {
                    presence = FindAnyObjectByType<PresenceController>();
                }

                if (presence != null)
                {
                    presence.TogglePresence();
                }
            });

            // Lista con scroll
            GameObject scrollGo = new GameObject("Scroll", typeof(RectTransform));
            scrollGo.transform.SetParent(panel.transform, false);
            RectTransform scrollRect = scrollGo.GetComponent<RectTransform>();
            scrollRect.anchorMin = Vector2.zero;
            scrollRect.anchorMax = Vector2.one;
            scrollRect.offsetMin = new Vector2(15f, 15f);
            scrollRect.offsetMax = new Vector2(-15f, -125f);
            ScrollRect scroll = scrollGo.AddComponent<ScrollRect>();
            scroll.horizontal = false;
            scroll.scrollSensitivity = 40f;
            Image mask = scrollGo.AddComponent<Image>();
            mask.color = new Color(0f, 0f, 0f, 0.15f);
            scrollGo.AddComponent<Mask>().showMaskGraphic = true;

            GameObject content = new GameObject("Contenido", typeof(RectTransform));
            content.transform.SetParent(scrollGo.transform, false);
            RectTransform contentRect = content.GetComponent<RectTransform>();
            contentRect.anchorMin = new Vector2(0f, 1f);
            contentRect.anchorMax = new Vector2(1f, 1f);
            contentRect.pivot = new Vector2(0.5f, 1f);
            contentRect.anchoredPosition = Vector2.zero;
            contentRect.sizeDelta = Vector2.zero;
            VerticalLayoutGroup column = content.AddComponent<VerticalLayoutGroup>();
            column.spacing = 6f;
            column.padding = new RectOffset(8, 8, 8, 8);
            column.childForceExpandWidth = true;
            column.childForceExpandHeight = false;
            column.childControlHeight = true;
            column.childControlWidth = true;
            content.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            scroll.content = contentRect;
            scroll.viewport = scrollRect;

            SoniaMotionSet set = choreographer != null ? choreographer.MotionSet : null;
            if (set == null)
            {
                SoniaUiKit.MakeText(content.transform, "Aviso", "Sin set de animaciones.", 20, TextAnchor.MiddleLeft);
                _canvas.SetActive(false);
                return;
            }

            AddSection(content.transform, "Reposo (bucle)", new[] { set.idleLoop }, false);
            AddSection(content.transform, "Variaciones de reposo", set.idleVariations, false);
            AddSection(content.transform, "Escuchar (bucle)", new[] { set.listeningLoop }, false);
            AddSection(content.transform, "Asentimientos (torso)", set.nods, true);
            AddSection(content.transform, "Pensar (bucle)", new[] { set.thinkingLoop }, false);
            AddSection(content.transform, "Variaciones de pensar", set.thinkingVariations, false);
            AddSection(content.transform, "Hablar", set.talking, false);
            AddSection(content.transform, "Bailes", Filter(set, AttentionCategory.Dance), false);
            AddSection(content.transform, "Cuarta pared", Filter(set, AttentionCategory.FourthWall), false);
            AddSection(content.transform, "Gestos suaves", Filter(set, AttentionCategory.Soft), false);

            _canvas.SetActive(false);
        }

        private static AnimationClip[] Filter(SoniaMotionSet set, AttentionCategory category)
        {
            System.Collections.Generic.List<AnimationClip> clips = new System.Collections.Generic.List<AnimationClip>();
            for (int i = 0; i < set.attention.Length; i++)
            {
                AttentionMotion motion = set.attention[i];
                if (motion != null && motion.clip != null && motion.category == category)
                {
                    clips.Add(motion.clip);
                }
            }

            return clips.ToArray();
        }

        private void AddSection(Transform parent, string title, AnimationClip[] clips, bool upperBody)
        {
            if (clips == null)
            {
                return;
            }

            Text header = SoniaUiKit.MakeText(parent, "Seccion", title, 24, TextAnchor.MiddleLeft);
            header.fontStyle = FontStyle.Bold;
            header.GetComponent<LayoutElement>().preferredHeight = 44f;

            // Botones en filas de tres.
            GameObject row = null;
            int inRow = 0;
            for (int i = 0; i < clips.Length; i++)
            {
                AnimationClip clip = clips[i];
                if (clip == null)
                {
                    continue;
                }

                if (row == null || inRow >= 3)
                {
                    row = new GameObject("Fila", typeof(RectTransform));
                    row.transform.SetParent(parent, false);
                    row.AddComponent<LayoutElement>().preferredHeight = 52f;
                    HorizontalLayoutGroup layout = row.AddComponent<HorizontalLayoutGroup>();
                    layout.spacing = 8f;
                    layout.childForceExpandWidth = true;
                    layout.childForceExpandHeight = true;
                    inRow = 0;
                }

                AnimationClip captured = clip;
                SoniaUiKit.MakeButton(row.transform, Shorten(clip.name) + " (" + clip.length.ToString("F0") + " s)",
                    () => { if (choreographer != null) choreographer.Preview(captured, upperBody); });
                inRow++;
            }
        }

        private static string Shorten(string name)
        {
            return name.Replace("_", " ");
        }

        private void ForceState(AvatarState state)
        {
            if (stateController != null)
            {
                stateController.SetState(state);
            }

            if (choreographer != null)
            {
                choreographer.SetState(state);
                if (state == AvatarState.Speaking)
                {
                    choreographer.NotifySpeechStart();
                }
            }
        }
    }
}
