// Modo vídeo: la app no es la Sonnia del stand sino el renderizador de vídeos para
// redes («Sonnia Video», docs/video.md). Lo enciende el argumento -sonnia-video o
// una build hecha con SONNIA_VIDEO_APP (SoniaBuild.BuildMacVideo).
//
// En este modo no hay orquestador ni conversación: no se lanza el orquestador
// empaquetado, el cliente WebSocket no se conecta y la webcam no se abre. Lo que
// pasa en pantalla lo conduce Sonia.Video.SoniaVideoStudio reproduciendo una línea
// de tiempo de mensajes del protocolo, por el mismo camino que el stand.

using System;

namespace Sonia
{
    /// <summary>Si la app corre como renderizador de vídeos (ver la cabecera).</summary>
    public static class SoniaVideoMode
    {
        /// <summary>Argumento de la app que enciende el modo vídeo.</summary>
        public const string Argument = "-sonnia-video";

        private static bool? _active;

        /// <summary>Cierto en el renderizador de vídeos.</summary>
        public static bool Active
        {
            get
            {
                if (_active == null)
                {
#if SONNIA_VIDEO_APP
                    _active = true;
#else
                    _active = Array.IndexOf(Environment.GetCommandLineArgs(), Argument) >= 0;
#endif
                }

                return _active.Value;
            }
        }
    }
}
