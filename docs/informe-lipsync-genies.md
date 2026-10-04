# Lip-sync para avatares Genies: investigación

Investigación del 4 de octubre de 2026, cinco días antes del DevFest, sobre qué
usar para el lip-sync del avatar de Genies (Genies Avatar SDK 3.8.6). El sistema
actual (uLipSync, el analizador propio de envolvente y `FaceRig`) está descrito
en `docs/cara-y-lipsync.md`; aquí solo están la comparativa de alternativas y la
recomendación.

## Requisitos de partida

- La voz llega de GPT-Live en streaming: PCM 16 bit mono a 24 kHz, en trozos de
  unos 100 ms, y se reproduce por `OnAudioFilterRead`.
- La cara de Genies son 84 parámetros FACS con los nombres del face tracking de
  Meta (`JAW_DROP`, `LIP_PUCKER_L`, `LIP_FUNNELER_LB`...) más formas propias,
  sobre todo de lengua (`TONGUE_CURLER_UP`, `TONGUE_TIP_OUT`...). Están
  repartidos en varias mallas y el SDK los mueve con parámetros float del
  Animator (`GeniesAvatarAnimator.controller`). El SDK no trae lip-sync ni
  procesa audio.
- Editor en un Mac con Apple Silicon; el stand, probablemente un Windows 11 x64
  con GPU AMD, sin NVIDIA ni CUDA.
- Tiempo real con menos de unos 100 ms añadidos, sin nube, y gratis, open source
  o como mucho 50 USD.

## Conclusión

No hay nada público y probado de lip-sync con avatares Genies en Unity. Tampoco
hay ninguna solución que mueva la cara entera a partir del audio (tipo Audio To
Expression) y funcione sin conexión en Mac y en Windows con AMD. **uLipSync
sigue siendo la mejor opción que cumple todo.** Donde se puede ganar barato es
en el perfil y en las recetas FACS, y para eso sí hay tablas oficiales.

## Genies

- El **Web SDK** tiene "voice lipsync", pero solo reproduce fotogramas de
  blendshapes que le llegan de un servicio (`parseVoiceBlendshapes`,
  `loadVoiceAnimation`; la documentación dice "Audio playback remains
  consumer-owned"). La versión 0.1.57 (junio de 2026) solo añade escalar la boca
  según el volumen, y es solo web
  ([API](https://docs.genies.com/docs/sdk-web/api/summary),
  [notas](https://docs.genies.com/docs/sdk-web/release-notes/sdk-web-0-1-57)).
- El **Smart Avatar SDK** habla de animación facial "intent-driven", pero no ha
  publicado nada sobre lip-sync
  ([roadmap](https://genies.com/blog/genies-developer-roadmap-what-to-expect-and-how-you-can-help-shape-it)).
- No hay repos, hilos ni vídeos que usen Genies con uLipSync, OVRLipSync, SALSA
  o Convai.

## Audio To Expression de Meta: descartado

Produce las 70 expresiones FACS de Meta (o 15 visemas Oculus, y ARKit por
retarget), justo el vocabulario de Genies. Pero no sirve aquí:

- Lo ejecuta el propio sistema del visor (Horizon OS v71 o posterior) y solo
  existe en Quest 2, 3, 3S y Pro.
- Solo escucha el micrófono del visor y necesita el permiso `RECORD_AUDIO`. No
  acepta un AudioClip ni audio en streaming
  ([spec OpenXR](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrFaceTrackingDataSource2FB.html),
  [docs](https://developers.meta.com/horizon/documentation/unity/move-face-tracking/),
  [UploadVR](https://uploadvr.com/meta-audio-to-expression-in-action)).
- Según un
  [hilo del foro de Meta](https://communityforums.atmeta.com/discussions/dev-unity/audio-2-expression-a2e-with-audio-files/1264216),
  no hay planes de aceptar otras fuentes de audio. No verificado: solo se vio el
  extracto del buscador, la página da 403.
- No funciona ni en el editor de Mac ni en una build de Windows.

## Comparativa

| Opción | Licencia/coste | Mac arm64 | Win x64 AMD | Salida | Streaming/latencia | Madurez | Esfuerzo/riesgo |
|---|---|---|---|---|---|---|---|
| [uLipSync](https://github.com/hecomi/uLipSync) 3.1.5 (la actual) | MIT | Sí | Sí | Fonemas que se calibran | `OnDataReceived`; ya analiza por adelantado (`lipSyncLeadMs`) | 1,7 k estrellas; último commit en enero de 2026 | Ninguno; no reconoce bien las consonantes |
| [OVRLipSync](https://developers.meta.com/horizon/downloads/package/oculus-lipsync-unity/) 29.0.0 | [Audio SDK de Meta](https://developers.meta.com/horizon/licenses/audio-3.3/) (según el foro); no limita la plataforma | No ([DllNotFound](https://discussions.unity.com/t/ovr-lipsync-not-working-on-macos-dll-not-found-exception/1557867)) | Sí | 15 visemas + risa | Por bloques de audio | Abandonado desde mayo de 2021 ([docs "subject for removal"](https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-unity/)) | Unas horas de integración; plugin nativo |
| [SALSA](https://assetstore.unity.com/packages/tools/animation/salsa-lipsync-suite-148442) 2.5.6 | 41,40 € | Sí | Sí | Por amplitud, [sin fonemas](https://crazyminnowstudio.com/docs/salsa-lip-sync/modules/overview/) | Sí | Muy usado | Peor que uLipSync con las vocales |
| [HeadAudio](https://github.com/met4citizen/HeadAudio) | MIT | Solo JS | Solo JS | 15 visemas | ~50 ms | 50 estrellas; modelo solo en inglés | Hay que portarlo a C# y reentrenarlo |
| [Audio2Face-3D](https://github.com/NVIDIA/Audio2Face-3D-SDK) | SDK MIT y modelo con licencia NVIDIA Open | No | No (CUDA ≥ 12.8 y TensorRT) | ARKit | Solo en GPU NVIDIA | Activo | Inviable |
| [NeuroSync](https://huggingface.co/AnimaVR/NEUROSYNC_Audio_To_Face_Blendshape) | MIT si se ingresa menos de 1 M USD | PyTorch | PyTorch | 61 ARKit + 7 emociones | Por ventanas de audio; sin medir | Los repos originales daban 404 el 4 de octubre de 2026 | Alto |
| [LAM-A2E](https://github.com/aigc3d/LAM_Audio2Expression) | Apache-2.0 | Scripts CUDA | Scripts CUDA | ARKit | Streaming en GPU | 2025 | Alto |
| Convai / [Inworld](https://docs.inworld.ai/docs/tutorial-integrations/Unity/create-your-own/ovr-lipsync) | Nube | — | — | ARKit / visemas | Llega de [su servidor](https://docs.convai.com/api-docs/plugins-and-integrations/convai-unity-sdk/getting-started/add-lip-sync), con su propio TTS | — | Inviable |
| [DeepLips](https://assetstore.unity.com/packages/tools/generative-ai/deeplips-lip-sync-ai-361844) | 36,80 € | ? | ? | Genera fotogramas | No documentado | v1.2; 2,5 GB | Descartado |

## Mapeos hacia los FACS de Meta

Ambos verificados en su código fuente.

- **Meta,
  [ARKitOVRCustomFace.cs](https://github.com/meta-quest/agentic-tools/blob/main/skills/hz-unity-face-tracking/references/ARKitOVRCustomFace.cs)
  (Apache-2.0).** Asigna cada una de las 52 formas ARKit a una expresión de
  Meta: jawOpen→JawDrop, mouthClose→LipsToward, mouthFunnel→LipFunnelerLT,
  mouthRollLower→LipSuckLB, mouthShrugUpper→ChinRaiserT...
  - Los 52 destinos existen entre los 84 parámetros de
    `GeniesAvatarAnimator.controller`.
  - Las formas centrales (mouthFunnel, mouthPucker, cheekPuff...) solo apuntan
    al lado izquierdo; en Genies hay que repartirlas entre L/R y LB/LT/RB/RT.
  - El Movement SDK trae el mismo tipo de mapeo como
    `arkit_retarget_a2e_v10.json`.
- **TalkingHead,
  [build-visemes-from-arkit.py](https://github.com/met4citizen/TalkingHead/blob/main/blender/build-visemes-from-arkit.py)
  (MIT).** Define los 15 visemas Oculus como mezclas de formas ARKit, por
  ejemplo viseme_PP = mouthRollLower 0,8 + mouthRollUpper 0,8 + mouthUpperUp
  0,3. Combinado con la tabla de Meta da recetas de visema → FACS de Genies.

## Las tres mejores opciones

1. **uLipSync mejorado.** Es la única que cumple todos los requisitos, y ya
   compensa la latencia analizando el audio por adelantado. Lo que limita la
   calidad hoy es el perfil y las recetas, no el motor.
2. **OVRLipSync solo en Windows**, como fuente alternativa de visemas. `FaceRig`
   ya entiende `viseme_*`, así que conectarlo cuesta poco; en principio bastaría
   con `OVRLipSync.ProcessFrame` sobre el mismo bloque de audio que recibe
   uLipSync (sin compilar). Aporta consonantes y risa con un modelo entrenado.
   En contra:
   - Está abandonado y es un plugin nativo.
   - No carga en Mac arm64.
   - Está entrenado sobre todo en inglés. Meta da
     [+30 % de precisión](https://developers.meta.com/horizon/blog/tech-note-enhancing-oculus-lipsync-with-deep-learning/)
     en inglés con su modelo nuevo; para español no hay datos.
3. **Un modelo de IA de audio a ARKit** (NeuroSync o LAM-A2E exportado a ONNX),
   ejecutado con Inference Engine 2.6.1 en la GPU (Metal o DX12). Es la única
   opción que movería la cara entera, como Audio To Expression. Queda para
   después del evento:
   - Nadie lo ha publicado funcionando en Unity con AMD o con Mac.
   - El modelo necesita oír un tramo de audio antes de responder, así que habría
     que retrasar el audio.
   - Comparte la GPU integrada con el render.

## Recomendación para el 9 y 10 de octubre

Seguir con uLipSync y hacer estos cambios:

1. **Recalibrar el perfil con la voz real de GPT-Live.** Usar las frases de
   `cache/voice` como AudioClips: varias muestras por vocal, más S, N y "-"
   (respiración). Probar `CompareMethod.CosineSimilarity` y
   `useStandardization`, que vienen en la 3.1.5, y medir cuántos fonemas acierta
   con frases conocidas.
2. **Generar las recetas de consonantes con la cadena TalkingHead → Meta →
   FACS**, en lugar de ajustarlas a ojo. Los cierres de p, b y m siguen saliendo
   de la envolvente, y la S de su fonema.
3. **Añadir movimiento secundario sencillo** a partir de la envolvente: cejas,
   `CHEEK_RAISER` y parpadeo en las pausas. Es lo que Audio To Expression añade
   a un lip-sync solo de visemas.
4. **Solo si sobra un día y el stand es Windows, probar OVRLipSync contra
   uLipSync** detrás de un interruptor, que vuelva solo a uLipSync si el DLL no
   carga (en Mac, siempre uLipSync). Se queda solo si gana con claridad en
   español con la voz de Sonia.

Ningún modelo de IA para el lip-sync antes del evento.

## Qué está verificado y qué no

Verificado en las fuentes enlazadas o en el código del proyecto:

- La uLipSync 3.1.5 instalada (`unity/Library/PackageCache`) tiene
  `OnDataReceived` y `CompareMethod` (L1, L2 y coseno) con `useStandardization`.
- Los 84 parámetros FACS de `GeniesAvatarAnimator.controller` y que incluyen
  los 52 destinos del mapeo ARKit de Meta.
- Licencias, versiones, fechas y plataformas de la tabla, salvo lo indicado
  abajo.

Sin verificar:

- Las latencias reales de OVRLipSync y de uLipSync.
- Que OVRLipSync funcione en Unity 6.
- Que el fallo de OVRLipSync en Mac venga de que sus binarios son solo x86_64.
- Que OVRLipSync use la licencia del Audio SDK (lo dice un hilo del foro).
- Que HeadAudio se pueda reentrenar en español con calidad suficiente.
- Cómo funciona DeepLips por dentro: su ficha no documenta si hace streaming.
- Que Meta no tenga planes de aceptar en Audio To Expression audio que no venga
  del micrófono.
