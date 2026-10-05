"""Rutas del gorro Noogler de la trivia (las comparten texto.py, construir.py y encajar.py)."""

import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(AQUI, "..", ".."))
# El zip de Sketchfab («HAT - Propeller Silly Hat - PBR Game Ready», de Dekogon)
# descomprimido aquí. No va al repo.
FUENTE = os.path.join(AQUI, "fuente")
GLTF = os.path.join(FUENTE, "HAT_-_Propeller_Silly_Hat_-_PBR_Game_Ready.gltf")
IMAGENES = os.path.join(FUENTE, "images")
# Intermedios, vistas previas y la gorra oficial medida en Unity. No va al repo.
TRABAJO = os.path.join(AQUI, "trabajo")
# Lo que monta "Sonia > Crear gorro Noogler" en Unity (GORRO_NOOGLER_SALIDA la
# cambia, por ejemplo para probar sin tocar el proyecto con el editor abierto).
SALIDA = os.environ.get("GORRO_NOOGLER_SALIDA") or os.path.join(
    REPO, "unity", "Assets", "Sonia", "Trivia", "NooglerCap"
)

os.makedirs(TRABAJO, exist_ok=True)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, data, indent=None):
    with open(path, "w") as f:
        json.dump(data, f, indent=indent)
