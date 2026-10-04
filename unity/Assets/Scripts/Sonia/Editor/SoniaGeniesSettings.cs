// Ajustes del Genies Avatar SDK que Sonia fija al abrir el editor.
//
// La telemetría de Genies solo arranca en el editor (en las builds su instalador
// sale antes) y su cliente nativo tumbó el editor al entrar en Play con recarga
// de dominio (SIGSEGV en libGeniesTelemetryBridge). Sonia no la necesita: se
// desactiva con la misma clave de PlayerPrefs que escribe su ventana Tools >
// Genies > Settings > Telemetry Settings. El instalador de Genies está parcheado
// para respetarla también al arrancar el cliente nativo.

using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    [InitializeOnLoad]
    internal static class SoniaGeniesSettings
    {
        /// <summary>Clave de Genies (GeniesTelemetry.TelemetryEnabledKey, interna en el SDK).</summary>
        private const string TelemetryEnabledKey = "Genies.Telemetry.Enabled";

        static SoniaGeniesSettings()
        {
            if (PlayerPrefs.GetInt(TelemetryEnabledKey, 1) == 0)
            {
                return;
            }

            PlayerPrefs.SetInt(TelemetryEnabledKey, 0);
            PlayerPrefs.Save();
            Debug.Log("[Sonia] Telemetría de Genies desactivada (ver SoniaGeniesSettings).");
        }
    }
}
