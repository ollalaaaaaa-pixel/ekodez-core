from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.ads.config import AdsConfig, load_ads_config
from app.ads.metrics import ads_metrics
from app.ads.notifications import create_notification
from app.models import AdImportRun, Notification

ANALYSIS_ROOT = Path(r"C:\D\Экодез\analysis")


def create_upload_reminders(
    session: Session, config: AdsConfig, now: datetime
) -> list[Notification]:
    created: list[Notification] = []
    for platform, settings in config.platforms.items():
        if settings.mode != "manual":
            continue
        cutoff = now - timedelta(days=settings.reminder_period_days)
        fresh = session.scalar(
            select(AdImportRun.id).where(
                AdImportRun.platform == platform,
                AdImportRun.status == "ok",
                AdImportRun.created_at >= cutoff,
            )
        )
        period_key = (
            f"{platform}:{now.date().isoformat()}:{settings.reminder_period_days}"
        )
        recent_reminders = session.scalars(
            select(Notification).where(
                Notification.kind == "ads_upload_reminder",
                Notification.created_at >= cutoff,
            )
        ).all()
        duplicate = any(
            row.payload.get("platform") == platform for row in recent_reminders
        )
        if fresh is not None or duplicate:
            continue
        created.append(
            create_notification(
                session,
                "ads_upload_reminder",
                {
                    "platform": platform,
                    "folder": str(config.root / platform),
                    "instructions": [
                        "расход, показы и клики по кампаниям",
                        "конверсии и звонки",
                        "период отчета",
                    ],
                    "period_key": period_key,
                },
                now,
            )
        )
    return created


def _versioned_draft(platform: str, period: str, text: str) -> Path:
    ANALYSIS_ROOT.mkdir(parents=True, exist_ok=True)
    base = ANALYSIS_ROOT / f"ads-recommendation-{platform}-{period}.md"
    path = base
    version = 2
    while path.exists():
        path = base.with_name(f"{base.stem}-v{version}{base.suffix}")
        version += 1
    path.write_text(text, encoding="utf-8")
    return path


def run_ads_weekly(
    engine: Engine, now: datetime, sender: Callable[[str], bool]
) -> dict[str, object]:
    start = now.date() - timedelta(days=7)
    end = now.date() - timedelta(days=1)
    with Session(engine) as session:
        config = load_ads_config()
        metrics = ads_metrics(session, start, end)
        previous_metrics = ads_metrics(
            session, start - timedelta(days=7), end - timedelta(days=7)
        )
        lines = [f"Реклама за {start:%d.%m}–{end:%d.%m}:"]
        drafts: list[str] = []
        for row in metrics:
            cpl = "нет лидов" if row.cpl is None else f"{row.cpl:.2f} ₽/лид"
            lines.append(
                f"{row.platform}: расход {row.spend:.2f} ₽, лиды {row.leads}, {cpl}"
            )
            settings = config.platforms.get(row.platform)
            previous_cpl = next(
                (
                    item.cpl
                    for item in previous_metrics
                    if item.platform == row.platform and item.campaign == row.campaign
                ),
                None,
            )
            alert = bool(
                settings
                and (
                    (
                        settings.target_cpl is not None
                        and row.cpl is not None
                        and previous_cpl is not None
                        and row.cpl > settings.target_cpl
                        and previous_cpl > settings.target_cpl
                    )
                    or (
                        settings.zero_lead_spend_threshold is not None
                        and row.leads == 0
                        and row.spend > settings.zero_lead_spend_threshold
                    )
                )
            )
            if alert:
                period = f"{start.isoformat()}-{end.isoformat()}"
                draft = _versioned_draft(
                    row.platform,
                    period,
                    "# Черновик рекомендации\n\n"
                    f"Площадка: {row.platform}\n\nРасход: {row.spend:.2f} ₽; "
                    f"лиды: {row.leads}; CPL: {cpl}.\n\n"
                    "Решение для согласования владельцем: торговаться, "
                    "приостановить или перераспределить бюджет.\n\n"
                    "Письмо менеджеру (черновик, не отправлено): просьба предложить "
                    "условия, соответствующие фактической стоимости лида.\n",
                )
                drafts.append(str(draft))
                create_notification(
                    session,
                    "ads_alert",
                    {
                        "platform": row.platform,
                        "reason": "CPL/нулевые лиды",
                        "period": period,
                        "metrics": row.json(),
                    },
                    now,
                )
                create_notification(
                    session,
                    "draft_ready",
                    {
                        "platform": row.platform,
                        "draft_path": str(draft),
                        "period": period,
                    },
                    now,
                )
        session.commit()
    message = "\n".join(lines)
    sender(message)
    return {"message": message, "drafts": drafts}
