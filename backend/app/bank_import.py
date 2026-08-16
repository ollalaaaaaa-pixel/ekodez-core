"""Pure parser and deterministic rules for T-Bank XLSX statements."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO
from typing import Literal

from openpyxl import load_workbook

MONEY_QUANTUM = Decimal("0.01")
REQUIRED_HEADERS = (
    "Тип операции",
    "Дата проведения",
    "Номер документа",
    "Сумма в валюте счёта",
    "Описание операции",
    "Назначение платежа",
    "Наименование контрагента",
    "ИНН контрагента",
)


class BankImportError(ValueError):
    """A safe validation error that never contains statement row values."""


@dataclass(frozen=True)
class BankRow:
    operation_type: str
    operation_date: date
    doc_number: str
    amount: Decimal
    description: str
    payment_purpose: str
    counterparty_name: str
    counterparty_inn: str


@dataclass(frozen=True)
class ClassificationResult:
    kind: Literal["income", "expense"]
    category: str | None
    channel: str | None
    needs_review: bool
    is_transfer: bool


def parse_amount(value: object) -> Decimal:
    """Parse a spreadsheet monetary value without binary-float arithmetic."""
    if isinstance(value, bool) or value is None:
        raise BankImportError("invalid amount")

    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
    elif isinstance(value, str):
        raw = value.strip().replace("\u00a0", "").replace("\u202f", "")
        raw = raw.replace(" ", "")
        if not raw:
            raise BankImportError("invalid amount")
        comma_index = raw.rfind(",")
        dot_index = raw.rfind(".")
        if comma_index >= 0 and dot_index >= 0:
            decimal_separator = "," if comma_index > dot_index else "."
            thousands_separator = "." if decimal_separator == "," else ","
            raw = raw.replace(thousands_separator, "")
            if decimal_separator == ",":
                raw = raw.replace(",", ".")
        elif comma_index >= 0:
            raw = raw.replace(",", ".")
    else:
        raise BankImportError("invalid amount")

    try:
        return Decimal(raw).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as error:
        raise BankImportError("invalid amount") from error


def parse_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(raw, pattern).date()
            except ValueError:
                continue
    raise BankImportError("invalid operation date")


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_tbank_xlsx(content: bytes) -> list[BankRow]:
    """Read the first sheet containing the complete T-Bank header set."""
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as error:
        raise BankImportError("invalid xlsx file") from error

    try:
        for sheet in workbook.worksheets:
            header_indexes: dict[str, int] | None = None
            header_row_number = 0
            for row_number, values in enumerate(
                sheet.iter_rows(values_only=True), start=1
            ):
                normalized = {
                    _cell_text(value): index
                    for index, value in enumerate(values)
                    if _cell_text(value)
                }
                if all(header in normalized for header in REQUIRED_HEADERS):
                    header_indexes = {
                        header: normalized[header] for header in REQUIRED_HEADERS
                    }
                    header_row_number = row_number
                    break
                if row_number >= 100:
                    break

            if header_indexes is None:
                continue

            result: list[BankRow] = []
            for row_number, values in enumerate(
                sheet.iter_rows(values_only=True), start=1
            ):
                if row_number <= header_row_number:
                    continue
                row_values = {
                    header: values[index] if index < len(values) else None
                    for header, index in header_indexes.items()
                }
                if all(row_values[header] in (None, "") for header in REQUIRED_HEADERS):
                    continue
                try:
                    result.append(
                        BankRow(
                            operation_type=_cell_text(row_values["Тип операции"]),
                            operation_date=parse_date(row_values["Дата проведения"]),
                            doc_number=_cell_text(row_values["Номер документа"]),
                            amount=parse_amount(row_values["Сумма в валюте счёта"]),
                            description=_cell_text(row_values["Описание операции"]),
                            payment_purpose=_cell_text(
                                row_values["Назначение платежа"]
                            ),
                            counterparty_name=_cell_text(
                                row_values["Наименование контрагента"]
                            ),
                            counterparty_inn=_cell_text(row_values["ИНН контрагента"]),
                        )
                    )
                except BankImportError as error:
                    raise BankImportError(
                        f"invalid statement row {row_number}"
                    ) from error
            return result
    finally:
        workbook.close()

    raise BankImportError("required columns not found")


def source_hash(row: BankRow) -> str:
    canonical = (
        f"{row.operation_date.isoformat()}|{row.amount.quantize(MONEY_QUANTUM):.2f}|"
        f"{row.doc_number.strip()}|{row.counterparty_inn.strip()}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mask_inn(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if len(normalized) <= 4:
        return "*" * len(normalized)
    return "*" * (len(normalized) - 4) + normalized[-4:]


def _contains(text: str, *needles: str) -> bool:
    folded = text.casefold()
    return any(needle.casefold() in folded for needle in needles)


def classify_transaction(row: BankRow) -> ClassificationResult:
    operation_type = row.operation_type.strip().casefold()
    purpose = row.payment_purpose
    description = row.description
    counterparty = row.counterparty_name

    if operation_type == "кредит":
        if _contains(purpose, "перевод собственных средств", "возврат"):
            return ClassificationResult("income", None, None, False, True)
        if _contains(purpose, "акарицид", "клещ"):
            return ClassificationResult(
                "income", "Обработка от клещей", "Прочее", False, False
            )
        if _contains(purpose, "химчистк"):
            return ClassificationResult("income", "Химчистка", "Прочее", False, False)
        if _contains(purpose, "дератизац"):
            return ClassificationResult("income", "Дератизация", "Прочее", False, False)
        if _contains(purpose, "дезинфекц"):
            return ClassificationResult("income", "Дезинфекция", "Прочее", False, False)
        if _contains(purpose, "дезинсекц", "таракан", "клоп"):
            return ClassificationResult("income", "Дезинсекция", "Прочее", False, False)
        if row.counterparty_inn.strip():
            return ClassificationResult(
                "income", "Юридические клиенты", "Прочее", True, False
            )
        return ClassificationResult("income", "Другие работы", None, True, False)

    if operation_type == "дебет":
        if _contains(purpose, "перевод собственных средств"):
            return ClassificationResult("expense", None, None, False, True)
        if _contains(counterparty, "медилис") or _contains(description, "дез средства"):
            return ClassificationResult(
                "expense", "Материалы и химия", None, False, False
            )
        if _contains(f"{purpose} {description}", "енс", "фнс", "взносы"):
            return ClassificationResult(
                "expense", "Налоги и взносы", None, False, False
            )
        if _contains(counterparty, "тбанк") or _contains(
            f"{purpose} {description}", "комиссия", "sms", "обслуживание"
        ):
            return ClassificationResult(
                "expense", "Банковские комиссии", None, False, False
            )
        return ClassificationResult("expense", None, None, True, False)

    raise BankImportError("unsupported operation type")


def transaction_comment(row: BankRow) -> str:
    return row.payment_purpose.strip() or row.description.strip()
