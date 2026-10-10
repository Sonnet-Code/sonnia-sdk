# Prompts de Sonnia editables desde la nube

Petición de Jean del 10 de octubre de 2026: poder editar él mismo, desde el backoffice y sin instalar nada, todos los textos que se les dan a los modelos de Sonnia. Al arrancar, si un prompt tiene versión en la nube, Sonnia usa solo esa, nunca las dos juntas, para no darle información doble.

## Dónde se edita

En el panel (sonia.sonnetcode.com, o el local de cada Sonnia), sección plegada **Developer**, tarjeta **«Prompts de Sonnia»**:

1. «Cargar prompts» trae la lista de piezas de la Sonnia elegida.
2. Se elige el grupo y la pieza. La marca «nube» o «app» dice cuál está en uso. Si la versión de la nube no valida, se ignora y sale avisada.
3. Se edita en el cuadro y se pulsa «Guardar en la nube». Vale para todas las Sonnias actualizadas.
4. «Volver al de la app» borra la versión de la nube de esa pieza. «Ver el de la app» carga el texto de la app en el cuadro, sin guardar.

Los editores de los bancos (trivia y juegos) también están en Developer. El modo fácil queda para el equipo del stand. «Avisos de hoy para Sonnia» sigue en el modo fácil: es la nota del día, y se suma a todo lo demás en vez de sustituir nada.

## Cómo funciona

- **Registro** (`server/sonia/prompts`). Cada pieza es un `PromptSpec`:
  - `id`, estable: `grupo/nombre`, por ejemplo `juez/busqueda` o `conocimiento/04-sonnet-code`;
  - el grupo y el título del panel;
  - el texto de la app (`default`), perezoso;
  - los marcadores que rellena el código (`fields` y `required`);
  - los textos que el código necesita que sigan ahí (`must_contain`, por ejemplo «JSON» en los jueces);
  - y cuándo se nota un cambio (`applies`).
- **Uso en el código:** `BOOK.text(id, fallback)` o `BOOK.render(id, fallback=..., **valores)`, siempre con el texto de la app como `fallback`. Si algo falla en el registro, Sonnia sigue con el de la app.
- **Nube:** el ajuste compartido `prompts` (`{id: texto}`, solo las piezas cambiadas) viaja como los demás ajustes compartidos. Lo guarda el Durable Object del panel y llega a todas las Sonnias.
  - Una Sonnia aplica las versiones que validan para su app.
  - Las de piezas que no conoce, porque las guardó una Sonnia más nueva, se guardan sin usarse.
- **Marcadores:** `{nombre}` en minúsculas. Solo se sustituyen los que declara la pieza. Las llaves de los JSON de ejemplo de los jueces (`{"visto": true}`) no son marcadores y se quedan tal cual.

## Qué se comprueba antes de guardar

Un texto no se guarda, y el panel dice por qué, si:
- está vacío (para eso está «Volver al de la app»);
- pasa del tope de su pieza (60 000 caracteres por defecto; las reglas que van por `instructions.append` a GPT-Live, 1 200);
- lleva marcadores que el código no rellena, o le falta alguno obligatorio;
- ha perdido un texto que necesita el código (por ejemplo «JSON» en un juez).

Además, todos los ajustes compartidos juntos tienen que caber en la nube (`SHARED_SETTINGS_MAX_CHARS`, 250 000 caracteres, por debajo de los 256 KB del Durable Object).

## Cuándo se nota un cambio

| `applies` | Piezas | Cuándo |
|---|---|---|
| `sesion` | Persona, conocimiento, reglas de GPT-Live, backend | En la próxima conversación: sesión nueva de GPT-Live |
| `ronda` | Trivia y juegos | En la próxima ronda o partida |
| `peticion` | Juez, gestos, visión | En la próxima petición a ese modelo |

## No regresión

Con los textos de la app, lo que reciben los modelos es idéntico, byte a byte, a lo de antes del editor:
- `tests/test_prompts_referencia.py` compara las instrucciones de GPT-Live y del backend en 8 configuraciones, la visión, los gestos y los jueces con `tests/data/prompts_referencia.json`, sacada antes del editor (commit 441157a).
- Los juegos y la trivia tienen sus instantáneas en sus propios tests.

Si se cambia a propósito un texto de la app, se regeneran las referencias.

## Piezas comunes de los juegos

Además de las de cada juego (`juegos/<juego>/…`), el `GameManager` registra dos para todos (grupo «Juegos», `prompt_specs()` en `server/sonia/games/manager.py`):

- `juegos/seguir_sonnet_code`: va delante del guion de arranque de cada juego cuando se empieza por voz sin saber si sigue a Sonnet Code (`docs/juegos.md`, «Seguir a Sonnet Code antes de jugar»). Termina en «sigue este guion:» y detrás va el del juego.
- `juegos/ya_nos_sigue`: lo que se le dice a Sonia cuando el equipo pulsa «Ya nos sigue» en el panel (`{spoken}`: el nombre del juego).

## Añadir una pieza nueva

1. El texto de la app se queda en su módulo, como constante o archivo.
2. Se registra en `server/sonia/prompts/specs_conversa.py` (conversación) o `specs_modelos.py` (modelos y juegos), dentro de `register_all()`, con su `default` perezoso: importa el módulo dentro de la función, para no crear ciclos.
3. Donde se usa, se pide con `BOOK.text` o `BOOK.render`, pasando la constante como `fallback`.
4. Se añade su instantánea a los tests.
