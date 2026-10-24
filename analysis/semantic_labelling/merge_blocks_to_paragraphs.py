#!/usr/bin/env python3
import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "paragraph_files_extracted"
DEFAULT_OUTPUT = SCRIPT_DIR / "paragraph_files_paragraphs"

WHITESPACE = re.compile(r"\s+")

def collapse_soft_wraps(text: str) -> str:
    """Fix hyphenated words and collapse newlines."""
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
    return WHITESPACE.sub(" ", text).strip()

def extract_lines(data: dict) -> list[dict]:
    """Extract individual lines with font info from PyMuPDF 'dict' output."""
    all_lines = []
    for page in data.get("pages", []):
        page_num = page.get("page", 0)
        for block in page.get("blocks", []):
            # Type 0 is text, type 1 is image
            if block.get("type") not in (None, 0):
                continue
            
            # If the JSON was extracted using "blocks" instead of "dict", 
            # there will be no "lines". We fall back to treating the block as a line.
            if "lines" not in block:
                text = collapse_soft_wraps(block.get("text", ""))
                if text:
                    bbox = block.get("bbox", [0,0,0,0])
                    all_lines.append({
                        "text": text, "bbox": bbox, "page": page_num, 
                        "font_size": 10.0, "font_flags": 0
                    })
                continue

            for line in block.get("lines", []):
                if "spans" in line:
                    line_text = ""
                    max_size = 0.0
                    font_flags = 0

                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                        max_size = max(max_size, span.get("size", 10.0))
                        font_flags = max(font_flags, span.get("flags", 0))
                else:
                    line_text = line.get("text", "")
                    max_size = line.get("font_size", 10.0)
                    font_flags = line.get("font_flags", 0)
                
                line_text = collapse_soft_wraps(line_text)
                if line_text:
                    all_lines.append({
                        "text": line_text,
                        "bbox": line.get("bbox", [0,0,0,0]),
                        "page": page_num,
                        "font_size": max_size,
                        "font_flags": font_flags
                    })
    return all_lines

def classify_lines(lines: list[dict]) -> None:
    """Assign semantic labels to lines based on font size, position, and alignment."""
    if not lines:
        return
        
    # Calculate page dimensions
    page_heights = {}
    page_widths = {}
    for line in lines:
        p = line["page"]
        page_heights[p] = max(page_heights.get(p, 0.0), line["bbox"][3])
        page_widths[p] = max(page_widths.get(p, 0.0), line["bbox"][2])
        
    # Calculate median font size across the document to detect headings
    font_sizes = [line["font_size"] for line in lines if line["font_size"] > 0]
    median_font_size = statistics.median(font_sizes) if font_sizes else 10.0

    for line in lines:
        x0, y0, x1, y1 = line["bbox"]
        p = line["page"]
        page_h = page_heights.get(p, 842.0)
        page_w = page_widths.get(p, 595.0)
        
        # 1. Header / Footer (Top 8% and Bottom 8%)
        if y0 < page_h * 0.08:
            line["label"] = "HEADER"
            continue
        if y1 > page_h * 0.92:
            line["label"] = "FOOTER"
            continue

        # 2. Title / Heading Detection via Font Size and Centering
        is_centered = abs((x0 + x1) / 2 - page_w / 2) < (page_w * 0.15)
        is_large_font = line["font_size"] > (median_font_size * 1.2)
        
        if is_large_font or (is_centered and len(line["text"]) < 60 and not line["text"].endswith('.')):
            line["label"] = "TITLE"
            continue

        # Default
        line["label"] = "PARAGRAPH"

def ends_sentence(text: str) -> bool:
    """Check for sentence boundaries, including legal semicolons."""
    return text.rstrip().endswith((".", "!", "?", "।", ":", ";"))

def merge_lines_to_paragraphs(all_lines: list[dict]) -> list[dict]:
    """Group lines into paragraphs using dynamic, relative thresholds."""
    if not all_lines:
        return []

    # Sort by page, then top-to-bottom, then left-to-right
    all_lines.sort(key=lambda l: (l["page"], l["bbox"][1], l["bbox"][0]))

    # Calculate dynamic thresholds based on median line height
    heights = [l["bbox"][3] - l["bbox"][1] for l in all_lines if (l["bbox"][3] - l["bbox"][1]) > 0]
    median_height = statistics.median(heights) if heights else 12.0
    
    # Gap threshold: 1.5x the typical line height. If gap > this, it's a new paragraph.
    dynamic_gap_threshold = median_height * 1.5
    # Indent threshold: If the left margin shifts by more than 1 character width, it's a new paragraph.
    dynamic_indent_threshold = median_height * 0.8

    final_paragraphs = []
    current_para = None

    for line in all_lines:
        label = line["label"]
        
        # If it's a Header, Footer, or Title, it stands alone.
        if label in ["HEADER", "FOOTER", "TITLE"]:
            if current_para:
                final_paragraphs.append(current_para)
                current_para = None
            final_paragraphs.append({
                "text": line["text"],
                "label": label,
                "page": line["page"],
                "pages": [line["page"]],
                "last_bbox": line["bbox"],
                "last_page": line["page"]
            })
            continue

        # Logic for PARAGRAPH lines
        if current_para is None:
            current_para = {
                "text": line["text"],
                "label": "PARAGRAPH",
                "page": line["page"],
                "pages": [line["page"]],
                "last_bbox": line["bbox"],
                "last_page": line["page"]
            }
        else:
            prev_y1 = current_para["last_bbox"][3]
            curr_y0 = line["bbox"][1]
            prev_x0 = current_para["last_bbox"][0]
            curr_x0 = line["bbox"][0]
            is_same_page = line["page"] == current_para["last_page"]

            should_merge = False

            if is_same_page:
                vertical_gap = curr_y0 - prev_y1
                left_shift = abs(curr_x0 - prev_x0)
                
                # Merge if vertically close AND left margins are aligned
                if vertical_gap <= dynamic_gap_threshold and left_shift <= dynamic_indent_threshold:
                    should_merge = True
            else:
                # Cross-page merging: Check if the sentence continues
                continued_at_page_break = (prev_y1 >= current_para.get("page_height", 800) * 0.8)
                
                # Only merge if it didn't end with punctuation AND text continues
                if continued_at_page_break and not ends_sentence(current_para["text"]):
                    should_merge = True

            if should_merge:
                if current_para["text"].endswith("-"):
                    current_para["text"] = current_para["text"][:-1] + line["text"]
                else:
                    current_para["text"] += " " + line["text"]
                
                if line["page"] not in current_para["pages"]:
                    current_para["pages"].append(line["page"])
                
                current_para["last_bbox"] = line["bbox"]
                current_para["last_page"] = line["page"]
            else:
                # Start a new paragraph
                final_paragraphs.append(current_para)
                current_para = {
                    "text": line["text"],
                    "label": "PARAGRAPH",
                    "page": line["page"],
                    "pages": [line["page"]],
                    "last_bbox": line["bbox"],
                    "last_page": line["page"]
                }

    if current_para:
        final_paragraphs.append(current_para)

    # Clean up and add IDs
    output = []
    for idx, p in enumerate(final_paragraphs):
        output.append({
            "id": idx,
            "text": p["text"],
            "label": p["label"],
            "pages": p["pages"]
        })
        
    return output

def process_file(input_path: Path, output_path: Path) -> dict[str, Any]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    
    # 1. Extract lines and font data
    all_lines = extract_lines(data)
    
    # 2. Classify lines (Header, Footer, Title, Paragraph)
    classify_lines(all_lines)
    
    # 3. Merge lines into paragraphs using dynamic thresholds
    final_paragraphs = merge_lines_to_paragraphs(all_lines)

    # Add page_height back for cross-page logic (approximate)
    for p in final_paragraphs:
        p["page_height"] = 842.0 

    result = {
        "file_name": data.get("file_name", input_path.name),
        "status": data.get("status", "UNKNOWN"),
        "source_page_count": data.get("page_count", 0),
        "paragraph_count": sum(1 for p in final_paragraphs if p["label"] == "PARAGRAPH"),
        "record_count": len(final_paragraphs),
        "paragraphs": final_paragraphs,
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result

# --- KEEP YOUR EXISTING main() FUNCTION HERE ---
def main() -> int:
    parser = argparse.ArgumentParser(description="Merge blocks using dict/font logic.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.input.is_dir():
        parser.error(f"Input folder does not exist: {args.input}")
    args.output.mkdir(parents=True, exist_ok=True)

    json_files = sorted(args.input.rglob("*.json"))
    if not json_files:
        parser.error(f"No JSON files found in {args.input}")

    total = len(json_files)
    summary: dict[str, int] = {}
    for idx, in_path in enumerate(json_files, start=1):
        relative_path = in_path.relative_to(args.input)
        out_path = args.output / relative_path
        print(f"[{idx}/{total}] {relative_path.as_posix()}", flush=True)

        if out_path.exists() and not args.force:
            summary["SKIPPED_EXISTING"] = summary.get("SKIPPED_EXISTING", 0) + 1
            continue

        try:
            record = process_file(in_path, out_path)
        except Exception as exc:
            summary["FAILED"] = summary.get("FAILED", 0) + 1
            print(f"  FAILED: {exc}", flush=True)
            continue

        status = record.get("status", "UNKNOWN")
        summary[status] = summary.get(status, 0) + 1

    print(f"\nProcessed: {total}")
    print(f"Statuses: {json.dumps(summary, sort_keys=True)}")
    print(f"Output: {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())