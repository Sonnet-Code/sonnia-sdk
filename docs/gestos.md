# Gestos al hablar

Sonnia gesticula al hablar con los gestos del personaje Sage del chat de Genies (162 clips, ver `gestos-genies/README.md`). En Genies, el LLM que escribe la respuesta elige los gestos de una lista con una ficha por gesto (`llmMetadata`) y su backend los alinea con la voz (`docs/informe-mia.md`, apartados 5.2 y 5.3). Aquí la voz la genera GPT-Live, que habla voz a voz y no escribe etiquetas, así que el trabajo se reparte en dos:

- **El orquestador elige** (el director de gestos): un modelo de texto ligero lee lo que va diciendo Sonia y elige el gesto de cada frase.
- **Unity reproduce** (la capa de gestos): manda su catálogo al conectar y lanza cada gesto sobre la frase que acompaña.

Se hablan con dos mensajes del protocolo (`docs/protocolo.md`): `gesture_catalog` (Unity → orquestador, al recibir `hello`) y `gesture` (orquestador → Unity, con el `utterance_id` de la frase o `null` para la próxima).

## Orquestador: el director de gestos

Código en `server/sonia/gestures/`:

| Archivo | Qué hace |
|---|---|
| `catalog.py` | El catálogo que manda Unity (`gesture_catalog`), con la ficha de cada gesto. |
| `prompt.py` | El prompt (parte fija y mensaje de cada llamada) y el parser de la respuesta. |
| `director.py` | `GestureDirector`: cuándo pedir, las reglas de frecuencia, los plazos, el relleno y el registro. |

`sonia run` (y `sonia reunion`) lo monta en `cli.build_components` con su propio `LLMClient` y se lo pasa a `LiveEngine`; `sonia chat` no lo usa. Sin clave para su modelo se apaga con un aviso en el registro que dice qué clave falta, y Sonia habla igual, sin gestos elegidos.

### Cuándo pide un gesto

- **Apertura.** Al cerrarse el turno del visitante (texto final de la transcripción, o un `text_input` escrito) se pide un gesto con lo que dijo, mientras GPT-Live prepara la respuesta. Va con `utterance_id: null` y Unity lo lanza con la siguiente frase no ambiental (lo guarda hasta 4 s). Esa primera frase ya no pide otro. Si la respuesta del modelo llega cuando Sonia ya empezó a hablar, el gesto va con el `utterance_id` de esa frase; si esa frase ya terminó, se tira. Si el visitante sigue hablando tras mandarse la apertura, la que tiene guardada Unity sigue valiendo hasta que llegue otra (gana la última) o pasen 4 s.
- **Por frase.** En cada `speech_start` no ambiental, en cuanto el texto de la frase llega a `GESTURE_TRIGGER_CHARS` (20) caracteres o pasan `GESTURE_TRIGGER_S` (0,5 s), lo primero. La transcripción de la voz de Sonia llega casi a la vez que el audio, así que normalmente decide el texto.
- **Como mucho una petición en vuelo.** Si una frase se dispara con otra petición en marcha, espera a que termine y entonces pide (si aún llega a tiempo).
- **Nunca** en las frases `ambient` (animación de stand, «Solo saludos»), sin sesión de GPT-Live («Solo saludos», «Fuera», modo debug, editor de personaje, Modo Jean), sin Unity conectado, sin catálogo o con `GESTURES_ENABLED=false`.
- Si Sonia empieza a contestar antes de que el orquestador dé por cerrado el turno del visitante (GPT-Live es rápido), no hay apertura: la frase pide su gesto con lo que el visitante iba diciendo.

### Qué lee el modelo

**Parte fija** (mensaje de sistema). Va primero y es idéntica en todas las llamadas mientras no cambie el catálogo, para que el servidor la sirva de su caché de prompts:

1. El papel: director de gestos de Sonnia, asistente virtual del staff del DevFest Santo Domingo 2026 creada por Sonnet Code, cercana y profesional ante un público de desarrolladores.
2. Cómo elegir:
   - que encaje con lo que dice ahora y con su intención;
   - «ninguno» es normal: no hace falta gesticular en cada frase;
   - Standard con normalidad, Uncommon solo si encaja claramente, Rare solo si el momento es justo ese;
   - HighImpact solo en momentos enfáticos;
   - Instant y Short para frases cortas, Long para explicaciones largas;
   - respetar USE / DO NOT USE;
   - nada de coqueteo, burla, sarcasmo ni agresividad (intenciones Flirt, Mock, Intimidate; estilos Flirty, Cocky) salvo que el visitante lleve claramente la broma;
   - no repetir los recientes ni usar los no disponibles;
   - los de relleno son casi neutros;
   - en la apertura, un gesto para cómo va a reaccionar Sonnia.
3. El formato de respuesta: `{"gesto": "<nombre>"}` o `{"gesto": "ninguno"}`.
4. El catálogo, una línea por gesto: nombre · frecuencia, duración, impacto, intensidad (y «relleno» si es de `Utility_NoImpact`) · descripción · intenciones · estilo (las etiquetas `personality:`) · reglas USE / DO NOT USE.

```
- handOnChest · Uncommon, Short, LowImpact, intensidad 1 · Hand over chest, solemn (sincerity/pledge) · intención: Comfort, Appreciate · estilo: Earnest · USE: Used to indicate ... DO NOT USE: Should not be used sarcastically or ironically
```

Con los 162 gestos de Sage la parte fija ocupa unos 34 500 caracteres, unos 8 500 tokens [Estimación: casi todo es inglés, unos 4 caracteres por token].

**Mensaje de cada llamada** (usuario), unos 100 tokens:

```
Frase 2 de la respuesta de Sonnia; lleva 0.6 s sonando.
Visitante: «¿Qué es Sonnet Code y qué hacen?»
Sonnia ya ha dicho: «¡Claro que sí!»
Frase actual: «Sonnet Code es una empresa de software»
Gestos recientes: noBigDeal hace 12 s
Ahora no disponibles: los Rare (hasta dentro de 3 min); noBigDeal (usados hace poco).
¿Qué gesto hace ahora? Responde solo con {"gesto": "..."}.
```

En la apertura cambian la primera línea («Apertura: el visitante acaba de hablar y Sonnia aún no ha empezado a contestar») y no hay frase actual. Lo que ahora no se puede usar por las reglas de frecuencia se le dice aquí, no en la parte fija, para no romper la caché.

**Respuesta.** El parser busca el primer objeto JSON (también dentro de ```` ``` ````) y su campo `gesto`; si no hay JSON, mira si contestó solo un nombre. Los nombres se buscan sin mirar mayúsculas. «ninguno», `null` o vacío es sin gesto. Un nombre que no está en el catálogo o un texto suelto cuentan como «ninguno» (contador `unknown`).

### Reglas de frecuencia

Se le piden al modelo y además se aplican en código: si elige un gesto que no toca, se tira (contador `vetoed`) y la frase se queda sin gesto.

| Regla | Valor por defecto |
|---|---|
| Un gesto no empieza hasta que acaba el núcleo del anterior: inicio del anterior + `core_stop` + `GESTURE_MIN_GAP_S`. Si llega antes, espera; si esperar le haría pasarse del plazo de su frase, se tira. Si a la frase ya no le da tiempo, ni se pide. | 0,5 s de margen |
| Como mucho un gesto por frase (el de apertura cuenta para la primera). | |
| El mismo gesto no se repite antes de `GESTURE_REPEAT_S`. | 90 s |
| Como mucho un `Uncommon` cada `GESTURE_UNCOMMON_S`. | 45 s |
| Como mucho un `Rare` cada `GESTURE_RARE_S`. | 300 s |
| Lo que llegaría más de `GESTURE_MAX_DELAY_S` después de empezar su frase, o con la frase ya terminada, se tira (como hace Genies con lo que llega tarde). | 2,5 s |
| Una interrupción (`interrupt`, «Callar a Sonia») o el fin de la sesión cancelan lo pendiente. Al salir de `speaking` Unity corta el gesto, así que el siguiente puede empezar ya. | |

### Plazos y relleno

- Cada petición tiene de tope `GESTURE_TIMEOUT_S` (3 s). Con la frase ya sonando, el tope es además lo que le quede hasta `GESTURE_MAX_DELAY_S` menos 0,1 s: después ya no serviría.
- Si el modelo falla (error, red, 429) o agota la espera, va un gesto de **relleno**, si `GESTURE_FALLBACK=true`. Es un gesto de la lista `Utility_NoImpact` al azar (Standard pesa 6, Uncommon 2 y Rare 1), sin repetir el último y respetando las reglas de frecuencia. Si el modelo contesta «ninguno», no hay relleno.
- Nada de lo que pase con el modelo tumba el motor: se registra y se sigue. Las peticiones corren en una tarea aparte; el motor solo llama a métodos síncronos y baratos del director.

### Modelo y esfuerzo de razonamiento

Dos opciones, que se eligen por variables de entorno (plantilla comentada en `.env.example`):

- **Por defecto con `GEMINI_API_KEY`: Gemini** por su endpoint compatible con OpenAI, con `gemini-3.1-flash-lite`, el que usa Genies para sus prompts auxiliares. Si está la clave y no se ponen `GESTURE_BASE_URL` ni `GESTURE_MODEL`, no hay que poner nada más. Medido el 6-oct-2026 con `sonia check`: **0,9-1,5 s** por petición.
- **Sin `GEMINI_API_KEY`: el modelo de los ojos.** Mismo servidor, modelo y clave que el modelo de visión (`LLM_*`: `gpt-6-luna` en la API de OpenAI con `OPENAI_API_KEY`). Funciona y acepta `none`, pero tarda **3,8-4,5 s** por petición (medido igual), más que el tope de 3 s: muchas frases acabarían con un gesto de relleno.

Para forzar Gemini con otra configuración:

```
GESTURE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GESTURE_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=<clave de Google AI Studio>
```

Si `GESTURE_BASE_URL` es la API de Gemini y no hay `GESTURE_API_KEY`, se usa `GEMINI_API_KEY`. Cualquier otro servidor compatible con OpenAI vale con `GESTURE_BASE_URL`, `GESTURE_MODEL` y `GESTURE_API_KEY`. Las claves no salen de su servidor: con otro servidor que el de visión no se heredan su clave, su temperatura ni sus campos extra; la clave de OpenAI solo va a la API de OpenAI y la de Gemini solo a la de Gemini.

Lo que se manda se ajusta solo a cada servidor (lo vacío; cada variable lo cambia):

| | OpenAI | Gemini 3 (3.1 Flash-Lite...) | Gemini 2.5 | Mismo servidor que `LLM_*` | Otro servidor |
|---|---|---|---|---|---|
| `reasoning_effort` (`GESTURE_REASONING_EFFORT`) | `none` | `minimal` | `none` | `LLM_REASONING_EFFORT` | `off` (no se manda) |
| Tope de tokens (`GESTURE_MAX_TOKENS`) | 64 | 512 | 64 | 64 con `none`, si no 512 | 64 con `none`, si no 512 |
| Nombre del tope (`GESTURE_MAX_TOKENS_PARAM`) | `max_completion_tokens` | `max_tokens` | `max_tokens` | `LLM_MAX_TOKENS_PARAM` | `max_tokens` |
| Campos extra (`GESTURE_EXTRA_BODY`) | ninguno | ninguno | ninguno | `LLM_EXTRA_BODY` | ninguno |

Por qué:

- **OpenAI, `none`.** En `gpt-6-luna` es el modo sin razonar: unos 0,74 s hasta la primera palabra frente a 1,59 s con `low` (`docs/informe-vision.md`, dato de terceros). Elegir un gesto de una lista no necesita razonar, y llegar tarde es peor que fallar.
- **Gemini 3, `minimal`.** Según la documentación de su compatibilidad con OpenAI, los Gemini 3 no dejan apagar el razonamiento (`none` solo vale en los 2.5) y `minimal` es el nivel más bajo de 3.1 Flash-Lite y 3 Flash. Sin el campo (`off`), el modelo razonaría a su nivel por defecto: más lento.
- **El tope de Gemini incluye lo que razona.** Por eso se le dan 512 tokens: con 64 podría gastarlos razonando y contestar vacío. El tope no cuesta nada si no se usa.
- **`max_tokens` con Gemini.** Es el nombre clásico que entiende su endpoint; OpenAI pide `max_completion_tokens` en sus modelos que razonan.
- **No se mezcla `reasoning_effort` con `thinking_config`.** En Gemini, `thinking_level`/`thinking_budget` se mandan dentro de `extra_body` y no se pueden usar a la vez que `reasoning_effort`. Para eso: `GESTURE_REASONING_EFFORT=off` y `GESTURE_EXTRA_BODY='{"extra_body": {"google": {"thinking_config": {"thinking_level": "minimal"}}}}'`. No hace falta con los valores por defecto.
- **Con un modelo que no acepte `none`** (uno sin razonamiento, por ejemplo), `GESTURE_REASONING_EFFORT=off`.

Se pide sin streaming (`LLMClient.complete`, con `Accept: application/json`) y sin reintentos. Si el modelo agota el tope razonando y contesta vacío, cuenta como fallo (va el relleno) y el registro dice qué variable tocar.

`sonia check` hace una petición mínima con los ajustes reales (línea «Gestos»), igual que con el modelo de visión, y enseña lo que tardó y los tokens que gastó razonando si el servidor lo dice. Si el servidor rechaza el esfuerzo de razonamiento, el tope o la clave, o si contesta vacío, sale como AVISO: no impide abrir el stand.

### Variables

| Variable | Defecto | Qué hace |
|---|---|---|
| `GESTURES_ENABLED` | `true` | `false` apaga el director: sin peticiones ni gasto. |
| `GESTURE_MODEL` | `LLM_MODEL` | Modelo que elige los gestos. |
| `GESTURE_BASE_URL` | `LLM_BASE_URL` | Servidor compatible con OpenAI (Chat Completions). |
| `GESTURE_API_KEY` | la de `LLM_*` | Con la API de OpenAI basta `OPENAI_API_KEY`. |
| `GEMINI_API_KEY` | | La clave de Gemini, si `GESTURE_BASE_URL` es la API de Gemini y no hay `GESTURE_API_KEY`. |
| `GESTURE_REASONING_EFFORT` | según el servidor | Ver la tabla del apartado anterior; `off` no lo manda. |
| `GESTURE_MAX_TOKENS` | 64 o 512 | Tope de la respuesta (512 si el modelo razona). |
| `GESTURE_MAX_TOKENS_PARAM` | según el servidor | `max_tokens` o `max_completion_tokens`. |
| `GESTURE_EXTRA_BODY` | | Campos extra del cuerpo, en JSON. |
| `GESTURE_TIMEOUT_S` | `3` | Tope de cada petición. |
| `GESTURE_TRIGGER_CHARS` | `20` | Caracteres de la frase con los que se pide su gesto... |
| `GESTURE_TRIGGER_S` | `0.5` | ... o segundos desde que empezó, lo primero. |
| `GESTURE_MIN_GAP_S` | `0.5` | Margen tras el núcleo del gesto anterior. |
| `GESTURE_MAX_DELAY_S` | `2.5` | Más tarde que esto desde el principio de su frase, se tira. |
| `GESTURE_REPEAT_S` | `90` | Sin repetir el mismo gesto. |
| `GESTURE_UNCOMMON_S` | `45` | Un `Uncommon` como mucho cada tanto. |
| `GESTURE_RARE_S` | `300` | Un `Rare` como mucho cada tanto. |
| `GESTURE_FALLBACK` | `true` | Relleno si el modelo falla o no llega. |

### Registro y panel

Una línea por decisión en el registro (`sonia.gestures.director`), con la frase (su `utterance_id`), la latencia y los tokens que da el servidor (y los que gastó razonando, si lo dice):

```
Gesto explain (frase 12, 0.84 s, 8123 tokens, 7936 en caché + 9 de salida): Sonnet Code hace software a medida…
Sin gesto (frase 13, 0.71 s, 8130 tokens, 7936 en caché + 9 de salida): ¡Gracias!
Gesto de apertura wave (0.92 s, 8101 tokens, 7936 en caché + 9 de salida)
Gesto shrug vetado por frecuencia (frase 14)
Gesto pointOut descartado (frase 15): llegaría 2.7 s después de empezar su frase
El modelo de gestos falló (no contestó en 1.9 s); relleno noImpact02 (frase 16)
```

«en caché» dice si la caché de prompts funciona: debería ser casi toda la entrada desde la segunda petición. El estado del panel trae los contadores en `gesture_director` (`docs/panel.md`); la página aún no los muestra.

### Coste

[Estimación] Por petición entran unos 8 600 tokens (la parte fija y unos 100 de la frase) y salen unos 10, más lo que razone con Gemini. Entre 6 y 12 peticiones por minuto de conversación: una apertura por turno y una por frase, aunque muchas frases no piden porque el gesto anterior sigue en su núcleo.

| | `gpt-6-luna` (OpenAI) | `gemini-3.1-flash-lite` |
|---|---|---|
| Precio por millón de tokens: entrada / en caché / salida | 0,10 / sin apuntar / 0,50 USD (`docs/informe-vision.md`) | 0,25 / 0,025 / 1,50 USD (precios de pago de Google, 6 de octubre de 2026) |
| Por petición, sin caché | ~0,0009 USD | ~0,002 USD |
| Por hora de conversación seguida, sin caché | 0,3 a 0,6 USD | 0,8 a 1,6 USD |
| Por hora, con la parte fija en caché | menos de 0,1 USD si el descuento es el habitual del 90 % | 0,15 a 0,3 USD |

- **La caché de prompts es automática en los dos.** OpenAI cachea el principio común de las peticiones. Gemini tiene caché implícita desde los 2.5, a partir de unos 4 096 tokens de prefijo común en los Flash: la parte fija pasa de sobra. El registro dice en cada línea cuántos tokens salieron de la caché, si el servidor lo cuenta.
- **En comparación:** GPT-Live cuesta 3 USD por hora. Gemini Flash-Lite tiene además un nivel gratuito, con límites, para probar.
- **Sin nadie conversando no gasta:** no hay frases. Tampoco gasta en «Solo saludos» ni en «Fuera».

Lo que hay que vigilar es el límite de tokens por minuto de la cuenta, más que el dinero: son de 50 000 a 100 000 tokens por minuto mientras alguien conversa. Si la API responde 429, cada frase cae al relleno y el registro lo dice.

### Cómo se engancha en el motor

`LiveEngine` recibe el director por el constructor (`gestures=`), registra `gesture_catalog` en el hub y le cuenta:

| Método | Cuándo lo llama el motor |
|---|---|
| `on_catalog(msg)` | Llega `gesture_catalog` de Unity. |
| `on_session(live)` | Se abre o se cierra la sesión de GPT-Live (`_begin_session`, `_end_session`). |
| `on_user_turn(text, answering=...)` | Se cierra el turno del visitante (`_finish_user_turn`) o llega un texto escrito (`submit_text`). `answering` dice si Sonia ya está hablando. |
| `on_speech_start(uid, ambient=..., text=..., user_text=...)` | Se abre una frase (`_open_segment`). |
| `on_assistant_text(uid, text)` | Llega más transcripción de la frase (`_on_output_transcript`). |
| `on_speech_end(uid, text)` | Se cierra la frase (`_close_segment`). |
| `on_interrupt()` | Interrupción (`_on_interrupt`). |
| `on_state(state)` | Cambia el estado del avatar (`_set_state`). |
| `snapshot()` | El estado del panel (`LiveEngine.snapshot`). |

Pruebas en `server/tests/test_gestures.py`, con un modelo falso y sin red. Entre otras: el catálogo, el prompt, las reglas de frecuencia, lo que llega tarde, la apertura con `utterance_id` null, el relleno cuando falla el modelo, que las frases ambientales no llevan gesto, que sin catálogo no se hace nada y el motor de punta a punta con el GPT-Live falso.

## Unity: la capa de gestos

Unity reproduce los gestos tal cual los guarda Genies. Detalle en
`docs/unity.md`, «Gestos de hablar de Genies (Sage)».

### Los clips y el catálogo

- **Los clips:** `unity/Assets/Animations/GeniesSage/ozz/` tiene los 162
  `runtimeOzz` de Sage. Los baja `scripts/gestos_genies/descarga_ozz.py` del
  CDN de Genies, con su `manifest.json`.
- **El set:** **Sonia > Gestos de Genies > Crear set de Sage** crea
  `SageGestureSet.asset` con 161 gestos y la ficha de cada uno. La emoción
  `Happy` queda fuera porque está vacía.
- **El catálogo:** Unity lo manda al orquestador en `gesture_catalog` al
  recibir `hello`. Al panel le añade los 161 en `animations`, grupo `sage`.

### El formato y cómo se aplica

- **Formato:** cada `.ozz` es un ozz-animation 0.15 con un envoltorio de
  Genies, en `gestos-genies/README.md` y `scripts/gestos_genies/ozz_genies.py`.
- **Qué guarda:** la diferencia de cada hueso con la pose de enlace del cuerpo.
- **Cómo se aplica:** `GeniesGestureLayer` hace lo mismo que el motor de
  Genies con cualquier cuerpo, `rotación local = enlace de Sonnia · clip`, sobre
  el torso: columna, cuello, cabeza, brazos, manos y dedos.
- **Cuándo corre:** en `LateUpdate`, antes del pelo, la mirada y la cara.
- **Fundidos:** entra y sale con el fundido de Sage (0,8 s, curva suave).
- **Cara:** pasa a `FaceRig` las curvas de cejas, párpados y mejillas de cada
  gesto.

| Comprobación | Resultado |
|---|---|
| Lector de Python contra el motor web de Genies (11 gestos) | 0,65° como máximo |
| Lector de C# contra el de Python (972 muestras de los 162 clips) | 0,0000° |
| Hojas de contactos de los 161 gestos sobre Sonnia (**Hojas de contactos (en Play)**) | Todos naturales |
| Orquestador falso con frases grabadas: apertura, gesto en frase, gesto tardío | Correcto en el encuadre real |

### Cuándo suena un gesto pedido

`SoniaBootstrap` recibe `gesture` y decide así:

- **Gesto con `utterance_id`:** suena en cuanto la voz de esa frase ya se oye.
  Si su frase ya terminó, se descarta.
- **Gesto de apertura (`utterance_id` null):** espera hasta 4 s a la siguiente
  frase no ambiental.
- **Condiciones** (`AvatarChoreographer.CanTalkGesture`): hablando y con voz,
  sin imagen, saludo, reacción, baile ni salida caminando. Si no se cumplen,
  espera hasta caducar.
- **Corte:** el gesto se funde hacia fuera al salir de `speaking`, en una pausa
  de voz, con otro clip de cuerpo y con `stop_speaking`. `stop_speaking`
  también descarta la apertura guardada.
- **Gestos de manos por código:** con el set de Sage se apagan
  (`AvatarStateController.handGestures`). Los acentos de brazos callan
  mientras suena un gesto.
- **Panel:** cualquier gesto de `sage` se puede lanzar por su nombre, en
  cualquier estado, para probarlo. Los clips desactivados en el panel y el modo
  debug frenan los automáticos.
