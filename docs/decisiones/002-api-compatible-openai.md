# 002. API compatible con OpenAI, agnóstica al modelo

## Contexto

El modelo de lenguaje es el componente que más cambia: puede que el hardware disponible el día del evento no sea el mismo que el de las pruebas, o que aparezca un modelo mejor antes de octubre. Acoplar el orquestador a un modelo concreto obligaría a tocar código cada vez que cambia esa elección.

## Decisión

El orquestador solo habla con un endpoint que expone el formato de API de OpenAI (`/v1/chat/completions`, tool calling, `image_url` para visión), da igual qué lo sirva: llama.cpp, vLLM, Ollama o un proveedor en la nube. Ningún archivo de código menciona un modelo por nombre. Kimi K3 es el modelo por defecto (multimodal, con buen soporte de español), configurado solo por variables de entorno (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`). Un endpoint en la nube es válido únicamente como paso provisional mientras no hay servidor local montado, nunca como configuración final del stand (ver [001](001-todo-local.md)).

## Consecuencias

Cambiar de modelo es cambiar variables de entorno y reiniciar, sin tocar código. El precio es no poder aprovechar particularidades de un modelo concreto (prompts específicos, parsers a medida): todo pasa por el formato estándar, y si un modelo no soporta imágenes o tool calling, esa capa se degrada limpiamente en vez de romper el resto (`LLM_SUPPORTS_VISION`, `LLM_TOOL_MODE`).
