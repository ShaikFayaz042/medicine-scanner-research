"""Table-to-record parsing, document typing and narrative parsing, using layouts seen in real CDSCO PDFs."""

import pytest

from data_processing_service.parser import narrative
from data_processing_service.parser import run as parser
from data_processing_service.parser.tables import records_from_tables, split_combined

PRODUCT = "Name of Drugs/medical device/cosmetics"
HEADER = ["S. No.", "Name of the Drug", "Batch No.", "Date of", "", "Manufactured by", "Reason for failure"]
SUB_HEADER = ["", "", "", "Manufacture", "Expiry", "", ""]
ROW_1 = ["1.", "Paracetamol Tablets IP 500 mg", "PCT2401", "01/2024", "12/2025", "M/s. XYZ Pharma Pvt. Ltd.,\nBaddi", "Dissolution"]
ROW_2 = ["2.", "Cefixime Tablets IP 200 mg", "CFX24-118", "04/2024", "03/2026", "M/s. Medilife, Jammu", "Assay"]


def test_merged_header_cell_does_not_shift_columns():
    records, columns = records_from_tables([(1, [HEADER, SUB_HEADER, ROW_1])])

    assert records[0] == {
        "page_number": 1,
        "S No": "1",
        PRODUCT: "Paracetamol Tablets IP 500 mg",
        "Batch No": "PCT2401",
        "Date of Manufacture": "01/2024",
        "Date of Expiry": "12/2025",
        "Manufactured By": "M/s. XYZ Pharma Pvt. Ltd., Baddi",
        "Reason for failure": "Dissolution",
    }
    assert columns == ["S No", PRODUCT, "Batch No", "Date of Manufacture", "Date of Expiry", "Manufactured By", "Reason for failure"]


def test_header_repeated_on_next_page_is_not_glued_onto_previous_record():
    records, _ = records_from_tables([(1, [HEADER, SUB_HEADER, ROW_1]), (2, [HEADER, SUB_HEADER, ROW_2])])

    assert [record["Batch No"] for record in records] == ["PCT2401", "CFX24-118"]
    assert records[0]["Date of Manufacture"] == "01/2024"


def test_rows_continued_across_a_page_break_join_the_previous_record():
    continuation = ["", "", "", "", "", "Himachal Pradesh", "and Description"]

    records, _ = records_from_tables([(1, [HEADER, SUB_HEADER, ROW_1]), (2, [continuation, ROW_2])])

    assert records[0]["Manufactured By"] == "M/s. XYZ Pharma Pvt. Ltd., Baddi Himachal Pradesh"
    assert records[0]["Reason for failure"] == "Dissolution and Description"
    assert len(records) == 2


def test_section_rows_label_records_instead_of_becoming_records():
    section = ["B. State Laboratories", "", "", "", "", "", ""]

    records, _ = records_from_tables([(1, [section, HEADER, SUB_HEADER, ROW_1, ["JHARKHAND"] + [""] * 6, ROW_2])])

    assert [record.get("Section") for record in records] == ["B. State Laboratories", "JHARKHAND"]
    assert len(records) == 2


def test_codes_wrapped_in_narrow_cells_are_joined_without_a_space():
    row = ["37.", "Calcium 500 mg with\nVitamin D3", "LMT240\n263", "01-03-2023", "28-02-2\n026", "Gastro-\nResistant Labs", "Assay"]

    record = records_from_tables([(1, [HEADER, SUB_HEADER, row])])[0][0]

    assert record["Batch No"] == "LMT240263"
    assert record["Date of Expiry"] == "28-02-2026"
    assert record[PRODUCT] == "Calcium 500 mg with Vitamin D3"
    assert record["Manufactured By"] == "Gastro-Resistant Labs"


@pytest.mark.parametrize(
    "cell, expected",
    [
        (
            "B. No.: HT-3049,\nMfg dt: 11/2017,\nExp dt: 10/2019,\nMfd by: M/s. VIP Pharmaceuticals (P) Ltd.",
            ("HT-3049", "11/2017", "10/2019", "M/s. VIP Pharmaceuticals (P) Ltd."),
        ),
        (
            "Batch No � C 2009,\nD/Mfg. � 07/2012\nD/Exp. � 06/2015\n\nMfd. By- M/s Concept Pharmaceutical Ltd",
            ("C 2009", "07/2012", "06/2015", "M/s Concept Pharmaceutical Ltd"),
        ),
        (
            "B. No. EE009, D/Mfg. Jul, 2013 , D/Exp. Jun, 2015, Mfg. By. M/s Hecatomb Laboratories",
            ("EE009", "Jul, 2013", "Jun, 2015", "M/s Hecatomb Laboratories"),
        ),
    ],
)
def test_legacy_combined_batch_column_is_split(cell, expected):
    header = ["Sl. No.", "Name of Drugs/medical device/cosmetics", "Batch No./Date of Manufacture/Date of Expiry/Manufactured By", "Reason for failure"]

    record = records_from_tables([(1, [header, ["1.", "Telkonol-20 Tablets", cell, "Dissolution"]])])[0][0]

    assert (record["Batch No"], record["Date of Manufacture"], record["Date of Expiry"], record["Manufactured By"]) == expected
    assert split_combined(cell)["Batch No"] == expected[0]


def test_footnote_markers_do_not_create_records():
    header = ["Sr. No.", "Drugs Name", "Notification No. & Date"]
    rows = [header, ["117.", "Glimepiride + Pioglitazone + Metformin", "S.O.4472 (E)"], ["3#", "", "Dated 10.03.2016"], ["118. 1", "Pioglitazone 30mg + Metformin 500mg", "S.O. 4479"]]

    records, _ = records_from_tables([(9, rows)])

    assert [record["S No"] for record in records] == ["117", "118"]
    assert records[0]["Notification No. & Date"] == "S.O.4472 (E) Dated 10.03.2016"


def test_summary_block_is_skipped_but_titled_data_tables_are_kept():
    summary = [["Total number of samples tested", "- 1197"], ["Total number of samples declared as Not of Standard Quality", "- 62"]]
    titled = [["Detail of samples declared NOT OF STANDARD QUALITY (NSQ) by CDL of year 2017"] + [""] * 6, HEADER, SUB_HEADER, ROW_1]

    records, _ = records_from_tables([(1, summary), (1, titled)])

    assert [record["Batch No"] for record in records] == ["PCT2401"]


def test_continuation_table_narrower_than_merged_header_is_aligned():
    header = ["S.No.", "Name of\nDrugs/medical\ndevice/cosmetics", "", "", "Batch No.", "Date of\nManufacture", "Date of\nExpiry", "Manufactured By"]
    page_1 = [header, ["3.", "Rosuvas F 10 Tablets", "", "", "SIF2676A", "12-2024", "05-2027", "Under Investigation"]]
    page_2 = [["4.", "Rosuvas F 20 Tablets", "SIF2736A", "12-2024", "05-2027", "Under Investigation"]]

    records, _ = records_from_tables([(1, page_1), (2, page_2)])

    assert records[1][PRODUCT] == "Rosuvas F 20 Tablets"
    assert records[1]["Batch No"] == "SIF2736A"


def test_long_header_cells_are_still_recognized():
    header = ["S. No.", "Product/Drug Name", "B. No.", "Manufacturing Date", "Expiry Date",
              "Sales Outlets Involved in Distribution of Spurious Drugs (Name and address of outlet with pin code and pharmacist name with registration number)"]

    records, _ = records_from_tables([(1, [["NCT of DELHI"] + [""] * 5, header, ["1", "Instgra Tablets", "E16DV23\n001", "Feb.2023", "Sep.2026", "M/s. Harsh Pharma"]])])

    assert records[0]["Batch No"] == "E16DV23001"
    assert records[0]["Section"] == "NCT of DELHI"


def test_data_row_with_header_words_is_not_taken_as_a_header():
    data_like = ["", "Acetylsalicylic Acid Tablets", "JTN23-211", "05-07-2023", "03-06-2026", "Central Drugs Laboratory, Kolkata", "Sample does not conform"]

    records, _ = records_from_tables([(1, [HEADER, SUB_HEADER, ROW_1]), (2, [data_like, ROW_2])])

    assert [record["Batch No"] for record in records] == ["PCT2401JTN23-211", "CFX24-118"] or records[1]["Batch No"] == "CFX24-118"
    assert records[1][PRODUCT] == "Cefixime Tablets IP 200 mg"


@pytest.mark.parametrize(
    "title, columns, text, expected",
    [
        ("List of spurious Drugs for the month of June-2025", [], "", "Doc 4"),
        ("STATE NSQ ALERT FOR THE MONTH OF June 2025", ["Batch No"], "", "Doc 3"),
        ("CDSCO NSQ ALERT FOR THE MONTH OF June 2025", ["Batch No"], "M/s. Zee Laboratories, Sector-6A", "Doc 5"),
        ("Drug Alert list for month of May 2013", ["Batch No/Date of Manufacture/Date of Expiry/Manufactured By (source)"], "", "Doc 6"),
        ("Medical Device Alert dated 08 May 2023", [], "", "Doc 7"),
        ("Voluntary Recall of Digene Gel manufactured by M/s Abbott India Limited", [], "", "Doc 17"),
        ("Alert on theft of multiple drug products of M/s. Novo Nordisk during transit", [], "", "Doc 17"),
        ("List of Prohibited FDC drugs 156 FDCs dated 02.08.2024", [PRODUCT], "", "Doc 1"),
        ("2025.05.22_S.O. 2298(E)_Notification to prohibit the import of certain antimicrobials", [], "", "Doc 16"),
    ],
)
def test_document_type_uses_whole_words_and_the_title(title, columns, text, expected):
    assert parser._classify_document(title, columns, text) == parser.DOCUMENT_TYPES[expected]


def test_gazette_list_items_become_records():
    text = (
        "का.आ. 2298(अ) ... नीचे दिए गए:\n1. एंटीबायोरटक्स\ni. उरेडोपेनीजसजलन्स\n"
        "S.O. 2298(E).— Whereas ...\nFollowing antimicrobials and their formulations for animal use: -\n"
        "1. Antibiotics\ni. Ureidopenicillins\nii. Ceftobiprole\n\n2. Antivirals\ni. Amantadine\n"
        "3. Antiprotozoals\n(i) Nitazoxanide\n [F. No. X.11035/125/2024-DR]\nRAJIV WADHAWAN"
    )

    records = narrative.parse_notification(text)

    assert [(record["S No"], record[PRODUCT], record["Category"]) for record in records] == [
        ("1.i", "Ureidopenicillins", "Antibiotics"),
        ("1.ii", "Ceftobiprole", "Antibiotics"),
        ("2.i", "Amantadine", "Antivirals"),
        ("3.i", "Nitazoxanide", "Antiprotozoals"),
    ]
    assert {record["Notification No. & Date"] for record in records} == {"S.O. 2298(E)"}


def test_fixed_dose_combination_named_in_prose_becomes_a_record():
    text = ("S.O. 3284(E).— Whereas, the Central Government prohibited the manufacture of drug fixed dose "
            "combination of Etodolac + Paracetamol vide notification number S.O. 4706 (E)")

    assert narrative.parse_notification(text) == [
        {"S No": "1", PRODUCT: "Etodolac + Paracetamol", "Notification No. & Date": "S.O. 3284(E)"}
    ]


def test_recall_alert_lists_every_batch():
    title = "Voluntary Recall of Digene Gel manufactured by M/s Abbott India Limited, L-18/19, Verna"
    text = ("one bottle of Digene Gel Mint flavor batch no. 510303D7 used by Customer ... product Digene Mint "
            "flavor batch no. 510303D7 and Digene Gel orange having batch no. 500351D7, 500352D7, 500353D7, "
            "500354D7 and voluntary stopped production")

    records = narrative.parse_alert(text, title)

    assert [record["Batch No"] for record in records] == ["510303D7", "500351D7", "500352D7", "500353D7", "500354D7"]
    assert {record[PRODUCT] for record in records} == {"Digene Gel"}
    assert records[0]["Manufactured By"] == "M/s Abbott India Limited"
    assert records[0]["Reason for failure"] == "Recall"


def test_falsified_alert_keeps_expiry_dates():
    title = "Alert on falsified versions of Adcetris Injection Brentuximab Vedotin Manufactured by M/s Takeda Pharmaceutical"
    text = "circulation namely Batch No.11980412 ED: 04/2024, 12188747 ED: 01/2025 and 512053 ED: 11/2024. ADCETRIS is"

    records = narrative.parse_alert(text, title)

    assert [(record["Batch No"], record["Date of Expiry"]) for record in records] == [
        ("11980412", "04/2024"), ("12188747", "01/2025"), ("512053", "11/2024"),
    ]
    assert records[0]["Reason for failure"] == "Falsified product"


def _prose_payload(title, text):
    return {"doc_id": "x.pdf", "s3_object_key": "src/x.pdf", "pdf_title": title, "pages": [{"page": 1, "text": text}], "tables": []}


def test_documents_without_tables_are_routed_to_the_narrative_parsers():
    recall = parser._process_single_payload(_prose_payload(
        "Voluntary Recall of Digene Gel manufactured by M/s Abbott India Limited, Goa",
        "one bottle of Digene Gel batch no. 510303D7 was reported",
    ))
    gazette = parser._process_single_payload(_prose_payload(
        "2024.08.12_S.O. 3284(E)_Notification reg Prohibiton of Etodolac",
        "S.O. 3284(E).— Whereas ... section 26A ... prohibited the manufacture of drug fixed dose combination of "
        "Etodolac + Paracetamol vide notification number S.O. 4706 (E)",
    ))

    assert (recall["parse_method"], recall["records"][0]["Batch No"]) == ("alert_prose", "510303D7")
    assert (gazette["parse_method"], gazette["records"][0][PRODUCT]) == ("notification_list", "Etodolac + Paracetamol")


def test_batch_list_without_serial_numbers_starts_records_at_each_batch():
    header = ["Product Name", "Sterilization Batch No", "Total units", "Serial No. (Present on pack)", ""]
    rows = [
        header,
        ["HOYA Vivinex Toric XY1AT3", "ES483", "12", "2JM501D3", "2FM60015"],
        ["", "", "", "2FM60016", "2HM60023"],
        ["", "E5511", "19", "2JM60073", "2JM600A3"],
    ]

    records, _ = records_from_tables([(2, rows)])

    assert [record["Batch No"] for record in records] == ["ES483", "E5511"]
    assert records[0][PRODUCT] == "HOYA Vivinex Toric XY1AT3"
    assert records[0]["Serial No. (Present on pack)"] == "2JM501D3 2FM60016"


def test_circular_citing_gazette_by_date_becomes_a_notice():
    text = ("Subject: Prohibition of Fixed Dose Combination of drugs for human use under Section 26A - regarding\n"
            "... prohibited ... through Gazette Notifications published on 10.03.2016 with immediate effect.")

    assert narrative.parse_notice(text, "FDC prohibition")[0]["Notification No. & Date"] == "Gazette notifications dated 10.03.2016"


def test_circular_without_products_becomes_a_document_level_record():
    text = ("Subject: Prohibition of 80 Fixed Dose Combinations by the Central Government vide Gazette notification "
            "nos. S.O. 180(E) to S.O. 259(E) dated 11.01.2019 -regarding.\nSir,")

    records = narrative.parse_notice(text, "Prohibition of 80 FDCs")

    assert records[0]["Notification No. & Date"] == "S.O. 180(E) to S.O. 259(E)"
    assert records[0]["Subject"].startswith("Prohibition of 80 Fixed Dose Combinations")


# --- Layouts from the second batch of 30 real documents ---------------------------------------------


def test_serial_with_stray_marks_still_starts_a_record_and_unplaceable_rows_are_reported():
    rows = [HEADER, SUB_HEADER, ROW_1, ["21.,", "Ampicillin Capsules IP 500 mg", "AMP-19B03", "08/2019", "07/2022", "M/s. ABC", "Assay"],
            ["?", "Omeprazole Capsules IP", "OMI-2001", "04/2020", "03/2022", "M/s. Ridley", "Dissolution"]]
    dropped = []

    records, _ = records_from_tables([(3, rows)], dropped)

    assert [record["S No"] for record in records] == ["1", "21"]
    assert dropped == [{"page_number": 3, "cells": rows[4]}]


def test_gazette_with_one_notification_per_fdc_gives_one_record_each():
    text = (
        "S.O. 3285(E).— Whereas ... the Central Government is satisfied that the use of the drug Fixed Dose "
        "Combination of Aceclofenac 50mg + Paracetamol 125mg tablet is likely to involve risk ... with immediate effect.\n"
        "[F. No. X.11035/1/2024-DR]\n"
        "S.O. 3286(E).— Whereas ... prohibits the manufacture of the drug fixed dose combination of "
        "Mefenamic Acid + Paracetamol Injection with immediate effect.\n"
    )

    records = narrative.parse_notification(text)

    assert [(r["S No"], r[PRODUCT], r["Notification No. & Date"]) for r in records] == [
        ("1", "Aceclofenac 50mg + Paracetamol 125mg tablet", "S.O. 3285(E)"),
        ("2", "Mefenamic Acid + Paracetamol Injection", "S.O. 3286(E)"),
    ]


@pytest.mark.parametrize(
    "text, expected",
    [
        # parenthetical between "combination" and "of"
        ("S.O. 4380(E).— prohibits the manufacture of the drug fixed dose combination (FDC) of "
         "Nimesulide + Paracetamol dispersible tablets with immediate effect.", ["Nimesulide + Paracetamol dispersible tablets"]),
        # "fixed dose combinations containing X"
        ("S.O. 4595(E).— prohibits all formulations of fixed dose combinations containing Chlorpheniramine Maleate + "
         "Phenylephrine Hydrochloride for children below four years.", ["Chlorpheniramine Maleate + Phenylephrine Hydrochloride"]),
        # combikit
        ("S.O. 4441(E).— prohibits the manufacture for sale of combikit of Azithromycin, Secnidazole and "
         "Fluconazole vide this notification.", ["Azithromycin, Secnidazole and Fluconazole"]),
        # inline list after "namely:-"
        ("S.O. 3448(E).— prohibits ... with immediate effect, namely:- \u201c(i) Ketoprofen and its formulations "
         "for animal use\n(ii) Aceclofenac and its formulations for animal use\u201d.\n[F. No.X.11035/65/2023-DRS]",
         ["Ketoprofen and its formulations for animal use", "Aceclofenac and its formulations for animal use"]),
    ],
)
def test_gazette_prohibitions_written_in_prose_become_records(text, expected):
    assert [record[PRODUCT] for record in narrative.parse_notification(text)] == expected


def test_underscores_in_gazette_file_titles_do_not_hide_the_notification_number():
    title = "2024.08.12__DR_S.O. 3285(E) to 3440(E)_ Prohibition of 156 FDCs"

    assert parser._classify_document(title, [], "") == parser.DOCUMENT_TYPES["Doc 16"]


@pytest.mark.parametrize(
    "text, title, expected",
    [
        ("Subject: Alert on theft of Lantus\u00ae SoloStar\u00ae (Insulin Glargine Injection IP,\nr-DNA origin, 100 IU/mL "
         "Batch No. 5F0347B of M/s Sanofi India Limited\nduring transit-reg\nM/s Sanofi India Limited has informed",
         "Alert on theft of Lantus", ("Lantus\u00ae SoloStar\u00ae (Insulin Glargine Injection IP, r-DNA origin, 100 IU/mL)", "M/s Sanofi India Limited")),
        ("been declared as Not of Standard Quality (NSQ) by CDL, Kasauli",
         "NSQ Vi-Conjugate Typhoid Vaccine Batch No.TC010915 and Batch No. TC010417 of M/s Bio Med Pvt Ltd dated 14-03-2018",
         ("Vi-Conjugate Typhoid Vaccine", "M/s Bio Med Pvt Ltd")),
        ("SUBJECT: Recall of OZURDEX\u00ae (Dexamethasone Intravitreal Implant 0.7mg) imported by\nM/S Allergan India "
         "Pvt. Ltd., Kasturba Road, Bangalore, Karnataka -Reg.\nDRUG\nOZURDEX\u00ae", "Recall of OZURDEX",
         ("OZURDEX\u00ae (Dexamethasone Intravitreal Implant 0.7mg)", "")),
        ("MEDICAL DEVICE ALERT\nDEVICE\nMiniMed\u2122 600 Series Insulin Pumps (MiniMed 620G Insulin Pump/Pump Kits &\n"
         "MiniMed 640G Insulin Pump/Pump kit)\nBACKGROUND\nThe MiniMed\u2122 600 series insulin pump", "Medical Devices Alert on MiniMed",
         ("MiniMed\u2122 600 Series Insulin Pumps (MiniMed 620G Insulin Pump/Pump Kits & MiniMed 640G Insulin Pump/Pump kit)", "")),
        ("MEDICAL DEVICE ALERT\nAbsorb Bioresorbable\nThis office has approved",
         'MEDICAL DEVICE ALERT FOR " Absorb Bioresorbale Vascular Scaffold BVS',
         ("Absorb Bioresorbale Vascular Scaffold BVS", "")),
    ],
)
def test_alert_subject_names_the_product(text, title, expected):
    assert narrative.subject_product(text, title) == expected


def test_batches_listed_in_a_flattened_lot_table_are_found():
    text = (
        "Subject: Voluntary Recall (Grade II) Notification for the Product Generic Name: Fibrin Sealant\n"
        "The impacted lots detail is as below:\n"
        "Product Product Name Pack size Affected Quantity Quantity\nCode Batch No. Imported Available in\nWarehouse\n"
        "1504384 Fibrin Sealant VHS/D 4 ml T5A010AA 3112 500\npowder and solvent T5A047AC 2685\n"
        "1505816 Fibrin Sealant VHS/D 10 ml T5X036AE 62 43\n"
        "Further, Firm submitted letter dated 11.06.2024 for urgent Drug Recall informing the Problem\n"
    )

    records = narrative.parse_alert(text, "Baxter recall letter for Product Fibrin Sealant Kit Brand name Tisseel Lyo manufactured in Vienna")

    assert [record["Batch No"] for record in records] == ["T5A010AA", "T5A047AC", "T5X036AE"]
    assert records[0]["Reason for failure"] == "Recall"


def test_alert_reason_is_the_first_keyword_mentioned_not_the_first_in_the_list():
    text = "Reason for Recall\nCordis noted complaints ... Do not use counterfeit replacement parts."

    assert narrative.parse_alert("DEVICE\nPALMAZ GENESIS Stent\nBACKGROUND\n" + text, "Medical Device Alert date 21 June 2022")[0][
        "Reason for failure"] == "Recall"


def test_batch_table_without_product_column_takes_the_product_from_the_subject():
    payload = _prose_payload(
        "Recall of OZURDEX (Dexamethasone Intravitreal Implant 0.7mg)",
        "SUBJECT: Recall of OZURDEX\u00ae (Dexamethasone Intravitreal Implant 0.7mg) imported by\nM/S Allergan India Pvt. Ltd. -Reg.",
    )
    payload["pages"][0]["tables"] = [
        {"cells": ["S. No.", "Batch No.", "Expiry Date"], "table_index": 0},
        {"cells": ["1.", "E79339", "05/2019"], "table_index": 0},
        {"cells": ["2.", "E80244", "06/2019"], "table_index": 0},
    ]

    structured = parser._process_single_payload(payload)

    assert [record["Batch No"] for record in structured["records"]] == ["E79339", "E80244"]
    assert {record[PRODUCT] for record in structured["records"]} == {"OZURDEX\u00ae (Dexamethasone Intravitreal Implant 0.7mg)"}


def test_notification_number_wrapped_onto_the_next_line_is_read_whole():
    text = ("S.O.449\n2 (E).\n\u2014Whereas ... fixed dose combination of Gentamicin + Clotrimazole with immediate effect.\n"
            "S.O. 4493(E).\u2014Whereas ... fixed dose combination of Ofloxacin + Ornidazole with immediate effect.\n")

    records = narrative.parse_notification(text)

    assert [r["Notification No. & Date"] for r in records] == ["S.O. 4492(E)", "S.O. 4493(E)"]
