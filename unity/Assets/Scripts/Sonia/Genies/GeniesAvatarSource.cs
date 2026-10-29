// Registers the Genies Avatar SDK as the avatar source of AvatarBinder.
//
// This assembly only compiles when the Genies Avatar SDK package is installed
// (SONNIA_GENIES, see Sonia.Genies.asmdef). Before the scene loads it tells
// AvatarBinder to add a GeniesAvatarLoader instead of showing the fallback
// avatar; the loader takes the definition and the fallback from the binder.

using UnityEngine;

namespace Sonia
{
    /// <summary>Hooks <see cref="GeniesAvatarLoader"/> into <see cref="AvatarBinder"/> at startup.</summary>
    public static class GeniesAvatarSource
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        private static void Register()
        {
            AvatarBinder.ExternalSource = Install;
        }

        private static bool Install(AvatarBinder binder)
        {
            if (binder.GetComponent<GeniesAvatarLoader>() == null)
            {
                binder.gameObject.AddComponent<GeniesAvatarLoader>();
            }

            return true;
        }
    }
}
