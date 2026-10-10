// Búsqueda relámpago (docs/plan-juegos.md, 5.6): controlador de Unity.
//
// Esqueleto de los cimientos: ya está registrado (GameRegistry) y anunciado en
// client_hello, abre y cierra la tarjeta común con su título (GameControllerBase)
// y no pinta nada más. Lo que falta, todo en esta carpeta:
// La vista en vivo, la tarjeta con el objeto y el contador circular, y «¡Encontrado!».
// API de lo común en docs/juegos-unity.md.

namespace Sonia.Games.Busqueda
{
    /// <summary>Pantalla de «Búsqueda relámpago» (id <c>busqueda</c>).</summary>
    public class BusquedaController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "busqueda";

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Búsqueda relámpago"; }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Log("evento sin pantalla todavía: " + eventName);
        }
    }
}
