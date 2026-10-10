// Simón dice con poses (docs/plan-juegos.md, 5.2): controlador de Unity.
//
// Esqueleto de los cimientos: ya está registrado (GameRegistry) y anunciado en
// client_hello, abre y cierra la tarjeta común con su título (GameControllerBase)
// y no pinta nada más. Lo que falta, todo en esta carpeta:
// La vista en vivo grande (CameraPreviewPanel), el pictograma de la pose, la orden, el contador «7 de 9» y la demostración de Sonnia.
// API de lo común en docs/juegos-unity.md.

namespace Sonia.Games.Poses
{
    /// <summary>Pantalla de «Simón dice con poses» (id <c>poses</c>).</summary>
    public class PosesController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "poses";

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Simón dice con poses"; }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Log("evento sin pantalla todavía: " + eventName);
        }
    }
}
