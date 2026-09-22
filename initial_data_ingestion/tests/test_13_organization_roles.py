"""Regression tests for explicit product organization roles."""

from shared.extract import extract_record_lineage
from shared.resolve import resolve_record


def test_explicit_organization_roles_are_separated():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Imported Drug 10mg",
        "batch_number": "B-1",
        "manufactured_by": "Manufacturer Labs",
        "importer": "Importer Trading Co.",
        "applicant": "Applicant Healthcare",
        "marketing_authorization_holder": "Market Authorization Ltd.",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]
    resolved = resolve_record("DOC001", "NSQ_STATE", extracted)

    assert resolved["organization_roles"]["MANUFACTURER"]
    assert resolved["organization_roles"]["IMPORTER"]
    assert resolved["organization_roles"]["APPLICANT"]
    assert resolved["organization_roles"]["MARKETING_AUTHORIZATION_HOLDER"]