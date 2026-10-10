// Akinator dev (docs/plan-juegos.md, 5.3): controlador de Unity.
//
// Esqueleto de los cimientos: ya está registrado (GameRegistry) y anunciado en
// client_hello, abre y cierra la tarjeta común con su título (GameControllerBase)
// y no pinta nada más. Lo que falta, todo en esta carpeta:
// La tarjeta de la bola de cristal con 20 puntos de progreso, la adivinanza final («¿Es… Kotlin?») y el resultado.
// API de lo común en docs/juegos-unity.md.

namespace Sonia.Games.Akinator
{
    /// <summary>Pantalla de «Akinator dev» (id <c>akinator</c>).</summary>
    public class AkinatorController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "akinator";

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Akinator dev"; }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Log("evento sin pantalla todavía: " + eventName);
        }
    }
}
