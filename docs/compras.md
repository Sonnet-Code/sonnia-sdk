# Assets de pago: lista de compra

Investigación de septiembre de 2026 para mejorar animaciones, ojos y lip-sync
del avatar. Precios en USD tal como aparecían en la Asset Store de Unity y en
las webs de los vendedores; la tienda cobra en la moneda de la cuenta. Las
compras las hace Jean con su cuenta; nada de esto es dependencia obligatoria:
todo lo que hay en el proyecto hoy es gratuito.

## Tope de 50 USD (vigente)

| Opción | Precio | Qué aporta | Recomendación |
|---|---|---|---|
| **Conversation Animation Pack**, MoCap Online: [mocaponline.com/products/convo](https://mocaponline.com/products/convo) (demo gratuita para probar el flujo: [mocaponline.itch.io/mocap-online-demo](https://mocaponline.itch.io/mocap-online-demo)) | 29,99 (35 en la Asset Store) | 28 clips de conversación capturados con mocap real, con dedos animados, versiones largas y en bucle, escuchar e "idea". Vídeo previo y visor 3D en la web. | **Primera compra.** Ataca justo el problema de manos y muñecas de los clips de Mixamo. |
| **Realistic Eye Movements** (Tore Knabe): [assetstore.unity.com/packages/tools/animation/realistic-eye-movements-29168](https://assetstore.unity.com/packages/tools/animation/realistic-eye-movements-29168) | 25 | Mirada, sacadas y parpadeo basados en datos reales; actualizado para Unity 6. | Segunda opción. Sustituiría `EyeGazeController`. Junto con el pack anterior se pasa del tope (54,99): es una u otra. |
| Motions sueltos femeninos de **ActorCore** (Reallusion): [actorcore.reallusion.com/3d-motion](https://actorcore.reallusion.com/3d-motion) (buscar "talk" o "gesture" y filtrar por Female; la web es una app y no enlaza cada motion de forma estable) | 2 a 3 cada uno | Gestos de habla individuales con dedos, personaje femenino, FBX compatible con Humanoid. | Para rellenar variedad si sobran 10 o 15 USD. |

Consejo: comprar solo el Conversation Animation Pack por 29,99 y probarlo
retargeteado sobre Babe antes de gastar más. Si el cuerpo sigue pareciendo
repetitivo, ampliar con motions de ActorCore.

### Descartado bajo 50 USD

- **FaceSync** (20): envuelve Oculus Lipsync, cuyo plugin nativo de macOS es
  solo x86_64 y no arranca en un Mac arm64. uLipSync (MIT) ya cubre el lip-sync
  por fonemas.
- **Animancer Lite**: sin capas ni fundidos configurables en builds; el
  reproductor por Playables (`MotionPlayer`) ya lo cubre.
- Packs de animación baratos de la Asset Store sin reseñas ni vídeo previo.
- **Final IK** (90): fuera de presupuesto y Animation Rigging gratis basta.

## Lista original sin tope (unos 310 USD, referencia)

| Asset | Precio | Para qué |
|---|---|---|
| Animancer Pro v8 | 90 | Fundidos por código y capas. Ya no hace falta: lo cubre `MotionPlayer` con Playables. |
| Conversation Animation Pack (MoCap Online) | 35 | Ver arriba ([enlace](https://mocaponline.com/products/convo)). |
| Core Motion Pack (MoCap Central): [mocapcentral.com](https://mocapcentral.com) | 50 | 659 animaciones: idles con tics, hablar, escuchar, saludar, señalar, bailes. Sample gratuito de 120 clips. |
| Realistic Eye Movements | 25 | Ver arriba ([enlace](https://assetstore.unity.com/packages/tools/animation/realistic-eye-movements-29168)). |
| FaceSync | 20 | Descartado (ver arriba). |
| Beautify 3 | 52 | Nitidez, bloom y color en Unity 6. El Volume de URP con ACES y bloom ya da un resultado parecido. |
| Volumetric Light Beam | 45 | Haz volumétrico detrás del avatar. Sustituido por el halo aditivo y las motas de `SoniaStageLighting`. |

Opcionales de aquella lista: HAZE (niebla volumétrica URP, 35), Lux URP
Essentials (piel y pelo, 25), SALSA LipSync Suite (45; por amplitud, no por
fonemas).

Descartados: Oculus Lipsync (fin de vida), Audio2Face de NVIDIA (exige GPU
NVIDIA; el mini PC del stand es AMD), Kevin Iglesias (combate y locomoción),
Aura 2 (no URP).

## Gratuito ya integrado

- Biblioteca de animaciones de Ready Player Me ([github.com/readyplayerme/animation-library](https://github.com/readyplayerme/animation-library); copia en `unity/Assets/Animations/RPM`,
  licencia en la carpeta): idles, variaciones, habla femenina y masculina,
  bailes. Hecha para el esqueleto de Babe, sin problemas de dedos ni muñecas.
- Mixamo (`unity/Assets/Animations/Mixamo`): bailes, gestos de cuarta pared,
  pensar y asentir. Los clips de habla de Mixamo se retiraron por dedos en
  garra y manos hundidas en las caderas de Babe.
- uLipSync (MIT) para el lip-sync por fonemas: [github.com/hecomi/uLipSync](https://github.com/hecomi/uLipSync).
- Mixamo: [mixamo.com](https://www.mixamo.com).
