// Catálogo de clips que usa el coreógrafo, como asset.
//
// Se rellena con el menú "Sonia/Crear set de animaciones" a partir de los
// nombres de SoniaAnimations y de los FBX de Assets/Animations. El coreógrafo
// no busca clips por nombre en tiempo de ejecución: recibe este asset ya
// resuelto, así que en una build no hace falta ningún cargador.

using System;
using UnityEngine;

namespace Sonia
{
    /// <summary>Un gesto de atención del idle con su categoría.</summary>
    [Serializable]
    public sealed class AttentionMotion
    {
        public AnimationClip clip;
        public AttentionCategory category;
    }

    /// <summary>Clips del avatar agrupados por lo que hace Sonia con ellos.</summary>
    [CreateAssetMenu(fileName = "SoniaMotionSet", menuName = "Sonia/Motion Set")]
    public class SoniaMotionSet : ScriptableObject
    {
        [Header("Reposo")]
        [Tooltip("Bucle base de reposo. Siempre está sonando de fondo en idle.")]
        public AnimationClip idleLoop;

        [Tooltip("Variaciones de reposo (una sola vez cada una): cambiar el peso, mirar alrededor, tocarse el pelo...")]
        public AnimationClip[] idleVariations = new AnimationClip[0];

        [Header("Escuchar")]
        [Tooltip("Bucle de escucha atenta.")]
        public AnimationClip listeningLoop;

        [Tooltip("Asentimientos (una sola vez), en la capa de torso sobre el bucle de escucha.")]
        public AnimationClip[] nods = new AnimationClip[0];

        [Header("Pensar")]
        [Tooltip("Bucle de pensar.")]
        public AnimationClip thinkingLoop;

        [Tooltip("Variaciones de pensar (una sola vez).")]
        public AnimationClip[] thinkingVariations = new AnimationClip[0];

        [Header("Hablar")]
        [Tooltip("Gesticulación al hablar. Se encadenan una tras otra sin bucle mientras dura la frase.")]
        public AnimationClip[] talking = new AnimationClip[0];

        [Header("Saludo")]
        [Tooltip("Saludo con la mano al acercarse alguien tras un rato sola.")]
        public AnimationClip greeting;

        [Tooltip("Gesto de presentar una imagen (se congela señalando mientras la imagen está puesta).")]
        public AnimationClip present;

        [Header("Atención en el idle")]
        [Tooltip("Bailes, gestos de cuarta pared y gestos suaves que rompen el idle.")]
        public AttentionMotion[] attention = new AttentionMotion[0];

        /// <summary>Cuántos gestos de atención hay en una categoría.</summary>
        public int CountInCategory(AttentionCategory category)
        {
            int count = 0;
            for (int i = 0; i < attention.Length; i++)
            {
                if (attention[i] != null && attention[i].clip != null && attention[i].category == category)
                {
                    count++;
                }
            }

            return count;
        }
    }
}
