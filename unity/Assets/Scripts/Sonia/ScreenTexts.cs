// What Sonnia writes on the screen, in the language of the orchestrator's LANGUAGE
// setting. The orchestrator sends them in the sticky screen_texts message (one file
// per language in assets/languages); until then, and for any key it does not send,
// the built-in English texts below are used, so an older orchestrator keeps working.
//
// Texts may carry {name} placeholders, filled in with Format:
//   ScreenTexts.Format(ScreenTexts.TriviaCounter, "number", 2, "total", 5)

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>The screen texts in use, by key, and the event raised when they change.</summary>
    public static class ScreenTexts
    {
        public const string Invitation = "invitation";
        public const string You = "you";
        public const string Thinking = "thinking";
        public const string Searching = "searching";
        public const string AwayMessage = "away_message";
        public const string AwayFooter = "away_footer";
        public const string TriviaTitle = "trivia_title";
        public const string TriviaCounter = "trivia_counter";
        public const string TriviaLevelPrefix = "trivia_level_";
        public const string TriviaCorrect = "trivia_correct";
        public const string TriviaItWas = "trivia_it_was";
        public const string TriviaOops = "trivia_oops";
        public const string TriviaWon = "trivia_won";
        public const string TriviaClose = "trivia_close";
        public const string TriviaScore = "trivia_score";
        public const string TriviaWonLine = "trivia_won_line";
        public const string TriviaLostLine = "trivia_lost_line";

        /// <summary>The built-in texts: assets/languages/en.json (a test checks they match).</summary>
        public static readonly IReadOnlyDictionary<string, string> English = new Dictionary<string, string>
        {
            [Invitation] = "Come closer and ask me\nanything!",
            [You] = "YOU",
            [Thinking] = "Thinking…",
            [Searching] = "Searching the web…",
            [AwayMessage] = "Back in a few minutes",
            [AwayFooter] = "Virtual assistant",
            [TriviaTitle] = "TRIVIA",
            [TriviaCounter] = "QUESTION {number} OF {total}",
            [TriviaLevelPrefix + "easy"] = "EASY",
            [TriviaLevelPrefix + "medium"] = "MEDIUM",
            [TriviaLevelPrefix + "hard"] = "HARD",
            [TriviaCorrect] = "Correct!",
            [TriviaItWas] = "It was {letter}",
            [TriviaOops] = "Oops! It was {letter}",
            [TriviaWon] = "YOU WON!",
            [TriviaClose] = "SO CLOSE!",
            [TriviaScore] = "{score} of {total} correct",
            [TriviaWonLine] = "Great job, trivia champ!",
            [TriviaLostLine] = "You needed {threshold}. Ask me for another trivia and try again!",
        };

        private static readonly Dictionary<string, string> Current = new Dictionary<string, string>(English);

        /// <summary>Code of the language in use (<c>en</c> until the orchestrator says otherwise).</summary>
        public static string Language { get; private set; } = "en";

        /// <summary>Raised on the main thread after <see cref="Apply"/>: redraw the texts on screen.</summary>
        public static event Action Changed;

        /// <summary>The text <paramref name="key"/>; empty if there is none.</summary>
        public static string Get(string key)
        {
            return key != null && Current.TryGetValue(key, out string text) ? text : string.Empty;
        }

        /// <summary>The text <paramref name="key"/> with its placeholders filled in from name, value pairs.</summary>
        public static string Format(string key, params object[] nameValuePairs)
        {
            string text = Get(key);
            for (int i = 0; i + 1 < nameValuePairs.Length; i += 2)
            {
                text = text.Replace("{" + nameValuePairs[i] + "}", Convert.ToString(nameValuePairs[i + 1]));
            }

            return text;
        }

        /// <summary>
        /// The texts of a <c>screen_texts</c> message: English for every key it leaves out,
        /// and keys this client does not use are kept but ignored.
        /// </summary>
        public static void Apply(ScreenTextsMessage message)
        {
            if (message == null)
            {
                return;
            }

            Current.Clear();
            foreach (KeyValuePair<string, string> pair in English)
            {
                Current[pair.Key] = pair.Value;
            }

            if (message.Texts != null)
            {
                foreach (KeyValuePair<string, string> pair in message.Texts)
                {
                    if (!string.IsNullOrWhiteSpace(pair.Key) && !string.IsNullOrWhiteSpace(pair.Value))
                    {
                        Current[pair.Key] = pair.Value;
                    }
                }
            }

            Language = string.IsNullOrWhiteSpace(message.Language) ? "en" : message.Language;
            Changed?.Invoke();
        }

        // Play mode without a domain reload keeps statics: start each run in English.
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void ResetOnLoad()
        {
            Current.Clear();
            foreach (KeyValuePair<string, string> pair in English)
            {
                Current[pair.Key] = pair.Value;
            }

            Language = "en";
            Changed = null;
        }

        /// <summary>Back to English (tests and the editor).</summary>
        public static void Reset()
        {
            Apply(new ScreenTextsMessage { Language = "en" });
        }
    }
}
