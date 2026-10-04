# 005. Captura de cámara: OpenCV o Unity

## Contexto

Hay dos sitios razonables desde donde capturar la imagen de la cámara: el propio proceso Python del orquestador, o el proceso de Unity, que de todas formas ya tiene que gestionar una ventana y podría tener acceso a la cámara vía `WebCamTexture`. Cada uno tiene compromisos distintos de latencia, acoplamiento y robustez frente a fallos de uno de los dos procesos.

## Decisión

`VISION_SOURCE` selecciona la fuente: `opencv` (por defecto), `unity` o `none`. Con `opencv`, `server/sonia/vision/camera.py` abre la cámara directamente con `cv2.VideoCapture` sin pasar por Unity. Con `unity`, Unity captura con su propia cámara y envía frames por WebSocket (`camera_frame`) cuando el orquestador los pide con `request_frame`. Ambas implementan la misma interfaz (`CameraSource`), así que el resto del orquestador no distingue cuál está activa.

## Consecuencias

OpenCV da menor latencia (no pasa por el WebSocket) y sigue funcionando aunque Unity se caiga o aún no esté conectado, pero exige que el orquestador tenga acceso directo al dispositivo de cámara y que este no esté ya en uso por Unity u otro programa. Unity evita compartir el dispositivo de cámara entre dos procesos y permite reutilizar el mismo feed que ya se muestra en pantalla, pero añade una vuelta de WebSocket a cada captura y depende de que Unity esté conectado. Por defecto se usa `opencv` por ser más simple y no depender de Unity para la visión; se documenta la alternativa porque puede ser necesaria si dos procesos compitiendo por la cámara da problemas en el hardware del stand.
