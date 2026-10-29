// Menu Sonnia > On-screen Developer Controls: turns the buttons, text box and
// status labels (SoniaDevMode) on or off in the editor.
// Off by default, so the screen looks like the real installation.

using UnityEditor;

namespace Sonia.EditorTools
{
    public static class SoniaDevMenu
    {
        private const string MenuPath = "Sonnia/On-screen Developer Controls";

        [MenuItem(MenuPath)]
        private static void Toggle()
        {
            bool value = !EditorPrefs.GetBool(SoniaDevMode.EditorPrefKey, false);
            EditorPrefs.SetBool(SoniaDevMode.EditorPrefKey, value);
            UnityEngine.Debug.Log("[Sonnia] On-screen developer controls: " + (value ? "yes" : "no") + " (applied when entering Play).");
        }

        [MenuItem(MenuPath, true)]
        private static bool ToggleValidate()
        {
            Menu.SetChecked(MenuPath, EditorPrefs.GetBool(SoniaDevMode.EditorPrefKey, false));
            return true;
        }
    }
}
