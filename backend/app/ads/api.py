import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.ads.attribution import set_manual_attribution
from app.ads.config import AdsConfigError, load_ads_config
from app.ads.importer import import_ads_file
from app.ads.metrics import ads_metrics
from app.models import AdImportRun, Lead, Notification
from app.security.tg_auth import require_owner
from app.tg_poller import send_message


class ManualAttributionIn(BaseModel):
    platform: Literal["yandex_direct", "yandex_business", "2gis"] | None


def ads_router(engine_factory: Callable[[], Engine]) -> APIRouter:
    router = APIRouter(prefix="/api/ads", tags=["ads"])

    @router.post("/import")
    def import_files(request: Request, platform: str) -> dict[str, object]:
        require_owner(request)
        try:
            config = load_ads_config()
        except AdsConfigError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if platform not in config.platforms:
            raise HTTPException(status_code=400, detail="Площадка не настроена")
        folder = config.root / platform
        paths = sorted(
            path
            for path in folder.glob("*")
            if path.suffix.lower() in {".csv", ".xlsx", ".xls"}
        )
        summaries: list[dict[str, object]] = []
        with Session(engine_factory()) as session:
            for path in paths:
                try:
                    result = import_ads_file(session, platform, path)
                except (OSError, ValueError) as exc:
                    session.commit()
                    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
                    owner = os.getenv("OWNER_TG_ID", "").strip()
                    if token and owner.isdigit():
                        send_message(
                            token,
                            int(owner),
                            f"Ошибка импорта рекламы {platform}: {path.name}; "
                            f"{str(exc)[:160]}",
                        )
                    continue
                summaries.append(
                    {
                        "source_file": result.source_file,
                        "rows": result.rows,
                        "period": result.period,
                    }
                )
                session.commit()
        return {"platform": platform, "files": summaries}

    @router.get("/metrics")
    def metrics(request: Request, start: date, end: date) -> list[dict[str, object]]:
        require_owner(request)
        with Session(engine_factory()) as session:
            return [row.json() for row in ads_metrics(session, start, end)]

    @router.get("/import-runs")
    def import_runs(request: Request) -> list[dict[str, object]]:
        require_owner(request)
        with Session(engine_factory()) as session:
            rows = session.scalars(
                select(AdImportRun).order_by(AdImportRun.id.desc()).limit(100)
            ).all()
            return [
                {
                    "id": row.id,
                    "platform": row.platform,
                    "source_file": row.source_file,
                    "status": row.status,
                    "rows": row.rows_imported,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    @router.get("/attribution-queue")
    def attribution_queue(request: Request) -> list[dict[str, object]]:
        require_owner(request)
        with Session(engine_factory()) as session:
            rows = session.scalars(
                select(Lead).where(Lead.attribution_method.is_(None)).order_by(Lead.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "created_at": row.created_at,
                    "source": row.source,
                    "category": row.category,
                }
                for row in rows
            ]

    @router.post("/leads/{lead_id}/attribution")
    def manual_attribution(
        lead_id: int, payload: ManualAttributionIn, request: Request
    ) -> dict[str, object]:
        require_owner(request)
        with Session(engine_factory()) as session:
            lead = session.get(Lead, lead_id)
            if lead is None:
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            set_manual_attribution(session, lead, payload.platform, datetime.now(UTC))
            session.commit()
        return {"status": "ok"}

    @router.get("/notifications")
    def notifications(request: Request) -> list[dict[str, object]]:
        require_owner(request)
        with Session(engine_factory()) as session:
            rows = session.scalars(
                select(Notification).order_by(Notification.id.desc()).limit(100)
            ).all()
            return [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "payload": row.payload,
                    "created_at": row.created_at,
                    "read_at": row.read_at,
                }
                for row in rows
            ]

    @router.get("/notifications/unread-count")
    def unread_count(request: Request) -> dict[str, int]:
        require_owner(request)
        with Session(engine_factory()) as session:
            count = (
                session.scalar(
                    select(func.count(Notification.id)).where(
                        Notification.read_at.is_(None)
                    )
                )
                or 0
            )
            return {"count": count}

    @router.post("/notifications/{notification_id}/read")
    def mark_read(notification_id: int, request: Request) -> dict[str, object]:
        require_owner(request)
        with Session(engine_factory()) as session:
            row = session.get(Notification, notification_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Уведомление не найдено")
            row.read_at = datetime.now(UTC)
            session.commit()
        return {"status": "ok"}

    return router
