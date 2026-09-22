"""Regression tests for organization name and address normalization."""

from shared.extract import extract_record_lineage


def test_organization_address_is_separated_from_name():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Test product",
        "batch_number": "B-1",
        "manufactured_by": (
            "M/s. Ridley Life Sciences Pvt. Ltd., D- 1651, DSIDC, "
            "Indl. Complex, Narela, Delhi 110 040."
        ),
        "reporting_organization": "CDSCO, East Zone Kolkata",
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert extracted["manufacturer_name"] == "Ridley Life Sciences Pvt. Ltd."
    assert extracted["manufacturer_address"].startswith("D- 1651")
    assert extracted["reporting_organization_name"] == "CDSCO, East Zone Kolkata"
    assert extracted["reporting_organization_address"] == ""