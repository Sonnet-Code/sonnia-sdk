# Cara, lip-sync y gestos de Sonia: estado del trabajo

Trabajo **en pausa desde el 4 de octubre de 2026**. Vive en la rama `cara-sonia`
(worktree `/Users/jeanc.calderon/Documents/git/sonia-cara`, sale de `f0b559c`) y
**no está fusionado en `main`**. Todo compila sin errores ni avisos en Unity
6000.6.0f1; qué está verificado en imagen y qué no, abajo.

## Cómo se ha trabajado

Cada cambio se mide con renders fotograma a fotograma, no a ojo de código. Para
no tocar el editor abierto sobre `main` (en Play con una sesión real de GPT-Live
de otra sesión de trabajo), el worktree lleva su propia `unity/Library`, una
copia APFS (`cp -cR`) de la de `main` que casi no ocupa disco, y Unity corre en
batchmode sobre ella con el puente MCP desactivado (`UNITY_MCP_DISABLE_BATCH=1`).

### Laboratorio de cara

`Editor/SoniaFaceLab.cs` y `SoniaFaceLabDriver.cs` (solo editor, no entran en la
build). Abren `SampleScene`, desconectan el cliente WebSocket y la webcam, y un
guion hace de orquestador llamando a los mismos manejadores de `SoniaBootstrap`
que el protocolo (`state`, `speech_start`, chunks de audio de 100 ms a ritmo
real, `speech_end`, `attention`). Se prueba el camino real entero: reproductor,
línea de retardo, análisis, lip-sync, expresiones, ojos y gestos.

- Tiempo fijo (`Time.captureDeltaTime`, 60 fps por defecto) y audio consumido
  por el propio guion (llama a `OnAudioFilterRead` con los bloques de cada
  fotograma): cada ejecución da los mismos fotogramas y se puede renderizar más
  despacio que el tiempo real.
- Cada fotograma se renderiza al principio del siguiente, con huesos, malla y
  blendshapes ya en su estado final.
- Salida: `stand/` (plano del stand, 540x960), `closeup/` (primer plano desde
  la misma cámara con teleobjetivo: misma perspectiva y mismo enfoque),
  `frames.tsv` (por fotograma: estado, clip, fonema, apertura, cabeza, ojos y
  todos los blendshapes con peso), `heard.wav` (lo que sonó, con la latencia de
  un búfer DSP) y `blendshapes.txt`.
- Pasos del guion: `state`, `speak` (WAV de la caché de voz, opcionalmente
  `ambient`), `attention`, `wait`, `freeze` (apaga lo que escribe en la cara) y
  `shape` (pesos fijos, `"viseme_aa:1,jawOpen:0.3"`) para galerías de
  blendshapes. `overrides` cambia campos de componentes antes de entrar en Play
  y `loadTuning` decide si se aplica `sonia-tuning.json`.
- Para la escena, sin orquestador: `message` (un mensaje del protocolo en
  `text`, como si llegara por el WebSocket: trivia, `activity`...),
  `particles` (efecto de `StageParticles` a la fuerza: `ambient`, `trivia` o
  `matrix`), `tuning` (`"matrix amount=200 size=150"`; al terminar los ajustes
  de partículas quedan como estaban) y `menu` (abre un menú de Esc por su
  componente, por ejemplo `ParticleSettingsMenu`, y lo graba aparte en `menu/`
  a la proporción de la captura).

```bash
# Unity no abre dos veces el mismo proyecto: con el editor abierto en main,
# lanzar sobre el worktree.
FACELAB_PROJECT=/Users/jeanc.calderon/Documents/git/sonia-cara/unity \
  scripts/facelab/run_lab.sh scripts/facelab/guion_ejemplo.json

# Análisis (dependencias efímeras con uv):
PY="uv run --with numpy --with scipy --with pillow --with matplotlib python"
$PY scripts/facelab/analyze.py unity/Temp/facelab/ejemplo plot                 # curvas vs. audio
$PY scripts/facelab/analyze.py unity/Temp/facelab/ejemplo sheet 306 402 4 120,300,400,300 5 0.75  # boca
$PY scripts/facelab/sync.py unity/Temp/facelab/ejemplo                         # desfase boca-voz
$PY scripts/facelab/gallery_sheet.py <salida> 140,300,360,250 6 0.7 "" hoja.jpg # galería de shape
$PY scripts/facelab/voice_stats.py <wav> "texto"                                # bandas de la voz
$PY scripts/facelab/nuclei.py <wav> 0 1.5                                       # formantes por sílaba
```

Los 25 WAV de `cache/voice/marin` son la voz real de Sonia (GPT-Live, 24 kHz).
El nombre es `sha1("marin\n24000\n" + texto)[:16]` sobre las líneas de
`assets/showcase/{saludos,frases,cantos}.md`; la prueba de referencia es
`1c0f6081268e61b1.wav`, "Estás en la Biblioteca Nacional Pedro Henríquez Ureña.
Tiene más historias de las que parece." (7,3 s, muchas p, b y m).

## Diagnóstico del estado de partida (`f0b559c`)

Medido con el laboratorio y la frase de referencia:

| Qué | Medida | Cómo se veía |
|---|---|---|
| Boca | visemas a 0,20-0,27 como máximo, `jawOpen` siempre a 0 | una rendija con los dientes asomando; desde el stand, boca quieta |
| Causa | proporción de cada vocal (repartida entre 5) × volumen × `visemeMaxWeight` 0,65 (del `sonia-tuning.json` de Jean) | |
| Consonantes | ningún cierre de labios en p, b, m | |
| Vocales | perfil de uLipSync de muestra (voz femenina japonesa), sin calibrar con la voz de Sonia | clasificación ruidosa, "U" donde hay "I" |
| Sonrisa | 0,14 fija al hablar | cara plana |
| Cejas al hablar | 0,05-0,1 (dependían de una apertura de boca mínima) | quietas |
| Pensar | cabeza girada 27°, ojos abajo a un lado, ceño | parecía enfadada o desinteresada; el punto de pensar (`thinkingLookOffset` y = 0,9 desde los pies) quedaba por debajo de la cabeza |
| Parpadeo | triángulo simétrico de 0,14 s; 2 parpadeos en 12 s | mecánico |
| Sincronía boca-voz | correlación 0,80 | |

La galería de blendshapes de `Sonia_Cabeza` (15 visemas Oculus + 52 ARKit)
muestra que los visemas de Ready Player Me a peso 1 se ven bien en esta cara
(`viseme_aa`, `O`, `PP` cerrado, `SS` con dientes) y que `jawOpen` a 0,5 ya abre
mucho. Las cejas quedan medio tapadas por el flequillo: `browInnerUp` y
`browOuterUp` apenas se notan; los párpados (`eyeSquint`, `eyeWide`) y la boca
cargan más la expresión.

La voz de Sonia, medida (`voice_stats.py`): sílabas entre -20 y -30 dBFS
(mediana -26), cierres casi en silencio, sibilantes 10-30 dB por encima de
graves y medios en 4-10 kHz. En las vocales, medios menos graves (500-1500 frente
a 100-500 Hz) va de +3..+8 dB en la "a" a -14..-16 dB en la "i"; formantes por
LPC: "a" F1 ≈ 800-1000 Hz y F2 ≈ 1550-1900 Hz, "i" F1 ≈ 250-290 Hz y F2 ≈ 2600 Hz.

## Hecho y verificado en imagen

### Lip-sync nuevo (`LipSyncController` + `SpeechAnalyzer`)

- `SpeechAnalyzer` (nuevo): analiza la voz con ventanas de 5 ms en el hilo
  principal; el hilo de audio solo copia muestras a un anillo. Da nivel con
  control de ganancia (0..1 respecto al pico reciente), energía por bandas
  (graves, medios, agudos, sibilantes), envolvente de sílaba (ataque 10 ms,
  caída 35 ms), cierres (valles hondos entre tramos con voz) y eventos de
  prosodia: sílaba con su fuerza, principio y fin de frase.
- `LipSyncController` (reescrito): la boca sale de la apertura (envolvente de
  sílaba), la forma de la vocal (proporciones de uLipSync, afiladas, suavizadas
  y mezcladas con una forma neutra según la confianza), el cierre de labios
  (`viseme_PP`) en los valles y los dientes (`viseme_SS`) en la "s"; con
  `jawOpen` extra en las sílabas fuertes. Todo con muelles críticamente
  amortiguados (`FaceMath.cs`). Acumula por blendshape antes de escribir (en
  los VRM varios visemas comparten uno).
- Reloj: lo que suena = lo último analizado menos el retardo de la voz y un
  búfer DSP, avanzado con el tiempo de juego entre bloques. La boca va 35 ms por
  delante (`mouthLeadMs`) y los gestos 70 ms (`gestureLeadMs`). Al arrancar sube
  el retardo de `AudioStreamPlayer` a 100 ms (`voiceDelayMs`; antes 60): 40 ms
  más de latencia de voz a cambio de poder ver la sílaba antes de que suene.
- Reparte los eventos de prosodia por `OnSpeechEvent` cuando les llega su
  momento.
- `PhonemeLipSyncBridge` solo pasa las proporciones de vocal; cuánto abre lo
  mide el lip-sync.
- `SetVisemes`, `SetEnvelope` y `NotifyUtteranceFinished` quedan vacíos por
  compatibilidad (GPT-Live no manda visemas ni envolvente).

Resultado (pasada `v2a`, solo con el lip-sync nuevo): visemas de vocal a
0,4-0,65, cierres a 0,8 en las oclusivas, "s" a 0,5; correlación boca-voz 0,91
con la boca 17 ms por delante del audio (incluida la latencia de salida). En la
hoja de fotogramas se ven las p, b y m cerradas, las "o" redondas y los dientes
de la "s"; antes era una rendija fija.

## Hecho, compilado y sin verificar en imagen

La pasada `v2b` (todo junto) no llegó a ejecutarse:

- `FacialExpressionController` (reescrito): base por estado (reposo: sonrisa
  amable; escuchando: cejas algo arriba y sonrisa abierta; pensando: una ceja
  arriba y la otra frunce, labios apretados y llevados a un lado; hablando:
  sonrisa de conversación), cejas en las sílabas tónicas (55 % de las que pasan
  de 0,82), flash de cejas al empezar frase y sonrisa al acabarla,
  microexpresiones cada 2,5-6 s en reposo y escuchando, asimetría lenta entre
  lados y sonrisa que baja con los labios redondos o cerrados.
- `AvatarStateController` (reescrito): asentimientos en sílabas tónicas (empujón
  a un muelle, 3,5°), pose de cabeza nueva en cada frase (giro e inclinación de
  hasta 4°), cabeza ladeada 6° y "ajá" cada 2,8-5,5 s al escuchar, punto de
  pensar arriba y a un lado respecto a la cabeza (`thinkingGaze`), parpadeo que
  cierra en un tercio y abre en el resto, a veces doble o a medias, al empezar y
  acabar frases y al cambiar de estado, y párpado superior que baja al mirar
  abajo. Orden de ejecución 12010.
- `EyeGazeController`: expone `CurrentPitchDown` para el párpado.
- `SoniaTuningUI`: sección "Boca" con los campos nuevos; fuera la de fonemas.

## Pendiente, en orden

1. **Pasada `v2b`** con todo junto y revisión por fotogramas: reposo,
   escuchar, pensar, hablar y frases `ambient` (modo Solo saludos).
2. **Rango dinámico de la boca**: en `v2a` la apertura satura (`MouthOpen` ≈ 1
   en casi todas las sílabas). Probar `SpeechAnalyzer.RangeDb` 30 (ahora 26) y
   `LipSyncController.openCurve` 1 (ahora 0,75), con `overrides` del
   laboratorio antes de tocar código.
3. **Vocales**: la clasificación de uLipSync con el perfil de muestra falla con
   esta voz. Dos caminos: calibrar un perfil propio (copiarlo a
   `Assets/Resources` y cargarlo desde el puente, sin tocar la escena; subir
   `mfccDataCount`, que por defecto solo promedia las 16 últimas muestras) con
   tramos de vocal conocidos ("Lalalá", "Tiki tiki, tam tam", "Na na na na"), o
   un clasificador propio por bandas F1/F2 con los datos medidos arriba. Ojo con
   las mezclas grandes de dos vocales (O + aa): el interior de la boca sale
   raro; conviene que gane una.
4. **Gestos del cuerpo al hablar** (clips de Ready Player Me): sin revisar.
5. **Fusión con `main`**, coordinada con la otra sesión (sonia-00), que usa y
   necesita sin cambios: `AvatarChoreographer.MotionSet` (get y set: le pasa
   una copia filtrada del set), `Preview(AnimationClip, bool upperBody = false)`,
   `Player`, `MotionPlayer.CurrentClip(capa)` e `IsReady`, los campos de
   `SoniaMotionSet` (`idleVariations`, `nods`, `thinkingVariations`, `talking`,
   `greeting`, `present`, `attention[].clip/.category`) y `AttentionCategory`;
   el coreógrafo tiene que seguir leyendo `motionSet.*` en cada elección (sin
   cachear arrays). En esta rama no se ha tocado nada de eso, ni
   `SoniaBootstrap`, `SoniaClient`, `Protocol.cs` ni `SampleScene.unity`.
6. **Verificar en el editor de `main`** en Play con la voz real y en la build.

## Notas para retomar

- Campos serializados que usan los menús de montaje y que se han mantenido:
  `faceRenderer`, `audioPlayer`, `visemeBindings`, `jawOpenBlendShape`,
  `mouthOpenBlendShape` (lip-sync); `faceRenderer`, `stateController`, `lipSync`
  (expresiones); `headBone`, `avatarRoot`, `lookTarget`, `faceRenderer`,
  `blinkLeftBlendShape`, `blinkRightBlendShape`, `lipSync`, `choreographer`
  (estado); `audioPlayer`, `analyzer`, `lipSync` (puente).
- Los campos cuyo significado cambió tienen nombre nuevo, para que no los pisen
  los valores viejos de la escena ni el `sonia-tuning.json` del Mac de Jean
  (que se sigue aplicando a ojos, cabeza y parpadeo; las entradas de campos que
  ya no existen se ignoran).
- La escena guarda `thinkingLookOffset` y `speechNodDegrees` de
  `AvatarStateController` y los campos viejos de `FacialExpressionController` y
  del puente: ya no se leen.
- Ruido conocido del log en batchmode: `ArgumentOutOfRangeException` de
  `UnityEditor.Search.SearchDatabase` al indexar, ajeno a Sonia.
- Para quitar el worktree: `git worktree remove ../sonia-cara` (la `Library`
  copiada se va con él).
