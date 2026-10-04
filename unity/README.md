# Proyecto Unity de Sonia

Avatar 3D de Sonia: reproduce la voz de GPT-Live que le envía el orquestador,
mueve los labios según los fonemas del audio (uLipSync), dispara las
animaciones de estado y muestra imágenes en la escena.

- Versión del editor: **6000.6.0f1** (Unity 6.6), plantilla URP.
- Escena inicial: `Assets/Scenes/SampleScene.unity`.
- Scripts: `Assets/Scripts/Sonia/` (namespace `Sonia`).
- Solo Input System nuevo: `UnityEngine.Input` lanza excepción, se usa
  `UnityEngine.InputSystem`.
- Pantalla del stand: monitor **vertical 9:16, 1080x1920**. La escena, la cámara
  y el HUD están montados para ese formato.

La guía completa (montar la escena, conseguir el avatar, animaciones,
lip-sync, ajustes de audio, build para el stand y licencias) está en
[`../docs/unity.md`](../docs/unity.md).

Arranque rápido:

1. Abrir el proyecto y esperar a que resuelva `com.unity.nuget.newtonsoft-json`.
2. Menú **Sonia > Crear escena base**. Deja también los ajustes de build en
   1080x1920; **Sonia > Configurar build 9:16** los vuelve a poner si hace falta.
3. Poner la Game view en **9:16 Portrait**.
4. Importar el avatar en el origen del objeto `Sonia` y asignar sus campos en el
   inspector.
5. Levantar el orquestador desde `server/` y darle a Play. F1 muestra el HUD.
