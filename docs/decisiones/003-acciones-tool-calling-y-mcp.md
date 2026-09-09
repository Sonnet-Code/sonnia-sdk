# 003. Acciones por tool calling y por MCP

## Contexto

Las acciones de Sonia (`look`, `show_image`, `hide_image`) necesitan funcionar sea cual sea el modelo o servidor configurado. Tool calling estándar de la API de OpenAI es la vía más extendida y la que mejor integra la respuesta en el propio turno, pero no todos los servidores locales lo soportan bien, y algún modelo puede no tener tool calling nativo entrenado.

## Decisión

Cada acción se define una sola vez, en `server/sonia/actions`, con su nombre, esquema de argumentos y handler. Desde esa única definición se generan dos vías de exposición: tool calling nativo de la API (vía principal) y un servidor MCP local (`server/mcp`, opcional, activado con `MCP_ENABLED`) para clientes o modelos sin tool calling nativo. Como tercera red de seguridad, `LLM_TOOL_MODE=prompt` describe las acciones en el system prompt y parsea bloques `<action>` del texto generado, para servidores que no soportan ni tool calling ni MCP. Ninguna acción se implementa solo en una de las tres vías.

## Consecuencias

Añadir una acción cuesta un poco más (hay que pensar en las tres vías desde el diseño), pero cambiar de servidor de inferencia nunca deja a Sonia sin poder mostrar imágenes o mirar por la cámara. El modo `prompt` es el más frágil de los tres (depende de que el modelo respete el formato pedido) y se trata como último recurso, no como opción habitual.
