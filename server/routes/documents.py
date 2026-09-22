"""Document-related routes."""
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from server.config import AWS_REGION, PDF_DIR, S3_BUCKET_NAME
from server.database.database import SessionLocal
from server.database.medicine_database import MedicineSessionLocal
from server.database.medicine_models import MedicineRegulatoryDocument, MedicineRegulatoryEvent
from server.database.models import Document

router = APIRouter(prefix="/api", tags=["documents"])


def _parse_cdsco_date(s: str) -> datetime:
    """Parse CDSCO's release_date format 'YYYY-Mon-DD' into a datetime."""
    return datetime.strptime(s, "%Y-%b-%d")


def _date_sort_key(d: Document) -> datetime:
    try:
        return _parse_cdsco_date(d.release_date)
    except (ValueError, TypeError):
        return datetime.min


@router.get("/documents")
def list_documents():
    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        docs.sort(key=lambda d: d.document_id)
        docs.sort(key=_date_sort_key, reverse=True)
        return {
            "count": len(docs),
            "documents": [
                {
                    "id": d.id,
                    "document_id": str(d.document_id),
                    "source": d.source,
                    "source_key": d.source_key,
                    "document_type": d.document_type,
                    "metadata": d.source_metadata,
                    "title": d.title,
                    "release_date": d.release_date,
                    "status": d.status,
                    "file_size_bytes": d.file_size_bytes,
                    "pdf_url": d.pdf_url,
                    "local_file_path": d.local_file_path,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in docs
            ],
        }
    finally:
        db.close()


@router.get("/documents/{document_id}")
def get_document(document_id: int):
    db = SessionLocal()
    try:
        d = db.query(Document).filter(Document.document_id == document_id).first()
        if not d:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "document_id": str(d.document_id),
            "source": d.source,
            "source_key": d.source_key,
            "document_type": d.document_type,
            "metadata": d.source_metadata,
            "title": d.title,
            "release_date": d.release_date,
            "status": d.status,
            "pdf_url": d.pdf_url,
            "local_file_path": d.local_file_path,
            "file_size_bytes": d.file_size_bytes,
            "content_hash": d.content_hash,
        }
    finally:
        db.close()


def _remove_local_files(document_id: int, local_file_path: str | None) -> None:
    candidates = {PDF_DIR / f"{document_id}.pdf"}
    if local_file_path:
        candidate = Path(local_file_path)
        try:
            if candidate.resolve().is_relative_to(PDF_DIR.resolve()):
                candidates.add(candidate)
        except ValueError:
            pass
    for path in candidates:
        path.unlink(missing_ok=True)


def _remove_s3_object(object_key: str | None, pdf_url: str | None = None) -> bool:
    if not object_key and pdf_url and not pdf_url.startswith(("http://", "https://")):
        object_key = pdf_url.removeprefix("s3://").split("/", 1)[-1]
    if not S3_BUCKET_NAME or not object_key:
        return False
    boto3.client("s3", region_name=AWS_REGION).delete_object(
        Bucket=S3_BUCKET_NAME,
        Key=object_key,
    )
    return True


@router.delete("/documents/{document_id}")
def delete_document(document_id: int):
    db = SessionLocal()
    medicine_db = MedicineSessionLocal()
    try:
        document = db.query(Document).filter(Document.document_id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        s3_deleted = _remove_s3_object(document.s3_object_key, document.pdf_url)
        _remove_local_files(document_id, document.local_file_path)

        deleted_events = medicine_db.query(MedicineRegulatoryEvent).filter(
            MedicineRegulatoryEvent.document_id == document_id
        ).delete(synchronize_session=False)
        deleted_normalized_document = medicine_db.query(MedicineRegulatoryDocument).filter(
            MedicineRegulatoryDocument.id == document_id
        ).delete(synchronize_session=False)
        medicine_db.commit()

        db.delete(document)
        db.commit()
        return {
            "deleted": True,
            "document_id": document_id,
            "deleted_events": deleted_events,
            "deleted_normalized_documents": deleted_normalized_document,
            "s3_deleted": s3_deleted,
        }
    except HTTPException:
        medicine_db.rollback()
        raise
    except Exception as exc:
        medicine_db.rollback()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {exc}") from exc
    finally:
        medicine_db.close()
        db.close()


@router.get("/static-pdf/{document_id}.pdf")
def serve_pdf(document_id: int):
    path = PDF_DIR / f"{document_id}.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(path), media_type="application/pdf")


@router.get("/documents/{document_id}/pdf")
def download_document_pdf(document_id: int):
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.document_id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        local_path = PDF_DIR / f"{document_id}.pdf"
        if local_path.exists():
            return FileResponse(
                str(local_path),
                media_type="application/pdf",
                filename=f"{document_id}.pdf",
            )

        object_key = document.s3_object_key
        if not object_key and document.pdf_url and not document.pdf_url.startswith(("http://", "https://")):
            object_key = document.pdf_url.removeprefix("s3://").split("/", 1)[-1]
        if not S3_BUCKET_NAME or not object_key:
            raise HTTPException(status_code=404, detail="PDF file not found")

        try:
            response = boto3.client("s3", region_name=AWS_REGION).get_object(
                Bucket=S3_BUCKET_NAME,
                Key=object_key,
            )
            content = response["Body"].read()
        except (BotoCoreError, ClientError) as exc:
            raise HTTPException(status_code=404, detail="PDF file not found in S3") from exc

        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{document_id}.pdf"'},
        )
    finally:
        db.close()
