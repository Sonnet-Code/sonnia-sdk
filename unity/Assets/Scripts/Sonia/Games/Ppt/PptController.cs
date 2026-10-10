// Piedra, papel o tijera (docs/plan-juegos.md, 5.4): controlador de Unity.
//
// Esqueleto de los cimientos: ya está registrado (GameRegistry) y anunciado en
// client_hello, abre y cierra la tarjeta común con su título (GameControllerBase)
// y no pinta nada más. Lo que falta, todo en esta carpeta:
// La vista en vivo, la jugada de cada uno en grande, el marcador «Sonnia 1 - 2 Tú» y la mano de Sonnia (SoniaHandPoser).
// API de lo común en docs/juegos-unity.md.

namespace Sonia.Games.Ppt
{
    /// <summary>Pantalla de «Piedra, papel o tijera» (id <c>piedra_papel_tijera</c>).</summary>
    public class PptController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "piedra_papel_tijera";

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Piedra, papel o tijera"; }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Log("evento sin pantalla todavía: " + eventName);
        }
    }
}
