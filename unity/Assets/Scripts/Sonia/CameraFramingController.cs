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
//   panel    mientras hay una imagen puesta: se echa atrás y sube para dejar
//            libre la mitad de arriba de la pantalla
//   base     el plano medio de siempre, con la cara grande
//
// La prioridad es esa: si Sonia baila mientras hay una imagen, manda el baile.

using UnityEngine;

namespace Sonia
{
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
        [Tooltip("Posición de la cámara mientras hay una imagen puesta. La calcula Sonia > Colocar avatar.")]
        private Vector3 panelShotPosition = new Vector3(0f, 1.62f, -1.42f);

        [SerializeField]
        [Tooltip("Campo de visión con imagen puesta. Cero o menos deja el mismo que el plano base.")]
        private float panelShotFieldOfView;

        [Header("Movimiento")]
        [SerializeField]
        [Range(0.2f, 10f)]
        [Tooltip("Velocidad con la que la cámara alcanza el encuadre que toca. Más alto, más brusco.")]
        private float smoothing = 2.5f;

        private Vector3 _basePosition;
        private Quaternion _baseRotation;
        private float _baseFieldOfView;
        private bool _wide;
        private bool _panel;
        private bool _ready;

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

            _basePosition = targetCamera.transform.position;
            _baseRotation = targetCamera.transform.rotation;
            _baseFieldOfView = targetCamera.fieldOfView;
            _ready = true;
        }

        /// <summary>Vuelve al plano medio de golpe, sin animación.</summary>
        public void ResetToBase()
        {
            _wide = false;
            _panel = false;
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

            _wide = NeedsWideShot();
            _panel = !_wide && imagePanel != null && imagePanel.IsVisible;

            Vector3 targetPosition = _basePosition;
            float targetFieldOfView = _baseFieldOfView;

            if (_wide)
            {
                targetPosition = wideShotPosition;
                if (wideShotFieldOfView > 0f)
                {
                    targetFieldOfView = wideShotFieldOfView;
                }
            }
            else if (_panel)
            {
                targetPosition = panelShotPosition;
                if (panelShotFieldOfView > 0f)
                {
                    targetFieldOfView = panelShotFieldOfView;
                }
            }

            float step = 1f - Mathf.Exp(-Mathf.Max(0.2f, smoothing) * Time.deltaTime);
            Transform cameraTransform = targetCamera.transform;
            cameraTransform.position = Vector3.Lerp(cameraTransform.position, targetPosition, step);
            cameraTransform.rotation = Quaternion.Slerp(cameraTransform.rotation, _baseRotation, step);
            targetCamera.fieldOfView = Mathf.Lerp(targetCamera.fieldOfView, targetFieldOfView, step);
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
