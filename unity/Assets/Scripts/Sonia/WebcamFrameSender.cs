// Sends webcam captures to the orchestrator.
//
// Only needed if VISION_SOURCE=unity. With VISION_SOURCE=opencv the
// orchestrator opens the camera by itself and this component can stay
// disabled.

using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>
    /// Opens a <see cref="WebCamTexture"/> and sends a JPEG when the orchestrator
    /// asks for it with <c>request_frame</c>, or periodically if configured.
    /// </summary>
    [DisallowMultipleComponent]
    public class WebcamFrameSender : MonoBehaviour
    {
        [Header("References")]
        [SerializeField]
        [Tooltip("Client the captures are sent through.")]
        private SoniaClient client;

        [SerializeField]
        [Tooltip("Optional RawImage to see what the camera captures while debugging.")]
        private RawImage previewImage;

        [Header("Camera")]
        [SerializeField]
        [Tooltip("Device name. Empty to use the first one found.")]
        private string deviceName = string.Empty;

        [SerializeField]
        [Tooltip("Width requested from the camera.")]
        private int requestedWidth = 640;

        [SerializeField]
        [Tooltip("Height requested from the camera.")]
        private int requestedHeight = 480;

        [SerializeField]
        [Tooltip("Frames per second requested from the camera.")]
        private int requestedFps = 15;

        [Header("Sending")]
        [SerializeField]
        [Range(1, 100)]
        [Tooltip("Quality of the JPEG that is sent.")]
        private int jpegQuality = 80;

        [SerializeField]
        [Tooltip("Send a capture periodically in addition to when requested. 0 to disable.")]
        private float periodicSendSeconds;

        private WebCamTexture _webcam;
        private Texture2D _frameTexture;
        private Color32[] _pixelBuffer;
        private bool _capturing;
        private float _periodicTimer;

        /// <summary>True if the camera is open and producing images.</summary>
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
        // Camera
        // ------------------------------------------------------------------

        private IEnumerator StartCameraRoutine()
        {
            // On desktop this request resolves by itself; on other platforms it
            // opens the system dialog. If there is no permission a warning is
            // logged, but opening is attempted anyway to stay platform-independent.
            yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
            if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
            {
                Debug.LogWarning("[Sonnia] The system did not confirm camera permission; trying to open it anyway.", this);
            }

            WebCamDevice[] devices = WebCamTexture.devices;
            if (devices == null || devices.Length == 0)
            {
                Debug.LogWarning("[Sonnia] No camera available.", this);
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
                        "[Sonnia] Camera \"" + deviceName + "\" not found; using " + chosen + ".",
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
        // Capture
        // ------------------------------------------------------------------

        /// <summary>Captures the current frame and sends it. Ignored if a capture is already in progress.</summary>
        public void RequestFrameNow()
        {
            if (_capturing || !isActiveAndEnabled)
            {
                return;
            }

            if (!IsRunning)
            {
                Debug.LogWarning("[Sonnia] A capture was requested but the camera is not active.", this);
                return;
            }

            _capturing = true;
            StartCoroutine(CaptureRoutine());
        }

        private IEnumerator CaptureRoutine()
        {
            // Waiting for the end of the frame guarantees the camera texture
            // already holds this frame's image.
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
                Debug.LogWarning("[Sonnia] Could not encode the camera capture.", this);
                return;
            }

            if (client != null)
            {
                client.SendCameraFrame(jpeg);
            }
        }
    }
}
