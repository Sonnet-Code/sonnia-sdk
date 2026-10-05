// Cuerpo de un avatar mientras no suena un clip nuestro.
//
// El Modo Jean (GuestPresenter) solo decide la secuencia: cuándo entra el
// invitado, cuándo habla, a quién mira, qué gesto lanza Jean desde su modal. Lo
// que hace el cuerpo entre medias (reposo, respiración, mirada, gestos al
// hablar) es de quien implemente esta interfaz:
//
//   ChoreographerBody   lo de siempre de Sonia: clips del set con el
//                       coreógrafo, cabeza y parpadeo con AvatarStateController.
//   (pendiente)         el motor de comportamiento de Genies
//                       (GeniesBehaviorDriver), con su propio adaptador. Basta
//                       con añadir ese componente a la raíz «Invitado»: el
//                       presentador usa el primer IAvatarBody que encuentre y
//                       prefiere uno que no sea el de respaldo.
//
// Lo que no es del cuerpo se queda fuera: caminar (PresenceController), la mano
// (HandshakeRig), la voz y la boca (AudioStreamPlayer, LipSyncController).

using UnityEngine;

namespace Sonia
{
    /// <summary>Reposo, mirada y gestos de un avatar, para que el Modo Jean no dependa de quién los hace.</summary>
    public interface IAvatarBody
    {
        /// <summary>Cierto cuando ya puede mover al avatar.</summary>
        bool IsReady { get; }

        /// <summary>Cierto si es la implementación de respaldo (se prefiere cualquier otra).</summary>
        bool IsFallback { get; }

        /// <summary>Habla (su voz suena) o calla y escucha a quien tiene delante.</summary>
        void SetTalking(bool talking);

        /// <summary>Empieza una frase nueva mientras habla: el cuerpo puede cambiar de gesto.</summary>
        void NotifyPhrase();

        /// <summary>
        /// Atiende a un punto del mundo (por ejemplo, la cabeza de Sonia en el
        /// apretón de manos). Se llama cada frame mientras dure; null vuelve a
        /// mirar al público.
        /// </summary>
        void SetAttention(Transform target);

        /// <summary>Un gesto o animación del catálogo, por el nombre de su clip. Devuelve si lo lanzó.</summary>
        bool PlayGesture(string clipName);

        /// <summary>Saluda con la mano (al despedirse). Devuelve si lo lanzó.</summary>
        bool Wave();

        /// <summary>
        /// Quieto en su reposo, sin variaciones ni gestos por su cuenta, mientras
        /// otro mueve una parte del cuerpo (el apretón de manos). False lo
        /// devuelve a lo suyo.
        /// </summary>
        void Hold(bool hold);
    }
}
