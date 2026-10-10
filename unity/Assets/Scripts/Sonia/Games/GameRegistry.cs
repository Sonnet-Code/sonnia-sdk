// Los juegos que Unity sabe pintar: un controlador por juego, cada uno en su
// carpeta (Games/<Juego>/). GameRouter los añade por código al objeto de
// SoniaBootstrap y anuncia sus ids en client_hello.games, así que el orquestador
// solo ofrece estos.
//
// Un juego que todavía no se pinta bien no se anuncia: se quita (o se comenta) su
// línea aquí. Cada agente de juego trabaja solo en su carpeta; esta lista la
// toca la integración.

using System;

namespace Sonia
{
    /// <summary>Lista de los controladores de los juegos, en el orden del plan.</summary>
    public static class GameRegistry
    {
        /// <summary>Tipos de los controladores (MonoBehaviour que implementan <see cref="IGameController"/>).</summary>
        public static readonly Type[] Controllers =
        {
            typeof(Games.Ruleta.RuletaController),
            typeof(Games.Poses.PosesController),
            typeof(Games.Akinator.AkinatorController),
            typeof(Games.Ppt.PptController),
            typeof(Games.Wordle.WordleController),
            typeof(Games.Busqueda.BusquedaController),
        };
    }
}
