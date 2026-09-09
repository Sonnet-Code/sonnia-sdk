# Decisiones de diseño (ADR)

Registro corto de decisiones de arquitectura que no son obvias solo leyendo
el código: por qué se eligió algo, qué alternativas se descartaron y qué
consecuencias trae. Formato de cada ADR: **Contexto**, **Decisión**,
**Consecuencias**, en 10 a 20 líneas.

No es un registro exhaustivo de todo lo que se decide en el proyecto, solo
de las decisiones que alguien podría cuestionar o repetir por error si no
quedan escritas.

## Índice

- [001. Todo corre en local](001-todo-local.md)
- [002. API compatible con OpenAI, agnóstica al modelo](002-api-compatible-openai.md)
- [003. Acciones por tool calling y por MCP](003-acciones-tool-calling-y-mcp.md)
- [004. Visión por capturas puntuales](004-vision-por-capturas.md)
- [005. Captura de cámara: OpenCV o Unity](005-captura-de-camara-opencv-o-unity.md)

## Cuándo añadir una nueva

Cuando se tome una decisión que afecte a más de un módulo, que alguien
podría querer deshacer sin conocer el motivo original, o que ya se discutió
y se descartó una alternativa razonable. Numerar de forma consecutiva y
enlazar la decisión relacionada si la hay.
