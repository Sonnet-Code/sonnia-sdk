# Informe: los ojos de Sonia con Kimi u OpenAI (4 de octubre de 2026)

Pregunta de Jean: "hay que habilitar la cámara de nuevo; si es posible usar Kimi para eso mejor, pero si GPT-Live funciona mejor con un modelo de ellos por algún tipo de integración, me dejas saber".

Marcas: **[Oficial]** documentación de Moonshot u OpenAI leída el 4-oct; **[Tercero]** benchmark o documentación de terceros; **[Estimación]** cálculo propio con los supuestos indicados. No se llamó a ninguna API real ni se leyó `.env`.

## 1. Respuesta corta

1. **GPT-Live no tiene ninguna integración de visión que favorezca a un modelo de OpenAI.** La ficha de `gpt-live-1` dice "Unsupported modalities: image, video" [Oficial]. La cámara le llega como nota de texto `[Cámara] ...` (`session.thinking.append`), y GPT-Live no sabe qué modelo la escribió. La vía oficial para que hable de una foto es mandarla a un backend con visión [Oficial], que es lo que ya hace la acción `look`.
2. **Kimi sí se puede usar, con `kimi-k2.6` y el razonamiento apagado.** Funciona con los cambios de código de la sección 6. **`kimi-k3` no sirve**: razona siempre y no se puede apagar [Oficial], tarda unos 50-58 s hasta la primera palabra [Tercero] y el narrador corta a los 12 s.
3. **La recomendación sigue siendo OpenAI `gpt-6-luna`**, que es el valor por defecto. No es por integración, sino por:
   - Velocidad: unas 2 veces más rápida.
   - Coste: de 12 a 15 veces más barata.
   - Simplicidad: usa la misma clave que GPT-Live.
   - Privacidad: las fotos de los visitantes no salen hacia otra empresa. Moonshot guarda los datos en Singapur y, según su política, usa el contenido para mejorar sus modelos salvo acuerdo empresarial [Oficial].
4. **Qué pudo apagar la cámara.** Es una hipótesis, porque no se leyó `.env`:
   - El JPEG de prueba de `sonia check` estaba corrupto (su segunda tabla de cuantización medía 3 bytes menos de lo declarado).
   - Un servidor que valida la imagen lo rechaza. Entonces el check sugería poner `LLM_SUPPORTS_VISION=false`, que apaga la cámara entera.
   - Las dos cosas están corregidas.

## 2. Qué controla la cámara

Flujo de la cámara:
1. Alguien empieza a hablar.
2. `LiveEngine._maybe_look` hace la captura con OpenCV (o Unity).
3. `VisionNarrator.describe` la describe con el modelo `LLM_*`, con un tope de 12 s.
4. La descripción entra como nota `[Cámara] ...`.

La acción `look` es aparte: manda la foto al backend de OpenAI (`LIVE_BACKEND_MODEL`). **Con Kimi como ojos, `look` sigue usando OpenAI.**

| Variable | Defecto | Efecto |
|---|---|---|
| `LLM_SUPPORTS_VISION` | `true` | `false` apaga todo (descripciones y `look`). |
| `VISION_SOURCE` | `opencv` | `none` apaga; `unity` exige Unity conectado. |
| `VISION_ON_TURN_START` | `true` | `false`: solo `VISION_INTERVAL_SECONDS` o `look`. |
| `VISION_INTERVAL_SECONDS` | `0` | 0 = nunca periódico. |
| `LIVE_VISION_MIN_INTERVAL_SECONDS` | `10` | Mínimo entre dos descripciones (hasta 6 por minuto). |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | OpenAI / `gpt-6-luna` / `OPENAI_API_KEY` | Si el `.env` aún apunta al motor anterior (`localhost:8000`, `kimi-k3`, clave `local`), la capa parece activa pero cada descripción falla. |
| `LLM_REASONING_EFFORT` | `low` | En OpenAI: `none`, `low`, `medium` (el defecto del modelo, lento) o `high`. `off` no lo envía. **Dejarlo vacío no lo quita**: vuelve a `low`. |
| `LLM_IMAGE_DETAIL` | `low` | `detail` de la imagen en OpenAI; `off` no lo envía. |
| `LLM_EXTRA_BODY` | `{}` | Campos extra del cuerpo, en JSON entre comillas simples. |
| `VISION_CAMERA_INDEX` | `0` | En Mac, un iPhone cercano (Continuidad) puede ser el índice 0. Hace falta además el permiso de cámara de macOS para la terminal y `uv sync --extra camera`, y que Unity no tenga la cámara abierta. |

En «Solo saludos» y «Fuera» no hay sesión, así que tampoco hay ojos. `sonia chat` no usa la cámara.

## 3. Variables de `.env` (sin claves)

**A. OpenAI (recomendado).** Basta con borrar del `.env` las líneas `LLM_*` y `LLM_SUPPORTS_VISION=false` que queden del motor anterior, o dejar:

```
LLM_SUPPORTS_VISION=true
VISION_SOURCE=opencv
VISION_ON_TURN_START=true
# Sin LLM_BASE_URL, LLM_MODEL ni LLM_API_KEY: https://api.openai.com/v1, gpt-6-luna y OPENAI_API_KEY
LLM_REASONING_EFFORT=low        # prueba `none` si «Cámara descrita en» pasa de ~2 s
LLM_IMAGE_DETAIL=low            # `high` lee mejor gafetes y logos por ~100 tokens más
```

**B. Kimi K2.6 (viable).**

```
LLM_SUPPORTS_VISION=true
VISION_SOURCE=opencv
LLM_BASE_URL=https://api.moonshot.ai/v1
LLM_MODEL=kimi-k2.6
LLM_API_KEY=<clave de platform.kimi.ai>      # obligatoria
LLM_REASONING_EFFORT=off                     # K2.6 no usa reasoning_effort
LLM_IMAGE_DETAIL=off                         # Kimi no documenta `detail`
LLM_EXTRA_BODY='{"thinking":{"type":"disabled"}}'   # sin esto K2.6 razona y tarda
LLM_MAX_TOKENS=400
# No pongas LLM_TEMPERATURE: Kimi la fija y rechaza otros valores.
LIVE_VISION_MIN_INTERVAL_SECONDS=20          # solo si la cuenta de Moonshot sigue en Tier 0 (3 RPM)
```

Si falta `LLM_API_KEY` con un servidor que no es OpenAI, la cámara se apaga con un aviso en el registro y `sonia check` lo dice. La clave de OpenAI nunca se manda a otro servidor.

## 4. Comparativa

Supuestos [Estimación]:
- Texto: unos 190 tokens.
- Imagen de 768 px: unos 350 tokens en OpenAI con `detail: low`; de 1.600 a 2.200 en Kimi.
- Salida: 90 tokens. Hay que sumar unos 150 de razonamiento oculto en luna con `low`.

| | gpt-6-luna | kimi-k2.6 sin razonar | kimi-k3 `low` |
|---|---|---|---|
| Acepta imagen en base64 | sí | sí | sí |
| Hasta la primera palabra [Tercero] | `none` 0,74 s; `low` 1,59 s | 2,75-2,85 s | 50-58 s |
| Descripción completa [Estimación] | `low` ~2,2 s | ~4,6 s más la ida y vuelta a Singapur | decenas de segundos |
| Precio por 1M tokens, entrada / salida [Oficial] | 0,10 / 0,50 USD | 0,95 / 4,00 USD | 3,00 / 15,00 USD |
| Coste por descripción [Estimación] | 0,0001-0,00017 USD | 0,0021-0,0026 USD | 0,011-0,031 USD |
| Con 100 descripciones por hora | 0,01-0,02 USD/h | 0,21-0,26 USD/h | 1,1-3,1 USD/h |
| Límites de una cuenta nueva [Oficial] | 500 RPM (Tier 1) | 3 RPM y 1 a la vez (Tier 0); 100 RPM con 10 USD (Tier 1) | igual |
| Datos de las fotos [Oficial] | no se usan para entrenar por defecto | Singapur; se usan para mejorar modelos salvo acuerdo | igual |

Referencia: GPT-Live cuesta 3 USD/h. Con luna, los ojos son calderilla; con K2.6 añaden entre un 5 y un 30 %; con K3 podrían costar más que la voz.

La descripción corre en paralelo y no frena la respuesta de Sonia. Aun así, cuanto más tarda, más vieja es la foto cuando GPT-Live la recibe.

## 5. Qué manda nuestro cliente y qué acepta Kimi

| Campo | Estado |
|---|---|
| `max_completion_tokens` | Documentado en Kimi; `max_tokens` es un alias obsoleto [Oficial]. |
| `reasoning_effort` | `off` lo quita. K2.6 no lo usa. |
| `thinking` | Se manda con `LLM_EXTRA_BODY`, que no puede pisar `model`, `messages` ni `stream`. |
| `temperature` | Solo si se pone `LLM_TEMPERATURE`; en Kimi, no ponerla. |
| `detail` de `image_url` | Lo controla `LLM_IMAGE_DETAIL`; `off` lo quita en todas las peticiones, también en las de `sonia check`. |
| Imagen | Data URL JPEG de 768 px como máximo; Kimi acepta jpeg, png, gif, webp, bmp, heic y heif [Oficial]. |
| JPEG de prueba de `sonia check` | Corregido: ahora es un JPEG válido de 112x112 (el antiguo no lo decodificaban ni OpenCV ni macOS). |

## 6. Cambios de código

- `server/sonia/config.py`:
  - `LLM_IMAGE_DETAIL` y `LLM_EXTRA_BODY`.
  - `LLM_API_KEY` y `OPENAI_API_KEY` separadas: `LLMSettings.key` usa la de OpenAI solo contra `https://api.openai.com`.
- `server/sonia/llm/client.py`:
  - `off` quita `reasoning_effort`.
  - `extra_body` se mezcla en el cuerpo.
  - `detail` se aplica o se quita en todas las peticiones.
  - Aviso en el registro si un modelo agota el tope de tokens sin dar texto.
- `server/sonia/cli.py`:
  - JPEG de prueba válido.
  - Sin clave para el proveedor, la cámara se apaga con un aviso.
  - Si la visión falla, `sonia check` ya no sugiere `LLM_SUPPORTS_VISION=false`: pide revisar `LLM_BASE_URL`, `LLM_MODEL` y `LLM_API_KEY`.
- `.env.example`: variables nuevas y la receta de Kimi K2.6, comentada.
- Tests en `server/tests/test_llm.py` y `server/tests/test_cli.py`, sin llamadas reales.

## 7. Pendiente

- Un timeout del narrador se registra con el mensaje vacío (`TimeoutError` no trae texto), lo que dificulta el diagnóstico con modelos lentos.
- `look` manda la foto al backend de OpenAI aunque los ojos sean Kimi. Unificarlo exige tocar `actions` y `engine` (unas 20 líneas, más tests).
- El `ping()` de `sonia check` usa 5 tokens. Con un modelo que razona devuelve texto vacío aunque funcione bien.

## 8. Comprobación manual (gasta)

1. `sonia check`: mira la línea "Visión", que ahora prueba con un JPEG válido.
2. `sonia run` y habla delante de la cámara. Busca `Cámara descrita en X s` en el registro:
   - Con OpenAI, menos de 3 s.
   - Con K2.6, de 4 a 6 s.
   - Si pasa de unos 8 s, mejor volver a OpenAI.
3. Con Kimi, antes del evento, revisa el saldo y el Tier en platform.kimi.ai.

## Fuentes

- GPT-Live: https://developers.openai.com/api/docs/models/gpt-live-1.md, https://developers.openai.com/api/docs/guides/live-delegation.md, https://developers.openai.com/api/docs/guides/live-conversations.md
- gpt-6-luna, imágenes y datos: https://developers.openai.com/api/docs/models/gpt-6-luna.md, https://developers.openai.com/api/docs/guides/images-vision.md, https://developers.openai.com/api/docs/guides/your-data.md
- Kimi: https://platform.kimi.ai/docs/guide/use-kimi-vision-model.md, https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart.md, https://platform.kimi.ai/docs/guide/kimi-k3-quickstart.md, https://platform.kimi.ai/docs/guide/use-thinking-models.md, https://platform.kimi.ai/docs/api/chat.md, https://platform.kimi.ai/docs/pricing/chat, https://platform.kimi.ai/docs/pricing/limits.md, https://platform.kimi.ai/docs/agreement/userprivacy.md
- Latencia [Tercero]: https://artificialanalysis.ai/models/kimi-k3-low/providers, https://artificialanalysis.ai/models/kimi-k2-6-non-reasoning/providers, https://artificialanalysis.ai/models/gpt-6-luna-low/providers
