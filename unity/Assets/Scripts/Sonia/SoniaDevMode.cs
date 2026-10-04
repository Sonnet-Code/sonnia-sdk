// Controles de desarrollo en pantalla: botones "Ajustes" y "Animaciones", la
// caja de texto con "Interrumpir", las etiquetas de conexión y estado, y los
// atajos de teclado (F1, F2, Escape).
//
// En el stand Sonia está en su estado final: en pantalla solo se ve ella y
// sus subtítulos, y todo se controla desde el panel web (docs/panel.md). Los
// controles de desarrollo solo aparecen:
//  - en la app compilada, arrancándola con -dev-ui;
//  - en el editor, con el menú Sonia > Controles de desarrollo en pantalla.

using System;
using UnityEngine;

namespace Sonia
{
    public static class SoniaDevMode
    {
        /// <summary>Clave de EditorPrefs del interruptor del editor.</summary>
        public const string EditorPrefKey = "Sonia.DevUI";

        private static bool? _commandLine;

        /// <summary>¿Se muestran los controles de desarrollo?</summary>
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

        /// <summary>Apaga un objeto de la interfaz si los controles de desarrollo están ocultos.</summary>
        public static void HideUnlessEnabled(Component component)
        {
            if (component != null && !Enabled)
            {
                component.gameObject.SetActive(false);
            }
        }
    }
}
