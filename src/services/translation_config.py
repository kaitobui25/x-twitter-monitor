from __future__ import annotations

from dataclasses import dataclass


VALID_TRANSLATION_MODES = {"auto", "off", "required"}


def normalize_api_keys(raw: object) -> list[str]:
    if isinstance(raw, dict):
        values = [raw[key] for key in sorted(raw)]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    elif isinstance(raw, str):
        values = [raw]
    else:
        values = []

    result = []
    for value in values:
        key = str(value).strip()
        if key:
            result.append(key)
    return result


@dataclass(frozen=True)
class TranslationSettings:
    mode: str = "auto"
    provider: str = "gemini"
    model: str = "gemini-2.5-flash-lite"
    batch_size: int = 20
    max_attempts_per_batch: int = 3
    api_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        mode = self.mode.strip().lower()
        provider = self.provider.strip().lower()
        if mode not in VALID_TRANSLATION_MODES:
            raise ValueError(
                "translation.mode must be one of: auto, off, required"
            )
        if provider != "gemini":
            raise ValueError("translation.provider currently supports only 'gemini'")
        if self.batch_size < 1:
            raise ValueError("translation.batch_size must be >= 1")
        if self.max_attempts_per_batch < 1:
            raise ValueError("translation.max_attempts_per_batch must be >= 1")

        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self,
            "api_keys",
            tuple(normalize_api_keys(self.api_keys)),
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_keys)
