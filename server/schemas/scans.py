"""Schemas shared by the scan routes and OCR extraction service."""

from server.schemas.common import CamelModel


class MedicineFields(CamelModel):
    name: str = ""
    salt: str = ""
    batch_number: str = ""
    mfd_date: str = ""
    exp_date: str = ""
    dose: str = ""