// Catálogo de animaciones del avatar.
//
// Este archivo es la única fuente de verdad: lo usa el generador del set de
// animaciones (Editor/SoniaMotionSetBuilder.cs) para rellenar el asset
// SoniaMotionSet a partir de los clips de Assets/Animations, y el propio menú
// para decidir qué clips van en bucle. Si se añade un clip nuevo hay que tocarlo
// solo aquí y volver a ejecutar "Sonia > Crear set de animaciones".
//
// Solo hay clips oficiales de Genies, hechos para su esqueleto (ver
// Assets/Animations/Genies/LICENSE.md): los del Genies Avatar SDK, los del
// Starter Pack y los de sus repos públicos GeniesIRL y GeniesCamera
// (Apache-2.0). Todos han pasado Sonia > Comprobar animaciones (en Play); se
// quedaron fuera los que dan la espalda a la cámara (IdleZoneOut3, vogue) y los
// que solo tienen sentido encadenados en inicio, bucle y final. Genies no
// publica clips para hablar ni escuchar: al hablar suena el reposo, al escuchar
// un reposo más contenido, y la cabeza, la cara y los ojos siguen moviéndose
// por código. Los reposos que se compararon están en
// docs/informe-reposo-genies.md.

using UnityEngine;

namespace Sonia
{
    /// <summary>Familia a la que pertenece una animación de atención del idle.</summary>
    public enum AttentionCategory
    {
        /// <summary>Baile completo. Es lo más llamativo, se usa con cuentagotas.</summary>
        Dance = 0,

        /// <summary>Gesto que rompe la cuarta pared: saludar o dirigirse a quien mira la pantalla.</summary>
        FourthWall = 1,

        /// <summary>Gesto suave de relleno.</summary>
        Soft = 2
    }

    /// <summary>Una animación de atención: nombre del clip y categoría.</summary>
    public sealed class AttentionClip
    {
        /// <summary>Nombre del clip (y de su archivo), sin extensión.</summary>
        public readonly string Name;

        /// <summary>Familia usada para repartir probabilidades.</summary>
        public readonly AttentionCategory Category;

        public AttentionClip(string name, AttentionCategory category)
        {
            Name = name;
            Category = category;
        }
    }

    /// <summary>Nombres de clips y rutas compartidas entre el editor y el runtime.</summary>
    public static class SoniaAnimations
    {
        /// <summary>Carpetas con los clips (.anim o FBX con un clip del mismo nombre).</summary>
        public static readonly string[] ClipFolders =
        {
            "Assets/Animations/Genies"
        };

        /// <summary>Asset generado por "Sonia > Crear set de animaciones".</summary>
        public const string MotionSetPath = "Assets/Animations/SoniaMotionSet.asset";

        /// <summary>Máscara de la capa de torso, generada junto al set.</summary>
        public const string UpperBodyMaskPath = "Assets/Animations/SoniaUpperBody.mask";

        // ------------------------------------------------------------------
        // Clips por estado
        // ------------------------------------------------------------------

        /// <summary>
        /// Bucle base de reposo (y de hablar, que no tiene clips propios): el reposo
        /// del SDK de Genies (renovado en la 3.8.6). Lleva un traspaso de peso de
        /// unos 3 cm cada 10 s que solo se ve con el avance XZ dentro de la pose
        /// (ver <see cref="KeepsHorizontalMotionInPose"/>).
        /// </summary>
        public const string IdleLoopClip = "DefaultIdle";

        /// <summary>Variaciones de reposo de una sola vez. Genies no publica ninguna.</summary>
        public static readonly string[] IdleVariationClips = new string[0];

        /// <summary>
        /// Bucle de escucha: un reposo de Genies más contenido (idles-0024, de la
        /// carpeta de especies del SDK que trae GeniesCamera): 1 cm de vaivén de
        /// cadera y la cabeza algo ladeada, atenta. La pose quieta (StillPose) la
        /// dejaba tiesa. Encima asiente y ladea la cabeza AvatarStateController.
        /// </summary>
        public const string ListeningLoopClip = "idles-0024-basicIdle";

        /// <summary>Asentimientos de una sola vez. Vacío: AvatarStateController asiente por código.</summary>
        public static readonly string[] NodClips = new string[0];

        /// <summary>
        /// Bucle de pensar: el mismo reposo que idle y hablar, así el paso de
        /// pensar a hablar no cambia de clip (la mirada y la cara hacen el resto).
        /// </summary>
        public const string ThinkingLoopClip = "DefaultIdle";

        /// <summary>Variaciones de pensar: mirarse la mano como examinando algo (GeniesIRL).</summary>
        public static readonly string[] ThinkingVariationClips = { "actions-0224-lookAtObject_Trimmed" };

        /// <summary>Gesticulación al hablar. Genies no publica ninguna: se habla desde el reposo.</summary>
        public static readonly string[] TalkingClips = new string[0];

        /// <summary>Saludo con la mano a quien se acerca (Starter Pack, el más amplio).</summary>
        public const string GreetingClip = "Wave";

        /// <summary>
        /// Gesto de presentar una imagen: extiende el brazo hacia el visitante con
        /// la palma arriba (GeniesIRL, presentItem_intro). Va en la capa del brazo
        /// derecho y se congela en <see cref="PresentHoldTime"/> mientras la imagen
        /// está puesta.
        /// </summary>
        public const string PresentClip = "actions-presentItem_intro";

        /// <summary>Segundo del clip de presentar en el que el brazo ya está extendido.</summary>
        public const float PresentHoldTime = 1.0f;

        /// <summary>
        /// Ciclo de caminar para salir y entrar en el modo "Fuera" (SDK de Genies).
        /// Se usa en bucle y con el avance XZ fuera de la pose (centro de masas):
        /// PresenceController lee ese avance cada fotograma y mueve a Sonia
        /// exactamente lo que dan los pies.
        /// </summary>
        public const string WalkClip = "Walk";

        /// <summary>
        /// Gestos de atención que Sonia lanza sola mientras está en idle, para que
        /// el stand no parezca una estatua. Todos se reproducen una sola vez.
        /// </summary>
        public static readonly AttentionClip[] AttentionClips =
        {
            new AttentionClip("QuickAction_vibe", AttentionCategory.Dance),
            new AttentionClip("WaveGeneric", AttentionCategory.FourthWall),
            new AttentionClip("Peace", AttentionCategory.FourthWall),
            new AttentionClip("QuickAction_salute", AttentionCategory.FourthWall),
            new AttentionClip("QuickAction_twoThumbsUp", AttentionCategory.FourthWall)
        };

        /// <summary>
        /// Solo los bucles base (y el ciclo de caminar) van en bucle. Todo lo demás
        /// se reproduce una vez y termina: así el coreógrafo sabe cuándo encadenar
        /// el siguiente clip en lugar de cortar un gesto a mitad.
        /// </summary>
        public static bool IsLoopingClip(string clipName)
        {
            return clipName == IdleLoopClip
                || clipName == ListeningLoopClip
                || clipName == ThinkingLoopClip
                || clipName == WalkClip;
        }

        /// <summary>
        /// Los reposos llevan el avance horizontal dentro de la pose. Sacado como
        /// root motion (y descartado, con applyRootMotion apagado) se pierde
        /// justo el traspaso de peso: la cadera se queda clavada y en su lugar
        /// patinan los pies (DefaultIdle pasaba de 3,2 cm de vaivén a 0,6 cm, con
        /// los pies resbalando 1,8 cm). El resto de clips lo siguen sacando: el
        /// paseo del modo Fuera lo lee PresenceController, y los gestos y bailes
        /// se quedan en el sitio.
        /// </summary>
        public static bool KeepsHorizontalMotionInPose(string clipName)
        {
            return clipName == IdleLoopClip
                || clipName == ListeningLoopClip
                || clipName == ThinkingLoopClip;
        }
    }
}
