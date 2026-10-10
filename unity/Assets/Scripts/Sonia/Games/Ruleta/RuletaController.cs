// La ruleta de Sonnia (docs/plan-juegos.md, 5.1): controlador de Unity.
//
// Esqueleto de los cimientos: ya está registrado (GameRegistry) y anunciado en
// client_hello, abre y cierra la tarjeta común con su título (GameControllerBase)
// y no pinta nada más. Lo que falta, todo en esta carpeta:
// La ruleta de cinco retos en la franja alta (wheel_stopped al pararse), las tarjetas de los retos y sus resultados.
// API de lo común en docs/juegos-unity.md.

namespace Sonia.Games.Ruleta
{
    /// <summary>Pantalla de «La ruleta de Sonnia» (id <c>ruleta</c>).</summary>
    public class RuletaController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "ruleta";

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "La ruleta de Sonnia"; }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Log("evento sin pantalla todavía: " + eventName);
        }
    }
}
