"""Scanner-oriented medicine identification endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from server.database.medicine_database import MedicineSessionLocal
from server.services.medicine_service import get_medicine as get_medicine_record
from server.services.medicine_service import search_medicines

router = APIRouter(prefix="/api/medicines", tags=["medicines"])


class MedicineSearchRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    ingredient: str | None = Field(default=None, max_length=200)
    strength: str | None = Field(default=None, max_length=100)
    dosage_form: str | None = Field(default=None, max_length=100)
    batch_number: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("name", "manufacturer", "ingredient", "strength", "dosage_form", "batch_number")
    @classmethod
    def normalize_search_value(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_search_field(self):
        search_fields = (
            self.name,
            self.manufacturer,
            self.ingredient,
            self.strength,
            self.dosage_form,
            self.batch_number,
        )
        if not any(search_fields):
            raise ValueError("At least one non-empty search field is required")
        return self


def get_medicine_db():
    db = MedicineSessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/search")
def identify_medicines(request: MedicineSearchRequest, db=Depends(get_medicine_db)):
    query = request.model_dump(exclude={"limit"})
    fields = {key: value.casefold() for key, value in query.items() if value}
    return search_medicines(db, fields, request.limit, query=query)


@router.get("/{medicine_id}")
def get_medicine(medicine_id: int, db=Depends(get_medicine_db)):
    medicine = get_medicine_record(db, medicine_id)
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")
    return medicine
