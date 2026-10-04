# Decisiones de diseño (ADR)

Registro corto de decisiones de arquitectura que no son obvias solo leyendo
el código: por qué se eligió algo, qué alternativas se descartaron y qué
consecuencias trae. Formato de cada ADR: **Contexto**, **Decisión**,
**Consecuencias**, en 10 a 20 líneas.

No es un registro exhaustivo de todo lo que se decide en el proyecto, solo
de las decisiones que alguien podría cuestionar o repetir por error si no
quedan escritas.

Las decisiones sustituidas no se borran: llevan arriba una línea que dice
cuál las sustituye y cuándo, y se conservan como historia.

## Índice

- [001. Todo corre en local](001-todo-local.md) (sustituida por 007)
- [002. API compatible con OpenAI, agnóstica al modelo](002-api-compatible-openai.md) (sustituida por 007)
- [003. Acciones por tool calling y por MCP](003-acciones-tool-calling-y-mcp.md) (sustituida por 007)
- [004. Visión por capturas puntuales](004-vision-por-capturas.md)
- [005. Captura de cámara: OpenCV o Unity](005-captura-de-camara-opencv-o-unity.md)
- [006. TTS provisional en la nube con Gemini](006-tts-provisional-gemini.md) (sustituida por 007)
- [007. Voz a voz con GPT-Live de OpenAI](007-voz-a-voz-gpt-live.md) (vigente: único motor desde el 4 de octubre de 2026)

## Cuándo añadir una nueva

Cuando se tome una decisión que afecte a más de un módulo, que alguien
podría querer deshacer sin conocer el motivo original, o que ya se discutió
y se descartó una alternativa razonable. Numerar de forma consecutiva y
enlazar la decisión relacionada si la hay.
