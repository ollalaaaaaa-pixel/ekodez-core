import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULT_ADS_CONFIG_PATH = Path(r"C:\D\Экодез\ads\config.json")
ALLOWED_PLATFORMS = frozenset({"yandex_direct", "yandex_business", "2gis"})


class AdsConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PlatformConfig:
    mode: str = "manual"
    reminder_period_days: int = 7
    target_cpl: Decimal | None = None
    zero_lead_spend_threshold: Decimal | None = None


@dataclass(frozen=True)
class AdsConfig:
    root: Path
    platforms: dict[str, PlatformConfig]
    scheduler_stale_timeout_minutes: int = 30


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise AdsConfigError("invalid monetary threshold") from exc
    if parsed < 0:
        raise AdsConfigError("monetary threshold must be nonnegative")
    return parsed


def load_ads_config(path: Path = DEFAULT_ADS_CONFIG_PATH) -> AdsConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdsConfigError("advertising configuration is unavailable") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("platforms"), dict):
        raise AdsConfigError("platform configuration is required")
    root = Path(str(raw.get("root") or path.parent)).resolve()
    try:
        timeout = int(raw.get("scheduler_stale_timeout_minutes", 30))
    except (TypeError, ValueError) as exc:
        raise AdsConfigError("invalid scheduler stale timeout") from exc
    if timeout < 1:
        raise AdsConfigError("scheduler stale timeout must be positive")
    platforms: dict[str, PlatformConfig] = {}
    for name, item in raw["platforms"].items():
        if name not in ALLOWED_PLATFORMS or not isinstance(item, dict):
            raise AdsConfigError("unknown advertising platform")
        mode = str(item.get("mode", "manual"))
        if mode not in {"manual", "disabled"}:
            raise AdsConfigError("unsupported import mode")
        reminder = int(item.get("reminder_period_days", 7))
        if reminder < 1:
            raise AdsConfigError("reminder period must be positive")
        platforms[name] = PlatformConfig(
            mode=mode,
            reminder_period_days=reminder,
            target_cpl=_optional_decimal(item.get("target_cpl")),
            zero_lead_spend_threshold=_optional_decimal(
                item.get("zero_lead_spend_threshold")
            ),
        )
    return AdsConfig(
        root=root, platforms=platforms, scheduler_stale_timeout_minutes=timeout
    )
