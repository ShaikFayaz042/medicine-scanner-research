from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


Color = Literal["RED", "YELLOW", "GREEN"]
Severity = Literal["HIGH", "MEDIUM", "LOW"]
MatchType = Literal["EXACT", "FUZZY", "MULTIPLE", "NONE"]


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    medicine_name: Optional[str] = None
    batch_number: Optional[str] = None
    active_ingredient: Optional[str] = None
    expiry_date: Optional[str] = None
    barcode: Optional[str] = None


class ResultBlock(BaseModel):
    color: Color
    status: str
    severity: Severity
    title: str


class MatchBlock(BaseModel):
    type: MatchType
    confidence: float = 0.0


class MedicineBlock(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    ingredient: Optional[str] = None
    dosage_form: Optional[str] = None
    manufacturer: Optional[str] = None


class BatchBlock(BaseModel):
    id: Optional[int] = None
    number: Optional[str] = None
    manufacturing_date: Optional[str] = None
    expiry_date: Optional[str] = None


class RegulatoryBlock(BaseModel):
    event_type: Optional[str] = None
    status: Optional[str] = None
    scope: Optional[str] = None
    action: Optional[str] = None
    reason: Optional[str] = None
    legal_status: Optional[str] = None
    effective_date: Optional[str] = None
    investigation_status: Optional[str] = None
    legal_reference: Optional[str] = None


class GovernmentStatementBlock(BaseModel):
    authority: Optional[str] = None
    summary: Optional[str] = None
    reference: Optional[str] = None


class SourceBlock(BaseModel):
    document_id: Optional[int] = None
    document_type: Optional[str] = None
    title: Optional[str] = None
    publication_date: Optional[str] = None
    pdf_filename: Optional[str] = None
    pdf_url: Optional[str] = None


class MatchItem(BaseModel):
    regulatory: RegulatoryBlock = Field(default_factory=RegulatoryBlock)
    government_statement: GovernmentStatementBlock = Field(
        default_factory=GovernmentStatementBlock
    )
    source: SourceBlock = Field(default_factory=SourceBlock)


class CandidateItem(BaseModel):
    product_id: int
    name: str
    manufacturer: Optional[str] = None
    score: float = 0.0


class SafetyBlock(BaseModel):
    assessment: Optional[str] = None
    message: Optional[str] = None


class ScanResponse(BaseModel):
    result: ResultBlock
    match: MatchBlock
    medicine: MedicineBlock = Field(default_factory=MedicineBlock)
    batch: BatchBlock = Field(default_factory=BatchBlock)
    matches: List[MatchItem] = Field(default_factory=list)
    candidates: List[CandidateItem] = Field(default_factory=list)
    safety: SafetyBlock = Field(default_factory=SafetyBlock)


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody