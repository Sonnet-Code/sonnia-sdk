# 004. Visión por capturas puntuales, nunca vídeo

## Contexto

Sonia necesita "ver" a quien tiene delante para saludar con naturalidad y reaccionar a lo que le muestren, pero también corre en un evento público con visitantes reales que no han dado un consentimiento explícito para que se procese vídeo continuo de ellos. Enviar vídeo en cada frame al modelo también sería inviable en latencia y coste de prefill.

## Decisión

La cámara nunca envía vídeo continuo al modelo. Solo capturas puntuales: una automática al inicio de cada turno (cuando alguien empieza a hablar, política en `server/sonia/vision/policy.py`) y otras bajo demanda del modelo a través de la acción `look`. Desde [007](007-voz-a-voz-gpt-live.md), como GPT-Live no acepta imágenes, la captura del inicio de turno la describe en texto un modelo con visión y a la sesión solo llega esa descripción; la foto de `look` va al backend de acciones. Ninguna captura se guarda en disco, salvo en modo debug explícito (`VISION_DEBUG_SAVE_FRAMES`), que no se activa en el stand.

## Consecuencias

Sonia puede reaccionar a lo que ve sin mantener una huella de vídeo de los visitantes ni disparar cada fotograma a un modelo. El coste es que no "ve" en tiempo real de forma continua: si algo cambia entre capturas, Sonia no se entera hasta la siguiente captura o hasta que el modelo pida `look`. Es una limitación aceptada a cambio de privacidad y de latencia.
