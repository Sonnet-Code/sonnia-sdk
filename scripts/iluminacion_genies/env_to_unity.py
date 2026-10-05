"""Gira el HDR equirectangular de Mia (three.js) para que Unity lo importe con los mismos ejes.

three.js pone el centro de la imagen (u = 0,5) en +X; el "Latitude-Longitude
Layout" de Unity lo pone en +Z. Con el avatar mirando a −Z en Sonia (a +Z en
Mia), la imagen tiene que desplazarse un cuarto de ancho hacia la derecha para
que cada dirección de Unity vea lo mismo que veía la dirección equivalente en
Mia. Comprobado en Unity renderizando el cubemap en varias direcciones.

Uso (desde server/, con --extra camera):
  uv run --no-sync python ../scripts/iluminacion_genies/env_to_unity.py original.exr salida.exr
"""

import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

image = cv2.imread(sys.argv[1], cv2.IMREAD_UNCHANGED)
if image is None:
    raise SystemExit(f"No se pudo leer {sys.argv[1]} (¿OpenCV sin OpenEXR?)")
width = image.shape[1]
if width % 4:
    raise SystemExit("El ancho tiene que ser múltiplo de 4")
rotated = np.roll(image, width // 4, axis=1)
params = [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF]
if hasattr(cv2, "IMWRITE_EXR_COMPRESSION"):
    params += [cv2.IMWRITE_EXR_COMPRESSION, cv2.IMWRITE_EXR_COMPRESSION_ZIP]
if not cv2.imwrite(sys.argv[2], rotated, params):
    raise SystemExit(f"No se pudo escribir {sys.argv[2]}")
print(f"{sys.argv[2]}: {width}x{image.shape[0]}, desplazado {width // 4} columnas")
