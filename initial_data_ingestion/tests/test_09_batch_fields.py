"""Regression tests for combined batch/date/manufacturer source fields."""

from shared.extract import extract_record_lineage


def test_combined_batch_field_is_split_into_structured_values():
    record = {
        "page_number": 1,
        "table_number": 1,
        "product_name": "Telmirid-40 (Telmisartan Tablets I.P. 40 mg)",
            "batch_number": "B. No.: RT220651 Mfg dt: 08/2022 Exp dt: 07/2024 Mfd by: M/s. Ridley Life Sciences Pvt. Ltd., D- 1651, Delhi",
        "Batch No/Date of Manufacture/Date of Expiry/Manufactured By": (
            "B. No.: RT220651 Mfg dt: 08/2022 Exp dt: 07/2024 "
            "Mfd by: M/s. Ridley Life Sciences Pvt. Ltd., D- 1651, Delhi"
        ),
    }

    extracted = extract_record_lineage("DOC001", [record])[0]

    assert extracted["batch_number"] == "RT220651"
    assert extracted["manufacturing_date"] == "08/2022"
    assert extracted["expiry_date"] == "07/2024"
    assert extracted["manufacturer_name"] == "Ridley Life Sciences Pvt. Ltd."
    assert extracted["manufacturer_address"] == "D- 1651, Delhi"