// Encuadre dinámico de la cámara del stand.
//
// El plano base es un plano medio muy cerrado: de las caderas a un palmo por
// encima de la cabeza, para que la cara y la boca se vean grandes. Ese encuadre
// es perfecto para hablar y escuchar, pero corta a Sonia por los lados en cuanto
// se pone a bailar o saluda con el brazo en alto.
//
// Este componente maneja tres encuadres y va al que toque, siempre con una
// interpolación suave para que se lea como un movimiento de cámara:
//
//   abierto  bailes, gestos de atención y saludo (lo dice el coreógrafo)
//   panel    mientras hay una imagen puesta: se echa un poco atrás y sube para
//            que la imagen, fija en la franja alta de la pantalla, no tape a
//            Sonia (que sigue de cintura para arriba)
//   base     el plano medio de siempre, con la cara grande
//
// La prioridad es esa: si Sonia baila mientras hay una imagen, manda el baile.
// El plano abierto está apagado por defecto (en el stand la cámara no se mueve
// por bailes ni reverencias); el de panel es un retroceso suave.
//
// Por encima de todos va el plano de salida (modo "Fuera"): mientras Sonia se
// va caminando, está fuera y vuelve, la cámara se abre al plano de cuerpo
// entero para que el paseo se vea (en el plano medio no se ven las piernas y
// saldría de cuadro en un paso). Ese movimiento es un travelling con
// SmoothDamp, que arranca y frena suave; el resto conserva su suavizado.
//
// El panel (sección «Developer») puede mover el plano base: desplazamiento,
// zoom e inclinación sobre la pose que dejó el menú del editor. El plano de
// panel va con él (es un desplazamiento del base); los de cuerpo entero
// (abierto y salida) se quedan en su sitio.
//
// Y por encima de todo, un encuadre impuesto desde fuera (SetOverride): el Modo
// Jean pone a los dos en plano entero mientras el invitado entra y se dan la
// mano, y luego al invitado en el plano medio. Va con el mismo travelling.

using System.Collections.Generic;
using UnityEngine;

namespace Sonia
{
    /// <summary>Pose de cámara de un encuadre (posición, rotación y campo de visión vertical).</summary>
    public struct ShotPose
    {
        public Vector3 Position;
        public Quaternion Rotation;
        public float FieldOfView;

        public ShotPose(Vector3 position, Quaternion rotation, float fieldOfView)
        {
            Position = position;
            Rotation = rotation;
            FieldOfView = fieldOfView;
        }
    }

    /// <summary>
    /// Aleja la cámara mientras Sonia hace una animación grande y la devuelve al
    /// plano medio al acabar. Sin cámara o sin coreógrafo no hace nada.
    /// </summary>
    [DisallowMultipleComponent]
    public class CameraFramingController : MonoBehaviour
    {
        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Cámara del stand. Si está vacío se usa la cámara principal.")]
        private Camera targetCamera;

        [SerializeField]
        [Tooltip("Coreógrafo del avatar. Dice cuándo suena un gesto grande que pide plano abierto.")]
        private AvatarChoreographer choreographer;

        [SerializeField]
        [Tooltip("Panel de imágenes. Mientras esté visible se usa el encuadre de panel.")]
        private ImagePanelController imagePanel;

        [Header("Plano abierto")]
        [SerializeField]
        [Tooltip("Abrir el plano durante bailes y gestos grandes. Apagado: la cámara se queda en el plano medio aunque no quepa el cuerpo entero.")]
        private bool wideShotEnabled;

        [SerializeField]
        [Tooltip("Posición de la cámara en plano abierto. La calcula Sonia > Colocar avatar con las medidas del modelo.")]
        private Vector3 wideShotPosition = new Vector3(0f, 0.83f, -2.7f);

        [SerializeField]
        [Tooltip("Campo de visión en plano abierto. Cero o menos deja el mismo que el plano base.")]
        private float wideShotFieldOfView;

        [Header("Plano de panel")]
        [SerializeField]
        [Tooltip("Echar la cámara un poco atrás mientras hay una imagen puesta, para que la imagen (fija arriba en pantalla) no tape a Sonia.")]
        private bool panelShotEnabled = true;

        [SerializeField]
        [Tooltip("Desplazamiento de la cámara respecto al plano base mientras hay una imagen: un poco más alta y más atrás. Sonia sigue de cintura para arriba, algo más pequeña.")]
        private Vector3 panelShotOffset = new Vector3(0f, 0.13f, -0.45f);

        [SerializeField]
        [Tooltip("Posición absoluta de la cámara con imagen (solo si el desplazamiento es cero). La calculaba Sonia > Colocar avatar.")]
        private Vector3 panelShotPosition = new Vector3(0f, 1.62f, -1.42f);

        [SerializeField]
        [Tooltip("Campo de visión con imagen puesta. Cero o menos deja el mismo que el plano base.")]
        private float panelShotFieldOfView;

        [Header("Salida y entrada caminando")]
        [SerializeField]
        [Tooltip("Presencia de Sonia (modo Fuera). Si está vacío se busca en este objeto o sus hijos.")]
        private PresenceController presence;

        [SerializeField]
        [Tooltip("Abrir a cuerpo entero mientras Sonia sale caminando, está fuera y vuelve. Apagado: la cámara se queda en el plano medio y Sonia sale de cuadro en un par de pasos, sin que se vean las piernas.")]
        private bool presenceShotEnabled = true;

        [SerializeField]
        [Tooltip("Posición de la cámara para la salida y la entrada. Cero: la del plano abierto (Wide Shot Position), que ya encuadra el cuerpo entero.")]
        private Vector3 presenceShotPosition = Vector3.zero;

        [SerializeField]
        [Tooltip("Campo de visión para la salida y la entrada. Cero o menos: el del plano abierto o, si tampoco tiene, el del plano base.")]
        private float presenceShotFieldOfView = 0f;

        [SerializeField]
        [Range(0.1f, 3f)]
        [Tooltip("Tiempo de suavizado (SmoothDamp) del travelling al abrir y al cerrar el plano de salida. Unos 2,5 veces este valor hasta quedar quieta.")]
        private float presenceSmoothTime = 0.75f;

        [Header("Movimiento")]
        [SerializeField]
        [Range(0.2f, 10f)]
        [Tooltip("Velocidad con la que la cámara alcanza el encuadre que toca. Más alto, más brusco.")]
        private float smoothing = 2.5f;

        private Vector3 _basePosition;
        private Quaternion _baseRotation;
        private float _baseFieldOfView;

        // Pose de la escena (la del menú del editor), antes de los ajustes de «Developer».
        private Vector3 _capturedPosition;
        private Quaternion _capturedRotation = Quaternion.identity;
        private float _capturedFieldOfView = 40f;
        private Vector3 _tuningOffset;
        private float _tuningZoom = 1f;
        private float _tuningTilt;
        private bool _wide;
        private bool _panel;
        private bool _presenceShot;
        private bool _ready;

        // Travelling del plano de salida: dura hasta que la cámara llega quieta
        // al encuadre que toque, aunque el plano de salida ya haya terminado.
        private bool _dolly;
        private Vector3 _dollyVelocity;
        private float _fieldOfViewVelocity;
        private bool _snapNextFrame;
        private bool _presenceSearched;

        // Encuadre impuesto desde fuera (Modo Jean): manda sobre todos.
        private bool _hasOverride;
        private ShotPose _override;

        /// <summary>Cierto mientras la cámara está abriendo o ya abierta.</summary>
        public bool IsWideShot
        {
            get { return _wide; }
        }

        /// <summary>Cierto mientras la cámara está en el encuadre del panel de imágenes.</summary>
        public bool IsPanelShot
        {
            get { return _panel; }
        }

        /// <summary>
        /// Pide el encuadre de panel sin imagen puesta (la tarjeta de la trivia
        /// ocupa la misma franja alta de la pantalla).
        /// </summary>
        public bool PanelRequested { get; set; }

        /// <summary>
        /// Desplazamiento extra (metros) sobre el plano de panel mientras se pide
        /// con <see cref="PanelRequested"/>: la tarjeta de la trivia es más alta
        /// que una imagen y Sonia tiene que caber debajo con el gorro.
        /// </summary>
        public Vector3 PanelRequestOffset { get; set; }

        /// <summary>Cierto mientras manda el plano de salida y entrada caminando.</summary>
        public bool IsPresenceShot
        {
            get { return _presenceShot; }
        }

        /// <summary>Cámara que mueve este componente.</summary>
        public Camera TargetCamera
        {
            get { return targetCamera; }
        }

        /// <summary>Cierto cuando ya tomó la pose de la escena (hay cámara).</summary>
        public bool IsReady
        {
            get { return _ready; }
        }

        /// <summary>Plano base: el plano medio de Sonia, con los ajustes de «Developer».</summary>
        public ShotPose BaseShot
        {
            get { return new ShotPose(_basePosition, _baseRotation, _baseFieldOfView); }
        }

        /// <summary>Plano de cuerpo entero (el de la salida y la entrada caminando).</summary>
        public ShotPose FullBodyShot
        {
            get { return new ShotPose(PresencePosition(), _capturedRotation, PresenceFieldOfView()); }
        }

        /// <summary>Cierto mientras manda un encuadre impuesto desde fuera.</summary>
        public bool HasOverride
        {
            get { return _hasOverride; }
        }

        /// <summary>
        /// Impone un encuadre por encima de todos los demás (Modo Jean), con el
        /// travelling del plano de salida, hasta <see cref="ClearOverride"/>. Se
        /// puede volver a llamar con otra pose: la cámara va hacia ella suave.
        /// </summary>
        public void SetOverride(ShotPose pose)
        {
            _override = pose;
            _hasOverride = true;
        }

        /// <summary>Quita el encuadre impuesto: la cámara vuelve, con travelling, al que toque.</summary>
        public void ClearOverride()
        {
            if (_hasOverride)
            {
                _hasOverride = false;
                _dolly = true;
            }
        }

        /// <summary>Presencia de Sonia, para el plano de salida. La asigna SoniaBootstrap.</summary>
        public PresenceController Presence
        {
            get { return presence; }
            set { presence = value; }
        }

        /// <summary>
        /// Añade las poses de todos los encuadres posibles (base, abierto, panel y
        /// salida). Sirve para saber si un punto queda fuera de cuadro en
        /// cualquiera de ellos, aunque la cámara esté a medio camino.
        /// </summary>
        public void CollectShotPoses(List<ShotPose> poses)
        {
            if (!_ready || poses == null)
            {
                return;
            }

            poses.Add(new ShotPose(_basePosition, _baseRotation, _baseFieldOfView));
            poses.Add(new ShotPose(wideShotPosition, _capturedRotation, WideFieldOfView()));
            poses.Add(new ShotPose(PanelPosition(), _baseRotation, PanelFieldOfView()));
            if (presenceShotEnabled)
            {
                poses.Add(new ShotPose(PresencePosition(), _capturedRotation, PresenceFieldOfView()));
            }

            if (_hasOverride)
            {
                poses.Add(_override);
            }
        }

        /// <summary>
        /// En el siguiente frame la cámara salta al encuadre que toque, sin
        /// travelling. Se usa cuando Sonia se aplica como "fuera" nada más
        /// conectar: no tiene sentido ver la cámara abrirse sobre un escenario vacío.
        /// </summary>
        public void SnapNextFrame()
        {
            _snapNextFrame = true;
        }

        private void Awake()
        {
            if (targetCamera == null)
            {
                targetCamera = Camera.main;
            }

            if (choreographer == null)
            {
                choreographer = GetComponentInChildren<AvatarChoreographer>(true);
            }

            if (imagePanel == null)
            {
                imagePanel = GetComponentInChildren<ImagePanelController>(true);
            }

            CaptureBasePose();
        }

        /// <summary>
        /// Toma la pose actual de la cámara como plano base. Se llama al arrancar,
        /// cuando la cámara todavía está donde la dejó el menú del editor.
        /// </summary>
        public void CaptureBasePose()
        {
            if (targetCamera == null)
            {
                _ready = false;
                return;
            }

            _capturedPosition = targetCamera.transform.position;
            _capturedRotation = targetCamera.transform.rotation;
            _capturedFieldOfView = targetCamera.fieldOfView;
            _ready = true;
            ApplyTuningToBase();
        }

        /// <summary>
        /// Ajustes de «Developer» del panel sobre el plano base: <paramref name="offset"/>
        /// en metros (x a la derecha de la pantalla, y arriba, z alejándose de
        /// Sonia), <paramref name="zoom"/> (más de 1 acerca) e
        /// <paramref name="tiltDegrees"/> (positivo mira más abajo). La cámara
        /// llega suave al encuadre nuevo con su interpolación de siempre.
        /// </summary>
        public void SetTuning(Vector3 offset, float zoom, float tiltDegrees)
        {
            _tuningOffset = offset;
            _tuningZoom = Mathf.Clamp(zoom, 0.25f, 4f);
            _tuningTilt = Mathf.Clamp(tiltDegrees, -45f, 45f);
            ApplyTuningToBase();
        }

        private void ApplyTuningToBase()
        {
            if (!_ready)
            {
                return;
            }

            // Lateral y distancia en el plano del suelo, según hacia dónde mira la cámara.
            Vector3 forward = _capturedRotation * Vector3.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.000001f)
            {
                forward = Vector3.forward;
            }

            forward.Normalize();
            Vector3 right = Vector3.Cross(Vector3.up, forward);
            _basePosition = _capturedPosition
                            + right * _tuningOffset.x
                            + Vector3.up * _tuningOffset.y
                            - forward * _tuningOffset.z;
            _baseRotation = _capturedRotation * Quaternion.Euler(_tuningTilt, 0f, 0f);

            // El zoom estrecha el campo de visión como un objetivo más largo.
            float halfTan = Mathf.Tan(_capturedFieldOfView * 0.5f * Mathf.Deg2Rad) / _tuningZoom;
            _baseFieldOfView = Mathf.Clamp(2f * Mathf.Atan(halfTan) * Mathf.Rad2Deg, 5f, 120f);
        }

        /// <summary>Vuelve al plano medio de golpe, sin animación.</summary>
        public void ResetToBase()
        {
            _wide = false;
            _panel = false;
            _presenceShot = false;
            _dolly = false;
            _dollyVelocity = Vector3.zero;
            _fieldOfViewVelocity = 0f;
            if (!_ready)
            {
                return;
            }

            targetCamera.transform.position = _basePosition;
            targetCamera.transform.rotation = _baseRotation;
            targetCamera.fieldOfView = _baseFieldOfView;
        }

        private void LateUpdate()
        {
            if (!_ready)
            {
                return;
            }

            if (presence == null && !_presenceSearched)
            {
                // SoniaBootstrap lo añade por código en su Awake; puede no existir
                // aún cuando corre el Awake de este componente.
                _presenceSearched = true;
                presence = GetComponentInChildren<PresenceController>(true);
            }

            _presenceShot = !_hasOverride && presenceShotEnabled && presence != null && presence.WantsWideShot;
            _wide = !_hasOverride && !_presenceShot && NeedsWideShot();
            _panel = panelShotEnabled && !_hasOverride && !_presenceShot && !_wide
                     && ((imagePanel != null && imagePanel.IsVisible) || PanelRequested);

            Vector3 targetPosition = _basePosition;
            Quaternion targetRotation = _baseRotation;
            float targetFieldOfView = _baseFieldOfView;

            if (_hasOverride)
            {
                targetPosition = _override.Position;
                targetRotation = _override.Rotation;
                targetFieldOfView = _override.FieldOfView;
                _dolly = true;
            }
            else if (_presenceShot)
            {
                targetPosition = PresencePosition();
                targetRotation = _capturedRotation;
                targetFieldOfView = PresenceFieldOfView();
                _dolly = true;
            }
            else if (_wide)
            {
                targetPosition = wideShotPosition;
                targetRotation = _capturedRotation;
                targetFieldOfView = WideFieldOfView();
            }
            else if (_panel)
            {
                targetPosition = PanelPosition() + (PanelRequested ? PanelRequestOffset : Vector3.zero);
                targetFieldOfView = PanelFieldOfView();
            }

            Transform cameraTransform = targetCamera.transform;

            if (_snapNextFrame)
            {
                _snapNextFrame = false;
                _dolly = false;
                _dollyVelocity = Vector3.zero;
                _fieldOfViewVelocity = 0f;
                cameraTransform.position = targetPosition;
                cameraTransform.rotation = targetRotation;
                targetCamera.fieldOfView = targetFieldOfView;
                return;
            }

            float dt = Time.deltaTime;
            if (_dolly)
            {
                // Travelling: velocidad continua, arranque y frenada suaves.
                float smoothTime = Mathf.Max(0.05f, presenceSmoothTime);
                cameraTransform.position = Vector3.SmoothDamp(
                    cameraTransform.position, targetPosition, ref _dollyVelocity, smoothTime, Mathf.Infinity, dt);
                targetCamera.fieldOfView = Mathf.SmoothDamp(
                    targetCamera.fieldOfView, targetFieldOfView, ref _fieldOfViewVelocity, smoothTime, Mathf.Infinity, dt);
                cameraTransform.rotation = Quaternion.Slerp(
                    cameraTransform.rotation, targetRotation, 1f - Mathf.Exp(-4f * dt));

                bool arrived = (cameraTransform.position - targetPosition).sqrMagnitude < 0.000004f
                               && _dollyVelocity.sqrMagnitude < 0.0001f
                               && Mathf.Abs(targetCamera.fieldOfView - targetFieldOfView) < 0.01f;
                if (!_presenceShot && !_hasOverride && arrived)
                {
                    _dolly = false;
                    _dollyVelocity = Vector3.zero;
                    _fieldOfViewVelocity = 0f;
                }

                return;
            }

            float step = 1f - Mathf.Exp(-Mathf.Max(0.2f, smoothing) * dt);
            cameraTransform.position = Vector3.Lerp(cameraTransform.position, targetPosition, step);
            cameraTransform.rotation = Quaternion.Slerp(cameraTransform.rotation, targetRotation, step);
            targetCamera.fieldOfView = Mathf.Lerp(targetCamera.fieldOfView, targetFieldOfView, step);
        }

        private float WideFieldOfView()
        {
            return wideShotFieldOfView > 0f ? wideShotFieldOfView : _capturedFieldOfView;
        }

        private Vector3 PanelPosition()
        {
            return panelShotOffset.sqrMagnitude > 0.0001f ? _basePosition + panelShotOffset : panelShotPosition;
        }

        private float PanelFieldOfView()
        {
            return panelShotFieldOfView > 0f ? panelShotFieldOfView : _baseFieldOfView;
        }

        private Vector3 PresencePosition()
        {
            return presenceShotPosition.sqrMagnitude > 0.0001f ? presenceShotPosition : wideShotPosition;
        }

        private float PresenceFieldOfView()
        {
            return presenceShotFieldOfView > 0f ? presenceShotFieldOfView : WideFieldOfView();
        }

        /// <summary>
        /// Mira el estado actual y, si hay una transición en marcha, también el de
        /// destino: así la cámara empieza a abrirse a la vez que arranca el baile
        /// en lugar de ir un cuarto de segundo por detrás.
        /// </summary>
        private bool NeedsWideShot()
        {
            return wideShotEnabled && choreographer != null && choreographer.IsWideShot;
        }
    }
}
