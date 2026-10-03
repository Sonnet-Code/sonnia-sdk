# sonia (orquestador)

Paquete Python del orquestador de Sonia. Ver el README de la raíz del repositorio para la visión general y `docs/protocolo.md` para el contrato con Unity.

```bash
uv sync --extra all     # instalar todo
uv run sonia check      # comprobar micrófono, cámara, voz y modelo
uv run sonia chat       # conversar por texto sin micrófono
uv run sonia say "Hola" # oír la voz
uv run sonia run        # arrancar la demo completa
```

`VOICE_ENGINE=live` (por defecto) usa GPT-Live de OpenAI (`sonia/live`, ADR 007); `VOICE_ENGINE=pipeline`, el motor en cascada de `sonia/orchestrator.py`.
