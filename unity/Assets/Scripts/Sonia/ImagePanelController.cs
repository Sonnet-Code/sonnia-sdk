// Panel de imágenes de la escena.
//
// Soporta dos montajes: un Renderer (por ejemplo un Quad) con material propio, o
// un RawImage dentro de un Canvas en World Space. En ambos casos la imagen llega
// en base64 dentro del mensaje show_image y se muestra con una animación de
// escala.

using System;
using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Sonia
{
    /// <summary>
    /// Muestra y retira la imagen que pide el orquestador, ajustando la proporción
    /// y liberando las texturas anteriores.
    /// </summary>
    [DisallowMultipleComponent]
    public class ImagePanelController : MonoBehaviour
    {
        [Header("Montaje")]
        [SerializeField]
        [Tooltip("Transform que se escala al aparecer y desaparecer. Por defecto, este objeto.")]
        private Transform panelRoot;

        [SerializeField]
        [Tooltip("Renderer del panel 3D (por ejemplo un Quad). Alternativa al RawImage.")]
        private Renderer targetRenderer;

        [SerializeField]
        [Tooltip("RawImage de un Canvas en World Space. Alternativa al Renderer.")]
        private RawImage rawImage;

        [SerializeField]
        [Tooltip("Texto del pie de imagen. Opcional.")]
        private TMP_Text captionLabel;

        [SerializeField]
        [Tooltip("Objeto que se activa y desactiva junto al pie de imagen. Opcional.")]
        private GameObject captionRoot;

        [Header("Tamaño")]
        [SerializeField]
        [Tooltip("Altura del panel en metros cuando se usa un Renderer. El ancho sale de la proporción.")]
        private float panelHeight = 0.6f;

        [SerializeField]
        [Tooltip("Ancho máximo en metros. En pantalla vertical es el límite que manda: una imagen apaisada baja de altura antes que salirse por los lados.")]
        private float panelMaxWidth = 1.25f;

        [SerializeField]
        [Tooltip("Tamaño máximo en píxeles cuando se usa un RawImage. Pensado para una pantalla de 1080x1920.")]
        private Vector2 rawImageMaxSize = new Vector2(960f, 700f);

        [Header("Animación")]
        [Header("Posición fija en pantalla")]
        [SerializeField]
        [Tooltip("Cámara con la que se calcula el encuadre. Vacío: la principal.")]
        private Camera framingCamera;

        [SerializeField]
        [Tooltip("Colocar el panel en un sitio fijo de la pantalla al mostrar la imagen (elemento de pantalla, no sigue al personaje). Apagado: se queda donde lo dejó Sonia > Colocar avatar.")]
        private bool fixedOnScreen = true;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Centro horizontal del panel en pantalla (0..1).")]
        private float screenCenterX = 0.5f;

        [SerializeField]
        [Range(0f, 0.4f)]
        [Tooltip("Distancia del borde superior del panel al borde superior de la pantalla, en fracción del alto. Deja libre la franja del logo y de los botones.")]
        private float screenTopMargin = 0.12f;

        [SerializeField]
        [Range(0.3f, 3f)]
        [Tooltip("Distancia del panel a la cámara, en metros. Por delante del avatar.")]
        private float screenDepth = 0.9f;

        [SerializeField]
        [Range(0.2f, 0.9f)]
        [Tooltip("Ancho máximo del panel, en fracción del ancho de pantalla.")]
        private float screenMaxWidth = 0.7f;

        [SerializeField]
        [Range(0.05f, 0.5f)]
        [Tooltip("Alto máximo del panel, en fracción del alto de pantalla.")]
        private float screenMaxHeight = 0.22f;

        [SerializeField]
        [Range(0.1f, 2f)]
        [Tooltip("Alto de panel (metros) para el que se diseñó el pie de imagen; el pie se escala en proporción.")]
        private float captionReferenceHeight = 0.6f;

        [SerializeField]
        [Tooltip("Duración de la animación de aparición y desaparición, en segundos.")]
        private float animationSeconds = 0.25f;

        [SerializeField]
        [Tooltip("Curva de la animación de escala.")]
        private AnimationCurve animationCurve = AnimationCurve.EaseInOut(0f, 0f, 1f, 1f);

        private static readonly int BaseMapId = Shader.PropertyToID("_BaseMap");
        private static readonly int MainTexId = Shader.PropertyToID("_MainTex");

        private Texture2D _texture;
        private Material _materialInstance;
        private Coroutine _animation;
        private Vector3 _baseScale = Vector3.one;

        // Colocación fija en pantalla mientras hay imagen.
        private bool _anchored;
        private Vector3 _homePosition;
        private Vector3 _homeScale;
        private bool _homeSaved;
        private bool _visible;

        /// <summary>Cierto mientras hay una imagen puesta.</summary>
        public bool IsVisible
        {
            get { return _visible; }
        }

        /// <summary>Transform hacia el que el avatar puede girar la cabeza.</summary>
        public Transform PanelTransform
        {
            get { return panelRoot != null ? panelRoot : transform; }
        }

        /// <summary>Identificador de la última imagen mostrada, para depuración.</summary>
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
        // API pública
        // ------------------------------------------------------------------

        /// <summary>Muestra la imagen que viene en un mensaje <c>show_image</c>.</summary>
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
                Debug.LogWarning("[Sonia] show_image trae un base64 inválido; se ignora.", this);
                return;
            }

            if (bytes.Length == 0)
            {
                Debug.LogWarning("[Sonia] show_image llegó sin datos de imagen; se ignora.", this);
                return;
            }

            Texture2D texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            texture.name = "SoniaImage";
            texture.wrapMode = TextureWrapMode.Clamp;
            if (!ImageConversion.LoadImage(texture, bytes, false))
            {
                Debug.LogWarning("[Sonia] No se pudo decodificar la imagen de show_image.", this);
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

            // Sitio y tamaño de pantalla antes de animar: la animación va hacia
            // la escala final, así que tiene que estar calculada ya.
            if (fixedOnScreen)
            {
                PlaceOnScreen();
            }

            // Si ya había una imagen puesta se crece desde la escala actual, para
            // que el cambio no dé un salto.
            Vector3 from = wasVisible && panelRoot != null ? panelRoot.localScale : Vector3.zero;
            _visible = true;
            StartScaleAnimation(from, _baseScale, false);
        }

        /// <summary>
        /// Coloca el panel en su sitio fijo de pantalla (banda superior central),
        /// dimensionado al encuadre de la cámara. La imagen no sigue al personaje:
        /// es un elemento de pantalla, como el HUD. Al retirarla se vuelve a la
        /// posición y al tamaño de siempre.
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

        /// <summary>Vuelve al sitio de siempre (al ocultarse).</summary>
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

        /// <summary>Cierto mientras el panel está en su sitio fijo de pantalla.</summary>
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

            // El pie va dentro del panel, pegado al borde inferior y un pelo por
            // delante, y escala con él.
            if (captionRoot != null)
            {
                float factor = _baseScale.y / Mathf.Max(0.05f, captionReferenceHeight);
                captionRoot.transform.localScale = Vector3.one * factor;
                captionRoot.transform.localPosition = new Vector3(0f, -(_baseScale.y * 0.5f) + 0.05f * factor, -0.002f);
            }
        }

        private void LateUpdate()
        {
            // La cámara puede estar echándose atrás para dejar sitio: el panel se
            // recoloca cada frame para quedarse fijo en pantalla.
            if (_anchored && _visible)
            {
                PlaceNow();
            }
        }

        /// <summary>Retira el panel con la animación de salida.</summary>
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

        /// <summary>Retira el panel sin animación y libera la textura.</summary>
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
        // Detalles
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

                // En una pantalla 9:16 sobra alto y falta ancho, así que el ancho
                // máximo manda: una imagen apaisada se queda más baja en lugar de
                // salirse por los lados.
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
                // Acceder a .material crea la instancia propia de este Renderer.
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
                    "[Sonia] No se encontró ningún shader unlit para el panel. Asigna un material al Renderer.",
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
