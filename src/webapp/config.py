from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.services.translation_config import TranslationSettings, normalize_api_keys


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebSettings:
    host: str = "127.0.0.1"
    port: int = 8766
    open_browser: bool = True


@dataclass(frozen=True)
class XSettings:
    monitor_config: Path
    cookies_dir: Path


@dataclass(frozen=True)
class AppSettings:
    source_path: Path
    web: WebSettings
    x: XSettings
    translation: TranslationSettings


def _mapping(value: object, name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SettingsError(f"{name} must be a YAML mapping.")
    return value


def _resolve_path(root: Path, value: object, default: str) -> Path:
    selected = default if value is None or value == "" else value
    raw = str(selected).strip()
    if not raw:
        raise SettingsError("Configured path cannot be empty.")
    path = Path(raw)
    return path if path.is_absolute() else (root / path).resolve()


def load_app_settings(
    root: str | Path,
    settings_path: str | Path | None = None,
) -> AppSettings:
    root_path = Path(root).resolve()
    source_path = (
        Path(settings_path).resolve()
        if settings_path is not None
        else root_path / "config.yaml"
    )

    if source_path.is_file():
        try:
            with source_path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            raise SettingsError(f"Cannot read settings YAML: {exc}") from exc
        data = _mapping(loaded, "root settings")
    else:
        data = {}

    web_raw = _mapping(data.get("web"), "web")
    x_raw = _mapping(data.get("x"), "x")
    translation_raw = _mapping(data.get("translation"), "translation")

    try:
        port = int(web_raw.get("port", 8766))
    except (TypeError, ValueError) as exc:
        raise SettingsError("web.port must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise SettingsError("web.port must be between 1 and 65535.")

    open_browser = web_raw.get("open_browser", True)
    if not isinstance(open_browser, bool):
        raise SettingsError("web.open_browser must be true or false.")

    try:
        translation = TranslationSettings(
            mode=str(translation_raw.get("mode", "auto")),
            provider=str(translation_raw.get("provider", "gemini")),
            model=str(
                translation_raw.get("model")
                or "gemini-2.5-flash-lite"
            ),
            batch_size=int(translation_raw.get("batch_size", 20)),
            max_attempts_per_batch=int(
                translation_raw.get("max_attempts_per_batch", 3)
            ),
            api_keys=tuple(
                normalize_api_keys(
                    translation_raw.get("gemini_api_keys", ())
                )
            ),
        )
    except (TypeError, ValueError) as exc:
        raise SettingsError(str(exc)) from exc

    host = str(web_raw.get("host") or "127.0.0.1").strip()
    if not host:
        raise SettingsError("web.host cannot be empty.")

    return AppSettings(
        source_path=source_path,
        web=WebSettings(
            host=host,
            port=port,
            open_browser=open_browser,
        ),
        x=XSettings(
            monitor_config=_resolve_path(
                root_path,
                x_raw.get("monitor_config"),
                "config/config.json",
            ),
            cookies_dir=_resolve_path(
                root_path,
                x_raw.get("cookies_dir"),
                "cookies",
            ),
        ),
        translation=translation,
    )
