// Catalog of the clips the choreographer uses, as an asset.
//
// Filled in with the "Sonnia/Create animation set" menu from the names in
// SoniaAnimations and the FBX files in Assets/Animations. The choreographer
// does not look clips up by name at runtime: it receives this asset already
// resolved, so a build needs no loader.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>An idle attention gesture with its category.</summary>
    [Serializable]
    public sealed class AttentionMotion
    {
        public AnimationClip clip;
        public AttentionCategory category;
    }

    /// <summary>Avatar clips grouped by what Sonnia does with them.</summary>
    [CreateAssetMenu(fileName = "SoniaMotionSet", menuName = "Sonnia/Motion Set")]
    public class SoniaMotionSet : ScriptableObject
    {
        [Header("Idle")]
        [Tooltip("Base idle loop. Always playing in the background while idle.")]
        public AnimationClip idleLoop;

        [Tooltip("Idle variations (played once each): shifting weight, looking around, touching hair...")]
        public AnimationClip[] idleVariations = new AnimationClip[0];

        [Header("Listening")]
        [Tooltip("Attentive listening loop.")]
        public AnimationClip listeningLoop;

        [Tooltip("Nods (played once), on the torso layer over the listening loop.")]
        public AnimationClip[] nods = new AnimationClip[0];

        [Header("Thinking")]
        [Tooltip("Thinking loop.")]
        public AnimationClip thinkingLoop;

        [Tooltip("Thinking variations (played once).")]
        public AnimationClip[] thinkingVariations = new AnimationClip[0];

        [Header("Talking")]
        [Tooltip("Gesturing while talking. Chained one after another without looping for the length of the phrase.")]
        public AnimationClip[] talking = new AnimationClip[0];

        [Header("Greeting")]
        [Tooltip("Hand wave when someone approaches after a while alone.")]
        public AnimationClip greeting;

        [Tooltip("Gesture for presenting an image (freezes pointing while the image is shown).")]
        public AnimationClip present;

        [Header("Walking")]
        [Tooltip("Looping walk cycle with forward root motion. Used when leaving and entering in away mode (PresenceController). Without it, Sonnia slides out.")]
        public AnimationClip walk;

        [Header("Trivia")]
        [Tooltip("Trivia mode gestures (correct, wrong, encouragement). Only TriviaController plays them; the choreographer does not use them on its own.")]
        public AnimationClip[] trivia = new AnimationClip[0];

        [Header("Idle attention")]
        [Tooltip("Dances, fourth-wall gestures and soft gestures that break up the idle.")]
        public AttentionMotion[] attention = new AttentionMotion[0];

        /// <summary>How many attention gestures a category has.</summary>
        public int CountInCategory(AttentionCategory category)
        {
            int count = 0;
            for (int i = 0; i < attention.Length; i++)
            {
                if (attention[i] != null && attention[i].clip != null && attention[i].category == category)
                {
                    count++;
                }
            }

            return count;
        }
    }
}
