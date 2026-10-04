// Catálogo de animaciones del avatar.
//
// Este archivo es la única fuente de verdad: lo usa el generador del set de
// animaciones (Editor/SoniaMotionSetBuilder.cs) para rellenar el asset
// SoniaMotionSet a partir de los clips de Assets/Animations, y el propio menú
// para decidir qué clips van en bucle. Si se añade un clip nuevo hay que tocarlo
// solo aquí y volver a ejecutar "Sonia > Crear set de animaciones".
//
// Solo hay clips oficiales de Genies, hechos para su esqueleto (ver
// Assets/Animations/Genies/LICENSE.md): el reposo, la pose quieta, la caminata
// y los saludos del Genies Avatar SDK y del Starter Pack. Genies no publica
// clips para hablar, escuchar, pensar ni señalar: esos huecos quedan vacíos y
// el coreógrafo se queda en el reposo (la cabeza, la cara y los ojos siguen
// moviéndose por código). Lo que se añada para cubrirlos tiene que nacer del
// esqueleto de Genies, tomando sus clips como referencia, y pasar la
// validación antes de entrar aquí.

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

        /// <summary>Bucle base de reposo: el reposo del SDK de Genies (renovado en la 3.8.6).</summary>
        public const string IdleLoopClip = "DefaultIdle";

        /// <summary>Variaciones de reposo de una sola vez. Genies no publica ninguna.</summary>
        public static readonly string[] IdleVariationClips = new string[0];

        /// <summary>Bucle de escucha: la pose quieta de Genies (la cabeza asiente y se ladea por código).</summary>
        public const string ListeningLoopClip = "StillPose";

        /// <summary>Asentimientos de una sola vez. Vacío: AvatarStateController asiente por código.</summary>
        public static readonly string[] NodClips = new string[0];

        /// <summary>Bucle de pensar: la pose quieta (la mirada y la cara hacen el resto).</summary>
        public const string ThinkingLoopClip = "StillPose";

        /// <summary>Variaciones de pensar. Genies no publica ninguna.</summary>
        public static readonly string[] ThinkingVariationClips = new string[0];

        /// <summary>Gesticulación al hablar. Genies no publica ninguna: se habla desde el reposo.</summary>
        public static readonly string[] TalkingClips = new string[0];

        /// <summary>Saludo con la mano (SDK de Genies, de una sola vez).</summary>
        public const string GreetingClip = "WaveGeneric";

        /// <summary>
        /// Gesto de presentar una imagen (señalar arriba). Genies no publica
        /// ninguno: vacío, la imagen sale sin gesto.
        /// </summary>
        public const string PresentClip = "";

        /// <summary>Segundo del clip de presentar en el que la mano está arriba señalando.</summary>
        public const float PresentHoldTime = 0.45f;

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
            new AttentionClip("Wave", AttentionCategory.FourthWall),
            new AttentionClip("Peace", AttentionCategory.FourthWall)
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
    }
}
