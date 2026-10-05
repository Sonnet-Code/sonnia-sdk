# Mia de Genies: qué la hace natural y qué traer a Sonia (5 de octubre de 2026)

Pregunta de Jean, a cuatro días del DevFest: a Jean le encantó lo natural que se
mueve Mia (`https://genies.com/chat/mia`) en reposo, con un balanceo sutil de un
lado a otro, y pidió "seguir investigando a Mia para ver qué más podemos aprender
para implementar aquí" y "usar todos los recursos del SDK oficial que podamos".

Este informe completa `docs/informe-reposo-genies.md`. Ese informe explica por qué
el motor de comportamiento nativo de Genies no entra en Unity antes del evento.
Aquí están los valores medidos en Mia y todo lo demás que hace la página: habla,
gestos, mirada, cámara, luz e interfaz.

**Marcas**

| Marca | Origen |
|---|---|
| **[Medido]** | Medido en la página en vivo. El controlador de animación de Mia se avanzó a mano en una pestaña propia y se midieron sus huesos y blendshapes (método en el apartado 11). |
| **[Código]** | Leído en los bundles JavaScript públicos o en las cadenas del WASM de NAF. |
| **[Datos]** | Datos que sirve la propia página o su CDN: `__NEXT_DATA__`, `scene.json`, la LUT. |
| **[Docs]** | Documentación pública del Web SDK de Genies (release notes y API). |
| **[Inferencia]** | Deducción propia a partir de lo anterior. |

**Qué no se hizo**
- No se pulsó "Start Chatting", no se aceptaron términos y no se chateó.
- No se copió código de Genies al repositorio.
- No se tocó Unity.

## 1. Respuesta corta

1. **El balanceo de Mia son dos clips mezclados, sin nada procedural** [Medido]:
   - **Reposo**: `actions-baseIdle01`, de 10,97 s en bucle.
   - **Respiración**: `rnd-smartBreathing`, de 9,93 s, en una capa aditiva.

   La cadera va de un lado a otro **±2,5 cm** con un ciclo principal de **11 s**. La respiración hace **una inspiración cada 5 s** y mueve el pecho ±1,1° y la cabeza ±1°. Como los dos bucles duran distinto, la suma no se repite a la vista. El motor tiene un sistema procedural de traspaso de peso y pasos (`WeightShift`, `FootBalance`, FBIK), pero **con Mia está apagado de hecho** (`solverReady: false`). Apagarlo a mano no cambia el balanceo.
2. **Lo demás que da naturalidad en reposo:**
   - **La cabeza no mira a cámara** (`lookWeight` 0). La mueve el clip.
   - **Los ojos sí miran al espectador** (`gazeWeight` 1), con fijaciones de 1,25 a 3,25 s y vistazos fuera.
   - **Parpadea unas 20 veces por minuto**, con parpadeos de 0,35-0,4 s que cierran rápido y abren despacio.
   - **Sonrisa base constante** (emoción "Happy" a intensidad 1).
   - **En reposo no hace ningún gesto.** Mia no tiene clips de aburrimiento.
   - **Los gestos entran y salen en 0,8 s** con una curva suave tipo smoothstep.
3. **Al hablar, nada se calcula del audio en el navegador.**
   - **Mia solo tiene chat de texto** (`enableVoice: false`). La boca hace un bucle genérico de hablar (clip `0063`, solo cara) mientras sale el texto.
   - **Los gestos y las emociones los elige el LLM** (DeepSeek v4 Pro) como etiquetas con tiempos.
   - **En modo voz** (en el catálogo solo lo tiene Veyra):
     - Los blendshapes de la cara llegan del servidor (74 canales FACS a 30 fps) en ventanas sincronizadas con el reloj del audio.
     - Llega también un "énfasis" por palabra que dispara acentos procedurales del cuerpo.
     - Genies baja a mano las formas redondeadas de ese lip-sync: funneler ×0,5, pucker ×0,75, lips toward ×0,4 y chin raiser ×0,3.
4. **Cámara de teleobjetivo**: FOV vertical de **20°** a 3,5-4 m, sin inclinar y a la altura del pecho. Da proporciones planas, de retrato.
5. **Luz y color sobrios.**
   - Sin tonemapping fílmico fuerte: lineal más una LUT con una curva en S suave.
   - Sin bloom, sin viñeta y sin profundidad de campo.
   - Hemisférica cálida, una direccional cálida casi frontal y HDR a 0,5.
   - Dos "luces de normal" de color dentro del shader.
   - Fondo con degradado radial y un foco arriba.
6. **El SDK de Unity 3.8.6 trae el mismo tipo de controlador nativo** (`GnWrappers.AvatarController`), pero más viejo:
   - Le faltan demeanor, body motion y énfasis.
   - El otro informe ya lo descartó por fallos silenciosos y un cierre de Unity.
   - Lo que sí sirve del SDK son sus clips oficiales y sus nombres FACS. El clip `DefaultIdle` (3 cm cada 10 s, según `SoniaAnimations.cs`) ya se parece mucho a `baseIdle01`. Los clips concretos de Mia no son públicos.
7. **Lo que más rinde para Sonia** está en el apartado 9. Por orden:
   - Las ganancias por canal del lip-sync de Genies en `FaceRig` (minutos).
   - Respiración aditiva continua.
   - Un solo reposo largo y nada más mientras se conversa.
   - Cabeza más libre con los ojos al visitante.
   - Mirada distinta por estado.
   - Parpadeo más largo.
   - Fundidos con curva suave.

## 2. Cómo está montada la página

- **Pila técnica:** Next.js con three.js r180 y `@geniesinc/genies-naf-webgl` 0.1.101. El WASM (`/chat/_next/static/wasm/v0.1.101/release/NAFWebGL.wasm`) pesa 5,5 MB [Código]. La clase `NafScene` (chunk `772-…`, módulo 5685) monta la escena. El controlador nativo de animación (`AvatarController`, del espacio de nombres `GnBehaviour`) mueve esqueleto y blendshapes, y `syncPose()` los copia a three.js cada fotograma.
- **Datos de Mia** (en `__NEXT_DATA__` de la propia página) [Datos]:
  - `smartAvatar.behavior` (`bm_behavior-config_70e1…`) trae:
    - Dos listas de clips: `Utility_NoImpact` con 10 y `Mia(IDset)` con 174.
    - Un clip de emoción, "Happy".
    - El bloque `demeanor`, con 30 parámetros (apartado 3.6).
  - `metadata.camera` trae las cámaras por tamaño de pantalla.
  - `brain` trae el LLM y su configuración de comportamiento.
  - Cada clip trae `llmMetadata`, que sirve para que el LLM lo elija (apartado 5.3).
- **Clips fijos que inyecta la página para cualquier personaje** [Código, `772-…`, `_activateBehavior` y constantes `eQ`/`eK`/`e$`]. Los nombres salen de los metadatos CAMP [Medido]:

| Papel | Id | Nombre | Duración |
|---|---|---|---|
| Reposo | `bm_anim-asset_7ab09ca7…` | `actions-baseIdle01`, "State: Idle". Su descripción: "Basic idle with limited body movement and slightly looking around with the head". | 10,97 s, bucle |
| Respiración | `bm_anim-asset_0b5363d7…` | `rnd-smartBreathing` | 9,93 s, bucle, aditivo |
| Hablar | `bm_anim-asset_df14b7a8…` | `rnd-0063-smartAvatarTalking`, solo cara | 3,97 s, bucle |
| Emoción | `bm_anim-asset_c54a903c…` | `poses-allEmotes`, una hoja de poses de 1,2 s | — |

- **Grafo nativo** (`serializeGraph()`) [Medido]. Tiene 22 nodos, en este orden:
  1. Mezclador de cuerpo:
     - Mezcla 0 Idle, 1 Boredom, 2 EmotionBody y 3 Gesture.
     - Suma 4 Breath como capa aditiva.
  2. Mezclador de cara: BaseEmotion y Emote1-4.
  3. Mezclador de boca: Talking.
  4. `BodyMotionNode`.
  5. `GazeNode`.
  6. `DynamicsNode` (pelo y ropa).
  7. `SkeletonFixupNode`.
  8. `BlinkNode`.
  9. `BehaviorSettingsNode`.
  10. `VoiceAnimation`.
  11. `MouthCloserNode`.

  Los pesos `BlendingWeight0/1/3` que expone el SDK web (`setIdleWeight`, `setBoredomWeight`, `setGestureWeight`) son las ranuras 0, 1 y 3 de ese mezclador [Código]. Ponerlos a mano no sirve: `setIdleWeight(0)` no cambió nada [Medido]. [Inferencia] Con un behavior activo, el motor los reescribe en cada fotograma.

## 3. Cuerpo en reposo

### 3.1 Qué se mueve y cuánto [Medido]

Simulación de 90-120 s a 30 fps con todo como en la web. Mia mide unos 1,45 m: cadera a 0,75 m y hueso de la cabeza a 1,255 m.

| Medida | Rango total | Componente principal |
|---|---|---|
| Cadera, lateral (X) | −2,7 a +2,4 cm (SD 1,1 cm) | 11 s: ~1 cm. 5,5 s: 0,6 cm. 3,7 s: 0,25 cm. |
| Cabeza, lateral | −2,7 a +2,2 cm | Igual que la cadera: el cuerpo entero se traslada, sin inclinarse. |
| Cabeza, adelante y atrás | 3,6 cm | 11 s y 5 s (respiración) |
| Cadera, giro / alabeo / cabeceo | ±1,2° / ±0,6° / −4,6 a +2,7° | 11 s |
| Pecho (`Spine2`), giro | ~±2° | 11 s: 2°. 5,5 s: 1,7°. |
| Pecho, cabeceo | 7,8° de rango | 11 s: 1,2°. 5 s: 1,1° (respiración). |
| Cabeza, giro | −3,9 a +0,8° | 11 s: 1,3°. 5,5 s: 0,9°. |
| Cabeza, cabeceo | 3,5 a 11° (mira algo hacia abajo) | 11 s: 1,1°. 5 s: 1,1° (respiración). |
| Cabeza, alabeo | ±2,5° | 5,5 s: 1° |
| Pies | Deriva de 2-5 mm, elevación ≤ 3,5 mm | Sin pasos en 90 s |

**El balanceo es un único traspaso de peso lento por cada vuelta del clip de 11 s.**
Lleva armónicos a 5,5 y 3,7 s que lo hacen orgánico. Sobre eso, la respiración añade
una inspiración cada 5 s.

### 3.2 Qué NO lo produce [Medido]

| Prueba | Resultado | Conclusión |
|---|---|---|
| FBIK apagado (apaga el movimiento procedural) | Balanceo idéntico: ±2,5 cm | La parte procedural no aporta nada. |
| Diagnóstico de body motion | `solverReady: false`, `rigRecipeApplied: false` | Mia no trae receta de rig, así que el solver ni arranca. |
| Respiración a 0 | Cadera ±2,0 cm, sin el componente de 5 s en pecho y cabeza | La respiración solo aporta la oscilación de 5 s. |
| Toda la simulación | Ningún aburrimiento, gesto ni variación en reposo | Mia no tiene etiqueta "Bored". |

Con aburrimiento automático, el motor buscaría la etiqueta "Bored". La página filtra a
propósito el error "Failed to find Bored animation tag" [Código], señal de que en Genies
lo normal es no tenerla.

### 3.3 Respiración

`rnd-smartBreathing`:
- Aditiva y en bucle de 9,93 s con **dos respiraciones** (una cada ~5 s, 12/min).
- Mueve el pecho ±1,1°, la cabeza ±1° y la cabeza ±4 mm adelante y atrás [Medido].

Por defecto suena a peso 1,0 desde la versión 0.1.33 del SDK web ("Breathing animation now
plays at weight 1.0 by default") [Docs]. El look-at de la cabeza solo toca cabeza y
cuello para "no pelearse con la respiración" (0.1.32) [Docs].

Cada clip del behavior trae un `breathingSpeed`: 1 en todos los gestos y **2 en la
emoción "Happy"** [Datos]. [Inferencia] La respiración se acelera mientras dura una
emoción.

### 3.4 Aburrimiento, variaciones y "secondary"

Valores por defecto del grafo nativo [Medido, `serializeGraph`]:
- `IdleTimeBase` 8 s ±1.
- `BoredTimeBase` 15 s ±5. Es la cadencia de los clips de aburrimiento con `setAutoBoredom`.
- Gestos y aburrimientos se sostienen hasta 15 s ("hold for 15 seconds by default") [Docs 0.1.33].
- Gestos, aburrimiento y emociones de cuerpo se reproducen **en espejo con probabilidad del 50 %** ("mirrored with 50% probability"). Se intercambian huesos y blendshapes izquierda y derecha [Docs 0.1.33].

[Inferencia] `IdleTimeBase` es el cambio entre varios reposos base. El WASM tiene
`PlayRandomIdle` y una lista `baseidles`. Con un solo reposo, como Mia, no hace nada.

**Un personaje completo, Veyra** (el único con voz) [Datos, `/chat/veyra`], trae listas
de utilidad que Mia no tiene:

| Lista | Contenido |
|---|---|
| `bored` (8 clips) | Cinco reposos de 11 s (`baseIdle01` a `baseIdle05`, "standing still with subtle swaying and head movement"), "lookingAround" ("shifting weight between legs while slowly looking around aimlessly", 11,7 s), "lookAtNails" y "listeningGeneric". |
| `think` | "subtleThinkChaotic" ("tilts head upward and slowly looks around with eyes raised"), "subtleThinkCalm" ("tilts head slowly left/right") y "subtleThinkGeneric" ("looks upward and slowly to the left and right with their eyes only"), de 5-6 s. |
| `listen` | "listeningLeaningIn" (se inclina hacia delante y ladea la cabeza, y después asiente, 8,8 s), "listeningGeneric" ("slightly raising eyebrows to show interest"), "nodYesCalm" ("closes eyes and nods slowly"), "listeningNod" y "listeningTildedNod". |

Su demeanor también usa `baseIdle01` como reposo (`Base_Idle`, mismo identificador
interno). El aburrimiento de un personaje completo es, por tanto, alternar reposos y
miradas alrededor de 11 s cada 15 ±5 s. Pensar es mirar arriba y a los lados con poco
cuerpo. Escuchar es inclinarse, levantar las cejas y asentir despacio.

**Qué es "secondary".** No está documentado. Los dos enums encajan uno a uno [Medido]:

| Canal (`AnimationChannel`) | Ranura del mezclador del grafo |
|---|---|
| Idle = 0 | Idle |
| Boredom = 1 | Boredom |
| Secondary = 2 | EmotionBody |
| Gesture = 3 | Gesture |
| Breath = 4 | Breath |

[Inferencia] "secondary" es la capa de **cuerpo de las emociones** (`playEmotionBody`).
Encaja con `SetEmotionSecondary` de la librería nativa de Unity.

### 3.5 Transiciones [Medido]

Al lanzar un gesto (`noImpact02`):
- **Entrada:** el peso sube de 0 a 1 en 0,77 s siguiendo **smoothstep**. Muestras cada 0,1 s: 0,07, 0,20, 0,37, 0,57, 0,75, 0,90, 0,98, 1.
- **Salida:** es simétrica, en 0,83 s.

Coincide con `TransitionToClip_Duration` 0.8 del demeanor. Sonia funde en lineal
(`MotionPlayer`, `MoveTowards`) y en 0,3-0,7 s.

### 3.6 Demeanor de Mia [Datos]

Son los parámetros del personaje para los sistemas procedurales del motor. No hay
documentación de cada clave salvo las de parpadeo [Docs 0.1.77]. El significado sale del
nombre y de lo medido.

| Grupo | Valores de Mia | Qué hace (medido o inferido) |
|---|---|---|
| WeightShift | Cada 5,5-11 s. Duración 0,9 s. Rango 0,5. Curva "Dramatic". | Traspaso de peso procedural. Inactivo en Mia: sin solver. |
| FootBalance | Base de apoyo 0,11 m. Paso de 0,4 s, 2 cm de alto, 3° de giro. | Pasitos de reequilibrio. Inactivo. |
| PoseSettle | 2-3 s | Asentarse tras un cambio de pose. |
| TransitionToClip | 0,8 s, "Dramatic" | Entrada y salida de gestos (apartado 3.5). |
| TransitionToPose | 1,05 s, "Dramatic" | Paso a poses. |
| EyeMotion | Fijación de 1,25 a 3,25 s. Sacada de 0,3 s. Máximo 8 sacadas seguidas. 20 % de volver al objetivo. Rango 0,5. Preset "Moderate". | Mirada (apartado 4.2). |
| EyeMotion_BlinkDuration | 0,35 s (por defecto 0,4) | Parpadeo (apartado 4.1). |
| EyeAim | Centro desplazado 10° abajo. Desvío máximo X 30, Y 20. | Límites y centro de la mirada. |
| StartingEmotion | "Happy", intensidad 1 | Sonrisa base constante (apartado 4.3). |
| Lipsync_Blendshape_Scalar | 1 | Ganancia del lip-sync. |

### 3.7 El movimiento procedural que trae el WASM

Aunque en Mia está apagado, el WASM trae una configuración por defecto de
`BodyMotionConfig`. Es la que devuelve `getBodyMotionConfig()` [Código y Medido]. Es una
buena referencia para nuestros acentos al hablar (recomendación B2).

- **Columna:** la definen 4 huesos (`Spine`, `Spine2`, `Neck`, `Head`) y clases de curva
  sagital y coronal ("smallC", "largeS"...) con su reparto por hueso. La postura
  "relaxed" es una C pequeña de 5°.
- **Secuencia "breakdown"** (acento de énfasis, unos 0,8 s, en cascada):
  1. **Preparación**, de 0 a 0,16 s:
     - Cadera −0,4°, `Spine` −0,8° y `Spine2` −1,2°.
     - Los brazos van un poco atrás.
  2. **Acento**, cada parte un poco después de la anterior:
     - Cadera desde 0,025 s: rodillas flexionadas y raíz +3°.
     - Torso desde 0,11 s: `Spine` −0,8° y `Spine2` +3,4°.
     - Cabeza desde 0,18 s: cuello +2° y cabeza +5,5°.
     - Brazos desde 0,2 s.
  3. **Vuelta a cero:** cadera a 0,195 s, torso a 0,30 s, brazos a 0,34 s y cabeza a 0,385 s. Cada tramo dura de 0,3 a 0,4 s.
  4. Todos los pasos llevan `scaled: true`. [Inferencia] Se escalan por la intensidad del énfasis.
- **Secuencia "headNod"**, 1,2 s:
  - Arriba 0,3 s, abajo 0,5 s y rebote al 12,5 % en 0,23 s.
  - Lleva un pequeño giro y alabeo para que no sea simétrico.
  - Las magnitudes del JSON (cabeza −54/+63) solo tienen sentido escaladas. [Inferencia] Son 5-6° reales.
- **Pies:** se fijan en el mundo (`preservePosition` y `preserveRotation`, transición de 0,05 s) para que lo procedural no los haga patinar.
- **Ajustes propios de Mia:** `dynamics` 0,08 y `dynamicsOverlap` 0,75.

### 3.8 De dónde salen los clips

**Formato y licencia**
- Los clips son OZZ en `cdn.genies.com/animation/…` y se resuelven por CAMP [Medido].
- `baseIdle01` y `smartBreathing` no están en el SDK de Unity ni en los repositorios públicos de `geniesinc` (búsqueda por nombre con `gh`).
- Usarlos en Sonia plantea la misma duda de licencia que la AnimationLibrary interna, ya descartada.

**Lo más parecido que ya tenemos**
- `DefaultIdle` del SDK: 9,97 s, con un traspaso de unos 3 cm cada 10 s según `SoniaAnimations.cs`.
- `idles-0024-basicIdle`: 1 cm de vaivén.

**Los gestos de Mia**
- Son 184 clips de los animadores de Genies (Ryan, Geoff, Jin, Mandy).
- La mayoría están en estado "WIP" o "Not Ready".
- Cada uno trae vídeo de referencia y `llmMetadata` (apartado 5.3).

## 4. Cara en reposo

### 4.1 Parpadeo [Medido]

- **Frecuencia:** 40 parpadeos en 120 s, unos **20 por minuto**.
  - Los intervalos siguen un patrón de 2,3, 4,2 y 4,5 s, más dobles parpadeos a 0,2-0,7 s en un 18 % de los casos.
  - Con `blinkEnabled = false` no queda ninguno, así que son procedurales.
  - [Inferencia] El patrón sigue la vuelta del reposo porque el motor parpadea en cada cambio de objetivo de la mirada ("Blink triggers on any eye or head gaze-target change", 0.1.32 [Docs]) y el reposo trae atributos de ojos (`hasEyeAttrs`).
- **Duración:** el ojo pasa más de 0,25 s cerrado más de la mitad.
- **Valores por defecto del grafo:**

| Parámetro | Valor |
|---|---|
| Intervalo | 4 s ±1 |
| Duración | 0,4 s ±0,04 (Mia usa 0,35) |
| Reparto cerrar / mantener / abrir | 0,333 / 0 / 0,667 |
| Desfase entre ojos | ±16 ms |
| Cejas | Acompañan con su propia curva de 1,2 s. Bajan hasta 0,25 en `BROW_LOWERER`. |

Sonia hoy, en `AvatarStateController`: parpadeo de 0,14 s cada 2,5-6 s, 12 % de dobles.

### 4.2 Mirada: plantillas de atención [Medido]

**Cómo mira Mia**
- En Mia **la cabeza no sigue al espectador**: `getLookWeight()` es 0. La doc lo confirma: "eye gaze defaults to fully on; head look-at consumer-driven" (0.1.54) [Docs], y la página nunca lo sube.
- Los ojos apuntan a la posición de la cámara en cada fotograma (`setLookAtCamera`).
- No sigue al cursor.

**Plantillas de atención**
- Modos del enum nativo: 0 Listening, 1 Speaking (sin nombre en el enum web, pero así lo lista la doc de iOS), 2 Bored, 3 Thinking, 4 Angry y 5 Custom.
- La página pone el 1 al empezar a hablar y el 0 al acabar, con 1 s de fundido [Código].
- Los valores de cada plantilla no se pueden leer (son nativos). Se midió su efecto en los ojos durante 60 s por modo:

| Modo | Mirando al espectador | Saltos de mirada por minuto | Fijación media | Hasta dónde se va |
|---|---|---|---|---|
| Speaking (1) | Casi siempre. Solo microderivas de ±0,1 en el blendshape. | 0 | — | 0,13 |
| Listening (0) | 37 % | 10 | 5,7 s | ±0,45 en horizontal (≈13°) |
| Thinking (3) | 29 % | 20 | 2,8 s | Arriba y a los lados |
| Bored (2) | 13 % | 17 | 3,3 s | ±0,75 (≈20°), a menudo abajo |
| Angry (4) | 30 % | 25 | 2,2 s | Abajo y a un lado |

"Hasta dónde se va" está en unidades de blendshape `EYES_LOOK_*`. [Inferencia] Con un
desvío máximo de 30°, 0,45 ≈ 13°.

**Campos de la plantilla en el SDK de Unity**
`GnWrappers/AttentionTemplate.cs`: `eyeContactBias`, `scanEntropy`, `excursionRate`,
`maxExcursions`, `excursionReturnToCamera`, `returnUrgency`, `headSpeedDegrees`,
`headDeadZone`, `eyeSpeedDegrees`, `yawDeg`, `pitchUpDeg`, `pitchDownDeg`,
`up/side/downBias`, `microFixationMin/Max`, `excursionFixationMin/Max`,
`allowCameraDarts`, `cameraDartProb`, `eyeDartDuration`, `blinkPercentOnGazeChange` y
`blinkGazeChangeThreshold`. Sirven de lista de comprobación para nuestro
`EyeGazeController`.

**Sonia hoy:**
- Cabeza a la cámara con peso 0,7, más un vaivén Perlin de 1,4°.
- Ojos con sacadas de 2,5° cada 0,7-2,6 s.
- Vistazos de 5° cada 4-9 s, de 0,35-0,9 s.
- Desvío total tope de 7°.

### 4.3 Sonrisa base y emociones [Medido]

**Sonrisa base.** Es la emoción de arranque "Happy" a intensidad 1 y está siempre puesta:

| Blendshape | Valor |
|---|---|
| `LIP_CORNER_PULLER` | 0,52 |
| `CHEEK_RAISER` | 0,52 |
| `INNER_BROW_RAISER` | 0,26 |
| `LID_TIGHTENER` | 0,21 |
| `LIP_PUCKER` | 0,17 |
| `JAW_COMPRESSOR` | 0,07 |

**Emoción puntual** (`playEmotion("happy", n)`):
- Sustituye a la base durante unos 2,5 s y vuelve a ella.
- Valores del grafo: subida de 0,5 s, mantenida de 1 s y bajada de 1 s.
- "Happy(5)" da `LIP_CORNER_PULLER` 0,87 de pico, `CHEEK_RAISER` 0,64, `INNER_BROW_RAISER` 0,52, `OUTER_BROW_RAISER` 0,28, `UPPER_LID_RAISER` 0,42 y `JAW_DROP` 0,17.
- "Happy(3)" sale asimétrica: 0,24 a un lado y 0,38 al otro. [Inferencia] Por el espejo aleatorio.
- Al acabar una emoción sin estar hablando, la mandíbula se cierra en 1 s (`EmotionMouthCloserDuration`, 0.1.54 [Docs]).

Los nombres FACS son los mismos que los de nuestro `FaceRig`.

## 5. Al hablar

### 5.1 Chat de texto, el caso de Mia [Código]

- **Petición al backend:** `POST https://chat.genies.com/v2/chat` con `enable_animation: true`. `need_voice` y `need_facemotion` van a falso fuera del modo voz.
- **Respuesta:** texto, etiquetas (`tags`) y una línea de tiempo por carácter (`timestamp`).
- **Mientras se escribe el texto:**
  - La página lo escribe a máquina.
  - Pone el bucle de boca `0063` (`startTalking`: `setTalkingEnabled(true)` y plantilla 1).
  - Al medirlo, ese bucle solo mueve la cara: `JAW_DROP` hasta 0,47, `LIP_FUNNELER` 0,46, `LIP_PUCKER` 0,45, `UPPER_LIP_RAISER` 0,54 y `DIMPLER` hasta 0,95. El cuerpo sigue en su reposo [Medido].
  - El texto entre asteriscos (narración) no mueve la boca.
  - Gestos y emociones salen en su instante de la línea de tiempo.
- **Mientras se espera la respuesta:** `startThinking()` pide el gesto "Think".
- **Al teclear:** `startListening()` pide "Listen", con 10 s de espera entre uno y otro.
- La lista de etiquetas de Mia no incluye ni "think" ni "listen" [Medido]. [Inferencia] Con ella no se ve nada.

### 5.2 Modo voz, para comparar con GPT-Live [Código, `dyn/91.cf7840f870465a40.js`]

Solo lo tiene Veyra en el catálogo público [Datos].

**Transporte**
- Sala LiveKit en `wss://realtime.genies.com:7880`. El formato de audio por defecto es PCM de 16 bit a 16 kHz.
- El agente devuelve su audio y, por un canal de datos, **ventanas de comportamiento** por frase (`utterance_id`, `utterance_window_index`).
- Cada ventana trae:
  - texto y tiempos por carácter;
  - `audio_start_ms` y `audio_duration_ms`;
  - `blendshape_values` con `blendshape_meta.fps`;
  - etiquetas G/E;
  - un mapa `emphasis` de `{word, t0, calibrated}`;
  - `is_final`.

**Boca: la manda el servidor, el navegador no analiza el audio**
- **Formato:**
  - Configuración activa: **74 canales por fotograma, 30 fps, ganancia 3 por defecto** (`getVoiceConfiguration()`) [Medido]. Los fotogramas llegan como `blendshape_values` (lista de listas, plana o indexada; `parseVoiceBlendshapes` acepta las tres).
  - El volcado de depuración lo etiqueta como "arkit-52", pero la configuración dice 74.
  - [Inferencia] Son las formas FACS de la cara de Genies, no visemas: la malla de la cabeza de Mia tiene 70. La doc 0.1.54 dice que la voz también movía la sonrisa y el cheek-squint ("no longer double-driven by voice") [Docs], así que el modelo del servidor anima la cara entera.
- **Audio:**
  - En streaming, PCM por LiveKit.
  - En respuestas completas, MP3 en base64 (`audio_code`), que se decodifica con Web Audio.
- **Carga y sincronía:**
  - Los fotogramas se cargan con `setVoiceAnimation(fotogramas, ganancia, añadir)`. El chat de Genies pasa **ganancia 1**, no la de 3 por defecto [Código, `772-…` y `91…`].
  - En cada fotograma se hace `setVoiceAnimationTime(reloj del audio)`. El reloj es la reproducción real del audio y no hay adelanto ni retraso configurado.
- **En streaming:**
  - Cada ventana se coloca en el fotograma `round(audio_start_ms/1000 × fps)`.
  - Si falta un tramo, se mantiene la última pose. Entre ventanas hay un fundido de 3 fotogramas.
  - La subida de fotogramas nuevos se aplaza mientras hay un gesto activo, para que no dé tirones.
- **Fallos:** si el servidor marca `degraded_modalities: motion`, se registra y se sigue sin boca.
- **Nodo nativo `VoiceAnimation`:** parámetros `VoiceAnimationGain`, `VoiceAnimationChannelGains`, `VoiceAnimationInterpolateFrames` (falso por defecto) y `VoiceAnimationBlend`. Después va `MouthCloserNode`, que cierra la boca al terminar [Medido, grafo].
- **Sin análisis de audio:** ni este WASM (0.1.101) ni su JavaScript tienen cadenas de volumen, envolvente o normalización para la voz. El escalado por volumen que anuncia la release 0.1.57 del SDK web no está en esta build [Código].
- **Ganancias por canal:** el demeanor de Veyra trae `Blendshape_Channel_Gains` [Datos, `__NEXT_DATA__` de `/chat/veyra`]. Genies **baja a mano las formas redondeadas** de su propio lip-sync:

| Canal | Ganancia |
|---|---|
| `LIP_FUNNELER_LB/LT/RB/RT` | 0,5 |
| `LIP_PUCKER_L/R` | 0,75 |
| `LIPS_TOWARD` | 0,4 |
| `CHIN_RAISER_T` | 0,3 |

  Mia usa en su lugar `Lipsync_Blendshape_Scalar` 1.

**Gestos**
- Se programan con la tabla de tiempos de cada etiqueta (`CLIP_START`, `CORE_START`, `CORE_END`, `CLIP_END` y `CRITICAL_BEAT`, cada uno en tiempo de TTS y de clip).
- El objetivo es que **el golpe del gesto caiga en su palabra**. Si hace falta, se empieza el clip a la mitad (`seek`).
- Un gesto no empieza hasta que acaba el núcleo del anterior.
- Si llega con más de 1,5 s de retraso, se salta.

**Énfasis**
- En cada `t0` llama a `playEmphasis(calibrated)`, que lanza los acentos procedurales del apartado 3.7.
- [Inferencia] Lo calcula el backend a partir de la prosodia.

**Subtítulos**
- Trozos de **20 caracteres en móvil y 30 en escritorio**, que salen cuando empieza su palabra.
- El subtítulo del visitante se borra 2 s después de su final.

**Interrupción**
- El agente pasa de `speaking` a otro estado y la página corta audio, boca, subtítulos y gestos a la vez.
- Después lanza un gesto "Interrupted".

**"Listen" al empezar a hablar el visitante**
- Nivel del micro ≥ 0,06, o ≥ 3 veces el suelo de ruido adaptativo, sostenido 200 ms.
- Silencio de cierre de 700 ms. Como mucho uno cada 6 s.
- Solo si el avatar no habla. También se dispara con el primer parcial de cada frase transcrita.

**Fin de la voz**
- En las respuestas con el audio completo (`playVoice`, sin streaming), el cuerpo deja de "hablar" 600 ms antes de que acabe el audio (`stopTalking`), para asentarse a la vez que la voz.

**Conexión**
- Reconexión con espera `min(15 s, 1 s·2^n)`, hasta 6 intentos.
- Indicador opcional de latencia y calidad (`?voiceLatency=1`).
- Saludo inicial con el micro cerrado y un tope de 30 s.

### 5.3 Quién elige gestos y emociones [Datos y Código]

**El LLM**
- Es `together_genies_deepseek-v4-pro`. La otra opción configurada es un experimento A/B entre DeepSeek v3.2 y `gpt-5-chat-latest`.
- Elige de una lista. La configuración del cerebro recomienda "no más de 20" gestos y 20 emociones.
- Escribe las etiquetas en la respuesta. Las emociones van como `Happy(4)`, con intensidad 3 si no se indica.
- La configuración del cerebro admite un `<monologue>` interno oculto para dosificar el ritmo. En Mia está vacío.

**Ficha de cada clip** (`llmMetadata`, que el LLM usa para elegir):
- `physical_description`: descripción en una frase.
- `intensity`: de 1 a 4.
- `impact`: `NoImpact`, `LowImpact` o `HighImpact`.
- `usage_frequency`: `Standard`, `Uncommon` o `Rare`.
- `usage_timing`: `Instant`, `Short` o `Long`.
- `core_start_time` y `core_stop_time`.
- `critical_beat_timestamp`.
- `is_gesture_held`.
- El backend usa estos datos para alinear el golpe con la voz.

**Otros clips**
- La lista `Utility_NoImpact` son gestos de relleno casi neutros ("lightly nods while gesturing with hands subtly at the side"), marcados como especiales.
- Hay reacciones a toques ("userTouch…", "touchHead…"): en web se puede tocar al avatar para que reaccione.

## 6. Cámara y encuadre [Datos y Medido]

La página elige la cámara según el ancho de ventana, con los puntos de corte de Chakra UI
(base, sm, md, lg, xl, 2xl; [Inferencia] por defecto 480/768/992/1280/1536 px). La lleva
a su sitio con un suavizado exponencial de factor 0,11 por fotograma: un 95 % en unos
0,4 s a 60 fps.

| Ventana | FOV vertical | Posición (m) | Inclinación | Qué se ve en 9:16 |
|---|---|---|---|---|
| base (móvil) | 20° | (0,02, 1,06, 4,00) | 0° | De las rodillas arriba, con mucho aire por encima |
| sm | 60° | (0, 1,19, 1,25) | −6,5° | Lo mismo, pero gran angular: cabeza grande, piernas cortas |
| md | 20° | (0,30, 1,05, 3,68), girada 3,8° | 0° | Avatar desplazado a un lado, para dejar sitio al chat |
| lg, xl, 2xl | 20° | (0,02, 1,07, 3,53) | 0,2° | De medio muslo arriba |

La cámara va **por debajo de los ojos** (1,07 m frente a unos 1,33 m), casi sin inclinar.
Con el teleobjetivo, la cara y el cuerpo conservan las proporciones del modelo.

Sonia usa FOV 40 a unos 1,3 m para la franja de cadera a cabeza (0,95 m). Con FOV 20
la misma franja pide la cámara a 2,7 m; con FOV 25, a 2,15 m.

## 7. Iluminación y postproceso

Valores efectivos en la página [Medido, `nafScene.scene` y `pipeline`], que vienen de
`https://d344oyp4d2jz0e.cloudfront.net/naf/scene.json` [Datos].

| Elemento | Mia | Equivalente en URP para Sonia |
|---|---|---|
| Tonemapping | Lineal, exposición 1 | `Neutral` (o `None`) en lugar de ACES |
| Etalonaje | LUT `CCNeutralTonemapFilmicLUT_09_SP.cube` (25³) a 1,0. Es una S suave: 0,125→0,09, 0,25→0,22, 0,5→0,54, 0,75→0,80, 0,875→0,91. No toca la saturación. | `Color Curves` (curva maestra con esos puntos) o una LUT propia en `Color Lookup` |
| Bloom | Apagado (intensidad 0) | Quitar, o umbral alto y 0,1 |
| Viñeta | Apagada en la práctica (el efecto está, a intensidad 0) | Quitar, o ≤0,15 |
| Profundidad de campo, SSAO | No | Quitar la DoF, o dejarla muy suave |
| Ambiente | Hemisférica: cielo `#FFF3E5`, suelo `#E6570A` (bote naranja), intensidad 1. Más ambiente `#B5B5B5` ×1. | Ambiente en modo Gradient, con los colores de marca |
| Luz principal | Direccional `#FFD8B8` ×2, casi frontal: 12° arriba, 11° a un lado. Sombras PCF de 2048, radio 3, bias −0,0008. | Una key cálida frontal y suave, con sombras suaves |
| Entorno | HDR `composer_hdr_v02…exr` a 0,5 | Reflection probe o skybox HDR a 0,5 |
| Luces del shader ("normal lights" del Mega Stylizer) | **A** cálida `#FFB189`, alfa 0,33, desde 317° de acimut y 30° arriba. **B** fría `#A9D2FF`, alfa 0,45, desde 36° y 30° abajo. [Inferencia] Leo `Equator` como acimut y `Polar` como elevación. Además `flatness` 0,15, `cartoonMix` 0 y `normalMapInfluence` 0,8. | Dos luces de poca intensidad con Light Layers solo para el avatar. En Unity, `MegaSkin` es PBR y no trae estas luces (`MegaStylizerCategories.json` lista `_LightA*`, pero el shader no las expone). |
| Fondo | Degradado radial en pantalla. Interior: color del personaje (Mia `#633B00`), desde (0,5, −0,25), radio 1,5, caída 4, alfa 0,75. Más un "foco" `#FFF1C8` en (0,5, 1,1), radio 0,35, caída 6, alfa 0,75. | Sonia ya tiene halo y telón. Le falta el brillo del foco arriba en el centro. |

El aspecto de Mia es **plano, cálido y frontal**, con color fiel al material. Sonia usa
ACES, contraste +10, saturación +8, bloom, viñeta y DoF. Eso oscurece y cambia el tono
de piel respecto a como Genies diseña sus shaders.

## 8. Interfaz, carga y cómo disimulan la espera [Código]

- **Carga progresiva:**
  - Primero sale una **silueta negra que ya respira con el reposo**. Después llega el avatar con texturas, y el reposo continúa en el mismo instante (`setIdleTime`).
  - El lienzo aparece con un fundido de 0,4 s.
  - Mensajes de carga en el tono del personaje: "Plugging the aux back in", "Cracking another sour candy"…
  - Sonia ya no tiene copia local (5 de octubre): al entrar en Play el escenario está vacío hasta que llega el avatar del SDK, poco si ya está en su caché. Un fundido corto al aparecer, como el de Mia, suavizaría esa llegada.
- **Esperas:**
  - En texto: gesto "Think" mientras llega la respuesta.
  - En voz: "Listen" al empezar a hablar el visitante.
  - Ruedita de carga en el botón del micro mientras conecta o piensa.
  - Sonidos de micro abierto y cerrado (`mic_start`, `mic_stop`).
- **"Te escucho":**
  - Onda del micro a lo ancho, en el tercio inferior.
  - Desenfoque de 18 px, color `#FFE8C9`, 48 puntos.
  - Sube rápido (0,35) y baja lento (0,06).
  - Respeta `prefers-reduced-motion`.
  - Mensaje "X can hear you, start talking!".
- **Subtítulos:** dos bocadillos apilados abajo (visitante y personaje) que se pueden apagar.
- **Robustez:**
  - El delta de tiempo se limita a 1/15 s para que un tirón no haga saltar la animación.
  - El avatar se pausa cuando no se ve.
  - Varios reintentos de carga.
- **Al cargar, la página llama sola a dos servicios:** `/v2/chat`, que genera el texto de bienvenida, y `/v1/llm/infer`, que genera las preguntas sugeridas para el usuario (prompts de inicio y seguimiento). Las preguntas sugeridas son una idea aprovechable para el stand.

## 9. Recomendaciones para Sonia

Cada una indica si va con recursos del **SDK** oficial o con **lo nuestro**. El esfuerzo
es para una persona, y cualquier cambio visual se verifica con la captura 9:16 (principio 7).

### A. Antes del 9 de octubre: mucho efecto, poco riesgo

**A1. Respiración aditiva continua.**
- **Qué hacer:**
  - Una inspiración cada 5 s (12/min).
  - Valores: `Spine2` ±1,1° de cabeceo, cabeza ±1° y unos 4 mm adelante y atrás. Opcional: hombros ±2 mm.
  - Que siga sonando al hablar, al pensar y en los gestos.
  - Que no dure lo mismo que el bucle del reposo. Si es procedural, no hay bucle.
  - Bonus: acelerarla ×1,5-2 cuando Sonia ríe o se emociona (el `breathingSpeed` de Genies).
- **Con qué:** lo nuestro. Procedural en `LateUpdate`, antes de la mirada de la cabeza, o capa aditiva en `MotionPlayer`.
- **Esfuerzo:** 2-3 h. Ya está en el plan B de `informe-reposo-genies.md`; estos son los valores objetivo.

**A2. Un solo reposo largo con traspaso de peso, y nada más mientras alguien conversa.**
- **Qué hacer:**
  - Objetivo: cadera ±2-2,5 cm en ~11 s, pecho ±2° de giro, cabeza ±1,3°, pies quietos.
  - `DefaultIdle` (SDK) ya está ahí. Medir los candidatos con `SoniaIdleCheck` contra estos números.
  - Mia no hace gestos en reposo. Los gestos de atención de Sonia (bailes, cuarta pared) se dejan solo con el stand vacío y espaciados, como el aburrimiento de Genies: 15 ±5 s y nunca con alguien delante.
- **Con qué:** SDK (clip oficial) y lo nuestro (coreógrafo).
- **Esfuerzo:** 1 h.

**A3. Cabeza más libre, ojos al visitante.**
- **Qué hacer:**
  - Mia tiene la cabeza a 0 y los ojos a 1.
  - En Sonia, bajar `lookWeight` de 0,7 a ~0,3 en reposo y escucha (quizá 0,4 al hablar) y dejar que el clip mueva la cabeza.
  - Revisar que los ojos llegan: `maxYaw` 10°, `gazeGain` 0,65 y desvío de 7°. Mia los deja ir hasta ±13° al escuchar.
  - Quitar el vaivén Perlin si el clip ya mueve la cabeza.
- **Con qué:** lo nuestro (`AvatarStateController`, `EyeGazeController`).
- **Esfuerzo:** 1 h más las capturas.

**A4. Mirada por estado**, con las plantillas medidas del apartado 4.2:

| Estado de Sonia | Cómo mira |
|---|---|
| Hablando | Fija en el visitante, solo microsacadas |
| Escuchando | Casi siempre al visitante, unos 10 vistazos por minuto con fijaciones de 5-6 s |
| Pensando | Arriba y a un lado, unos 20 por minuto, fijaciones de 2-3 s |
| Sin nadie | Amplio, unos 17 por minuto, a veces abajo |

- **Transiciones:** cambiar de plantilla con 1 s de fundido.
- **Parámetros del demeanor:** fijación de 1,25-3,25 s, sacada de 0,3 s, máximo 8 sacadas seguidas y 20 % de volver.
- **Con qué:** lo nuestro (`EyeGazeController`). El SDK solo lo ofrece dentro del controlador nativo.
- **Esfuerzo:** 2-3 h.

**A5. Parpadeo más humano.**
- **Qué hacer:**
  - Duración de 0,35-0,4 s en lugar de 0,14: cierra en 1/3 y abre en 2/3.
  - Base cada 4 ±1 s, más un parpadeo en cada cambio de objetivo de mirada. En total, unos 20 por minuto.
  - Dobles en ~15 % de los casos, desfase entre ojos ≤16 ms y cejas que bajan ~0,2 con el parpadeo.
- **Con qué:** lo nuestro (`AvatarStateController`).
- **Esfuerzo:** 30-60 min.

**A0. Ganancias por canal del lip-sync al estilo Genies.**
- **Qué hacer:** aplicar en las recetas de `FaceRig` las ganancias de Veyra:
  - `LIP_FUNNELER_*` ×0,5
  - `LIP_PUCKER_*` ×0,75
  - `LIPS_TOWARD` ×0,4
  - `CHIN_RAISER_T` ×0,3
- **Cómo comprobarlo:** comparar la correlación del laboratorio de cara (hoy r = 0,92) y una captura de la boca en la "o" y la "u".
- **Con qué:** lo nuestro, con valores de Genies.
- **Esfuerzo:** 15-30 min. Es lo único del lip-sync de Genies que se puede copiar tal cual: el resto lo calcula su servidor y uLipSync ya hace localmente lo equivalente.

**A6. Fundidos con curva suave y espejo.**
- **Qué hacer:**
  - Pasar el progreso lineal de `MotionPlayer` por smoothstep (`3p² − 2p³`), sin perder la normalización.
  - Gestos a 0,8 s de entrada y de salida.
  - Generar copias en espejo de los gestos y elegir al 50 %: `AnimationClipSettings.mirror` en clips Humanoid, desde `SoniaMotionSetBuilder`.
- **Con qué:** lo nuestro, sobre clips del SDK.
- **Esfuerzo:** 1-2 h.

### B. Si sobra tiempo antes del evento

**B1. Inclinarse al empezar a hablar el visitante (lean-in).**
- **Qué hacer:**
  - Con el primer `transcript` parcial de cada turno, o con el nivel del micro (umbrales del apartado 5.2: 0,06, 200 ms, 700 ms).
  - Como mucho uno cada 6 s y solo si Sonia calla.
  - Procedural: unos 2-3° de columna hacia delante y 3-4° de ladeo de cabeza durante 1-1,5 s. Después, escucha normal.
  - Para la escucha posterior, el repertorio de Genies (lista `listen` de Veyra, apartado 3.4): cejas un poco arriba en señal de interés, asentir despacio, a veces con los ojos cerrados, y ladear la cabeza con un pequeño traspaso de peso.
- **Con qué:** lo nuestro (Unity). El parcial ya llega por el protocolo.
- **Esfuerzo:** 2 h.

**B2. Acentos al hablar.**
- **Qué hacer:**
  - La secuencia "breakdown" del apartado 3.7, o el cabeceo "headNod" de 1,2 s.
  - Disparada por picos de energía de la propia voz (`SpeechAnalyzer` o `LipSyncController`), con la intensidad escalada y un acento cada 0,6-1 s como mucho.
  - Sonia ya asiente hasta 2,5° en sílabas fuertes. Esto añade el torso (`Spine2` +3,4°) y la cascada cadera, torso, cabeza y brazos.
  - Mia no lo usa (solo voz), pero es lo que Genies hace con voz. Sonia habla sin clips de gesticulación, así que es lo que más cuerpo le daría al hablar.
- **Con qué:** lo nuestro.
- **Esfuerzo:** 3-4 h.

**B3. Reacción al ser interrumpida.**
- **Qué hacer:**
  - Al cortar la voz, cortar boca, subtítulos y gesto en el mismo fotograma.
  - Reacción breve de 0,6-1 s: cejas arriba y cabeza un poco atrás.
- **Con qué:** lo nuestro.
- **Esfuerzo:** 1 h.

**B4. Emociones cortas sobre la sonrisa base.**
- **Qué hacer:**
  - Comparar la sonrisa base de Sonia con la de Mia (apartado 4.3).
  - Añadir emociones puntuales: subida de 0,5 s, mantenida de 1 s y bajada de 1 s, intensidad 1-5, espejo al azar y cierre de boca en 1 s.
  - Disparadores sencillos: risa en el audio o transcripción ("jaja", "[laugh]"), exclamaciones y saludo.
- **Con qué:** lo nuestro (`FacialExpressionController` y `FaceRig`). Los nombres FACS del SDK son los mismos.
- **Esfuerzo:** 2-3 h.

**B5. Cámara de teleobjetivo.**
- **Qué hacer:**
  - FOV de 20-25° con la misma franja de encuadre y la cámara más lejos (2,1-2,7 m).
  - Recalcular los planos abierto, de panel y de Fuera con **Colocar avatar**.
  - Comparar con capturas 9:16 frente a FOV 40 y que decida Jean.
- **Con qué:** lo nuestro (`SoniaAvatarSetup`, `CameraFramingController`).
- **Esfuerzo:** 1-2 h.

**B6. Etalonaje y luz al estilo Mia** (apartado 7).
- **Qué hacer:**
  - Tonemapping `Neutral` con curva en S suave.
  - Sin bloom ni viñeta, y DoF mínima o ninguna.
  - Ambiente en degradado, key cálida frontal y dos luces de color solo para el avatar.
  - Probarlo como variante A/B con capturas.
- **Con qué:** lo nuestro (`SoniaStageLighting`).
- **Esfuerzo:** 2-4 h. Riesgo: cambia el aspecto a cuatro días.

### C. Para discutir o después del evento

**C1. Indicador de "te escucho".**
- Onda del micro abajo, frase "Sonia te escucha, ¡habla!" y sonidos de micro.
- Necesita el nivel del micro en el protocolo, en los dos lados.
- Esfuerzo: 3-4 h. Ayuda en un stand ruidoso a saber cuándo hablar.

**C2. Subtítulos por trozos de 20-30 caracteres** al ritmo de la voz.
- Esfuerzo: 1-2 h.

**C3. Preguntas sugeridas en pantalla.**
- Por ejemplo "¿Qué es Sonnet Code?" o "¿Cómo funcionas?". Pueden ser fijas y rotar.
- Es una funcionalidad nueva y hay que hablarla antes.
- Esfuerzo: 1-2 h.

**C4. Gestos elegidos por el modelo, como Mia.**
- GPT-Live no devuelve etiquetas.
- La vía sería reglas sobre el texto transcrito o una herramienta del backend, con poca densidad y el golpe alineado.
- Después del evento.

**C5. Motor nativo `GnWrappers.AvatarController` del SDK.**
- **Qué trae:**
  - Plantillas de atención.
  - Respiración (`SetBreath`, `SetBreathWeight`).
  - Aburrimiento.
  - Gestos por etiqueta.
  - Emociones.
  - Voz por blendshapes con ganancia (`PlayVoiceAnimation`).
- **Por qué no ahora:**
  - Es la API antigua, sin demeanor, body motion ni énfasis.
  - Necesita la entidad nativa del avatar, clips OZZ de Genies y volcar la pose a Unity.
  - Ya tumbó Unity una vez (ver `informe-reposo-genies.md`).
  - Y para el balanceo no aporta nada: en Mia su parte procedural ni funciona.

## 10. Lo que no se pudo averiguar, y qué podría grabar Jean

**No averiguado**

- **Los valores internos de las plantillas de atención.** Viven en código nativo y no hay getter. Solo se midió su efecto (apartado 4.2).
- **Cómo eligen el backend y el LLM los gestos, las emociones y el énfasis.** No se sabe cómo se calcula `calibrated` ni qué modelo convierte audio en los 74 canales. Solo se conoce el formato.
- **Tiempos reales de respuesta y densidad de gestos en una conversación**, porque no se chateó. La página mide el tiempo de "pensando" a "hablando" (`response_ms`), pero no se vio ningún valor.
- **El modo voz en vivo.** Mia no lo tiene; solo Veyra.
- **La escala real de las secuencias procedurales**, como el cabeceo de "−54" (apartado 3.7).
- **Las subconfiguraciones `balance`, `posture`, `micro` y `gaze`** del body motion. La doc las nombra, pero no aparecen en la configuración aplicada a Mia.
- **Si el traspaso de peso y los pasos de equilibrio funcionan con un avatar que sí tenga receta de rig.**

Chatear con Mia no enseñaría lip-sync: es un personaje solo de texto y su boca es el
bucle genérico del apartado 5.1. El lip-sync del servidor solo se ve con Veyra en modo voz,
que además pide permiso de micrófono.

**Qué podría grabar Jean**, si decide aceptar él mismo los términos de Genies:

1. **Mia en texto**, con `https://genies.com/chat/mia?animTimeline=1&voiceDebug=1` y la consola abierta.
   - Cada gesto y emoción sale como `[animTimeline] gesture play "…" @x.xxs`, con el `seek` y la tabla de tiempos.
   - Grabar la pantalla en 2-3 respuestas para ver densidad y estilo de los gestos.
2. **Veyra en voz** (`/chat/veyra`, la única con voz), con `?voiceDebug=1&voiceLatency=1&animTimeline=1`.
   - Tras una respuesta, `window.__voiceResponse.download()` guarda la respuesta con sus ventanas, los blendshapes, las etiquetas, el énfasis con `calibrated` y el audio.
   - El indicador de latencia da los milisegundos.
   - Con eso se ajustarían B2 y B4 con datos reales.

## 11. Qué está verificado y qué no

**Verificado** (5 de octubre, en una pestaña propia de Chrome):
- Datos de la página y del CDN: `__NEXT_DATA__`, `scene.json`, `studio-scene.json`, la LUT y el catálogo público.
- Código de los bundles y cadenas del WASM: el JSON de body motion, las claves de demeanor y los nodos del grafo.
- **Medidas en vivo.** La pestaña estaba en segundo plano y el bucle de la página no corría, así que se llamó a mano a `update(1/30)` y `syncPose()` del controlador de Mia, lo mismo que hace la página en cada fotograma. Se leyeron los huesos y los blendshapes:
  - balanceo con y sin FBIK y con y sin respiración;
  - parpadeos;
  - las cinco plantillas de atención;
  - un gesto y dos emociones;
  - el bucle de hablar.

**Huella en la página de Genies**:
- Para las capturas se ocultó solo por CSS, y se restauró después, el aviso "Setting the Scene…" con el botón "Start Chatting". No se pulsó.
- Se cambiaron cámara y tamaño del lienzo localmente y se restauraron.
- Se pidieron por la API de la propia página los metadatos de 4 clips (`campResolveItem`).
- Al recargar una vez la página para ver sus peticiones, ella sola llamó a `/v2/chat` (bienvenida) y `/v1/llm/infer` (sugerencias). Es su comportamiento de carga; no se escribió nada.
- La pestaña se cerró al terminar.

**Sin verificar:**
- Lo marcado [Inferencia].
- Los puntos de corte exactos de la cámara.
- Que las magnitudes de las secuencias procedurales estén en grados.
- Cómo se vería todo esto en Sonia: nada se ha probado en Unity.

## Fuentes

**La página y sus recursos** (consultados el 5 de octubre de 2026; los nombres de los bundles cambian con cada despliegue de Genies):
- Páginas: `https://genies.com/chat/mia` y `https://genies.com/chat/veyra` (su `__NEXT_DATA__`; la de Veyra se descargó con `curl`, sin ejecutar su JavaScript) y `https://genies.com/chat/api/catalog?resource=genies`.
- Bundles en `https://genies.com/chat/_next/static/chunks/`:

| Bundle | Qué contiene |
|---|---|
| `735259aa-d46bf19e612fa2cb.js` | SDK web: controlador, canales, `activateBehavior`, carga progresiva |
| `772-43eecdfbffdad0ab.js` | `NafScene`: cámara, mirada, voz, gestos, clips fijos |
| `552-72448e7609e302e1.js` | Página: configuración de la escena, cámaras, fondo, toques, chat |
| `91.cf7840f870465a40.js` | Voz en streaming |
| `340.fb0cf30a0006e244.js` | Chat de texto |

- WASM: `https://genies.com/chat/_next/static/wasm/v0.1.101/release/NAFWebGL.wasm`.
- Escena: `https://d344oyp4d2jz0e.cloudfront.net/naf/scene.json` y `…/naf/studio-scene.json`.
- LUT: `https://dbpochrf0zukx.cloudfront.net/luts/CCNeutralTonemapFilmicLUT_09_SP.cube`.

**Documentación del SDK web** (`https://docs.genies.com/docs/sdk-web/`): release notes
0.1.30, 0.1.32, 0.1.33, 0.1.35, 0.1.47, 0.1.54, 0.1.57, 0.1.77, 0.1.96 y 0.1.97, y la
página `api/summary`. De iOS, `sdk-ios/api/summary` (modos de atención).

**SDK de Unity 3.8.6** (`unity/Packages/com.genies.avatar-sdk.client/`):
- `Internal/NAF Plugin/Runtime/Scripts/SwigBindings/GnWrappers/AvatarController.cs`
- `…/GnWrappers/AttentionTemplate.cs`
- `Internal/NAF/Runtime/Scripts/Utilities/NativeSkeletonPoseSynchronizer.cs`
- `Internal/Shaders/Runtime/Shaders/Resources/MegaStylizerCategories.json`
- Cadenas de `libgnUnityPlugin.dll` y `libgnBehaviourWrapper.dylib`: no traen demeanor ni body motion.

**Del repositorio**: `docs/informe-reposo-genies.md`, `docs/unity.md`,
`unity/Assets/Scripts/Sonia/SoniaAnimations.cs`, `AvatarStateController.cs`,
`EyeGazeController.cs`, `AvatarChoreographer.cs` y `MotionPlayer.cs`.

## Resumen

- **El balanceo** de Mia es un reposo de 11 s con traspaso de peso (±2,5 cm de cadera) más una respiración aditiva de una inspiración cada 5 s. Nada procedural.
- **Lo que la hace natural**:
  - La cabeza no persigue al espectador y los ojos sí.
  - Parpadea a menudo y despacio.
  - Sonríe siempre un poco.
  - No hace nada más en reposo.
  - Funde los gestos en 0,8 s con curva suave.
- **Al hablar**:
  - Mia no tiene voz: su boca es un bucle genérico.
  - En los personajes con voz, la boca (74 canales FACS a 30 fps) y el énfasis vienen del servidor. El navegador solo los sincroniza con el audio, y Genies atenúa a mano las formas redondeadas.
  - Los gestos los elige el LLM y se alinean con la palabra.
  - Escucha inclinándose cuando el usuario empieza a hablar.
  - Reacciona si la interrumpen.
- **Cámara y luz**: teleobjetivo de 20° y luz frontal cálida con color fiel, sin bloom, viñeta ni DoF.
- **Para Sonia antes del 9 de octubre**, todo con nuestro código sobre clips oficiales del SDK:
  - Ganancias por canal del lip-sync de Genies.
  - Respiración aditiva.
  - Un solo reposo tranquilo.
  - Cabeza más libre con los ojos al visitante.
  - Mirada por estado.
  - Parpadeo más largo.
  - Fundidos suaves con espejo.
- **El motor nativo del SDK** no aporta nada al balanceo y queda para después del evento.
