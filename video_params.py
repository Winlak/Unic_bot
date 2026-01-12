from __future__ import annotations

import random
from dataclasses import dataclass

import config


@dataclass
class VariantParams:
    seed: int
    zoom: float
    brightness: float
    saturation_factor: float
    noise_value: float
    pitch_factor: float

    @property
    def saturation_delta(self) -> float:
        return self.saturation_factor - 1.0

    @property
    def noise_level(self) -> int:
        return max(1, int(self.noise_value * 256))

    def as_report(self) -> str:
        return (
            f"seed: {self.seed}\n"
            f"zoom: {self.zoom:.3f}\n"
            f"brightness: {self.brightness:+.3f}\n"
            f"saturation: {self.saturation_delta:+.3f}\n"
            f"noise: {self.noise_value:.3f}\n"
            "metadata stripped: yes\n"
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def generate_variant_params(seed: int) -> VariantParams:
    rng = random.Random(seed)
    zoom = rng.uniform(*config.ZOOM_RANGE)
    brightness = rng.uniform(*config.BRIGHTNESS_RANGE)
    sat_delta = rng.uniform(*config.SATURATION_DELTA_RANGE)
    saturation_factor = 1.0 + sat_delta
    noise = rng.uniform(*config.NOISE_RANGE)
    pitch_shift = rng.uniform(*config.AUDIO_PITCH_SHIFT_RANGE)
    pitch_factor = _clamp(1.0 + pitch_shift, 0.98, 1.02)
    return VariantParams(
        seed=seed,
        zoom=zoom,
        brightness=brightness,
        saturation_factor=saturation_factor,
        noise_value=noise,
        pitch_factor=pitch_factor,
    )
