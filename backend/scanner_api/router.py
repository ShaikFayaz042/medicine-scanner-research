from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.scanner_api import service
from backend.scanner_api.schemas import (
    ErrorBody,
    ErrorResponse,
    ScanRequest,
    ScanResponse,
)

logger = logging.getLogger("scanner.router")

router = APIRouter(prefix="/api", tags=["scanner"])


@router.post(
    "/scan",
    response_model=ScanResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def scan(req: ScanRequest, db: Session = Depends(get_db)) -> ScanResponse:
    if not (req.medicine_name or req.barcode or req.active_ingredient):
        raise HTTPException(
            status_code=400,
            detail=ErrorBody(
                code="INVALID_INPUT",
                message="medicine_name, barcode, or active_ingredient is required.",
            ).model_dump(),
        )
    try:
        return service.run_scan(db, req)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Scan failed")
        raise HTTPException(
            status_code=500,
            detail=ErrorBody(
                code="INTERNAL_ERROR",
                message="Unable to complete regulatory search.",
            ).model_dump(),
        )