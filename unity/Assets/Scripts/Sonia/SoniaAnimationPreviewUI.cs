// Animations panel ("Animations" button at the top right).
//
// Lists every clip of the set by category and plays it on click, plus buttons
// to force the state (idle, listening, thinking, speaking) without needing the
// orchestrator. It is for reviewing each clip in the real scene and deciding
// which ones to keep.

using System;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>Buttons to play any clip of the set and force states.</summary>
    [DisallowMultipleComponent]
    public class SoniaAnimationPreviewUI : MonoBehaviour
    {
        [SerializeField]
        [Tooltip("Avatar choreographer. If empty, it is looked up under this object.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Avatar state (to force states from the panel).")]
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
                SoniaUiKit.MakeCornerButton(_toggleCanvas.transform, "Animations", 1, Toggle);
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

            Text title = SoniaUiKit.MakeText(panel.transform, "Title",
                "Animations in the set. Loops (idle, listening, thinking) stay on; the rest play once and return.",
                18, TextAnchor.UpperLeft);
            RectTransform titleRect = title.GetComponent<RectTransform>();
            titleRect.anchorMin = new Vector2(0f, 1f);
            titleRect.anchorMax = new Vector2(1f, 1f);
            titleRect.pivot = new Vector2(0.5f, 1f);
            titleRect.anchoredPosition = new Vector2(0f, -10f);
            titleRect.sizeDelta = new Vector2(-30f, 50f);

            // States
            GameObject states = new GameObject("States", typeof(RectTransform));
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
            SoniaUiKit.MakeButton(states.transform, "Listen", () => ForceState(AvatarState.Listening));
            SoniaUiKit.MakeButton(states.transform, "Think", () => ForceState(AvatarState.Thinking));
            SoniaUiKit.MakeButton(states.transform, "Speak", () => ForceState(AvatarState.Speaking));
            SoniaUiKit.MakeButton(states.transform, "Greeting", () =>
            {
                if (choreographer != null && choreographer.MotionSet != null)
                {
                    choreographer.Preview(choreographer.MotionSet.greeting);
                }
            });

            // Away mode without the orchestrator: she walks out and leaves the away sign, or comes back.
            SoniaUiKit.MakeButton(states.transform, "Leave/Return", () =>
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

            // Scrolling list
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

            GameObject content = new GameObject("Content", typeof(RectTransform));
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
                SoniaUiKit.MakeText(content.transform, "Notice", "No animation set.", 20, TextAnchor.MiddleLeft);
                _canvas.SetActive(false);
                return;
            }

            AddSection(content.transform, "Idle (loop)", new[] { set.idleLoop }, false);
            AddSection(content.transform, "Idle variations", set.idleVariations, false);
            AddSection(content.transform, "Listening (loop)", new[] { set.listeningLoop }, false);
            AddSection(content.transform, "Nods (torso)", set.nods, true);
            AddSection(content.transform, "Thinking (loop)", new[] { set.thinkingLoop }, false);
            AddSection(content.transform, "Thinking variations", set.thinkingVariations, false);
            AddSection(content.transform, "Speaking", set.talking, false);
            AddSection(content.transform, "Dances", Filter(set, AttentionCategory.Dance), false);
            AddSection(content.transform, "Fourth wall", Filter(set, AttentionCategory.FourthWall), false);
            AddSection(content.transform, "Soft gestures", Filter(set, AttentionCategory.Soft), false);

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

            Text header = SoniaUiKit.MakeText(parent, "Section", title, 24, TextAnchor.MiddleLeft);
            header.fontStyle = FontStyle.Bold;
            header.GetComponent<LayoutElement>().preferredHeight = 44f;

            // Buttons in rows of three.
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
                    row = new GameObject("Row", typeof(RectTransform));
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
