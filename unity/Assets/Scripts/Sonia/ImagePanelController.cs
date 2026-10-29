// Image panel of the scene.
//
// Supports two setups: a Renderer (for example a Quad) with its own material, or
// a RawImage inside a World Space Canvas. In both cases the image arrives as
// base64 inside the show_image message and is shown with a scale animation.
// Camera photos are never shown here.

using System;
using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>
    /// Shows and removes the image the orchestrator asks for, fitting the aspect
    /// ratio and releasing previous textures.
    /// </summary>
    [DisallowMultipleComponent]
    public class ImagePanelController : MonoBehaviour
    {
        [Header("Setup")]
        [SerializeField]
        [Tooltip("Transform scaled when appearing and disappearing. Defaults to this object.")]
        private Transform panelRoot;

        [SerializeField]
        [Tooltip("Renderer of the 3D panel (for example a Quad). Alternative to the RawImage.")]
        private Renderer targetRenderer;

        [SerializeField]
        [Tooltip("RawImage of a World Space Canvas. Alternative to the Renderer.")]
        private RawImage rawImage;

        [SerializeField]
        [Tooltip("Caption text. Optional.")]
        private TMP_Text captionLabel;

        [SerializeField]
        [Tooltip("Object enabled and disabled together with the caption. Optional.")]
        private GameObject captionRoot;

        [Header("Size")]
        [SerializeField]
        [Tooltip("Panel height in meters when using a Renderer. The width follows the aspect ratio.")]
        private float panelHeight = 0.6f;

        [SerializeField]
        [Tooltip("Maximum width in meters. On a vertical screen this is the limit that matters: a landscape image gets shorter instead of spilling over the sides.")]
        private float panelMaxWidth = 1.25f;

        [SerializeField]
        [Tooltip("Maximum size in pixels when using a RawImage. Meant for a 1080x1920 screen.")]
        private Vector2 rawImageMaxSize = new Vector2(960f, 700f);

        [Header("Animation")]
        [Header("Fixed screen position")]
        [SerializeField]
        [Tooltip("Camera used to compute the framing. Empty: the main camera.")]
        private Camera framingCamera;

        [SerializeField]
        [Tooltip("Place the panel at a fixed spot on screen when showing the image (a screen element, it does not follow the character). Off: it stays where it was placed in the scene.")]
        private bool fixedOnScreen = true;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Horizontal center of the panel on screen (0..1).")]
        private float screenCenterX = 0.5f;

        [SerializeField]
        [Range(0f, 0.4f)]
        [Tooltip("Distance from the panel's top edge to the top of the screen, as a fraction of the height. Leaves the logo and button strip free.")]
        private float screenTopMargin = 0.12f;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Distance from the panel to the camera, in meters. In front of the avatar.")]
        private float screenDepth = 0.9f;

        [SerializeField]
        [Range(0.2f, 0.9f)]
        [Tooltip("Maximum panel width, as a fraction of the screen width.")]
        private float screenMaxWidth = 0.7f;

        [SerializeField]
        [Range(0.05f, 0.5f)]
        [Tooltip("Maximum panel height, as a fraction of the screen height.")]
        private float screenMaxHeight = 0.22f;

        [SerializeField]
        [Range(0.1f, 2f)]
        [Tooltip("Panel height (meters) the caption was designed for; the caption scales in proportion.")]
        private float captionReferenceHeight = 0.6f;

        [SerializeField]
        [Tooltip("Duration of the show and hide animation, in seconds.")]
        private float animationSeconds = 0.25f;

        [SerializeField]
        [Tooltip("Scale animation curve.")]
        private AnimationCurve animationCurve = AnimationCurve.EaseInOut(0f, 0f, 1f, 1f);

        private static readonly int BaseMapId = Shader.PropertyToID("_BaseMap");
        private static readonly int MainTexId = Shader.PropertyToID("_MainTex");

        private Texture2D _texture;
        private Material _materialInstance;
        private Coroutine _animation;
        private Vector3 _baseScale = Vector3.one;

        // Fixed screen placement while an image is shown.
        private bool _anchored;
        private Vector3 _homePosition;
        private Vector3 _homeScale;
        private bool _homeSaved;
        private bool _visible;

        /// <summary>True while an image is shown.</summary>
        public bool IsVisible
        {
            get { return _visible; }
        }

        /// <summary>Transform the avatar can turn its head toward.</summary>
        public Transform PanelTransform
        {
            get { return panelRoot != null ? panelRoot : transform; }
        }

        /// <summary>Id of the last image shown, for debugging.</summary>
        public string CurrentImageId { get; private set; }

        private void Awake()
        {
            if (panelRoot == null)
            {
                panelRoot = transform;
            }

            if (targetRenderer == null && rawImage == null)
            {
                targetRenderer = GetComponent<Renderer>();
            }

            _baseScale = panelRoot.localScale;
            HideImmediate();
        }

        private void OnDestroy()
        {
            ReleaseTexture();
            if (_materialInstance != null)
            {
                Destroy(_materialInstance);
                _materialInstance = null;
            }
        }

        // ------------------------------------------------------------------
        // Public API
        // ------------------------------------------------------------------

        /// <summary>Shows the image carried by a <c>show_image</c> message.</summary>
        public void Show(ShowImageMessage message)
        {
            if (message == null)
            {
                return;
            }

            byte[] bytes;
            try
            {
                bytes = Convert.FromBase64String(message.DataBase64 ?? string.Empty);
            }
            catch (FormatException)
            {
                Debug.LogWarning("[Sonnia] show_image has invalid base64; ignoring it.", this);
                return;
            }

            if (bytes.Length == 0)
            {
                Debug.LogWarning("[Sonnia] show_image arrived without image data; ignoring it.", this);
                return;
            }

            Texture2D texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            texture.name = "SoniaImage";
            texture.wrapMode = TextureWrapMode.Clamp;
            if (!ImageConversion.LoadImage(texture, bytes, false))
            {
                Debug.LogWarning("[Sonnia] Could not decode the show_image image.", this);
                Destroy(texture);
                return;
            }

            bool wasVisible = _visible;
            ReleaseTexture();
            _texture = texture;
            CurrentImageId = message.ImageId;

            ApplyTexture(texture);
            ApplyCaption(message.Caption);
            SetRendererEnabled(true);

            // Screen position and size before animating: the animation goes to
            // the final scale, so it has to be computed already.
            if (fixedOnScreen)
            {
                PlaceOnScreen();
            }

            // If an image was already shown, grow from the current scale so the
            // change does not jump.
            Vector3 from = wasVisible && panelRoot != null ? panelRoot.localScale : Vector3.zero;
            _visible = true;
            StartScaleAnimation(from, _baseScale, false);
        }

        /// <summary>
        /// Places the panel at its fixed screen spot (top center band), sized to
        /// the camera framing. The image does not follow the character: it is a
        /// screen element, like the HUD. When removed it goes back to its usual
        /// position and size.
        /// </summary>
        public void PlaceOnScreen()
        {
            if (panelRoot == null)
            {
                return;
            }

            if (!_homeSaved)
            {
                _homePosition = transform.position;
                _homeScale = _baseScale;
                _homeSaved = true;
            }

            _anchored = true;
            PlaceNow();
        }

        /// <summary>Goes back to the usual spot (when hidden).</summary>
        public void ReleaseAnchor()
        {
            _anchored = false;
            if (_homeSaved && !_visible)
            {
                transform.position = _homePosition;
                _baseScale = _homeScale;
                if (captionRoot != null)
                {
                    captionRoot.transform.localScale = Vector3.one;
                    captionRoot.transform.localPosition = new Vector3(0f, _homeScale.y * 0.78f, 0f);
                }
            }
        }

        /// <summary>True while the panel is at its fixed screen spot.</summary>
        public bool IsAnchored
        {
            get { return _anchored; }
        }

        private void PlaceNow()
        {
            Camera camera = framingCamera != null ? framingCamera : Camera.main;
            if (camera == null || panelRoot == null)
            {
                return;
            }

            float depth = Mathf.Max(0.2f, screenDepth);
            float frameHeight = 2f * depth * Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
            float frameWidth = frameHeight * camera.aspect;

            float aspect = _baseScale.y > 0.0001f ? _baseScale.x / _baseScale.y : 16f / 9f;
            float width = screenMaxWidth * frameWidth;
            float height = width / aspect;
            float maxHeight = screenMaxHeight * frameHeight;
            if (height > maxHeight)
            {
                height = maxHeight;
                width = height * aspect;
            }

            float halfW = width / frameWidth * 0.5f;
            float halfH = height / frameHeight * 0.5f;
            float centerX = Mathf.Clamp(screenCenterX, halfW, 1f - halfW);
            float centerY = Mathf.Clamp(1f - screenTopMargin - halfH, halfH, 1f - halfH);
            transform.position = camera.ViewportToWorldPoint(new Vector3(centerX, centerY, depth));
            transform.rotation = Quaternion.LookRotation(camera.transform.forward, camera.transform.up);
            _baseScale = new Vector3(width, height, 1f);

            if (_visible && _animation == null)
            {
                panelRoot.localScale = _baseScale;
            }

            // The caption sits inside the panel, against the bottom edge and a
            // hair in front, and scales with it.
            if (captionRoot != null)
            {
                float factor = _baseScale.y / Mathf.Max(0.05f, captionReferenceHeight);
                captionRoot.transform.localScale = Vector3.one * factor;
                captionRoot.transform.localPosition = new Vector3(0f, -(_baseScale.y * 0.5f) + 0.05f * factor, -0.002f);
            }
        }

        private void LateUpdate()
        {
            // The camera may be pulling back to make room: the panel is
            // repositioned every frame to stay fixed on screen.
            if (_anchored && _visible)
            {
                PlaceNow();
            }
        }

        /// <summary>Removes the panel with the exit animation.</summary>
        public void Hide()
        {
            _anchored = false;
            if (!_visible)
            {
                return;
            }

            _visible = false;
            if (captionRoot != null)
            {
                captionRoot.SetActive(false);
            }

            StartScaleAnimation(panelRoot.localScale, Vector3.zero, true);
        }

        /// <summary>Removes the panel without animation and releases the texture.</summary>
        public void HideImmediate()
        {
            _visible = false;
            StopAnimation();

            if (panelRoot != null)
            {
                panelRoot.localScale = Vector3.zero;
            }

            if (captionRoot != null)
            {
                captionRoot.SetActive(false);
            }

            SetRendererEnabled(false);
            ReleaseTexture();
        }

        // ------------------------------------------------------------------
        // Details
        // ------------------------------------------------------------------

        private void ApplyTexture(Texture2D texture)
        {
            float aspect = texture.height > 0 ? texture.width / (float)texture.height : 1f;
            if (aspect <= 0f)
            {
                aspect = 1f;
            }

            if (rawImage != null)
            {
                rawImage.texture = texture;
                RectTransform rect = rawImage.rectTransform;
                float width = Mathf.Max(1f, rawImageMaxSize.x);
                float height = Mathf.Max(1f, rawImageMaxSize.y);
                if (aspect > width / height)
                {
                    height = width / aspect;
                }
                else
                {
                    width = height * aspect;
                }

                rect.sizeDelta = new Vector2(width, height);
                _baseScale = Vector3.one;
            }

            if (targetRenderer != null)
            {
                Material material = GetPanelMaterial();
                if (material != null)
                {
                    if (material.HasProperty(BaseMapId))
                    {
                        material.SetTexture(BaseMapId, texture);
                    }

                    if (material.HasProperty(MainTexId))
                    {
                        material.SetTexture(MainTexId, texture);
                    }
                }

                // On a 9:16 screen there is spare height and not enough width, so
                // the maximum width rules: a landscape image gets shorter instead
                // of spilling over the sides.
                float height = Mathf.Max(0.01f, panelHeight);
                float width = height * aspect;
                float maxWidth = Mathf.Max(0.01f, panelMaxWidth);
                if (width > maxWidth)
                {
                    width = maxWidth;
                    height = width / aspect;
                }

                _baseScale = new Vector3(width, height, 1f);
            }
        }

        private void ApplyCaption(string caption)
        {
            bool hasCaption = !string.IsNullOrEmpty(caption);
            if (captionLabel != null)
            {
                captionLabel.text = hasCaption ? caption : string.Empty;
            }

            if (captionRoot != null)
            {
                captionRoot.SetActive(hasCaption);
            }
        }

        private void SetRendererEnabled(bool value)
        {
            if (targetRenderer != null)
            {
                targetRenderer.enabled = value;
            }

            if (rawImage != null)
            {
                rawImage.enabled = value;
            }
        }

        private Material GetPanelMaterial()
        {
            if (targetRenderer == null)
            {
                return null;
            }

            if (_materialInstance != null)
            {
                return _materialInstance;
            }

            if (targetRenderer.sharedMaterial != null)
            {
                // Accessing .material creates this Renderer's own instance.
                _materialInstance = targetRenderer.material;
                return _materialInstance;
            }

            Shader shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (shader == null)
            {
                shader = Shader.Find("Unlit/Texture");
            }

            if (shader == null)
            {
                Debug.LogError(
                    "[Sonnia] No unlit shader found for the panel. Assign a material to the Renderer.",
                    this);
                return null;
            }

            _materialInstance = new Material(shader);
            targetRenderer.material = _materialInstance;
            return _materialInstance;
        }

        private void StartScaleAnimation(Vector3 from, Vector3 to, bool releaseAtEnd)
        {
            StopAnimation();

            if (panelRoot == null)
            {
                return;
            }

            if (!isActiveAndEnabled || animationSeconds <= 0.001f)
            {
                panelRoot.localScale = to;
                if (releaseAtEnd)
                {
                    SetRendererEnabled(false);
                    ReleaseTexture();
                }

                return;
            }

            panelRoot.localScale = from;
            _animation = StartCoroutine(AnimateScale(from, to, releaseAtEnd));
        }

        private void StopAnimation()
        {
            if (_animation != null)
            {
                StopCoroutine(_animation);
                _animation = null;
            }
        }

        private IEnumerator AnimateScale(Vector3 from, Vector3 to, bool releaseAtEnd)
        {
            float duration = Mathf.Max(0.01f, animationSeconds);
            float elapsed = 0f;

            while (elapsed < duration)
            {
                elapsed += Time.deltaTime;
                float eased = animationCurve != null
                    ? animationCurve.Evaluate(Mathf.Clamp01(elapsed / duration))
                    : Mathf.Clamp01(elapsed / duration);
                panelRoot.localScale = Vector3.LerpUnclamped(from, to, eased);
                yield return null;
            }

            panelRoot.localScale = to;
            _animation = null;

            if (releaseAtEnd)
            {
                SetRendererEnabled(false);
                ReleaseTexture();
            }
        }

        private void ReleaseTexture()
        {
            if (_texture == null)
            {
                return;
            }

            if (rawImage != null && ReferenceEquals(rawImage.texture, _texture))
            {
                rawImage.texture = null;
            }

            if (_materialInstance != null)
            {
                if (_materialInstance.HasProperty(BaseMapId))
                {
                    _materialInstance.SetTexture(BaseMapId, null);
                }

                if (_materialInstance.HasProperty(MainTexId))
                {
                    _materialInstance.SetTexture(MainTexId, null);
                }
            }

            Destroy(_texture);
            _texture = null;
            CurrentImageId = null;
        }
    }
}
