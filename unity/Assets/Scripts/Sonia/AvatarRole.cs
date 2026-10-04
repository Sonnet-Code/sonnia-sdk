// De quién es un avatar de Genies: de Sonia o del invitado del Modo Jean.
//
// Los dos se cargan con GeniesAvatarLoader y se editan con el mismo editor de
// personaje; el rol decide qué mensaje del orquestador escuchan (set_avatar o
// set_guest_avatar), dónde se recuerda su último avatar y qué definición ve el
// editor al abrirse.

namespace Sonia
{
    /// <summary>Dueño de un avatar: Sonia o el invitado del Modo Jean.</summary>
    public enum AvatarRole
    {
        /// <summary>Sonia (set_avatar, ajuste compartido "avatar").</summary>
        Sonia = 0,

        /// <summary>El invitado del Modo Jean (set_guest_avatar, ajuste compartido "guest_avatar").</summary>
        Guest = 1
    }
}
