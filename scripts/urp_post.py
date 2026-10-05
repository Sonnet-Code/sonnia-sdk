"""Posprocesado de la cámara principal de Sonia, simulado en numpy.

El fondo de la pantalla lo dibuja la cámara principal y pasa por su
posprocesado. Este módulo reproduce esa cadena de color para que
stage_assets.py pinte el fondo precompensado y en pantalla se vea como la
maqueta. Es la cadena de URP con gradación LDR:

    color lineal -> viñeta -> ACES -> tabla interna de 32^3 (contraste en LogC,
    saturación) -> sRGB

Portado de com.unity.render-pipelines.core/ShaderLibrary/{ACES,Color}.hlsl y de
com.unity.render-pipelines.universal/Shaders/PostProcessing/{Common.hlsl,
LutBuilderLdr.shader}. Comprobado contra una captura de Unity: acierta el fondo
con un error medio de un nivel sobre 255. El desenfoque de profundidad, el bloom
(umbral 1) y el tramado no cambian el color del fondo y se ignoran.

Los parámetros se leen del perfil del Volume de la escena, así que basta con
volver a generar los recursos tras tocarlo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Matrices de ACES.hlsl (filas = componente de salida).
SRGB_TO_AP0 = np.array(
    [
        [0.4397010, 0.3829780, 0.1773350],
        [0.0897923, 0.8134230, 0.0967616],
        [0.0175440, 0.1115440, 0.8707040],
    ]
)
AP0_TO_AP1 = np.array(
    [
        [1.4514393161, -0.2365107469, -0.2149285693],
        [-0.0765537734, 1.1762296998, -0.0996759264],
        [0.0083161484, -0.0060324498, 0.9977163014],
    ]
)
AP1_TO_XYZ = np.array(
    [
        [0.6624541811, 0.1340042065, 0.1561876870],
        [0.2722287168, 0.6740817658, 0.0536895174],
        [-0.0055746495, 0.0040607335, 1.0103391003],
    ]
)
XYZ_TO_AP1 = np.array(
    [
        [1.6410233797, -0.3248032942, -0.2364246952],
        [-0.6636628587, 1.6153315917, 0.0167563477],
        [0.0117218943, -0.0082844420, 0.9883948585],
    ]
)
XYZ_TO_REC709 = np.array(
    [
        [3.2409699419, -1.5373831776, -0.4986107603],
        [-0.9692436363, 1.8759675015, 0.0415550574],
        [0.0556300797, -0.2039769589, 1.0569715142],
    ]
)
D60_TO_D65 = np.array(
    [
        [0.98722400, -0.00611327, 0.0159533],
        [-0.00759836, 1.00186000, 0.0053302],
        [0.00307257, -0.00509595, 1.0816800],
    ]
)
AP1_RGB2Y = np.array([0.272229, 0.674082, 0.0536895])
REC709_Y = np.array([0.2126729, 0.7151522, 0.0721750])

# LogC sin el tramo lineal (USE_PRECISE_LOGC 0 en Color.hlsl).
LOGC_A, LOGC_B, LOGC_C, LOGC_D = 5.555556, 0.047996, 0.244161, 0.386036
ACESCC_MIDGRAY = 0.4135884


@dataclass(frozen=True)
class PostSettings:
    """Lo que toca el color del fondo en el perfil del Volume."""

    aces: bool = True
    post_exposure: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    vignette_intensity: float = 0.0
    vignette_smoothness: float = 0.2
    vignette_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    vignette_center: tuple[float, float] = (0.5, 0.5)


def read_profile(path: Path) -> PostSettings:
    """Lee los ajustes de un VolumeProfile de Unity (YAML) sin dependencias.

    Solo cuenta lo que tiene el override activo, como hace Unity; lo demás
    queda en los valores por defecto de URP.
    """
    text = path.read_text(encoding="utf-8")
    blocks = {}
    for block in text.split("--- !u!")[1:]:
        name = re.search(r"\n  m_Name: (\w+)", block)
        active = re.search(r"\n  active: (\d)", block)
        if name and active and active.group(1) == "1":
            blocks[name.group(1)] = block

    def value(component: str, field: str) -> str | None:
        block = blocks.get(component)
        if block is None:
            return None
        match = re.search(rf"\n  {field}:\n    m_OverrideState: 1\n    m_Value: ([^\n]+)", block)
        return match.group(1) if match else None

    def number(component: str, field: str, default: float) -> float:
        raw = value(component, field)
        return float(raw) if raw is not None else default

    def components(raw: str | None, keys: str, default: tuple[float, ...]) -> tuple[float, ...]:
        if raw is None:
            return default
        return tuple(float(re.search(rf"\b{k}: ([-\d.e]+)", raw).group(1)) for k in keys)

    mode = value("Tonemapping", "mode")
    if mode not in (None, "0", "2"):
        raise ValueError(f"Tonemapping {mode} sin simular: solo None (0) y ACES (2)")
    vignette_color = components(value("Vignette", "color"), "rgb", (0.0, 0.0, 0.0))
    vignette_center = components(value("Vignette", "center"), "xy", (0.5, 0.5))
    if value("Vignette", "rounded") == "1":
        raise ValueError("Viñeta redondeada sin simular")
    return PostSettings(
        aces=mode == "2",
        post_exposure=number("ColorAdjustments", "postExposure", 0.0),
        contrast=number("ColorAdjustments", "contrast", 0.0),
        saturation=number("ColorAdjustments", "saturation", 0.0),
        vignette_intensity=number("Vignette", "intensity", 0.0),
        vignette_smoothness=number("Vignette", "smoothness", 0.2),
        vignette_color=(vignette_color[0], vignette_color[1], vignette_color[2]),
        vignette_center=(vignette_center[0], vignette_center[1]),
    )


def check_ldr_grading(pipeline_asset: Path) -> None:
    """La simulación es la de gradación LDR; con HDR el orden es otro."""
    match = re.search(r"m_ColorGradingMode: (\d)", pipeline_asset.read_text(encoding="utf-8"))
    if match and match.group(1) != "0":
        raise ValueError(f"{pipeline_asset.name} usa gradación HDR: la simulación es la LDR")


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def _mul(matrix: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    return rgb @ matrix.T


def vignette(settings: PostSettings, width: int, height: int) -> np.ndarray:
    """Factor de la viñeta por píxel y canal (ApplyVignette; uv.y crece hacia arriba)."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float64)
    u = (x + 0.5) / width
    v = 1.0 - (y + 0.5) / height
    dx = np.abs(u - settings.vignette_center[0]) * settings.vignette_intensity * 3.0
    dy = np.abs(v - settings.vignette_center[1]) * settings.vignette_intensity * 3.0
    factor = np.power(
        np.clip(1.0 - (dx * dx + dy * dy), 0.0, 1.0), settings.vignette_smoothness * 5.0
    )
    color = np.array(settings.vignette_color)
    return color + (1.0 - color) * factor[..., None]


def aces_tonemap(rgb: np.ndarray) -> np.ndarray:
    """AcesTonemap(unity_to_ACES(rgb)) de Color.hlsl, la versión ajustada, y saturate."""
    aces = _mul(SRGB_TO_AP0, rgb)

    # Brillo de los colores poco saturados (glow module).
    low = np.maximum(aces.min(-1), 1e-4)
    high = aces.max(-1)
    saturation = (np.maximum(high, 1e-4) - low) / np.maximum(high, 1e-2)
    r, g, b = aces[..., 0], aces[..., 1], aces[..., 2]
    chroma = np.sqrt(np.maximum(b * (b - g) + g * (g - r) + r * (r - b), 0.0))
    yc = (b + g + r + 1.75 * chroma) / 3.0
    x = (saturation - 0.4) / 0.2
    t = np.maximum(1.0 - np.abs(x / 2.0), 0.0)
    shaper = (1.0 + np.where(x > 0.0, 1.0, -1.0) * (1.0 - t * t)) / 2.0  # FastSign(0) = -1
    gain = 0.05 * shaper
    glow = np.where(
        yc <= 2.0 / 3.0 * 0.08,
        gain,
        np.where(yc >= 2.0 * 0.08, 0.0, gain * (0.08 / np.maximum(yc, 1e-9) - 0.5)),
    )
    aces = aces * (1.0 + glow)[..., None]

    # Rojos (red modifier).
    r, g, b = aces[..., 0], aces[..., 1], aces[..., 2]
    neutral = (r == g) & (g == b)
    hue = np.where(neutral, 0.0, np.degrees(np.arctan2(np.sqrt(3.0) * (g - b), 2.0 * r - g - b)))
    hue = np.where(hue < 0.0, hue + 360.0, hue)
    centered = np.where(hue > 180.0, hue - 360.0, hue)
    weight = np.clip(1.0 - np.abs(2.0 * centered / 135.0), 0.0, 1.0)
    weight = weight * weight * (3.0 - 2.0 * weight)
    weight = weight * weight
    aces = aces.copy()
    aces[..., 0] = r + weight * saturation * (0.03 - r) * (1.0 - 0.82)

    # RRT + ODT ajustados (BakingLab), sobre ACEScg algo desaturado.
    acescg = np.maximum(0.0, _mul(AP0_TO_AP1, aces))
    luma = (acescg @ AP1_RGB2Y)[..., None]
    acescg = luma + 0.96 * (acescg - luma)
    post = (acescg * (acescg + 0.0245786) - 0.000090537) / (
        acescg * (0.983729 * acescg + 0.4329510) + 0.238081
    )

    # De ambiente oscuro a tenue: gamma 0,9811 sobre la luminancia.
    xyz = _mul(AP1_TO_XYZ, post)
    total = np.maximum(xyz.sum(-1), 1e-4)
    cx, cy = xyz[..., 0] / total, xyz[..., 1] / total
    lum = np.power(np.clip(xyz[..., 1], 0.0, None), 0.9811)
    scale = lum / np.maximum(cy, 1e-4)
    linear = _mul(XYZ_TO_AP1, np.stack([cx * scale, lum, (1.0 - cx - cy) * scale], -1))
    luma = (linear @ AP1_RGB2Y)[..., None]
    linear = luma + 0.93 * (linear - luma)
    xyz = _mul(D60_TO_D65, _mul(AP1_TO_XYZ, linear))
    return np.clip(_mul(XYZ_TO_REC709, xyz), 0.0, 1.0)


def _rgb_to_hsv(c: np.ndarray) -> np.ndarray:
    """RgbToHsv de Color.hlsl, con su épsilon (desatura un pelo los oscuros)."""
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    zeros = np.zeros_like(r)
    p = np.where(
        (g >= b)[..., None],
        np.stack([g, b, zeros, zeros - 1.0 / 3.0], -1),
        np.stack([b, g, zeros - 1.0, zeros + 2.0 / 3.0], -1),
    )
    q = np.where(
        (r >= p[..., 0])[..., None],
        np.stack([r, p[..., 1], p[..., 2], p[..., 0]], -1),
        np.stack([p[..., 0], p[..., 1], p[..., 3], r], -1),
    )
    d = q[..., 0] - np.minimum(q[..., 3], q[..., 1])
    hue = np.abs(q[..., 2] + (q[..., 3] - q[..., 1]) / (6.0 * d + 1e-4))
    return np.stack([hue, d / (q[..., 0] + 1e-4), q[..., 0]], -1)


def _hsv_to_rgb(c: np.ndarray) -> np.ndarray:
    k = np.array([1.0, 2.0 / 3.0, 1.0 / 3.0])
    p = np.abs(np.modf(c[..., :1] + k)[0] * 6.0 - 3.0)
    return c[..., 2:3] * (1.0 + c[..., 1:2] * (np.clip(p - 1.0, 0.0, 1.0) - 1.0))


def _lut_builder_ldr(c: np.ndarray, settings: PostSettings) -> np.ndarray:
    """FragLutBuilderLdr con el resto de ajustes en su valor neutro."""
    contrast = settings.contrast / 100.0 + 1.0
    log = LOGC_C * np.log10(np.maximum(LOGC_A * c + LOGC_B, 0.0)) + LOGC_D
    log = (log - ACESCC_MIDGRAY) * contrast + ACESCC_MIDGRAY
    c = np.maximum(0.0, (np.power(10.0, (log - LOGC_D) / LOGC_C) - LOGC_B) / LOGC_A)
    c = _hsv_to_rgb(_rgb_to_hsv(c))
    luma = (c @ REC709_Y)[..., None]
    c = luma + (settings.saturation / 100.0 + 1.0) * (c - luma)
    return np.clip(c, 0.0, 1.0)


class PostProcess:
    """La cadena de color del fondo, con la tabla interna ya calculada."""

    LUT_SIZE = 32

    def __init__(self, settings: PostSettings) -> None:
        self.settings = settings
        grid = np.linspace(0.0, 1.0, self.LUT_SIZE)
        r, g, b = np.meshgrid(grid, grid, grid, indexing="ij")
        self._lut = _lut_builder_ldr(np.stack([r, g, b], -1), settings)

    def _sample_lut(self, c: np.ndarray) -> np.ndarray:
        n = self.LUT_SIZE
        p = np.clip(c, 0.0, 1.0) * (n - 1)
        base = np.minimum(np.floor(p).astype(int), n - 2)
        f = p - base
        out = np.zeros_like(c)
        for dr in (0, 1):
            wr = f[..., 0] if dr else 1.0 - f[..., 0]
            for dg in (0, 1):
                wg = f[..., 1] if dg else 1.0 - f[..., 1]
                for db in (0, 1):
                    wb = f[..., 2] if db else 1.0 - f[..., 2]
                    corner = self._lut[base[..., 0] + dr, base[..., 1] + dg, base[..., 2] + db]
                    out += (wr * wg * wb)[..., None] * corner
        return out

    def grade(self, linear: np.ndarray) -> np.ndarray:
        """Lineal de la escena (ya con la viñeta) a lineal de pantalla."""
        linear = linear * 2.0**self.settings.post_exposure
        if self.settings.aces:
            linear = aces_tonemap(linear)
        return self._sample_lut(np.clip(linear, 0.0, 1.0))

    def forward(self, srgb: np.ndarray) -> np.ndarray:
        """Imagen sRGB (0-1) dibujada por la cámara -> sRGB (0-1) en pantalla."""
        height, width = srgb.shape[:2]
        return linear_to_srgb(
            self.grade(srgb_to_linear(srgb) * vignette(self.settings, width, height))
        )

    def inverse(self, target: np.ndarray) -> np.ndarray:
        """Imagen sRGB (0-1) que la cámara tiene que dibujar para mostrar ``target``.

        Primero un acercamiento canal a canal y luego Newton por píxel con el
        jacobiano por diferencias y pasos cortos: en los azules oscuros el rojo
        sale a cero hasta que la entrada se acerca al gris, y un paso largo
        se iría lejos. Lo que la cadena no alcanza queda en el tope.
        """
        height, width = target.shape[:2]
        goal = srgb_to_linear(target)
        x = np.clip(goal * 2.0, 1e-7, 1.0)
        for _ in range(10):
            ratio = goal / np.maximum(self.grade(x), 1e-7)
            x = np.clip(x * np.clip(ratio, 0.5, 2.0), 1e-7, 1.0)
        step = 1e-4
        for _ in range(25):
            value = self.grade(x)
            jacobian = np.empty(x.shape + (3,))
            for channel in range(3):
                nudged = x.copy()
                nudged[..., channel] += step
                jacobian[..., :, channel] = (self.grade(nudged) - value) / step
            jacobian += np.eye(3) * 1e-6
            delta = np.linalg.solve(jacobian, (goal - value)[..., None])[..., 0]
            x = np.clip(x + np.clip(delta, -0.02, 0.02), 0.0, 1.0)
        source = x / vignette(self.settings, width, height)
        return linear_to_srgb(np.clip(source, 0.0, 1.0))
