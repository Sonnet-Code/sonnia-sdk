// Menú Sonia > Controles de desarrollo en pantalla: enciende o apaga en el
// editor los botones, la caja de texto y las etiquetas de estado (SoniaDevMode).
// Apagado por defecto: así se ve Sonia en el stand.

using UnityEditor;

namespace Sonia.EditorTools
{
    public static class SoniaDevMenu
    {
        private const string MenuPath = "Sonia/Controles de desarrollo en pantalla";

        [MenuItem(MenuPath)]
        private static void Toggle()
        {
            bool value = !EditorPrefs.GetBool(SoniaDevMode.EditorPrefKey, false);
            EditorPrefs.SetBool(SoniaDevMode.EditorPrefKey, value);
            UnityEngine.Debug.Log("[Sonia] Controles de desarrollo en pantalla: " + (value ? "sí" : "no") + " (se aplica al entrar en Play).");
        }

        [MenuItem(MenuPath, true)]
        private static bool ToggleValidate()
        {
            Menu.SetChecked(MenuPath, EditorPrefs.GetBool(SoniaDevMode.EditorPrefKey, false));
            return true;
        }
    }
}
