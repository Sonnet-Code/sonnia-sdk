// Contrato de un juego en la pantalla (docs/plan-juegos.md, 4.3).
//
// El orquestador lleva la partida y manda el sobre común:
//   {"type":"game","game":"wordle","event":"guess","seq":7,"data":{...}}
// GameRouter lo reparte por "game" al controlador con ese Id, que lee "data"
// (JSON en texto) con sus propias clases. Todo en el hilo principal.
//
// Lo normal es heredar de GameControllerBase, que ya monta la tarjeta común
// (GameHud) al empezar y la retira al terminar; esta interfaz es lo mínimo que
// necesita GameRouter.

namespace Sonia
{
    /// <summary>Un juego que Unity sabe pintar. Su <see cref="Id"/> va en <c>client_hello.games</c>.</summary>
    public interface IGameController
    {
        /// <summary>Id del juego en el protocolo: "ruleta", "poses", "akinator", "piedra_papel_tijera", "wordle" o "busqueda".</summary>
        string Id { get; }

        /// <summary>Cierto mientras el juego tiene algo en pantalla (también su resultado final, hasta retirarse).</summary>
        bool IsActive { get; }

        /// <summary>
        /// Un evento del orquestador para este juego: <see cref="GameEvents.Start"/>
        /// (lleva <c>data.title</c>) o uno propio del juego. El fin no llega aquí:
        /// va a <see cref="OnEnd"/>. <paramref name="dataJson"/> es el objeto
        /// <c>data</c> en JSON ("{}" si no venía).
        /// </summary>
        void OnEvent(string eventName, string dataJson);

        /// <summary>
        /// Fin de la partida: <paramref name="result"/> vale <see cref="GameResults.Win"/>,
        /// <see cref="GameResults.Lose"/> o <see cref="GameResults.Cancel"/>. Llega con el
        /// evento <c>end</c> (con su <c>data</c>) y también cuando Unity cancela por su
        /// cuenta: tras reconectar no volvió la partida o empezó otro juego (entonces
        /// <paramref name="dataJson"/> es "{}"). El controlador retira su pantalla.
        /// </summary>
        void OnEnd(string result, string dataJson);
    }
}
