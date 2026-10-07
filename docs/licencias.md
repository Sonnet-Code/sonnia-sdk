# Licencias de assets de terceros


> **Nota (septiembre de 2026):** Sonia es un proyecto sin ánimo de lucro y de uso personal. Por decisión del equipo, de momento no se gestionan ni verifican las licencias de los assets. Esta tabla queda como registro opcional por si el uso cambia en el futuro.

Registro opcional de los avatares, animaciones, librerías e imágenes de
terceros que usa Sonia. Los modelos de OpenAI (GPT-Live, el backend de
acciones y el de visión) se usan como servicio por su API y no se
distribuyen con el proyecto. Ver también las
"Convenciones" en `CLAUDE.md`.

| Asset | Autor | Licencia | Enlace | Uso en el proyecto |
|---|---|---|---|---|
| uLipSync | hecomi | MIT | https://github.com/hecomi/uLipSync | Lip-sync por fonemas en tiempo real en Unity |
| YuNet (`face_detection_yunet_2023mar.onnx`) | Shiqi Yu y otros, OpenCV Model Zoo | MIT | https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet | Encontrar caras en la foto de la cámara (`docs/caras.md`); se descarga a `cache/faces/modelos` |
| SFace (`face_recognition_sface_2021dec.onnx`) | Yaoyao Zhong y otros, OpenCV Model Zoo | Apache 2.0 | https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface | Huella de cada cara para reconocer al equipo y a los ponentes |
| Modelo/avatar 3D | _pendiente_ | _pendiente_ | _pendiente_ | Personaje de Sonia en Unity |
| Animaciones del avatar | _pendiente_ | _pendiente_ | _pendiente_ | Animaciones de escucha, pensamiento y habla |
| Gorra con hélice «HAT - Propeller Silly Hat - PBR Game Ready» | Dekogon | _por confirmar_ (Sketchfab) | https://sketchfab.com/3d-models/hat-propeller-silly-hat-pbr-game-ready-7640ad5df75841999065a474f83b76f2 | Gorro Noogler de la trivia (recoloreado y con el texto «Noogler»; `scripts/gorro_noogler`) |
| Imágenes de la galería (`assets/gallery`) | _pendiente_ | _pendiente_ | _pendiente_ | Panel de imágenes que Sonia muestra con `show_image` |

Al añadir una fila nueva: nombre del asset, autor u organización que lo
publica, licencia exacta (no solo "libre" o "gratis"), enlace a la fuente
original, y en qué parte del proyecto se usa. Si la licencia no queda clara
en la fuente, anota "verificar" en vez de asumir.
