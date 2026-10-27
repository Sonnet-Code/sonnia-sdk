// Envío de capturas de la webcam al orquestador.
//
// Solo hace falta si VISION_SOURCE=unity. Con VISION_SOURCE=opencv el
// orquestador abre la cámara por su cuenta y este componente puede quedarse
// desactivado.

using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>
    /// Abre una <see cref="WebCamTexture"/> y envía un JPEG cuando el orquestador
    /// lo pide con <c>request_frame</c>, o cada cierto tiempo si se configura.
    /// </summary>
    [DisallowMultipleComponent]
    public class WebcamFrameSender : MonoBehaviour
    {
        [Header("Referencias")]
        [SerializeField]
        [Tooltip("Cliente por el que se envían las capturas.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("RawImage opcional para ver lo que capta la cámara mientras se depura.")]
        private RawImage previewImage;

        [Header("Cámara")]
        [SerializeField]
        [Tooltip("Nombre del dispositivo. Vacío para usar el primero que encuentre.")]
        private string deviceName = string.Empty;

        [SerializeField]
        [Tooltip("Ancho solicitado a la cámara.")]
        private int requestedWidth = 640;

        [SerializeField]
        [Tooltip("Alto solicitado a la cámara.")]
        private int requestedHeight = 480;

        [SerializeField]
        [Tooltip("Fotogramas por segundo solicitados a la cámara.")]
        private int requestedFps = 15;

        [Header("Envío")]
        [SerializeField]
        [Range(1, 100)]
        [Tooltip("Calidad del JPEG que se envía.")]
        private int jpegQuality = 80;

        [SerializeField]
        [Tooltip("Enviar una captura cada cierto tiempo además de cuando la piden. 0 para no hacerlo.")]
        private float periodicSendSeconds;

        private WebCamTexture _webcam;
        private Texture2D _frameTexture;
        private Color32[] _pixelBuffer;
        private bool _capturing;
        private float _periodicTimer;

        /// <summary>Cierto si la cámara está abierta y produciendo imagen.</summary>
        public bool IsRunning
        {
            get { return _webcam != null && _webcam.isPlaying; }
        }

        private void Awake()
        {
            if (client == null)
            {
                client = GetComponentInParent<SoniaClient>();
            }
        }

        private void OnEnable()
        {
            // El renderizador de vídeos no usa la cámara (ni pide el permiso).
            if (SoniaVideoMode.Active)
            {
                return;
            }

            StartCoroutine(StartCameraRoutine());
        }

        private void OnDisable()
        {
            StopCamera();
        }

        private void OnDestroy()
        {
            StopCamera();
            if (_frameTexture != null)
            {
                Destroy(_frameTexture);
                _frameTexture = null;
            }
        }

        private void Update()
        {
            if (periodicSendSeconds <= 0f || !IsRunning)
            {
                return;
            }

            _periodicTimer -= Time.deltaTime;
            if (_periodicTimer <= 0f)
            {
                _periodicTimer = periodicSendSeconds;
                RequestFrameNow();
            }
        }

        // ------------------------------------------------------------------
        // Cámara
        // ------------------------------------------------------------------

        private IEnumerator StartCameraRoutine()
        {
            // En escritorio esta petición se resuelve sola; en otras plataformas
            // abre el diálogo del sistema. Si no hay permiso se avisa, pero se
            // intenta abrir igualmente para no depender de la plataforma.
            yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
            if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
            {
                Debug.LogWarning("[Sonia] El sistema no confirmó el permiso de cámara; se intenta abrir igualmente.", this);
            }

            WebCamDevice[] devices = WebCamTexture.devices;
            if (devices == null || devices.Length == 0)
            {
                Debug.LogWarning("[Sonia] No hay ninguna cámara disponible.", this);
                yield break;
            }

            string chosen = devices[0].name;
            if (!string.IsNullOrEmpty(deviceName))
            {
                bool found = false;
                for (int i = 0; i < devices.Length; i++)
                {
                    if (devices[i].name == deviceName)
                    {
                        chosen = devices[i].name;
                        found = true;
                        break;
                    }
                }

                if (!found)
                {
                    Debug.LogWarning(
                        "[Sonia] No se encontró la cámara \"" + deviceName + "\"; se usa " + chosen + ".",
                        this);
                }
            }

            _webcam = new WebCamTexture(
                chosen,
                Mathf.Max(16, requestedWidth),
                Mathf.Max(16, requestedHeight),
                Mathf.Max(1, requestedFps));
            _webcam.Play();

            if (previewImage != null)
            {
                previewImage.texture = _webcam;
            }

            _periodicTimer = periodicSendSeconds;
        }

        private void StopCamera()
        {
            if (_webcam == null)
            {
                return;
            }

            if (previewImage != null && ReferenceEquals(previewImage.texture, _webcam))
            {
                previewImage.texture = null;
            }

            _webcam.Stop();
            Destroy(_webcam);
            _webcam = null;
            _capturing = false;
        }

        // ------------------------------------------------------------------
        // Captura
        // ------------------------------------------------------------------

        /// <summary>Captura el frame actual y lo envía. Se ignora si ya hay una captura en curso.</summary>
        public void RequestFrameNow()
        {
            if (_capturing || !isActiveAndEnabled)
            {
                return;
            }

            if (!IsRunning)
            {
                Debug.LogWarning("[Sonia] Se pidió una captura pero la cámara no está activa.", this);
                return;
            }

            _capturing = true;
            StartCoroutine(CaptureRoutine());
        }

        private IEnumerator CaptureRoutine()
        {
            // Esperar al final del frame garantiza que la textura de la cámara
            // ya tiene la imagen de este fotograma.
            yield return new WaitForEndOfFrame();

            CaptureAndSend();
            _capturing = false;
        }

        private void CaptureAndSend()
        {
            if (_webcam == null || !_webcam.isPlaying || _webcam.width < 16 || _webcam.height < 16)
            {
                return;
            }

            int width = _webcam.width;
            int height = _webcam.height;

            if (_frameTexture == null || _frameTexture.width != width || _frameTexture.height != height)
            {
                if (_frameTexture != null)
                {
                    Destroy(_frameTexture);
                }

                _frameTexture = new Texture2D(width, height, TextureFormat.RGBA32, false);
                _pixelBuffer = new Color32[width * height];
            }

            if (_pixelBuffer == null || _pixelBuffer.Length != width * height)
            {
                _pixelBuffer = new Color32[width * height];
            }

            _webcam.GetPixels32(_pixelBuffer);
            _frameTexture.SetPixels32(_pixelBuffer);
            _frameTexture.Apply(false);

            byte[] jpeg = ImageConversion.EncodeToJPG(_frameTexture, Mathf.Clamp(jpegQuality, 1, 100));
            if (jpeg == null || jpeg.Length == 0)
            {
                Debug.LogWarning("[Sonia] No se pudo codificar la captura de cámara.", this);
                return;
            }

            if (client != null)
            {
                client.SendCameraFrame(jpeg);
            }
        }
    }
}
