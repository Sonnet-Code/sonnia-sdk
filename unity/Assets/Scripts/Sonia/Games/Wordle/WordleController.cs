// Wordle de tecnología (docs/plan-juegos.md, 5.5): controlador de Unity.
//
// Esqueleto de los cimientos: ya está registrado (GameRegistry) y anunciado en
// client_hello, abre y cierra la tarjeta común con su título (GameControllerBase)
// y no pinta nada más. Lo que falta, todo en esta carpeta:
// La rejilla de 6×5 con volteo de fichas (GameAnim.Flip), la sacudida si la palabra no vale, las letras usadas y el confeti.
// API de lo común en docs/juegos-unity.md.

namespace Sonia.Games.Wordle
{
    /// <summary>Pantalla de «Wordle de tecnología» (id <c>wordle</c>).</summary>
    public class WordleController : GameControllerBase
    {
        /// <summary>Id del juego en el protocolo.</summary>
        public const string GameId = "wordle";

        public override string Id
        {
            get { return GameId; }
        }

        protected override string DefaultTitle
        {
            get { return "Wordle de tecnología"; }
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            Log("evento sin pantalla todavía: " + eventName);
        }
    }
}
