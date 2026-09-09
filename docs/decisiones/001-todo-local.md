# 001. Todo corre en local

## Contexto

Sonia se usa en un stand físico durante un evento de dos días, con conectividad a internet que no se puede garantizar (redes de eventos saturadas, salas grandes, mucha gente conectada a la vez). Además, la demo depende de audio y vídeo del visitante: cualquier llamada a un servicio en la nube añade latencia variable y un punto de fallo fuera de nuestro control justo cuando más falta hace que funcione.

## Decisión

Ningún componente en tiempo de ejecución depende de una API en la nube. Reconocimiento de voz, modelo de lenguaje, síntesis de voz y visión corren en la máquina del stand. No se añaden SDKs de OpenAI, Anthropic, Google, ElevenLabs ni similares como dependencia de ejecución. La única excepción tolerada es un endpoint de LLM en la nube como *fallback* explícitamente provisional mientras no hay servidor local listo (ver [002](002-api-compatible-openai.md)), nunca como plan por defecto.

## Consecuencias

El hardware del stand necesita GPU propia y suficiente memoria para cargar LLM, STT y TTS a la vez. La calidad máxima alcanzable está limitada por ese hardware, no por lo que hay disponible en la nube. A cambio, la demo funciona sin depender de la red del evento y no hay coste variable por uso durante las ocho horas del stand.
