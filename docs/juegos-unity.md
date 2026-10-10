# Juegos en Unity: cimientos, API y capturas en batch

Lado de Unity de los juegos nuevos del stand (`docs/plan-juegos.md`, 4.2 y 4.3). El orquestador lleva la partida y manda el sobre `game`; Unity solo pinta. Lo del orquestador (contrato `Game`, `GameHost`, bancos, `scripts/juegos_demo.py`) está en `docs/juegos.md` y el protocolo en `docs/protocolo.md`.

Todo va en el ensamblado `Sonia`, en `unity/Assets/Scripts/Sonia/Games/`, y se monta por código en Play, como la trivia: sale en las capturas 9:16 y en la build, sin prefabs ni cambios en la escena.

## Qué hay

| Archivo | Qué lleva |
|---|---|
| `IGameController.cs` | El contrato de un juego en la pantalla: `Id`, `IsActive`, `OnEvent(evento, dataJson)` y `OnEnd(resultado, dataJson)`. |
| `GameControllerBase.cs` | La base de la que hereda cada juego: abre y cierra la tarjeta común, lee `data` con clases propias, manda `game_event` y hace reaccionar a Sonnia. |
| `GameRouter.cs` | Recibe `game`, `camera_preview` y los frames `SNCV` de `SoniaClient` y los reparte; manda `game_event`; registra los controladores y los anuncia en `client_hello`. |
| `GameRegistry.cs` | La lista de controladores (uno por juego). Un juego que no se pinta bien se quita de aquí y deja de anunciarse. |
| `GameHud.cs` | Lo común de pantalla: tarjeta de la franja alta, contador circular, rótulos, resultado, confeti, plano de panel y aviso a `StageScreen`. Más el kit de piezas (fuentes, sprites, textos). |
| `CameraPreviewPanel.cs` | La vista en vivo de la cámara: 16:9, esquinas redondeadas, «En vivo · no se graba». |
| `GameStyle.cs` | `GameColors` (Google, tarjetas de la trivia, marca) y `GameUi` (colocar, curvas, texto de colores). |
| `GameAnim.cs` | Animaciones de una línea: `Pop`, `Shake`, `Pulse`, `Flip`, `Fade` y `Move`. |
| `<Juego>/<Juego>Controller.cs` | El controlador de cada juego, en su carpeta y con su namespace (`Sonia.Games.Wordle`...). Viene en esqueleto. |
| `Editor/SoniaGameCapture.cs` | La herramienta de capturas en batch (abajo). Solo editor. |

Los ids y las carpetas: `ruleta` (`Ruleta`), `poses` (`Poses`), `akinator` (`Akinator`), `piedra_papel_tijera` (`Ppt`), `wordle` (`Wordle`) y `busqueda` (`Busqueda`).

## Cómo llega un juego a la pantalla

1. `SoniaBootstrap` añade `GameRouter`, que añade `GameHud`, `CameraPreviewPanel` y un controlador por cada línea de `GameRegistry`, y le dice a `SoniaClient` qué anunciar: `client_hello` lleva `"games": [ids]` y `"features": ["camera_preview"]`. Todo antes de conectar.
2. Llega `{"type":"game","game":"wordle","event":"start","seq":7,"data":{"title":"Wordle de tecnología",...}}`. El router abre la partida (si había otra en pantalla, la cancela) y el controlador abre la tarjeta común con `data.title`.
3. Los demás eventos del juego llegan al controlador solo con la partida abierta (el orquestador siempre manda `start` antes).
4. `end` (con `data.result`: `win`, `lose` o `cancel`) cierra la partida: el controlador retira su pantalla.
5. Tras reconectar, el orquestador repite sus fijos (el `start` de la partida y el último estado) con su `seq` original: lo que ya vio de esa partida se ignora. Si en 2,5 s tras el `hello` no vuelve nada de la partida, terminó sin conexión y se cancela en pantalla (como la trivia).
6. Mientras hay partida, Sonnia no saluda sola (`GreetingSuppressed`, como la trivia) y `StageScreen` aparta el QR y no saca la invitación a hablar.

Compatibilidad: una Unity anterior ignora `game`, `camera_preview` y los frames `SNCV` (no conoce el tipo ni la marca). Esta Unity con un orquestador anterior no recibe nada de eso y sigue igual; el orquestador anterior ignora `games` y `features` de `client_hello`.

## Escribir el controlador de tu juego

Tu carpeta ya tiene `<Juego>Controller : GameControllerBase`. Lo que toca:

| Método | Cuándo | Qué hacer |
|---|---|---|
| `OnStart(dataJson)` | `start`, con la tarjeta ya abierta y titulada | Leer lo tuyo de `data`, montar (la primera vez) y resetear tu pantalla en `Content` o `Layer`. |
| `OnGameEvent(evento, dataJson)` | Cada evento propio del juego | Pintarlo. Obligatorio. |
| `OnFinish(result, dataJson)` | `end` | Si tu final no salió ya con tus eventos, enséñalo (`Hud.ShowResult`). |
| `OnClosed()` | La pantalla se retiró, o empieza otra partida del mismo juego | Dejarlo todo como al principio y apagar lo que encendiste (marcas, poses de Sonnia...). |
| `ShowDefaultResult(result, dataJson)` | `end` con `win` o `lose` sin `Hud.ShowResult` antes | Por defecto, «¡GANASTE!» o «¡CASI!» unos 3,5 s; sobrescríbelo si tu juego lo enseña de otra forma. |

Al `end`, si ya enseñaste el resultado con `Hud.ShowResult`, la pantalla se funde en 0,6 s; si no, sale el resultado genérico; con `cancel`, fuera al momento.

Ayudas de la base:

- `ParseData<T>(dataJson)`: `data` a una clase tuya con `[JsonProperty("...")]` (Newtonsoft). Nunca devuelve null.
- `Send("wheel_stopped", new { segment = 3 })`: `game_event` al orquestador. Ids y eventos en minúsculas, cifras y `_`.
- `PlayReaction(clip, respaldo)` y `ShowEmotion(emoción, segundos)`: como la trivia (`QuickAction_vibe`, `actions-highFive_actionSuccess`, `actions-highFive_actionFail`...).
- `Content`: tu contenedor dentro de la tarjeta, bajo el título. `Layer`: tu capa a pantalla completa (1080x1920), encima de la tarjeta y de la vista en vivo y debajo del confeti. Se construyen una vez y se reutilizan; solo se ven mientras tu juego tiene la pantalla.
- `Hud`, `Preview`, `Router`, `Choreographer`, `Face`, `Title`, `IsActive`, `IsEnding` y `Log(...)`.

Ejemplo mínimo:

```csharp
using Newtonsoft.Json;

namespace Sonia.Games.Wordle
{
    public class WordleController : GameControllerBase
    {
        private sealed class GuessData
        {
            [JsonProperty("row")] public int Row;
            [JsonProperty("letters")] public string Letters;
            [JsonProperty("marks")] public string Marks;
        }

        public override string Id => "wordle";

        protected override void OnStart(string dataJson)
        {
            Hud.SetContentHeight(Id, 640f);   // o un LayoutGroup propio en Content
            BuildGridOnce(Content);
            ResetGrid();
        }

        protected override void OnGameEvent(string eventName, string dataJson)
        {
            if (eventName == "guess")
            {
                GuessData guess = ParseData<GuessData>(dataJson);
                PaintRow(guess);                // GameAnim.Flip por ficha
            }
        }

        protected override void OnClosed()
        {
            ResetGrid();
        }
    }
}
```

Reglas de pantalla:

- Pantalla vertical 1080x1920. Todo lo del juego va en la franja alta (la de la trivia y del panel de imágenes) y la cámara pasa al plano de panel para que Sonnia quede debajo: **no tapes su cara**. Los subtítulos de abajo quedan libres.
- En pantalla, «Sonnia». Lo que llega del orquestador pásalo por `GameUi.Plain` (TextMeshPro leería `<` y `>` como etiquetas).
- Construye por código con el kit de `Hud` (capa UI, sin raycast). Nada de prefabs ni de tocar la escena.
- Nada de `UnityEngine.Input` (solo el Input System nuevo) y C# 9.

## `GameHud`

| Qué | API |
|---|---|
| Estado | `IsBuilt`, `IsOpen`, `CurrentGame`, `HoldsTopStrip` (juego o vista en vivo en pantalla), `IsResultShown`, `IsCountdownRunning`, `CountdownRemaining`. Eventos `Opened(id)`, `Closed(id)`, `CountdownFinished`. |
| Ciclo | `Open(id, título)` y `Close(id)`. Ya los llama `GameControllerBase` en `start` y `end`. `Close` solo cierra si la pantalla es de ese juego. |
| Tarjeta | `Card`, `ContentOf(id)`, `LayerOf(id)`, `SetContentHeight(id, px)`, `SetTitle(texto, colores = true)` (mayúsculas, letras en los colores de Google), `SetCaption("RONDA 2 DE 6")`, `HeaderRight` (hueco a la derecha de la cabecera), `SetCardVisible(bool)`, `SetCardTop(fracción)`, `PopCard()` (rebote de ronda nueva), `RefreshLayout()`, `CardWidth` (960), `ContentWidth` (872). La tarjeta mide lo que su contenido. Va arriba (a 0,105 del alto) y, mientras se ve la vista en vivo, justo debajo de ella, salvo que el juego la coloque con `SetCardTop`. |
| Contador circular | `StartCountdown(segundos)`, `StopCountdown(ocultar = true)` (si no se oculta, se queda quieto donde iba), `PlaceCountdown(padre, ancla, posición, diámetro)`, `Countdown`. Por defecto cuelga de la esquina de arriba a la derecha de la tarjeta; verde, amarillo y rojo según se agota, y late en los 5 últimos segundos. Solo visual: el tiempo de verdad lo lleva el orquestador. |
| Rótulos | `ShowBanner(texto, color)` (salta sobre el borde de abajo de la tarjeta: «¡Correcto!» en `GameColors.Green`), `HideBanner()`. `ShowResult(título, marcador, frase, won)`: tarjeta final arriba, en lugar de la del juego (la vista en vivo se aparta mientras se ve); con `won`, dorada y con lluvia de confeti. `HideResult()`. |
| Confeti y destellos | `Burst(punto, cantidad, velocidad, ángulo)`, `BurstFrom(rect)`, `Sparkles(punto, n)`, `SparklesAt(rect, n)`, `Rain(segundos)`, `Celebrate()` (lo de ganar la trivia), `EffectsPoint(rect)`, `Effects`. Coordenadas de la capa de efectos: (0, 0) es el centro de la pantalla. |
| Cámara | Plano de panel automático: mientras hay juego o vista en vivo, la cámara sube y se aleja lo justo para que Sonnia quede debajo de lo que haya en la franja alta (`TopStripBottom`: la tarjeta o el resultado, la vista en vivo y lo reservado), interpolando entre dos planos calibrados con capturas para dejar unos 100 px entre lo de arriba y la coronilla de Sonnia: `(0, 0.08, -0.2)` con lo de arriba hasta 644 px (una tarjeta como la de la trivia) y `(0, 0.55, -1.43)` con la vista en vivo y la tarjeta hasta 1062 px. El margen es por la pose: el plano base sale de dónde tiene Sonnia la cabeza cuando llega el avatar y varía algo de una vez a otra. `ReserveTopStrip(px)` si tu `Layer` baja más que la tarjeta. `RequestPanelShot(Vector3 extra)` fija otro desplazamiento (metros: y sube, z negativo aleja) y `RequestPanelShot()` vuelve al automático; `Open` y `Close` ya lo piden y lo sueltan. |
| Kit | `DisplayFont` (Manrope ExtraBold, la de la pantalla del stand), `BodyFont` (Manrope SemiBold), `MonoFont` (Geist Mono). `NewRect`, `NewImage`, `NewRound(nombre, padre, color, radio)`, `NewText(nombre, padre, texto, tamaño, color, alineación, fuente)`, `NewGroup`, `SetRadius(image, radio)`. Sprites: `RoundSprite` (radio 36, cortado en 9), `FrameSprite` (solo el contorno), `GlowSprite`, `DotSprite`, `RingSprite` (con `Image.Type.Filled` hace de arco), `CheckSprite`, `CrossSprite`, `StarSprite`, `SparkleSprite`, `PieceSprite`. |

## `CameraPreviewPanel` (vista en vivo)

Sale sola con el primer frame `SNCV` tras `camera_preview` encendido y se retira con `on: false` o a los 2 s sin frames. Muestra siempre el último (los de `seq` menor se descartan en el cliente) y decodifica como mucho uno por fotograma en una sola textura (`Texture2D.LoadImage`, hilo principal). Con `mirror: true` y un frame que no viene ya en espejo, se voltea aquí; si la imagen no es 16:9, se recorta al centro. Unity no guarda nada.

| Qué | API |
|---|---|
| Estado | `IsVisible`, `IsOn`, `FramesShown`, evento `VisibilityChanged(bool)`. |
| Piezas | `Frame` (el marco 16:9), `Overlay` (encima de la imagen, del tamaño del marco y sin recortar: tus marcas), `Root`. |
| Colocación | Por defecto 960 px de ancho y arriba a 0,105 del alto, como la tarjeta. `SetPlacement(fracción de arriba, ancho)` para agrandarla (las poses), `ResetPlacement()`, `FrameSize`, `BottomFraction` (para poner la tarjeta debajo: `Hud.SetCardTop(Preview.BottomFraction + 0.02f)`). Al retirarse vuelve a su sitio. |
| A mano | `Hide()`; `Suppressed` la aparta sin dejar de recibir frames (lo usa el resultado final). `HandleSwitch`, `HandleFrame` y `HandleReconnect` los llama el router. |

Los esqueletos y las marcas de la cámara los dibuja el orquestador sobre la imagen; lo que va en `Overlay` son las piezas de pantalla (pictograma, contador...).

## `GameColors`, `GameUi` y `GameAnim`

- `GameColors`: `Blue`, `Red`, `Yellow`, `Green` y `Google` (los cuatro), `CardFill`, `CardBorder`, `OptionFill`, `RightFill`, `WrongFill`, `Muted` (los de la trivia), `Navy`, `Brand`, `Dark` (la marca), `Live` y `Gold`.
- `GameUi`: `Stretch`, `PlaceTop(rect, fracción, tamaño)`, `PlaceCenter`, `WithAlpha`, `ColoredWord`, `Plain`, `EaseOutBack`, `EaseOutCubic`, `EaseInCubic`, `EaseInOutSine`.
- `GameAnim`: `Pop(rect, duración, retraso)`, `Shake(rect)`, `Pulse(rect, cantidad)`, `Flip(rect, alMedio, duración, retraso)` (se aplasta, llama a `alMedio` para cambiar color o letra y se abre: las fichas del Wordle), `Fade(group, a, duración)`, `Move(rect, a, duración)` y `Stop(componente)`. Van con `Time.deltaTime`.

## Capturas en batch

Cada pantalla se verifica con capturas 1080x1920 de la cámara principal, en Play y con el HUD, conducidas por el orquestador falso de tu juego (`server/sonia/games/<paquete>/demo.py`, `docs/juegos.md`). Unity corre en batch sobre un **clon APFS** del proyecto de la copia principal (allí están los assets de Genies, que git ignora): el editor abierto no se toca nunca.

### Con el script (lo normal)

Desde tu worktree, con tu secuencia ya escrita:

```bash
SONIA_UNITY_LOCKS=$SP/unity-locks \
  scripts/juegos_capturas.sh --juego wordle --puerto 8791 \
    --clon $SP/f0unity/clon --salida <tu scratchpad>/capturas-wordle
```

- `$SP` es el scratchpad de la sesión principal (donde están los candados y el clon compartido) y la salida va en tu scratchpad, nunca en `unity/Temp` ni en el repo. Un puerto distinto por agente.
- **Clon compartido.** Todos usan el mismo clon (`--clon`, o `SONIA_UNITY_CLONE`): cada clon nuevo acaba ocupando gigas, porque Unity reescribe `Library` al compilar. El script no crea uno nuevo si no se le pide con `SONIA_UNITY_NEW_CLONE=1`. Cada pasada le copia al clon los scripts de quien la lanza (`rsync --delete`, sin tocar los `.meta`) y Unity recompila: la primera tras otro agente tarda unos 2 minutos. Por eso tu rama tiene que traer la herramienta (si no, el script te pide juntar `juegos/base`).
- El script no arranca con menos de 5 GB libres (`SONIA_MIN_FREE_GB`), espera si otro Unity tiene abierto el clon (alguien sin candado) y borra antes `Library/ilpp.pid` y un `Temp/UnityLockfile` que haya quedado de una pasada cortada.
- Deja en la salida `<name>.png` por cada `Capture`, `capturas.txt`, `unity.log` y `orquestador.log`. Cada línea de `capturas.txt` dice el instante, el juego en pantalla, si había vista en vivo, el plano de cámara y dónde acaba lo de la franja alta frente a la coronilla de Sonnia, en px desde arriba; si algo le tapa la cabeza, lo avisa con «¡LO DE ARRIBA TAPA LA CABEZA DE SONNIA!».
- Código de salida: 0 con `dev_done`; 2 argumentos; 3 tiempo agotado (`--timeout`, 600 s); 4 Unity salió de Play; 5 error en la herramienta; otro, el de Unity (por ejemplo, scripts que no compilan: mira `unity.log`). Si el orquestador falso termina sin `dev_done` (un paso roto: mira `orquestador.log`), el script cierra Unity a los 20 s.
- Con `--juego ejemplo` corre la secuencia de ejemplo de `juegos_demo.py` (la pantalla común con la vista en vivo), útil para probar la receta antes de tener la tuya.
- **Revisa las capturas tú**, abriéndolas. Manos, cara y animaciones se validan con varias capturas seguidas, no con una suelta.

### Paso a paso, a mano

Lo mismo que hace el script:

1. **Turno.** Como mucho dos Unity en batch a la vez en la máquina: `mkdir $SP/unity-locks/1` (o `.../2` si el 1 existe; si existen los dos, espera con `until mkdir ...; do sleep 30; done`). Bórralo al terminar, también si falla.
2. **Clon.** Usa el compartido. Solo si no hay ninguno y sobra disco: `cp -cR <copia principal>/unity <clon>/unity` (APFS: instantáneo, pero Unity reescribe gigas de `Library` al compilar), `rm -rf <clon>/unity/Temp <clon>/unity/Logs`. Nunca dos Unity a la vez sobre el mismo clon.
3. **`rm -f <clon>/unity/Library/ilpp.pid`.** Si no, el Unity del clon mata el compilador (IL Post Processing) del editor de verdad y este se cierra.
4. **Tus scripts:** `rsync -a --delete --exclude '*.meta' <worktree>/unity/Assets/Scripts/ <clon>/unity/Assets/Scripts/`. Los `.cs` nuevos van sin `.meta`: Unity los genera en el clon. Antes, `$SP/compila_sonia.sh <worktree>` tiene que acabar en «Todo compila».
5. **Orquestador falso**, desde `server/`: `uv run --no-sync python ../scripts/juegos_demo.py --juego wordle --puerto 8791 &` (apunta su PID).
6. **Unity en batch** (sin `-nographics`: hace falta GPU):

   ```bash
   UNITY_MCP_DISABLE_BATCH=1 /Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity \
     -batchmode -projectPath <clon>/unity \
     -executeMethod Sonia.EditorTools.SoniaGameCapture.Run \
     -sonia-ws ws://127.0.0.1:8791 -sonia-captures <salida> \
     -logFile <salida>/unity.log &
   ```

   Opcionales: `-sonia-capture-timeout <s>` (600) y `-sonia-avatar-timeout <s>` (60).
7. Espera a que salga Unity; luego **cierra por PID** el orquestador falso (y Unity si no salió), comprueba con `ps` que no queda nada (`pgrep -fl "projectPath <clon>"`) y suelta el candado.

### Qué hace la herramienta (`Editor/SoniaGameCapture.cs`)

- Abre `SampleScene`, deja `SoniaClient` sin conectar y la webcam de Unity apagada, y entra en Play.
- En Play ata la cámara principal a una RenderTexture fija de 1080x1920 y la cámara del HUD a otra igual: el encuadre y los Canvas se calculan con la proporción de la pantalla del stand, sea cual sea la «pantalla» del modo batch. Los Canvas en Overlay pasan a Screen Space - Camera sobre la cámara del HUD.
- Espera al avatar de Genies (como mucho `-sonia-avatar-timeout`; si no llega, sigue con el doble) y a su camiseta de staff, que se hornea aparte (como mucho 20 s más), a que la pantalla del stand esté montada y 2,5 s de calma, y entonces conecta `SoniaClient` a `-sonia-ws`: el orquestador falso empieza al recibir el `client_hello`.
- Cada `dev_capture` renderiza la escena con la cámara principal, encima el HUD (su cámara aparte, sobre transparente, compuesto con alfa premultiplicado como lo mezcla la UI) y guarda `<name>.png`. Lo que llegue detrás del `dev_capture` espera a que la captura esté hecha (`SoniaClient.PauseDispatch`): la captura ve todo lo anterior y nada de lo siguiente. `dev_done` sale con código 0.
- Para tus pruebas, el resto del protocolo funciona igual que con el orquestador de verdad (`speech_start`, `transcript`, `state`, `play_animation`...): mándalo con `Send` en tu secuencia.

### Comprobación de la pantalla común

Sin orquestador, recorre la tarjeta, el contador, el rótulo con confeti, el resultado, el cierre y la vista en vivo con una foto (`hud-*.png`):

```bash
SONIA_UNITY_LOCKS=$SP/unity-locks \
  scripts/juegos_capturas.sh --hud-check --foto foto16x9.jpg --salida $SP/capturas-hud
```

La foto, pública (Wikimedia Commons, CC0) o sintética, en tu scratchpad: nunca la cámara de nadie.

### Problemas conocidos

- `ArgumentOutOfRangeException` de `UnityEditor.Search.SearchDatabase` en el registro: ruido del modo batch, ajeno a Sonia.
- Si Unity no llega a Play (scripts que no compilan), sale sola o la mata el vigilante del script a los `--timeout` + 180 s. Mira `error CS` en `unity.log`.
- No llames a `AssetDatabase.SaveAssets()` después de Play: reescribe `QualitySettings.asset`.
