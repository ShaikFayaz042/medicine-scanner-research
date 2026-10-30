"""Stage 5: rule matching, escalation and the LLM fallback, on layouts and wording seen in CDSCO PDFs."""

from __future__ import annotations

import pytest

from conftest import build_document
from idp.models.llm import LLMError
from idp.schemas.taxonomy import UnitSettings
from idp.stages.classifier.llm_fallback import FileCache
from idp.stages.classifier.service import output_name
from idp.stages.classifier.units import paragraph_units


def _table(header, rows=None, title="Test document", pages=(1,), caption=None):
    table = {"table_id": "t1", "pages": list(pages), "header_rows": [header], "rows": rows or [["1", "x"]]}
    if caption:
        table["caption"] = caption
    return build_document(tables=[table], title=title, pages=max(pages))


def _only_unit(result, kind):
    units = [u for u in result.units if u.kind == kind]
    assert len(units) == 1, [u.unit_id for u in result.units]
    return units[0]


# ------------------------------------------------------------------------------------------- tables
@pytest.mark.parametrize(
    "header, expected",
    [
        (["S.N o", "Name of Drugs/medical device/cosmetics", "Batch No.", "Date of Manufa cture", "Date of Expiry",
          "Manufactured By", "Reason for failure", "Drawn By (From state/CDSCO Zone)", "From (Name of Laboratory)"], "A"),
        (["S.No", "Name of the Drug", "Batch No./Date of Manufacture/Date of Expiry/Manufactured By",
          "Reason for failure", "Drawn By", "From"], "A"),
        (["Sr. No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date", "Manufactured By",
          "NSQ Result", "Reported by State Laboratory"], "B"),
        (["S. No.", "Name of the FDC", "Strength", "Dosage Form", "Notification No. & Date"], "K"),
        (["S. No.", "Issue Date", "Suspected Drugs", "Indication(s)", "Adverse Drug Reactions"], "Z"),
        (["Sr. No", "Medical Device Name", "Intended Use", "Risk Class"], "D"),
        (["S.No.", "Name of the Firm", "Type of Kit", "Country of Origin"], "M"),
        (["S.No", "Name of the Vaccine", "Strain", "Source of the Strain", "Dosage Form", "Indication", "Permission No",
          "Name of the Importer/Manufacturer with Address"], "J"),
        (["Sr. No", "Name of Drug", "BCS", "Product", "Name of Drug/Company/Trade Name"], "AE"),
        (["S.No", "Indian Agent", "Legal Manufacturer", "Registration No", "Validity"], "AU"),
        (["S.No", "File No", "Name of the Company and Address", "Product Name", "Intended Use", "Regulatory Status",
          "Date of Issue"], "E"),
        (["Rule No", "Subject", "Fee (INR)", "Fee (USD)"], "G"),
    ],
)
def test_table_headers_identify_their_archetype(classifier, header, expected):
    unit = _only_unit(classifier.classify(_table(header)), "table")

    assert unit.status == "classified"
    assert [label.label for label in unit.labels] == [expected]
    label = unit.labels[0]
    assert label.method == "rule" and label.layout_id.startswith(f"{expected}.")
    assert {e.kind for e in label.evidence} >= {"header_match"}


def test_spurious_table_needs_its_title_to_be_told_from_an_nsq_table(classifier):
    header = ["S.No", "Name of Drugs/medical device/cosmetics", "Batch No.", "Date of Manufacture", "Date of Expiry",
              "Manufactured By", "Reason for failure", "Drawn By", "Firm's reply", "Remarks"]

    untitled = _only_unit(classifier.classify(_table(header, title=None)), "table")
    titled = _only_unit(classifier.classify(_table(header, title="List of Drugs declared as Spurious for November 2024")), "table")

    assert untitled.status == "needs_review" and untitled.escalation.reasons == ["rule_conflict"]
    assert [label.label for label in titled.labels] == ["C"]
    assert any(e.kind == "context_cue" for e in titled.labels[0].evidence)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("List of Prohibited FDC drugs 156 FDCs dated 02.08.2024", "K"),
        ("Drugs banned in the country", "AR"),
    ],
)
def test_drug_and_notification_list_is_told_apart_by_its_title(classifier, title, expected):
    # The published lists (12087, banneddrugs.pdf) share the same three columns.
    unit = _only_unit(classifier.classify(_table(["S. No.", "Drugs Name", "Notification No. & Date"], title=title)), "table")

    assert [label.label for label in unit.labels] == [expected]


def test_2025_cdsco_laboratory_alert_is_a_not_b(classifier):
    header = ["S.No", "Product/Drug Name", "Batch No.", "Manufact uring Date", "Expiry Date", "Manufactured By",
              "NSQ Result", "Reported by CDSCO Laboratory"]

    unit = _only_unit(classifier.classify(_table(header, title="CDSCO NSQ ALERT FOR THE MONTH OF June 2025")), "table")

    assert unit.labels[0].layout_id == "A.nsq_result"


def test_header_below_a_section_row_is_found_when_stage_4_delivered_none(classifier):
    document = build_document(tables=[{"table_id": "t1", "header_rows": [], "rows": [
        ["NCT of DELHI", "", "", "", "", "", "", ""],
        ["S.No", "Product/Drug Name", "Batch No.", "Manufacturing Date", "Expiry Date", "Manufactured By", "NSQ Result",
         "Reported by State Laboratory"],
        ["1.", "Paracetamol Tablets", "PCT1", "01/2024", "12/2025", "M/s X", "Assay", "DTL Delhi"],
    ]}], title="STATE NSQ ALERT FOR THE MONTH OF APRIL 2024")

    label = _only_unit(classifier.classify(document), "table").labels[0]

    assert label.label == "B" and label.evidence[0].detail["header_source"] == "body_row_1"


def test_state_section_row_marks_a_state_alert_on_the_cdsco_template(classifier):
    # 11373 (NSQ May 2024, State Labs) reuses the CDSCO header, even 'Reported by CDSCO Laboratory'.
    header = ["S.No", "Name of Drugs/medical device/cosmetics", "Batch No.", "Date of Manufacture", "Date of Expiry",
              "Manufactured By", "NSQ Result", "Reported by CDSCO Laboratory"]
    document = build_document(tables=[{"table_id": "t1", "header_rows": [], "rows": [
        ["B. STATE LABORATORIES", "", "", "", "", "", "", ""], header,
        ["1.", "Cyra Tablets", "CA21868", "07/2023", "06/2025", "M/s Mepro", "NOT OF STANDARD QUALITY", "DCL Telangana"],
    ]}], title="NSQ May 2024")

    assert _only_unit(classifier.classify(document), "table").labels[0].label == "B"


def test_title_alone_never_classifies_a_table(classifier):
    unit = _only_unit(classifier.classify(_table(["Col 1", "Col 2"], title="Banned drugs in the country")), "table")

    assert unit.labels == [] and unit.status == "needs_review"
    assert unit.escalation.reasons == ["no_rule_match"]


def test_table_spanning_pages_is_one_unit(classifier):
    result = classifier.classify(_table(["Sr. No", "Drugs Name", "Notification No"], rows=[["1", "A", "S.O. 1"], ["2", "B", "S.O. 2"]],
                                        pages=(1, 2), title="Drugs banned in the country"))

    unit = _only_unit(result, "table")
    assert unit.source.pages == [1, 2] and unit.labels[0].label == "AR"


def test_mixed_record_tables_are_flagged_for_the_parser(classifier):
    spurious = ["S.No", "Name of Drugs/medical device/cosmetics", "Batch No.", "Date of Manufacture", "Date of Expiry",
                "Manufactured By", "Reason for failure", "Drawn By", "Firm's reply", "Remarks"]
    c_unit = _only_unit(classifier.classify(_table(spurious, title="List of spurious drugs")), "table")
    z_unit = _only_unit(classifier.classify(_table(["S. No.", "Issue Date", "Suspected Drugs", "Indication(s)", "Adverse Drug Reactions"])), "table")

    assert c_unit.requires_record_split and "REC-C-SPLIT" in c_unit.labels[0].record_rule_ids
    assert not z_unit.requires_record_split and z_unit.labels[0].record_rule_ids == []


# ------------------------------------------------------------------------------------------- paragraphs
PROHIBITION = ("S.O. 4595(E).- In exercise of the powers conferred by section 26A of the Drugs and Cosmetics Act, 1940, the "
               "Central Government hereby prohibits the manufacture for sale, sale and distribution of the fixed dose "
               "combination of Chlorpheniramine Maleate + Phenylephrine Hydrochloride with immediate effect.")


@pytest.mark.parametrize(
    "text, expected, legal",
    [
        ("Sample of Amoxycillin Capsules IP 500 mg, Batch No. AMX123, purported to be manufactured by M/s ABC Pharma, "
         "was declared spurious by the Government Analyst on test.", "P1", None),
        ("The following sample has been declared Not of Standard Quality: Paracetamol Tablets IP, Batch No. PCT2401, "
         "manufactured by M/s XYZ Pharma, failed in Dissolution.", "P2", None),
        (PROHIBITION, "P3", "final_or_effective_explicitly_stated"),
        ("The Central Government hereby restricts the fixed dose combination of Chlorpheniramine Maleate + Phenylephrine "
         "Hydrochloride, which shall not be used in children below four years of age.", "P3b", None),
        ("FDCs listed under Category 'C' are permitted for continued manufacturing and marketing under the 18 months "
         "policy, subject to the conditions specified by the expert committee.", "P3c", None),
        ("M/s Abbott India Limited has initiated a voluntary recall of Digene Gel Mint flavour, Batch No. 510303D7, "
         "from the market after complaints about taste and smell.", "P5", None),
        ("WHO Medical Product Alert: falsified DEFITELIO (defibrotide) 80 mg/ml concentrate, Batch 20G20A, has been "
         "identified in India and reported to the World Health Organization.", "P6", None),
        ("The Pharmacovigilance Programme of India (PvPI) has issued a drug safety alert: the suspected drug "
         "Ceftriaxone is associated with the adverse drug reaction DRESS syndrome.", "P7", None),
        ("In the country-wide survey, 24,000 samples were collected from retail outlets and the brand-wise results "
         "show that most samples were genuine and of standard quality.", "P19", None),
        ("Minutes of the meeting of the Drugs Consultative Committee held on 12 May 2023 at New Delhi. Members present "
         "are listed in Annexure I.", "P24", "administrative_or_informational"),
        ('Corrigendum: In the notification G.S.R. 102(E) dated 2nd February 2017, for "thirty days", read "sixty days".',
         "P27", "corrected"),
        ("The following draft of certain rules further to amend the Drugs Rules, 1945 is hereby published for the "
         "information of all persons likely to be affected thereby; objections and suggestions may be sent within "
         "thirty days.", "P29", "draft_or_proposed_explicitly_stated"),
    ],
)
def test_paragraph_wording_identifies_its_archetype(classifier, text, expected, legal):
    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert unit.status == "classified", (unit.review_reasons, [(c.label, c.score) for c in unit.candidates])
    assert expected in [label.label for label in unit.labels]
    if legal:
        assert unit.legal_status.value == legal
    label = next(label for label in unit.labels if label.label == expected)
    span = label.evidence[0].char_span
    assert label.evidence[0].text.lower() in text.lower() and span[1] > span[0]


def test_proposed_product_ban_is_p3_with_draft_status_not_p29(classifier):
    text = ("The Central Government proposes to prohibit the manufacture for sale and distribution of the fixed dose "
            "combination of Nimesulide + Paracetamol; objections and suggestions may be sent within thirty days.")

    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert [label.label for label in unit.labels] == ["P3"]
    assert unit.legal_status.value == "draft_or_proposed_explicitly_stated"


@pytest.mark.parametrize(
    "text, absent",
    [
        # Gazette prohibitions cite the Drugs Technical Advisory Board and reject any restriction.
        ("Whereas the Drugs Technical Advisory Board examined the said drug and recommended that no regulation or "
         "restriction can be justified; now therefore the Central Government hereby prohibits the manufacture for sale "
         "of the fixed dose combination of Aceclofenac + Paracetamol with immediate effect.", {"P8", "P3b"}),
        # NSQ lists name 'Drugs, Medical Devices and Cosmetics' without being device records.
        ("List of Drugs, Medical Devices and Cosmetics declared as Not of Standard Quality for the month of June 2025; "
         "the sample of Paracetamol Tablets, Batch No. PCT1, failed in Dissolution.", {"P9"}),
        # 'The DTAB in its meeting held on ...' is not a meeting record.
        ("The Drugs Technical Advisory Board in its meeting held on 12 May 2024 recommended that the Central Government "
         "hereby prohibits the manufacture for sale of the fixed dose combination of Etodolac + Paracetamol.", {"P24"}),
    ],
)
def test_gazette_and_alert_boilerplate_does_not_trigger_unrelated_labels(classifier, text, absent):
    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert not absent & {label.label for label in unit.labels}, [label.label for label in unit.labels]


def test_unit_with_two_distinct_actions_gets_two_labels(classifier):
    text = ("The Central Government hereby prohibits the manufacture for sale of the fixed dose combination of "
            "Nimesulide + Paracetamol, and restricts the fixed dose combination of Ofloxacin + Ornidazole, which shall "
            "not be used in children below twelve years.")

    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert {label.label for label in unit.labels} == {"P3", "P3b"}


def test_recall_label_keeps_its_conditional_class_and_gate(classifier):
    text = ("M/s Abbott India Limited has initiated a voluntary recall of Digene Gel, Batch No. 510303D7, from the "
            "market after complaints from consumers.")

    label = _only_unit(classifier.classify(build_document([text])), "paragraph").labels[0]

    assert (label.label, label.class_mode, label.app_classification, label.gate_ids) == ("P5", "conditional", "future_usable", ["GATE-P5P6"])


def test_conflicting_labels_are_escalated_not_guessed(classifier):
    text = ("In the countrywide survey for spurious drugs, samples were collected from retail outlets; the sample of "
            "Amoxycillin Capsules, Batch No. AMX12, was found spurious on investigation.")

    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert unit.status == "needs_review"
    assert unit.escalation.reasons == ["rule_conflict"] and "INV-12" in unit.escalation.detail
    assert {label.label for label in unit.labels} == {"P1", "P19"}  # kept for the reviewer


def test_unmatched_paragraph_goes_to_review_without_an_llm(classifier):
    text = "The office of the Drugs Controller will remain closed on Saturday because of maintenance work in the building."

    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert (unit.status, unit.labels, unit.escalation.outcome) == ("needs_review", [], "unavailable")
    assert unit.review_reasons == ["llm_unavailable", "escalated:no_rule_match"]


def test_fragments_are_not_records(classifier):
    result = classifier.classify(build_document(["Sir,"]))

    assert [(u.status, u.labels) for u in result.units] == [("not_a_record", [])]


# ------------------------------------------------------------------------------------------- units
def _settings(**changes):
    base = dict(paragraph_strategy="section", min_record_chars=20, max_unit_chars=4000, chunk_target_chars=200,
                skip_block_types=["header", "footer", "table_ref"], languages=["en"])
    return UnitSettings(**{**base, **changes})


def test_section_strategy_groups_blocks_under_their_heading():
    document = build_document([
        {"type": "heading", "level": 1, "text": "Prohibition"}, "First paragraph about the prohibition of a drug.",
        "Second paragraph about the same prohibition.", {"type": "heading", "level": 1, "text": "Advisory"},
        "A paragraph that advises patients about safe use.",
    ])

    units = paragraph_units(document, _settings(), context_chars=50)

    assert [u.heading_path for u in units] == [["Prohibition"], ["Advisory"]]
    assert units[0].text.startswith("Prohibition\nFirst paragraph") and units[1].previous_text


def test_chunk_strategy_splits_by_size_and_skips_headers_footers_and_other_languages():
    document = build_document([
        {"type": "header", "text": "THE GAZETTE OF INDIA : EXTRAORDINARY"},
        "x" * 150, "y" * 150,
        {"type": "paragraph", "text": "केन्द्रीय सरकार एतद्द्वारा प्रतिबंधित करती है", "language": "hi"},
        {"type": "footer", "text": "Page 1 of 2"},
    ])

    units = paragraph_units(document, _settings(paragraph_strategy="chunk"), context_chars=0)

    assert [u.text[:1] for u in units] == ["x", "y"]


# ------------------------------------------------------------------------------------------- LLM fallback
RECALL_TABLE = dict(header=["Batch", "Mfg Date", "Exp Date"], rows=[["E78550", "25-05-2016", "25-05-2019"]],
                    title="Recall of OZURDEX (Dexamethasone Intravitreal Implant 0.7mg)")


def test_low_confidence_table_is_settled_by_the_llm(make_classifier):
    classifier, provider = make_classifier([{"is_record": True, "labels": [{"label": "AV", "evidence_quote": "E78550", "confidence": "high"}]}])

    unit = _only_unit(classifier.classify(_table(**RECALL_TABLE)), "table")

    assert unit.status == "classified" and unit.escalation.reasons == ["low_confidence"]
    assert [(l.label, l.method, l.confidence) for l in unit.labels] == [("AV", "llm", 0.9)]
    request = provider.requests[0]
    assert "Header: Batch | Mfg Date | Exp Date" in request.user and "AV (score" in request.user
    assert "doc.pdf" not in request.user + request.system  # file names are never shown to the model
    assert request.json_schema["properties"]["labels"]["items"]["properties"]["label"]["enum"][-1] == "NU"


@pytest.mark.parametrize(
    "reply, reason, kept",
    [
        ({"is_record": True, "labels": [{"label": "AV", "evidence_quote": "batch E99999 recalled", "confidence": "high"}]},
         "llm_quote_not_in_source:AV", []),
        ({"is_record": True, "labels": [{"label": "P99", "evidence_quote": "E78550", "confidence": "high"}]},
         "llm_unknown_label:P99", []),
        ({"is_record": True, "labels": [{"label": "AV", "evidence_quote": "E78550", "confidence": "low"}]},
         "llm_low_confidence:AV", ["AV"]),
        ({"labels": "AV"}, "llm_invalid_reply", []),
    ],
)
def test_unverifiable_llm_answers_go_to_review(make_classifier, reply, reason, kept):
    classifier, _ = make_classifier([reply])

    unit = _only_unit(classifier.classify(_table(**RECALL_TABLE)), "table")

    assert unit.status == "needs_review" and reason in unit.review_reasons
    assert [label.label for label in unit.labels] == kept


def test_llm_error_keeps_the_document_going(make_classifier):
    classifier, _ = make_classifier([LLMError("throttled")])

    unit = _only_unit(classifier.classify(_table(**RECALL_TABLE)), "table")

    assert unit.status == "needs_review" and unit.escalation.outcome == "error" and "throttled" in unit.escalation.detail


def test_llm_resolves_a_rule_conflict_and_sets_legal_status(make_classifier):
    text = ("In the countrywide survey for spurious drugs, samples were collected from retail outlets; the sample of "
            "Amoxycillin Capsules, Batch No. AMX12, was found spurious on investigation.")
    classifier, provider = make_classifier([{
        "is_record": True, "legal_status": "administrative_or_informational",
        "labels": [{"label": "P1", "evidence_quote": "Batch No. AMX12, was found spurious", "confidence": "high"},
                   {"label": "P19", "evidence_quote": "samples were collected from retail outlets", "confidence": "medium"}],
    }])

    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert unit.status == "classified" and {l.label for l in unit.labels} == {"P1", "P19"}
    assert unit.legal_status.value == "administrative_or_informational" and unit.legal_status_rule_id == "LLM:classify-v1"
    assert "P1 (score" in provider.requests[0].user


def test_llm_can_mark_a_unit_as_not_a_record(make_classifier):
    classifier, _ = make_classifier([{"is_record": False, "labels": [], "legal_status": "unclear_from_excerpt"}])
    text = "Food and Drugs Administration Bhawan, Kotla Road, New Delhi 110002, Telephone 011-23236965, Fax 011-23236973."

    unit = _only_unit(classifier.classify(build_document([text])), "paragraph")

    assert unit.status == "not_a_record" and unit.labels == []


def test_cached_answers_are_reused_without_calling_the_model(make_classifier, tmp_path):
    reply = {"is_record": True, "labels": [{"label": "AV", "evidence_quote": "E78550", "confidence": "high"}]}
    first, _ = make_classifier([reply], cache=FileCache(tmp_path))
    second, provider = make_classifier([], cache=FileCache(tmp_path))

    first.classify(_table(**RECALL_TABLE))
    unit = _only_unit(second.classify(_table(**RECALL_TABLE)), "table")

    assert provider.requests == [] and unit.escalation.cached and unit.labels[0].label == "AV"


# ------------------------------------------------------------------------------------------- I/O
def test_classify_uri_writes_the_classified_document(classifier, tmp_path):
    import json

    from idp.stages.classifier.service import classify_uri

    source = tmp_path / "in" / "12087_prohibited.structured.json"
    source.parent.mkdir()
    source.write_text(build_document([PROHIBITION]).model_dump_json(), encoding="utf-8")

    target, result = classify_uri(classifier, str(source), str(tmp_path / "out"))

    assert target.endswith("12087_prohibited.classified.json")
    assert json.loads((tmp_path / "out" / "12087_prohibited.classified.json").read_text(encoding="utf-8"))["summary"]["units"] == 1
    assert output_name("x.json") == "x.classified.json"
