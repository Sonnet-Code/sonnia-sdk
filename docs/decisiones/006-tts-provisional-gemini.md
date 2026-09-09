# 006. TTS provisional en la nube con Gemini

## Contexto

La voz de Sonia la pone OmniVoice corriendo en local, pero OmniVoice necesita GPU y la máquina del stand todavía no existe: el hardware llega más adelante. Sin voz no hay nada que enseñar, y el resto del pipeline (VAD, STT, LLM, visemas, avatar, protocolo con Unity) no se puede probar de punta a punta ni ajustar en latencia mientras el último eslabón esté vacío. La alternativa de trabajar solo con `MockTTS` sirve para los tests, pero no permite evaluar cómo suena Sonia, ni afinar el troceado de frases, ni comprobar el lip-sync con audio real.

## Decisión

Se añade `server/sonia/tts/gemini.py`, un backend de síntesis contra la API de Gemini en su free tier, explícitamente **provisional** y en contra del principio de [001](001-todo-local.md), igual que el LLM en la nube que contempla [002](002-api-compatible-openai.md) como paso intermedio. Ofrece dos modos por configuración: `live`, que abre una sesión WebSocket de larga duración contra la Live API y devuelve audio en streaming con latencia baja, y `tts`, que llama a los modelos TTS por REST y lee el texto con fidelidad literal. Ambos entregan PCM s16le mono a 24 kHz, la misma forma que produce OmniVoice, y ambos implementan el protocolo `TextToSpeech` de `sonia.types` sin tocar el resto del código. Toda su configuración vive bajo el prefijo `TTS_GEMINI_` y aislada de `TTSSettings`, para que borrar el módulo y su bloque de `.env` sea todo lo que haga falta para retirarlo.

El día que llegue la GPU, `TTS_BACKEND=omnivoice` vuelve a ser el valor por defecto y este archivo se borra. No se construye nada encima de él: ni caché en disco, ni tuberías especiales, ni mensajes propios en el protocolo con Unity.

## Consecuencias

Mientras esté activo, el proyecto **deja de funcionar sin internet** y el texto que Sonia va a decir viaja a Google. Eso lo hace inaceptable para el stand y aceptable solo para desarrollo: no se enviarán a la API transcripciones de visitantes reales, porque en el evento el backend ya será local. El free tier impone límites de peticiones por minuto y por día que pueden agotarse en una sesión larga de pruebas, y la latencia depende de la red, así que las mediciones que se hagan con este backend no valen como referencia del objetivo de dos segundos. Las sesiones Live caducan (15 minutos en solo audio), de modo que el módulo reconecta solo al detectar `goAway` o un cierre, y los errores de clave o de cuota se traducen a un `TTSError` con un mensaje que se entiende sin leer el código. A cambio, el pipeline completo se puede probar y demostrar hoy, y el coste de esta decisión está acotado a un archivo, sus tests y unas variables de entorno.
