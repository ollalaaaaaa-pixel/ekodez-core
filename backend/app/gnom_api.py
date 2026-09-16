"""Owner commands for Gnom; only masked summaries by default."""

import re
from collections.abc import Callable

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.gnom_parser import GnomError
from app.gnom_service import (
    analytics,
    confirm_expense,
    history_summary,
    import_file,
    price_hint,
)
from app.models import (
    GnomCandidate,
    GnomImportRun,
    GnomPlatformRule,
    GnomRecord,
    GnomSettings,
    Inventory,
    Lead,
)
from app.security.pii import decrypt_sensitive_mapping
from app.security.tg_auth import (
    principal_from_request,
    require_owner,
    require_reveal_access,
)


class SettingsIn(BaseModel):
    weekly_enabled: bool
    warranty_days: int | None = Field(default=None, ge=0, le=3650)


class LookupIn(BaseModel):
    address: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=100)


class ExpenseIn(BaseModel):
    category_id: int = Field(gt=0)


class PlatformIn(BaseModel):
    platform: str = Field(min_length=1, max_length=100, pattern=r"^[\w .-]+$")
    deal_prefix: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^\d+$"
    )


class CandidateIn(BaseModel):
    status: str = Field(pattern=r"^(confirmed|rejected)$")
    inventory_id: int | None = Field(default=None, gt=0)


def gnom_router(get_engine: Callable[[], Engine]) -> APIRouter:
    router = APIRouter(prefix="/api/gnom", tags=["gnom"])

    @router.post("/import")
    async def upload(
        request: Request, file: UploadFile = File(...), confirmed: bool = False
    ):
        require_owner(request)
        if not confirmed:
            raise HTTPException(409, "Подтвердите импорт выбранного файла")
        content = await file.read(20 * 1024 * 1024 + 1)
        try:
            return import_file(
                get_engine(), content, file.filename or "export", authorized=True
            )
        except GnomError as error:
            raise HTTPException(422, str(error)) from None

    @router.get("/overview")
    def overview(request: Request):
        require_owner(request)
        with Session(get_engine()) as session:
            settings = session.get(GnomSettings, 1)
            return {
                "settings": {
                    "weekly_enabled": settings.weekly_enabled if settings else False,
                    "warranty_days": settings.warranty_days if settings else None,
                },
                "runs": [
                    {
                        "id": row.id,
                        "filename": row.filename,
                        "sha256": row.file_hash,
                        "rows": row.rows,
                        "status": row.status,
                        "error": row.error,
                    }
                    for row in session.scalars(
                        select(GnomImportRun)
                        .order_by(GnomImportRun.id.desc())
                        .limit(50)
                    )
                ],
                "expenses": [
                    {
                        "id": row.id,
                        "amount": f"{row.outcome:.2f}",
                        "suggested_category": row.signals.get("expense_category"),
                        "lead_id": row.lead_id,
                    }
                    for row in session.scalars(
                        select(GnomRecord).where(
                            GnomRecord.expense_confirmed.is_(False)
                        )
                    )
                    if row.outcome > 0 or row.expense_id
                ],
                "candidates": [
                    {
                        "id": row.id,
                        "kind": row.kind,
                        "preview": "Из истории, требует подтверждения: ***",
                        "status": row.status,
                        "inventory_id": row.inventory_id,
                    }
                    for row in session.scalars(
                        select(GnomCandidate).order_by(GnomCandidate.id)
                    )
                ],
                "analytics": analytics(session),
            }

    @router.patch("/settings")
    def settings(payload: SettingsIn, request: Request):
        require_owner(request)
        with Session(get_engine()) as session, session.begin():
            row = session.get(GnomSettings, 1)
            if row is None:
                row = GnomSettings(id=1)
                session.add(row)
            row.weekly_enabled, row.warranty_days = (
                payload.weekly_enabled,
                payload.warranty_days,
            )
        return payload

    @router.post("/records/{record_id}/expense")
    def expense(record_id: int, payload: ExpenseIn, request: Request):
        require_owner(request)
        with Session(get_engine()) as session, session.begin():
            row = session.get(GnomRecord, record_id)
            if row is None:
                raise HTTPException(404, "Запись не найдена")
            try:
                transaction = confirm_expense(session, row, payload.category_id)
            except GnomError as error:
                raise HTTPException(422, str(error)) from None
            return {"transaction_id": transaction.id}

    @router.patch("/records/{record_id}/platform")
    def platform(record_id: int, payload: PlatformIn, request: Request):
        require_owner(request)
        with Session(get_engine()) as session, session.begin():
            row = session.get(GnomRecord, record_id)
            if row is None or row.source != "aggregator":
                raise HTTPException(404, "Запись агрегатора не найдена")
            if re.search(r"\d{7,}", payload.platform):
                raise HTTPException(422, "Укажите название платформы без контактов")
            targets = (
                session.scalars(
                    select(GnomRecord).where(
                        GnomRecord.deal_id == row.deal_id,
                        GnomRecord.source == "aggregator",
                    )
                )
                if row.deal_id
                else [row]
            )
            for target in targets:
                target.platform = payload.platform
            if payload.deal_prefix:
                if not row.deal_id or not row.deal_id.startswith(payload.deal_prefix):
                    raise HTTPException(422, "Префикс не соответствует номеру сделки")
                rule = session.scalar(
                    select(GnomPlatformRule).where(
                        GnomPlatformRule.deal_prefix == payload.deal_prefix
                    )
                )
                if rule is None:
                    rule = GnomPlatformRule(
                        deal_prefix=payload.deal_prefix, platform=payload.platform
                    )
                    session.add(rule)
                rule.platform = payload.platform
        return {"ok": True}

    @router.get("/candidates/{candidate_id}/reveal")
    def reveal(candidate_id: int, request: Request, response: Response):
        require_reveal_access(request, owner_only=True)
        with Session(get_engine()) as session:
            row = session.get(GnomCandidate, candidate_id)
            if row is None:
                raise HTTPException(404, "Кандидат не найден")
            response.headers["Cache-Control"] = "no-store"
            try:
                value = decrypt_sensitive_mapping(row.encrypted_value).get("value")
            except ValueError:
                raise HTTPException(409, "Данные недоступны") from None
            print('{"event":"gnom_candidate_revealed"}')
            return {"value": value}

    @router.patch("/candidates/{candidate_id}")
    def candidate(candidate_id: int, payload: CandidateIn, request: Request):
        require_owner(request)
        with Session(get_engine()) as session, session.begin():
            row = session.get(GnomCandidate, candidate_id)
            if row is None:
                raise HTTPException(404, "Кандидат не найден")
            if (
                payload.inventory_id
                and session.get(Inventory, payload.inventory_id) is None
            ):
                raise HTTPException(422, "Позиция склада не найдена")
            row.status, row.inventory_id = payload.status, payload.inventory_id
        return {"ok": True}

    @router.post("/repeat")
    def repeat(payload: LookupIn, request: Request, response: Response):
        _require_gnom_owner(request)
        response.headers["Cache-Control"] = "no-store"
        with Session(get_engine()) as session:
            return history_summary(session, payload.address, payload.phone)

    @router.get("/leads/{lead_id}/history")
    def lead_history(lead_id: int, request: Request, response: Response):
        _require_gnom_owner(request)
        response.headers["Cache-Control"] = "no-store"
        with Session(get_engine()) as session:
            lead = session.get(Lead, lead_id)
            if lead is None:
                raise HTTPException(404, "Заявка не найдена")
            try:
                pii = decrypt_sensitive_mapping(lead.encrypted_pii)
            except ValueError:
                return None
            return history_summary(
                session, pii.get("address") or "", pii.get("phone") or "", lead.order_at
            )

    @router.get("/price-hint")
    def hint(request: Request, pest: str, area_unit: str, city: str):
        _require_gnom_owner(request)
        with Session(get_engine()) as session:
            return price_hint(session, pest, area_unit, city)

    return router


def _require_gnom_owner(request: Request) -> None:
    principal = principal_from_request(request)
    if principal is None or principal.role != "owner":
        raise HTTPException(403, "История Гном доступна только владельцу")
