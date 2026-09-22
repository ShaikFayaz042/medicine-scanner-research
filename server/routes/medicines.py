"""Scanner-oriented medicine identification endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.database.medicine_database import MedicineSessionLocal
from server.services.medicine_service import get_medicine as get_medicine_record
from server.services.medicine_service import search_medicines

router = APIRouter(prefix="/api/medicines", tags=["medicines"])


class MedicineSearchRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    manufacturer: str = Field(default="", max_length=200)
    ingredient: str = Field(default="", max_length=200)
    strength: str = Field(default="", max_length=100)
    dosage_form: str = Field(default="", max_length=100)
    limit: int = Field(default=50, ge=1, le=100)


def get_medicine_db():
    db = MedicineSessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/search")
def identify_medicines(request: MedicineSearchRequest, db=Depends(get_medicine_db)):
    fields = {
        key: value.strip().lower()
        for key, value in request.model_dump().items()
        if isinstance(value, str) and value.strip()
    }
    if not fields:
        return {"matches": [], "count": 0}

    matches = search_medicines(db, fields, request.limit)
    matches.sort(key=lambda match: (-match["relevance"], match["product"]["name"] or ""))
    return {"matches": matches, "count": len(matches)}


@router.get("/{medicine_id}")
def get_medicine(medicine_id: int, db=Depends(get_medicine_db)):
    medicine = get_medicine_record(db, medicine_id)
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return medicine
