"""Scan endpoints for authenticated mobile users."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import Field
from sqlalchemy.orm import Session

from server import config as server_config
from server import deps as server_deps
from server.database.medicine_database import MedicineSessionLocal
from server.database.mobile_models import Scan, User
from server.rate_limit import limiter
from server.schemas.common import CamelModel, Coordinates
from server.schemas.scans import MedicineFields
from server.services.medicine_service import search_medicines
from server.services.extraction import extract_fields

router = APIRouter(prefix="/scans", tags=["scans"])

MAX_RAW_TEXT = 20_000
MAX_BARCODE_PAYLOAD = 4_096


class MedicineResult(CamelModel):
    fields: MedicineFields
    status: Literal["safe", "unsafe", "unknown"]
    title: str
    message: str
    gtin: str = ""
    serial: str = ""
    query: dict[str, str | None] = Field(default_factory=dict)
    search_status: Literal["MATCHED", "NO_PRODUCT_MATCH"] = Field(
        default="NO_PRODUCT_MATCH", serialization_alias="search_status"
    )
    count: int = 0
    limit: int = 50
    has_more: bool = Field(default=False, serialization_alias="has_more")
    matches: list[dict] = Field(default_factory=list)


class TextScanRequest(CamelModel):
    raw_text: str = Field(min_length=1, max_length=MAX_RAW_TEXT)
    location: Coordinates | None = None
    method: Literal["ocr", "ocr_corrected"] = "ocr"


class BarcodeScanRequest(CamelModel):
    raw: str = Field(min_length=1, max_length=MAX_BARCODE_PAYLOAD)
    symbology: str = Field(default="", max_length=64)
    location: Coordinates | None = None
    method: Literal["barcode"] = "barcode"


class ManualEntryRequest(CamelModel):
    fields: MedicineFields
    gtin: str = Field(default="", max_length=14)
    serial: str = Field(default="", max_length=64)
    location: Coordinates | None = None
    method: Literal["manual", "ocr_corrected", "barcode_corrected"] = "manual"


class ScanHistoryEntry(CamelModel):
    id: str
    name: str
    dose: str = ""
    batch_number: str
    scanned_at: datetime
    status: Literal["safe", "unsafe", "unknown"]


_LABEL = re.compile(
    r"^(?:b\.?\s*no|batch(?:\s*(?:no|number))?|lot(?:\s*no)?)\s*(?:[.:\-]\s*|\s+)",
    re.IGNORECASE,
)
_DISALLOWED = re.compile(r"[^A-Z0-9\-/]")


def _normalise_batch_number(raw: str) -> str:
    if not raw:
        return ""
    value = raw.strip()
    for _ in range(2):
        stripped = _LABEL.sub("", value).strip()
        if stripped == value:
            break
        value = stripped
    value = _DISALLOWED.sub("", value.upper())
    return value[:64]


def _format_date(value):
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _decode_barcode(raw: str):
    from biip import ParseError, parse

    result = {"gtin": "", "batch_number": "", "exp_date": "", "mfd_date": "", "serial": ""}
    payload = raw.strip()
    if not payload:
        return result

    def _normalise(payload_value: str) -> str:
        if payload_value.startswith("]"):
            return payload_value[2:] if len(payload_value) > 2 else payload_value
        return payload_value

    try:
        parsed = parse(_normalise(payload))
    except (ParseError, ValueError):
        return result

    if parsed.gtin is not None:
        result["gtin"] = parsed.gtin.as_gtin_14()

    message = getattr(parsed, "gs1_message", None)
    if message is None:
        return result

    for element in getattr(message, "element_strings", []) or []:
        ai = getattr(getattr(element, "ai", None), "ai", "")
        value = element.value or ""
        if ai == "01" and value:
            result["gtin"] = value
        elif ai == "10":
            result["batch_number"] = value or ""
        elif ai == "21":
            result["serial"] = value or ""
        elif ai in {"15", "17"}:
            if ai == "17":
                result["exp_date"] = _format_date(getattr(element, "date", None))
        elif ai == "11":
            result["mfd_date"] = _format_date(getattr(element, "date", None))
    return result


def _resolve_verification(fields: MedicineFields, gtin: str = "", serial: str = "") -> MedicineResult:
    normalized_batch = _normalise_batch_number(fields.batch_number)
    gtin = (gtin or "").strip()
    result_fields = fields.model_copy(update={"batch_number": normalized_batch})
    query = {
        "name": result_fields.name.strip() or None,
        "manufacturer": None,
        "ingredient": result_fields.salt.strip() or None,
        "strength": result_fields.dose.strip() or None,
        "dosage_form": None,
        "batch_number": normalized_batch or None,
    }
    search_fields = {
        key: value.casefold()
        for key, value in query.items()
        if value
    }
    if search_fields:
        medicine_db = MedicineSessionLocal()
        try:
            lookup = search_medicines(medicine_db, search_fields, 50, query=query)
        finally:
            medicine_db.close()
    else:
        lookup = search_medicines(None, {}, 50, query=query)

    matched = lookup["matches"][0] if lookup["matches"] else None
    assessment = matched["assessment"] if matched else None
    is_restricted = bool(assessment and assessment["indicator"] == "RED")
    status_value = "unsafe" if is_restricted else "unknown"
    if not matched:
        title = "No product match"
        message = "No matching product was found in the indexed records. This does not establish whether the pack is authentic or safe."
    elif assessment["indicator"] == "RED":
        title = "Regulatory restriction recorded"
        message = assessment["summary"]
    elif assessment["indicator"] == "GREEN":
        title = "No indexed alert found"
        message = assessment["summary"]
    else:
        title = "Review regulatory records"
        message = assessment["summary"]

    return MedicineResult(
        fields=result_fields,
        status=status_value,
        title=title,
        message=message,
        gtin=gtin,
        serial=serial,
        **lookup,
    )


def _record_scan(
    db: Session,
    user_id: uuid.UUID,
    fields: MedicineFields,
    gtin: str,
    serial: str,
    method: str,
    location,
    raw_input: str | None,
) -> Scan:
    scan = Scan(
        id=uuid.uuid4(),
        user_id=user_id,
        method=method,
        status="unknown",
        created_at=datetime.now(timezone.utc),
        medicine_name=fields.name,
        salt=fields.salt,
        batch_number=_normalise_batch_number(fields.batch_number),
        mfd_date=fields.mfd_date,
        exp_date=fields.exp_date,
        dose=fields.dose,
        gtin=(gtin or "").strip(),
        serial=(serial or "").strip(),
        latitude=getattr(location, "latitude", None) if location else None,
        longitude=getattr(location, "longitude", None) if location else None,
        raw_input=raw_input,
    )
    db.add(scan)
    db.flush()
    return scan


def _persist_and_resolve_text_scan(
    db: Session,
    user: User,
    body: TextScanRequest,
    fields: MedicineFields,
) -> MedicineResult:
    scan = _record_scan(
        db, user.id, fields, "", "", body.method, body.location, body.raw_text
    )
    db.commit()
    result = _resolve_verification(fields)
    scan.status = result.status
    db.commit()
    return result


@router.post("/text", response_model=MedicineResult, status_code=status.HTTP_200_OK)
@limiter.limit(server_config.RATE_LIMIT_SCAN)
async def verify_text_scan(
    request: Request,
    body: TextScanRequest,
    db: Session = Depends(server_deps.get_mobile_db),
    user: User = Depends(server_deps.get_current_user),
) -> MedicineResult:
    fields = await extract_fields(body.raw_text)
    return await run_in_threadpool(_persist_and_resolve_text_scan, db, user, body, fields)


@router.post("/barcode", response_model=MedicineResult)
@limiter.limit(server_config.RATE_LIMIT_SCAN)
def verify_barcode_scan(
    request: Request,
    body: BarcodeScanRequest,
    db: Session = Depends(server_deps.get_mobile_db),
    user: User = Depends(server_deps.get_current_user),
) -> MedicineResult:
    decoded = _decode_barcode(body.raw)
    fields = MedicineFields(
        batch_number=decoded["batch_number"],
        exp_date=decoded["exp_date"],
        mfd_date=decoded["mfd_date"],
    )
    scan = _record_scan(
        db,
        user.id,
        fields,
        decoded["gtin"],
        decoded["serial"],
        body.method,
        body.location,
        body.raw,
    )
    db.commit()
    result = _resolve_verification(fields, gtin=decoded["gtin"], serial=decoded["serial"])
    scan.status = result.status
    db.commit()
    return result


@router.post("/manual", response_model=MedicineResult)
@limiter.limit(server_config.RATE_LIMIT_SCAN)
def verify_manual_entry(
    request: Request,
    body: ManualEntryRequest,
    db: Session = Depends(server_deps.get_mobile_db),
    user: User = Depends(server_deps.get_current_user),
) -> MedicineResult:
    scan = _record_scan(
        db,
        user.id,
        body.fields,
        body.gtin,
        body.serial,
        body.method,
        body.location,
        None,
    )
    db.commit()
    result = _resolve_verification(body.fields, gtin=body.gtin, serial=body.serial)
    scan.status = result.status
    db.commit()
    return result


@router.get("", response_model=list[ScanHistoryEntry])
def scan_history(
    db: Session = Depends(server_deps.get_mobile_db),
    user: User = Depends(server_deps.get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ScanHistoryEntry]:
    rows = (
        db.query(Scan)
        .filter(Scan.user_id == user.id)
        .order_by(Scan.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        ScanHistoryEntry(
            id=str(row.id),
            name=row.medicine_name or "Unknown medicine",
            dose=row.dose,
            batch_number=row.batch_number,
            scanned_at=row.created_at,
            status=row.status,
        )
        for row in rows
    ]


@router.get("/{scan_id}", response_model=MedicineResult)
def scan_result(
    scan_id: uuid.UUID,
    db: Session = Depends(server_deps.get_mobile_db),
    user: User = Depends(server_deps.get_current_user),
) -> MedicineResult:
    scan = (
        db.query(Scan)
        .filter(Scan.id == scan_id)
        .filter(Scan.user_id == user.id)
        .first()
    )
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    fields = MedicineFields(
        name=scan.medicine_name,
        salt=scan.salt,
        batch_number=scan.batch_number,
        mfd_date=scan.mfd_date,
        exp_date=scan.exp_date,
        dose=scan.dose,
    )
    return _resolve_verification(fields, gtin=scan.gtin, serial=scan.serial)
