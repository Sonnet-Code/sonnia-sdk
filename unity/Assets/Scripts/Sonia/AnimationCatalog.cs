// Catálogo de las animaciones que el panel de control puede lanzar una a una.
//
// Sale del SoniaMotionSet en uso: todo lo que se reproduce una sola vez
// (saludo, bailes, gestos de atención, gestos al hablar, variaciones de reposo
// y de pensar, asentimientos y el gesto de señalar). Los bucles base y el ciclo
// de caminar se quedan fuera: ya suenan solos en cada estado y caminar es del
// modo Fuera. Unity manda el catálogo al orquestador (mensaje "animations") al
// recibir "hello", y el panel pide un clip concreto con "play_animation", que
// el coreógrafo reproduce con Preview y luego vuelve a lo que tocaba.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Clips del set que se pueden lanzar por nombre, con el grupo que ve el panel.</summary>
    public static class AnimationCatalog
    {
        /// <summary>Un clip del catálogo.</summary>
        public struct Entry
        {
            /// <summary>Grupo para el panel: dance, fourth_wall, soft, greeting, talking, idle_variation, thinking, nod o present.</summary>
            public string Group;

            /// <summary>Clip del set.</summary>
            public AnimationClip Clip;
        }

        /// <summary>Todos los clips de una sola vez del set, sin repetir nombre.</summary>
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
            return entries;
        }

        /// <summary>Pares (clip, grupo) para el mensaje <c>animations</c>.</summary>
        public static List<KeyValuePair<string, string>> ToPairs(List<Entry> entries)
        {
            List<KeyValuePair<string, string>> pairs = new List<KeyValuePair<string, string>>(entries.Count);
            foreach (Entry entry in entries)
            {
                pairs.Add(new KeyValuePair<string, string>(entry.Clip.name, entry.Group));
            }

            return pairs;
        }

        /// <summary>Busca un clip del catálogo por su nombre.</summary>
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
            // Los bucles (reposo, escuchar, pensar, caminar) no se lanzan a mano.
            if (clip == null || clip.isLooping || !seen.Add(clip.name))
            {
                return;
            }

            entries.Add(new Entry { Group = group, Clip = clip });
        }
    }
}
