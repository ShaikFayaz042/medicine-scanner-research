from idp.schemas.extraction import Item, Segment, Source, Table
from idp.stages.classification_context.paragraphs import (
    build_document_anchors,
    extract_paragraphs,
)
from idp.stages.classification_context.tables import extract_tables


def _bold_heading(item_id: str, text: str, y: float) -> Item:
    return Item(
        item_id=item_id,
        type="text_line",
        bbox=(0.1, y, 0.9, y + 0.02),
        source=Source(engine="pymupdf", method="native_text"),
        text=text,
        segments=[Segment(text=text, size=12, font="Helvetica-Bold", bold=True)],
    )


def test_generic_file_reference_keeps_alphabetic_suffix():
    paragraphs, excluded_count = extract_paragraphs(
        "Imp/Misc/102/2018-DC",
        page_number=1,
        artifact="02_extraction/markdown/p001.md",
        source_method="pymupdf4llm",
        start_index=1,
        items=[],
        page_width=600,
        page_height=800,
    )

    assert excluded_count == 0
    assert paragraphs[0].file_no_candidates == ["Imp/Misc/102/2018-DC"]
    assert paragraphs[0].source_refs[0].item_id is None


def test_missing_bold_headings_are_restored_by_vertical_position():
    headings = [
        _bold_heading("heading1", "ADVERSE EFFECTS", 0.2),
        _bold_heading("heading2", "ACTION BY", 0.5),
        _bold_heading("heading3", "CONTACTS", 0.8),
    ]
    body = [
        Item(
            item_id=f"body{i}",
            type="text_line",
            bbox=(0.1, y, 0.9, y + 0.03),
            source=Source(engine="pymupdf", method="native_text"),
            text=text,
        )
        for i, (text, y) in enumerate(
            (
                ("Side effects are described here.", 0.25),
                ("The agency should take action.", 0.55),
                ("Contact details are provided.", 0.85),
            ),
            start=1,
        )
    ]

    paragraphs, excluded_count = extract_paragraphs(
        "Side effects are described here.\n\n"
        "The agency should take action.\n\n"
        "Contact details are provided.",
        page_number=2,
        artifact="02_extraction/markdown/p002.md",
        source_method="pymupdf4llm",
        start_index=1,
        items=[*headings, *body],
        page_width=600,
        page_height=800,
    )

    assert excluded_count == 0
    assert [paragraph.section_path for paragraph in paragraphs] == [
        ["ADVERSE EFFECTS"],
        ["ACTION BY"],
        ["CONTACTS"],
    ]
    assert [paragraph.source_refs[0].item_id for paragraph in paragraphs] == [
        "body1",
        "body2",
        "body3",
    ]


def test_markdown_headings_do_not_require_matching_bold_items():
    paragraphs, excluded_count = extract_paragraphs(
        "## CLINICAL FINDINGS\n\nPatients may experience side effects.",
        page_number=1,
        artifact="02_extraction/markdown/p001.md",
        source_method="pymupdf4llm",
        start_index=1,
        items=[],
        page_width=600,
        page_height=800,
    )

    assert excluded_count == 0
    assert [paragraph.section_path for paragraph in paragraphs] == [
        ["CLINICAL FINDINGS"],
    ]


def test_document_anchor_finds_file_number_in_heading_section_path():
    paragraphs, _ = extract_paragraphs(
        "# **F. No. Imp/Misc/102/2018-DC**\n\n"
        "FDA Bhawan, Kotla Road, New Delhi.\n\n"
        "## DRUG ALERT\n\nRecall information.",
        page_number=1,
        artifact="02_extraction/markdown/p001.md",
        source_method="pymupdf4llm",
        start_index=1,
        items=[],
        page_width=600,
        page_height=800,
    )

    anchors = build_document_anchors(paragraphs)

    assert paragraphs[0].content == "FDA Bhawan, Kotla Road, New Delhi."
    assert paragraphs[0].section_path == ["F. No. Imp/Misc/102/2018-DC"]
    assert anchors.file_no.value == "Imp/Misc/102/2018-DC"
    assert anchors.file_no.paragraph_ids == [paragraphs[0].id]


def test_source_reference_contains_all_matching_extraction_item_ids():
    items = [
        Item(
            item_id=item_id,
            type="text_line",
            bbox=(0.1, y, 0.9, y + 0.02),
            source=Source(engine="pymupdf", method="native_text"),
            text=text,
        )
        for item_id, text, y in (
            ("p001_i002", "First line", 0.1),
            ("p001_i003", "Second line", 0.15),
        )
    ]

    paragraphs, _ = extract_paragraphs(
        "First line\nSecond line",
        page_number=1,
        artifact="02_extraction/markdown/p001.md",
        source_method="pymupdf4llm",
        start_index=1,
        items=items,
        page_width=600,
        page_height=800,
    )

    assert paragraphs[0].source_refs[0].item_id == "p001_i002,p001_i003"


def test_page_numbers_return_count_without_consuming_chunk_ids():
    paragraphs, excluded_count = extract_paragraphs(
        "First paragraph.\n\nPage 1 of 3\n\n# NEXT SECTION\n\nSecond paragraph.",
        page_number=1,
        artifact="02_extraction/markdown/p001.md",
        source_method="pymupdf4llm",
        start_index=1,
        items=[],
        page_width=600,
        page_height=800,
    )

    assert excluded_count == 1
    assert [paragraph.id for paragraph in paragraphs] == ["C0001", "C0002"]
    assert paragraphs[1].section_path == ["NEXT SECTION"]


def test_cascading_header_inheritance_across_three_pages():
    """Page 3 inherits headers from Page 2, which inherited them from Page 1."""
    source = Source(engine="pymupdf", method="native_table")

    page1_item = Item(
        item_id="p001_i01",
        type="table",
        bbox=(0.1, 0.1, 0.9, 0.2),
        source=source,
        table=Table(
            rows=[["Batch", "Expiry"], ["A1", "2024"]],
            n_rows=2,
            n_cols=2,
            header_names=["Batch", "Expiry"],
        ),
    )
    page2_item = Item(
        item_id="p002_i01",
        type="table",
        bbox=(0.1, 0.1, 0.9, 0.2),
        source=source,
        table=Table(
            rows=[["B2", "2025"]],
            n_rows=1,
            n_cols=2,
            header_external=True,
            continuation_of="p001_i01",
        ),
    )
    page3_item = Item(
        item_id="p003_i01",
        type="table",
        bbox=(0.1, 0.1, 0.9, 0.2),
        source=source,
        table=Table(
            rows=[["C3", "2026"]],
            n_rows=1,
            n_cols=2,
            header_external=True,
            continuation_of="p002_i01",
        ),
    )

    item_to_context_table_id: dict[str, str] = {}
    table_headers_cache: dict[str, list[str]] = {}

    tables1, warnings1 = extract_tables(
        [page1_item], 1, 600, 800, "b0000",
        item_to_context_table_id, table_headers_cache,
    )
    tables2, warnings2 = extract_tables(
        [page2_item], 2, 600, 800, "b0000",
        item_to_context_table_id, table_headers_cache,
    )
    tables3, warnings3 = extract_tables(
        [page3_item], 3, 600, 800, "b0000",
        item_to_context_table_id, table_headers_cache,
    )

    expected_headers = ["Batch", "Expiry"]
    assert tables1[0].headers == expected_headers
    assert tables2[0].headers == expected_headers
    assert tables3[0].headers == expected_headers
    assert [tables2[0].continuation_of, tables3[0].continuation_of] == [
        tables1[0].id,
        tables2[0].id,
    ]
    assert warnings1 == warnings2 == warnings3 == []
