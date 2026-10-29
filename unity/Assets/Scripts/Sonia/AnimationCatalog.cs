// Catalog of the animations that the control panel can trigger one by one.
//
// It comes from the SoniaMotionSet in use: everything that plays once
// (greeting, dances, attention gestures, talking gestures, idle and thinking
// variations, nods and the pointing gesture). The base loops and the walk cycle
// are left out: they already play on their own in each state and walking
// belongs to away mode. Unity sends the catalog to the orchestrator (message
// "animations") on receiving "hello", and the panel asks for a specific clip
// with "play_animation", which the choreographer plays with Preview and then
// returns to whatever was due.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Clips of the set that can be triggered by name, with the group the panel shows.</summary>
    public static class AnimationCatalog
    {
        /// <summary>A catalog clip.</summary>
        public struct Entry
        {
            /// <summary>Panel group: dance, fourth_wall, soft, greeting, talking, idle_variation, thinking, nod, present o trivia.</summary>
            public string Group;

            /// <summary>Clip of the set.</summary>
            public AnimationClip Clip;
        }

        /// <summary>All the play-once clips of the set, without repeating names.</summary>
        public static List<Entry> Build(SoniaMotionSet set)
        {
            List<Entry> entries = new List<Entry>();
            if (set == null)
            {
                return entries;
            }

            HashSet<string> seen = new HashSet<string>();
            Add(entries, seen, "greeting", set.greeting);
            if (set.attention != null)
            {
                foreach (AttentionMotion motion in set.attention)
                {
                    if (motion != null)
                    {
                        Add(entries, seen, GroupOf(motion.category), motion.clip);
                    }
                }
            }

            AddAll(entries, seen, "talking", set.talking);
            AddAll(entries, seen, "idle_variation", set.idleVariations);
            AddAll(entries, seen, "thinking", set.thinkingVariations);
            AddAll(entries, seen, "nod", set.nods);
            Add(entries, seen, "present", set.present);
            AddAll(entries, seen, "trivia", set.trivia);
            return entries;
        }

        /// <summary>(clip, group) pairs for the <c>animations</c> message.</summary>
        public static List<KeyValuePair<string, string>> ToPairs(List<Entry> entries)
        {
            List<KeyValuePair<string, string>> pairs = new List<KeyValuePair<string, string>>(entries.Count);
            foreach (Entry entry in entries)
            {
                pairs.Add(new KeyValuePair<string, string>(entry.Clip.name, entry.Group));
            }

            return pairs;
        }

        /// <summary>Finds a catalog clip by its name.</summary>
        public static bool TryFind(SoniaMotionSet set, string clipName, out Entry entry)
        {
            entry = default(Entry);
            if (string.IsNullOrEmpty(clipName))
            {
                return false;
            }

            foreach (Entry candidate in Build(set))
            {
                if (candidate.Clip.name == clipName)
                {
                    entry = candidate;
                    return true;
                }
            }

            return false;
        }

        private static string GroupOf(AttentionCategory category)
        {
            switch (category)
            {
                case AttentionCategory.Dance:
                    return "dance";
                case AttentionCategory.FourthWall:
                    return "fourth_wall";
                default:
                    return "soft";
            }
        }

        private static void AddAll(List<Entry> entries, HashSet<string> seen, string group, AnimationClip[] clips)
        {
            if (clips == null)
            {
                return;
            }

            foreach (AnimationClip clip in clips)
            {
                Add(entries, seen, group, clip);
            }
        }

        private static void Add(List<Entry> entries, HashSet<string> seen, string group, AnimationClip clip)
        {
            // Loops (idle, listening, thinking, walking) are not triggered by hand.
            if (clip == null || clip.isLooping || !seen.Add(clip.name))
            {
                return;
            }

            entries.Add(new Entry { Group = group, Clip = clip });
        }
    }
}
