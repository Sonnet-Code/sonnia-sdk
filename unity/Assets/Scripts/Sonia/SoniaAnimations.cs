// Catálogo de animaciones del avatar.
//
// Este archivo es la única fuente de verdad: lo usa el generador del set de
// animaciones (Editor/SoniaMotionSetBuilder.cs) para rellenar el asset
// SoniaMotionSet a partir de los FBX de Assets/Animations, y el propio menú
// para decidir qué clips se importan en bucle. Si se añade un clip nuevo hay
// que tocarlo solo aquí y volver a ejecutar "Sonia > Crear set de animaciones".
//
// Los clips vienen de dos fuentes: la biblioteca de Ready Player Me (prefijo
// F_, hechos para el propio esqueleto de Babe) y Mixamo (retargeting humanoide).

using UnityEngine;

namespace Sonia
{
    /// <summary>Familia a la que pertenece una animación de atención del idle.</summary>
    public enum AttentionCategory
    {
        /// <summary>Baile completo. Es lo más llamativo, se usa con cuentagotas.</summary>
        Dance = 0,

        /// <summary>Gesto que rompe la cuarta pared: señalar, saludar o tocar la pantalla.</summary>
        FourthWall = 1,

        /// <summary>Gesto suave de relleno: encogerse de hombros, mirar alrededor, apoyarse.</summary>
        Soft = 2
    }

    /// <summary>Una animación de atención: nombre del clip y categoría.</summary>
    public sealed class AttentionClip
    {
        /// <summary>Nombre del clip y del FBX que lo contiene, sin extensión.</summary>
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
        /// <summary>Carpetas con los FBX. Cada FBX trae un clip con su mismo nombre.</summary>
        public static readonly string[] ClipFolders =
        {
            "Assets/Animations/RPM",
            "Assets/Animations/Mixamo"
        };

        /// <summary>Asset generado por "Sonia > Crear set de animaciones".</summary>
        public const string MotionSetPath = "Assets/Animations/SoniaMotionSet.asset";

        /// <summary>Máscara de la capa de torso, generada junto al set.</summary>
        public const string UpperBodyMaskPath = "Assets/Animations/SoniaUpperBody.mask";

        // ------------------------------------------------------------------
        // Clips por estado
        // ------------------------------------------------------------------

        /// <summary>Bucle base de reposo.</summary>
        public const string IdleLoopClip = "F_Standing_Idle_001";

        /// <summary>Variaciones de reposo, de una sola vez: empiezan y acaban en la pose base.</summary>
        public static readonly string[] IdleVariationClips =
        {
            "F_Standing_Idle_Variations_001",
            "F_Standing_Idle_Variations_002",
            "F_Standing_Idle_Variations_003",
            "F_Standing_Idle_Variations_004",
            "F_Standing_Idle_Variations_005",
            "F_Standing_Idle_Variations_006",
            "F_Standing_Idle_Variations_007",
            "F_Standing_Idle_Variations_008",
            "F_Standing_Idle_Variations_009"
        };

        /// <summary>Bucle de escucha.</summary>
        public const string ListeningLoopClip = "Listening";

        /// <summary>Asentimientos de una sola vez, en la capa de torso.</summary>
        public static readonly string[] NodClips = { "ListeningNod", "HeadGesture" };

        /// <summary>Bucle de pensar.</summary>
        public const string ThinkingLoopClip = "Thinking";

        /// <summary>Variaciones de pensar, de una sola vez.</summary>
        public static readonly string[] ThinkingVariationClips = { "ThoughtfulHeadShake" };

        /// <summary>Gesticulación al hablar. Se encadenan sin bucle.</summary>
        public static readonly string[] TalkingClips =
        {
            "F_Talking_Variations_001",
            "F_Talking_Variations_002",
            "F_Talking_Variations_003",
            "F_Talking_Variations_004",
            "F_Talking_Variations_005",
            "F_Talking_Variations_006",
            "Talking1", "Talking2", "Talking3", "Talking4", "Talking5",
            "Speaking", "Speaking2", "Speaking3"
        };

        /// <summary>Saludo con la mano.</summary>
        public const string GreetingClip = "Greeting";

        /// <summary>
        /// Gestos de atención que Sonia lanza sola mientras está en idle, para
        /// que el stand no parezca una estatua. Todos se reproducen una sola vez.
        /// </summary>
        public static readonly AttentionClip[] AttentionClips =
        {
            // Bailes.
            new AttentionClip("F_Dances_001", AttentionCategory.Dance),
            new AttentionClip("F_Dances_004", AttentionCategory.Dance),
            new AttentionClip("F_Dances_005", AttentionCategory.Dance),
            new AttentionClip("F_Dances_006", AttentionCategory.Dance),
            new AttentionClip("F_Dances_007", AttentionCategory.Dance),
            new AttentionClip("Dance_HipHop", AttentionCategory.Dance),
            new AttentionClip("Dance_House", AttentionCategory.Dance),
            new AttentionClip("Dance_Jazz", AttentionCategory.Dance),
            new AttentionClip("Dance_RunningMan", AttentionCategory.Dance),
            new AttentionClip("Dance_Gangnam", AttentionCategory.Dance),

            // Cuarta pared: se dirigen a quien mira la pantalla.
            new AttentionClip("Touch_Screen", AttentionCategory.FourthWall),
            new AttentionClip("Point_Forward", AttentionCategory.FourthWall),
            new AttentionClip("Point_ThisGuy", AttentionCategory.FourthWall),
            new AttentionClip("Blow_Kiss", AttentionCategory.FourthWall),
            new AttentionClip("Wave2", AttentionCategory.FourthWall),
            new AttentionClip("Salute", AttentionCategory.FourthWall),
            new AttentionClip("Thumbs_Up", AttentionCategory.FourthWall),

            // Relleno suave: dan vida sin robar protagonismo.
            new AttentionClip("Shrug", AttentionCategory.Soft),
            new AttentionClip("LookAround", AttentionCategory.Soft),
            new AttentionClip("Idle_Leaning", AttentionCategory.Soft),
            new AttentionClip("Excited", AttentionCategory.Soft),
            new AttentionClip("Cheering", AttentionCategory.Soft),
            new AttentionClip("Bow", AttentionCategory.Soft),
            new AttentionClip("Thankful", AttentionCategory.Soft),
            new AttentionClip("Dismissive", AttentionCategory.Soft),
            new AttentionClip("IdleLooking2", AttentionCategory.Soft)
        };

        /// <summary>
        /// Solo los bucles base se importan en bucle. Todo lo demás se reproduce
        /// una vez y termina: así el coreógrafo sabe cuándo encadenar el siguiente
        /// clip en lugar de cortar un gesto a mitad.
        /// </summary>
        public static bool IsLoopingClip(string clipName)
        {
            return clipName == IdleLoopClip
                || clipName == ListeningLoopClip
                || clipName == ThinkingLoopClip;
        }
    }
}
