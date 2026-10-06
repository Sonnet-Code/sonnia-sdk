// Un archivo .ozz de Genies importado como asset (GeniesOzzImporter, en el
// editor). Guarda los bytes tal cual; el clip se decodifica al usarlo
// (GeniesOzzClip.Parse), así que en el repo solo están los .ozz originales.

using UnityEngine;

namespace Sonia
{
    /// <summary>Bytes de un clip OZZ de Genies, listo para decodificar en tiempo de ejecución.</summary>
    public sealed class GeniesOzzAsset : ScriptableObject
    {
        [SerializeField]
        [HideInInspector]
        private byte[] data = new byte[0];

        /// <summary>Contenido del archivo .ozz.</summary>
        public byte[] Data
        {
            get { return data; }
        }

        /// <summary>Lo usa el importador al leer el archivo.</summary>
        public void SetData(byte[] bytes)
        {
            data = bytes ?? new byte[0];
        }

        /// <summary>Decodifica el clip (lanza FormatException si el archivo no es un OZZ de Genies).</summary>
        public GeniesOzzClip Decode()
        {
            return GeniesOzzClip.Parse(data);
        }
    }
}
