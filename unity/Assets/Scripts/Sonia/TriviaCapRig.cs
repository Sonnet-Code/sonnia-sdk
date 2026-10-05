// Datos del gorro de la trivia que monta "Sonia > Crear gorro Noogler" en su
// prefab: la hélice que gira, las medidas de la boca, dónde lo cogen las manos
// (los costados de la copa) y su sitio en la cabeza, medido encajándolo con la
// gorra oficial de Genies (scripts/gorro_noogler/encajar.py: NooglerCap_fit.json).
//
// El origen del prefab es el centro de la boca (el borde de abajo de la copa),
// la visera mira a +Z y la copa sube por +Y.

using UnityEngine;

namespace Sonia
{
    /// <summary>Hélice, medidas y encaje en la cabeza del gorro de la trivia (en metros, a escala real del modelo).</summary>
    [DisallowMultipleComponent]
    public class TriviaCapRig : MonoBehaviour
    {
        [Tooltip("Hélice: gira sobre propellerAxis.")]
        public Transform propeller;

        [Tooltip("Eje de giro de la hélice en su espacio local.")]
        public Vector3 propellerAxis = Vector3.up;

        [Tooltip("Ancho de la boca de lado a lado, en metros.")]
        public float openingWidth = 0.176f;

        [Tooltip("Fondo de la boca de delante a atrás, en metros.")]
        public float openingDepth = 0.224f;

        [Tooltip("Punto más alto de la copa, en el espacio del gorro.")]
        public Vector3 apex = new Vector3(0f, 0.1f, 0.03f);

        [Tooltip("Dónde apoyan las palmas para cogerlo: un punto en cada costado de la copa, por fuera.")]
        public Vector3[] gripPoints = new Vector3[0];

        [Tooltip("Normal de la tela (hacia fuera) en cada punto de agarre.")]
        public Vector3[] gripNormals = new Vector3[0];

        [Header("Encaje en la cabeza (medido con la gorra oficial de Genies)")]
        [Tooltip("Cierto si los tres valores de abajo están medidos. Si no, TriviaHat usa su colocación aproximada.")]
        public bool fitted;

        [Tooltip("Posición del gorro en el espacio del hueso de la cabeza.")]
        public Vector3 headPosition = new Vector3(0f, 0.12f, 0.02f);

        [Tooltip("Giro del gorro en el espacio del hueso de la cabeza.")]
        public Quaternion headRotation = Quaternion.identity;

        [Tooltip("Escala del gorro en el espacio del hueso de la cabeza.")]
        public float headScale = 1f;
    }
}
