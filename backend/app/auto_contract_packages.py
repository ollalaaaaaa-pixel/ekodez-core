from calendar import monthrange
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import next_invoice_number
from app.models import Client, Contract, ContractPeriod, InspectionReport, Treatment


@dataclass(frozen=True)
class AutoPackageDraft:
    contract: Contract
    report: InspectionReport
    period: ContractPeriod
    client: Client
    treatment: Treatment | None


@dataclass(frozen=True)
class AutoPackageSkip:
    label: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AutoPackageSummary:
    period_month: date
    ready: tuple[str, ...]
    skipped: tuple[AutoPackageSkip, ...]


DocumentGenerator = Callable[[AutoPackageDraft], list[dict[str, object]]]


def _month_end(month: date) -> date:
    return month.replace(day=monthrange(month.year, month.month)[1])


def _previous_month(value: date) -> date:
    return (value.replace(day=1) - timedelta(days=1)).replace(day=1)


def _active_during(contract: Contract, month: date) -> bool:
    return (
        contract.start_date is None or contract.start_date <= _month_end(month)
    ) and (contract.end_date is None or contract.end_date >= month)


def _participates(contract: Contract, month: date) -> bool:
    if contract.periodicity == "monthly":
        return True
    if contract.periodicity in {"semiannual", "custom"}:
        return month.month in set(contract.service_months or [])
    return False


def _next_two_invoice_numbers(session: Session) -> tuple[str, str]:
    first = next_invoice_number(session)
    second = str(int(first) + 1) if first.isdigit() else f"{first}-2"
    return first, second


def _preparations(treatments: Sequence[Treatment]) -> str | None:
    names = []
    for treatment in treatments:
        for item in treatment.chemicals_used or []:
            name = item.get("chemical_name")
            if isinstance(name, str) and name.strip() and name.strip() not in names:
                names.append(name.strip())
    return ", ".join(names) or None


def run_auto_contract_packages(
    session: Session,
    period_month: date,
    generate_documents: DocumentGenerator,
) -> AutoPackageSummary:
    month = period_month.replace(day=1)
    ready: list[str] = []
    skipped: list[AutoPackageSkip] = []
    contracts = session.scalars(select(Contract).order_by(Contract.id)).all()
    for contract in contracts:
        if not _active_during(contract, month):
            continue
        existing_report = session.scalar(
            select(InspectionReport.id).where(
                InspectionReport.contract_id == contract.id,
                InspectionReport.report_month == month,
            )
        )
        existing_period = session.scalar(
            select(ContractPeriod.id).where(
                ContractPeriod.contract_id == contract.id,
                ContractPeriod.period_month == month,
            )
        )
        if existing_report is not None or existing_period is not None:
            continue

        if contract.periodicity is not None and not _participates(contract, month):
            continue

        service_object = contract.object
        label = (
            service_object.name
            if service_object is not None
            else f"Договор {contract.number}"
        )
        client = None
        if service_object is not None:
            if service_object.status == "inactive":
                continue
            client = session.scalar(
                select(Client)
                .where(
                    Client.object_id == service_object.id,
                    Client.client_type == "legal_entity",
                )
                .order_by(Client.id)
                .limit(1)
            )
            if client is None:
                continue
        reasons: list[str] = []
        if service_object is None:
            reasons.append("нет объекта")
        if contract.periodicity is None:
            reasons.append("договор не настроен")
        if contract.inspection_price is None:
            reasons.append("не задана цена обследования")
        if reasons:
            skipped.append(AutoPackageSkip(label, tuple(reasons)))
            continue
        assert service_object is not None
        assert client is not None
        assert contract.inspection_price is not None
        start = datetime.combine(month, time.min)
        end = datetime.combine(_month_end(month) + timedelta(days=1), time.min)
        treatments = session.scalars(
            select(Treatment)
            .where(
                Treatment.object_id == service_object.id,
                Treatment.performed_at >= start,
                Treatment.performed_at < end,
            )
            .order_by(Treatment.performed_at.desc(), Treatment.id.desc())
        ).all()
        treatment = treatments[0] if treatments else None
        invoice_number, treatment_invoice_number = _next_two_invoice_numbers(session)
        report = InspectionReport(
            contract=contract,
            report_month=month,
            inspection_date=treatment.performed_at.date() if treatment else None,
            ksp_count=contract.default_ksp,
            derat_glue_count=contract.default_derat_glue,
            bait_count=contract.default_baits,
            rodents_caught=0,
            deratization_result="not_required",
            disinsection_glue_count=contract.default_disinsection_glue,
            insects_caught=0,
            disinsection_result="not_required",
            status="draft",
        )
        period = ContractPeriod(
            contract=contract,
            period_month=month,
            paid_service_due=True,
            price_snapshot=Decimal(contract.inspection_price),
            preparations=_preparations(treatments),
            infestation_degree="начальная",
            extra_services=[],
            invoice_number=invoice_number,
            invoice_date=_month_end(month),
            treatment_invoice_number=(
                treatment_invoice_number if treatment is not None else None
            ),
            treatment_price_snapshot=(
                Decimal(contract.price) if treatment is not None else None
            ),
            work_act_status="draft",
            file_manifest=[],
        )
        session.add_all((report, period))
        session.flush()
        period.file_manifest = generate_documents(
            AutoPackageDraft(contract, report, period, client, treatment)
        )
        period.generated_at = datetime.now(UTC)
        ready.append(service_object.name)
    session.commit()
    return AutoPackageSummary(month, tuple(ready), tuple(skipped))


def run_scheduled_auto_contract_packages(
    session: Session,
    current_date: date,
    generate_documents: DocumentGenerator,
) -> AutoPackageSummary | None:
    if current_date.day != 1:
        return None
    return run_auto_contract_packages(
        session, _previous_month(current_date), generate_documents
    )


def format_auto_package_summary(summary: AutoPackageSummary) -> str:
    month = summary.period_month.strftime("%m.%Y")
    ready = ", ".join(summary.ready) or "нет"
    skipped = (
        "; ".join(f"{row.label}: {', '.join(row.reasons)}" for row in summary.skipped)
        or "нет"
    )
    return f"Пакеты за {month}: готовы к подписи — {ready}; не готовы — {skipped}"
