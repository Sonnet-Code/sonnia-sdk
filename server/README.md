# sonia (orquestador)

Paquete Python del orquestador de Sonia: une el micrófono, GPT-Live de OpenAI (`sonia/live`, ADR 007), la cámara, las acciones, el panel de control y el avatar de Unity. Ver el README de la raíz del repositorio para la visión general, `docs/arquitectura.md` para los módulos y `docs/protocolo.md` para el contrato con Unity.

```bash
uv sync --extra audio --extra camera --extra panel   # demo (añade --group dev para tests y lint)
uv run sonia check      # micrófono, cámara, GPT-Live, modelo de visión y galería
uv run sonia chat       # escribir a GPT-Live por consola (--speak para oírla)
uv run sonia say "Hola" # oír la voz de GPT-Live
uv run sonia run        # arrancar la demo completa (--no-mic: solo text_input)
uv run pytest -q        # sin hardware, sin red, sin APIs reales
```

`check`, `chat`, `say` y `run` usan la API de OpenAI y gastan; los tests nunca.
