// Catálogo de animaciones del avatar y nombres de los parámetros del Animator.
//
// Este archivo es la única fuente de verdad: lo usan tanto el generador del
// controlador (Editor/SoniaAnimatorBuilder.cs) como los componentes de runtime
// que deciden qué animación lanzar. Si se añade un clip nuevo hay que tocarlo
// solo aquí y volver a ejecutar el menú "Sonia/Crear Animator Controller".
//
// Los índices de AttentionClips son FIJOS: se graban como condiciones
// "IdleVariant Equals N" dentro del controlador. Al añadir clips nuevos se
// añaden AL FINAL con el siguiente índice libre; reordenar la lista obliga a
// regenerar el controlador.

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

    /// <summary>Una animación de atención: nombre del clip, índice fijo y categoría.</summary>
    public sealed class AttentionClip
    {
        /// <summary>Nombre del clip y del FBX que lo contiene, sin extensión.</summary>
        public readonly string Name;

        /// <summary>Valor de <c>IdleVariant</c> que lleva a este clip.</summary>
        public readonly int Index;

        /// <summary>Familia usada para repartir probabilidades.</summary>
        public readonly AttentionCategory Category;

        public AttentionClip(string name, int index, AttentionCategory category)
        {
            Name = name;
            Index = index;
            Category = category;
        }
    }

    /// <summary>
    /// Constantes compartidas entre el generador del Animator Controller y los
    /// componentes de runtime.
    /// </summary>
    public static class SoniaAnimations
    {
        // ------------------------------------------------------------------
        // Parámetros del Animator
        // ------------------------------------------------------------------

        /// <summary>Entero: 0 idle, 1 listening, 2 thinking, 3 speaking.</summary>
        public const string StateParameter = "State";

        /// <summary>Entero: índice de la animación de atención que se quiere lanzar.</summary>
        public const string IdleVariantParameter = "IdleVariant";

        /// <summary>Trigger: lanza la animación de atención indicada por IdleVariant.</summary>
        public const string AttentionTrigger = "Attention";

        /// <summary>Entero 0..2: variante de gesticulación al hablar y al asentir.</summary>
        public const string GestureVariantParameter = "GestureVariant";

        /// <summary>Trigger: cambia a la variante de gesto indicada por GestureVariant.</summary>
        public const string GestureTrigger = "Gesture";

        /// <summary>Trigger: saludo con la mano al acercarse alguien.</summary>
        public const string GreetTrigger = "Greet";

        // ------------------------------------------------------------------
        // Rutas y clips principales
        // ------------------------------------------------------------------

        /// <summary>Controlador generado por el menú "Sonia/Crear Animator Controller".</summary>
        public const string ControllerPath = "Assets/Animations/SoniaAnimator.controller";

        /// <summary>Carpeta con los FBX de Mixamo. Cada FBX trae un clip con su mismo nombre.</summary>
        public const string ClipFolder = "Assets/Animations/Mixamo";

        /// <summary>Número de variantes de gesticulación al hablar (Speaking0, Speaking1, Speaking2).</summary>
        public const int SpeakingVariantCount = 3;

        public const string IdleClip = "Idle";
        public const string IdleAltClip = "Idle2";
        public const string ListeningClip = "Listening";
        public const string ListeningNodClip = "ListeningNod";
        public const string ThinkingClip = "Thinking";
        public const string GreetingClip = "Greeting";

        /// <summary>Clips de gesticulación al hablar, en el orden de GestureVariant.</summary>
        public static readonly string[] SpeakingClips = { "Speaking", "Speaking2", "Speaking3" };

        // Nombres de los estados del controlador. Coinciden con los que busca el
        // generador y sirven para depurar desde la ventana del Animator.
        public const string IdleState = "Idle";
        public const string IdleAltState = "IdleAlt";
        public const string ListeningState = "Listening";
        public const string ListeningNodState = "ListeningNod";
        public const string ThinkingState = "Thinking";
        public const string GreetingState = "Greeting";
        public const string SpeakingStatePrefix = "Speaking";
        public const string AttentionStateMachine = "Attention";

        /// <summary>
        /// Etiqueta que llevan los estados en los que Sonia se mueve mucho (bailes,
        /// gestos de atención y el saludo). <c>CameraFramingController</c> la usa
        /// para abrir el plano y que no se salga del encuadre.
        /// </summary>
        public const string WideShotTag = "wide";

        // ------------------------------------------------------------------
        // Animaciones de atención del idle
        // ------------------------------------------------------------------

        /// <summary>
        /// Catálogo de animaciones que Sonia lanza sola mientras está en idle,
        /// para que el stand no parezca una estatua. El índice es el valor de
        /// <c>IdleVariant</c> y no debe cambiar sin regenerar el controlador.
        /// </summary>
        public static readonly AttentionClip[] AttentionClips =
        {
            // Bailes (bucles: el controlador los corta tras una vuelta).
            new AttentionClip("Dance_HipHop", 0, AttentionCategory.Dance),
            new AttentionClip("Dance_House", 1, AttentionCategory.Dance),
            new AttentionClip("Dance_Jazz", 2, AttentionCategory.Dance),
            new AttentionClip("Dance_RunningMan", 3, AttentionCategory.Dance),
            new AttentionClip("Dance_Gangnam", 4, AttentionCategory.Dance),

            // Cuarta pared: se dirigen a quien mira la pantalla.
            new AttentionClip("Touch_Screen", 5, AttentionCategory.FourthWall),
            new AttentionClip("Point_Forward", 6, AttentionCategory.FourthWall),
            new AttentionClip("Point_ThisGuy", 7, AttentionCategory.FourthWall),
            new AttentionClip("Blow_Kiss", 8, AttentionCategory.FourthWall),
            new AttentionClip("Wave2", 9, AttentionCategory.FourthWall),
            new AttentionClip("Salute", 10, AttentionCategory.FourthWall),
            new AttentionClip("Thumbs_Up", 11, AttentionCategory.FourthWall),

            // Relleno suave: dan vida sin robar protagonismo.
            new AttentionClip("Shrug", 12, AttentionCategory.Soft),
            new AttentionClip("LookAround", 13, AttentionCategory.Soft),
            new AttentionClip("Idle_Leaning", 14, AttentionCategory.Soft),
            new AttentionClip("Excited", 15, AttentionCategory.Soft),
            new AttentionClip("Cheering", 16, AttentionCategory.Soft),
            new AttentionClip("Bow", 17, AttentionCategory.Soft)
        };

        /// <summary>Devuelve la animación de atención con ese índice, o null si no existe.</summary>
        public static AttentionClip FindByIndex(int index)
        {
            for (int i = 0; i < AttentionClips.Length; i++)
            {
                if (AttentionClips[i].Index == index)
                {
                    return AttentionClips[i];
                }
            }

            return null;
        }

        /// <summary>Cuántas animaciones de atención hay en una categoría.</summary>
        public static int CountInCategory(AttentionCategory category)
        {
            int count = 0;
            for (int i = 0; i < AttentionClips.Length; i++)
            {
                if (AttentionClips[i].Category == category)
                {
                    count++;
                }
            }

            return count;
        }

        /// <summary>
        /// Comprueba si el Animator tiene un parámetro con ese nombre y tipo.
        /// Devuelve falso sin quejarse si todavía no hay controlador asignado.
        /// </summary>
        public static bool HasParameter(Animator animator, string name, AnimatorControllerParameterType type)
        {
            if (animator == null || string.IsNullOrEmpty(name) || animator.runtimeAnimatorController == null)
            {
                return false;
            }

            AnimatorControllerParameter[] parameters = animator.parameters;
            for (int i = 0; i < parameters.Length; i++)
            {
                if (parameters[i].type == type && parameters[i].name == name)
                {
                    return true;
                }
            }

            return false;
        }
    }
}
