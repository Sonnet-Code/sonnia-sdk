// Genies Avatar SDK settings that Sonnia sets when the editor opens.
//
// Only compiled when the SDK is installed (SONNIA_GENIES). Genies telemetry
// only starts in the editor (in players its installer exits early) and its
// native client has crashed the editor when entering Play with domain reload
// (SIGSEGV in libGeniesTelemetryBridge). Sonnia does not need it: it is turned
// off with the same PlayerPrefs key that Genies' Tools > Genies > Settings >
// Telemetry Settings window writes.

#if SONNIA_GENIES

using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    [InitializeOnLoad]
    internal static class SoniaGeniesSettings
    {
        /// <summary>Genies key (GeniesTelemetry.TelemetryEnabledKey, internal in the SDK).</summary>
        private const string TelemetryEnabledKey = "Genies.Telemetry.Enabled";

        static SoniaGeniesSettings()
        {
            if (PlayerPrefs.GetInt(TelemetryEnabledKey, 1) == 0)
            {
                return;
            }

            PlayerPrefs.SetInt(TelemetryEnabledKey, 0);
            PlayerPrefs.Save();
            Debug.Log("[Sonnia] Genies telemetry turned off (see SoniaGeniesSettings).");
        }
    }
}

#endif
