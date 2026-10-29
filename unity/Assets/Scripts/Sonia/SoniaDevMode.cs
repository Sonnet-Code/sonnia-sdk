// On-screen development controls: "Settings" and "Animations" buttons, the
// text box with "Interrupt", the connection and state labels, and the
// keyboard shortcuts (F1, F2, Escape).
//
// In normal operation only the avatar and its subtitles are visible, and
// everything is driven from the control panel. The development controls only
// appear:
//  - in the built app, when launched with -dev-ui;
//  - in the editor, with the menu Sonnia > On-screen Developer Controls.

using System;
using UnityEngine;

namespace Sonia
{
    public static class SoniaDevMode
    {
        /// <summary>EditorPrefs key of the editor switch.</summary>
        public const string EditorPrefKey = "Sonia.DevUI";

        private static bool? _commandLine;

        /// <summary>Are the development controls shown?</summary>
        public static bool Enabled
        {
            get
            {
#if UNITY_EDITOR
                if (UnityEditor.EditorPrefs.GetBool(EditorPrefKey, false))
                {
                    return true;
                }
#endif
                if (_commandLine == null)
                {
                    _commandLine = Array.IndexOf(Environment.GetCommandLineArgs(), "-dev-ui") >= 0;
                }

                return _commandLine.Value;
            }
        }

        /// <summary>Turns off a UI object if the development controls are hidden.</summary>
        public static void HideUnlessEnabled(Component component)
        {
            if (component != null && !Enabled)
            {
                component.gameObject.SetActive(false);
            }
        }
    }
}
