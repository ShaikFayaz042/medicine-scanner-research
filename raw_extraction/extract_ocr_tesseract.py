#!/usr/bin/env python3
"""
OCR extraction pipeline for SCANNED PDFs using Tesseract.

Reads:
    downloads/_analysis/pdf_analysis.csv  (status == SCANNED)
    downloads/<source>/important/<file>.pdf

Outputs:
    raw_extraction/ocr_tesseract/<source>/<name>.txt           - page-marked OCR text
    raw_extraction/ocr_tesseract/<source>/<name>.blocks.json   - raw OCR blocks + coords
    raw_extraction/ocr_tesseract/<source>/_manifest.json       - per-source manifest
    raw_extraction/ocr_tesseract/_manifest.json                - global manifest

OCR STRATEGY
------------
1. Render PDF page → RGB image via PyMuPDF (default 200 DPI).
2. Optional preprocessing (grayscale + autocontrast + Otsu threshold).
3. pytesseract.image_to_data → word-level boxes + per-word confidence.
4. Reconstruct lines: group words by y-center, insert tabs at large
   horizontal gaps (so table columns stay visually aligned).
5. Write one .txt (page-marked) + one .blocks.json per PDF.

REQUIREMENTS
------------
- tesseract.exe installed. Common path on Windows:
      Z:\\Program Files\\Tesseract-OCR\\tesseract.exe
  Override with --tesseract-path, or set env var TESSERACT_CMD.
- pip install pytesseract pillow pymupdf

CONCURRENCY
-----------
Multiprocessing across PDFs (default 2 workers). Each worker spawns
tesseract.exe as a subprocess per page (that's how pytesseract works).
Safe with any number of workers; RAM overhead is minimal.

Idempotent by default (skips existing outputs). Use --force to redo.

Usage:
    python raw_extraction/extract_ocr_tesseract.py
    python raw_extraction/extract_ocr_tesseract.py --sources alerts
    python raw_extraction/extract_ocr_tesseract.py --limit 3
    python raw_extraction/extract_ocr_tesseract.py --files "a.pdf" "b.pdf"
    python raw_extraction/extract_ocr_tesseract.py --workers 2 --dpi 200
    python raw_extraction/extract_ocr_tesseract.py --psm 6 --oem 3 --lang eng
    python raw_extraction/extract_ocr_tesseract.py --preprocess auto
    python raw_extraction/extract_ocr_tesseract.py --force
"""

import argparse
import csv
import json
import logging
import multiprocessing as mp
import os
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# --- PyMuPDF ---
try:
    import pymupdf as fitz
except ImportError:
    import fitz

import numpy as np
from PIL import Image, ImageOps, ImageFilter

# --- pytesseract (required) ---
try:
    import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
RAW_ROOT = THIS_FILE.parent
REPO_ROOT = RAW_ROOT.parent
DOWNLOADS = REPO_ROOT / "downloads"
ANALYSIS_CSV = DOWNLOADS / "_analysis" / "pdf_analysis.csv"
OUTPUT_ROOT = RAW_ROOT / "ocr_tesseract"

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_DPI = 200
DEFAULT_WORKERS = 2
DEFAULT_PSM = 6           # 6 = "single uniform block" — good for notices
DEFAULT_OEM = 3           # 3 = default LSTM engine
DEFAULT_LANG = "eng"
DEFAULT_PREPROCESS = "none"    # none | auto | binarize

# Line reconstruction
Y_GROUP_FACTOR = 0.6      # tolerance = median box height * this
TAB_GAP_PIXELS = 25       # horizontal gap that triggers a tab
MIN_LINE_CHARS = 2
MIN_WORD_CONF = 0.0       # drop words below this confidence (0 = keep all)

# Silencing Tesseract/pytesseract noise
logging.getLogger("pytesseract").setLevel(logging.WARNING)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Tesseract resolution
# ---------------------------------------------------------------------------
# Common install locations, checked in order
_TESSERACT_CANDIDATES = [
    r"Z:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"Z:\Program Files\Tesseract-OCR\tesseract.exe",
]


def resolve_tesseract(explicit: str | None) -> str:
    """
    Find tesseract.exe. Priority:
        1. --tesseract-path CLI arg
        2. TESSERACT_CMD env var
        3. Common install locations
        4. `where tesseract` on PATH
    """
    if explicit:
        p = Path(explicit)
        if p.exists():
            return str(p)
        raise SystemExit(f"[!] --tesseract-path does not exist: {explicit}")

    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).exists():
        return env

    for cand in _TESSERACT_CANDIDATES:
        if Path(cand).exists():
            return cand

    found = shutil.which("tesseract")
    if found:
        return found

    raise SystemExit(
        "[!] tesseract.exe not found.\n"
        "    Install from: https://github.com/UB-Mannheim/tesseract/wiki\n"
        "    Then either:\n"
        "      - pass --tesseract-path \"C:\\Program Files\\Tesseract-OCR\\tesseract.exe\"\n"
        "      - set env var TESSERACT_CMD=<path>\n"
        "      - add the folder to PATH"
    )


def verify_tesseract(binary: str) -> None:
    """Confirm the binary actually runs and print its version."""
    pytesseract.pytesseract.tesseract_cmd = binary
    try:
        v = pytesseract.get_tesseract_version()
        print(f"[*] Tesseract       : {v}  ({binary})")
    except Exception as exc:
        raise SystemExit(
            f"[!] Tesseract found at {binary} but failed to run:\n    {exc}\n"
            f"    Try installing Visual C++ Redistributable:\n"
            f"    https://aka.ms/vs/17/release/vc_redist.x64.exe"
        )


# ---------------------------------------------------------------------------
# Target discovery (from pdf_analysis.csv, filter status == SCANNED)
# ---------------------------------------------------------------------------
def load_scanned_targets(
    csv_path: Path,
    only_sources: set[str] | None = None,
) -> list[dict]:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    targets: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

        required = {"source", "filename", "status"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"CSV missing required column(s): {sorted(missing)}"
            )

        for row in reader:
            status = (row.get("status") or "").strip().upper()
            if status != "SCANNED":
                continue
            source = (row.get("source") or "").strip()
            filename = (row.get("filename") or "").strip()
            if not source or not filename:
                continue
            if only_sources and source not in only_sources:
                continue
            targets.append({
                "source": source,
                "filename": filename,
                "status": status,
            })
    return targets


def filter_targets_by_files(
    targets: list[dict],
    wanted_files: list[str] | None,
) -> list[dict]:
    """Restrict to exact filenames (case-insensitive). Warns on misses."""
    if not wanted_files:
        return targets

    wanted = {f.strip().lower() for f in wanted_files if f.strip()}
    matched = [t for t in targets if t["filename"].lower() in wanted]

    found = {t["filename"].lower() for t in matched}
    missing = wanted - found
    if missing:
        print(f"[!] {len(missing)} requested file(s) not in SCANNED list:")
        for m in sorted(missing):
            print(f"      {m}")
        print()

    return matched


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------
def _preprocess_image(img: Image.Image, mode: str) -> Image.Image:
    """
    Optional preprocessing to help Tesseract on faded / noisy scans.

    modes:
        none      — return as-is
        auto      — grayscale + autocontrast + slight sharpen
        binarize  — auto + Otsu-like adaptive threshold
    """
    if mode == "none":
        return img

    # All modes start with grayscale
    gray = img.convert("L")

    if mode == "auto":
        return ImageOps.autocontrast(gray, cutoff=1)

    if mode == "binarize":
        # Simple Otsu-like threshold via PIL point()
        # (real Otsu needs numpy histogram; this is a cheap approximation)
        gray = ImageOps.autocontrast(gray, cutoff=2)
        # Sharpen to help thin characters
        gray = gray.filter(ImageFilter.SHARPEN)
        # Threshold: anything > 160 → white, else → black
        return gray.point(lambda x: 255 if x > 160 else 0)

    return img


# ---------------------------------------------------------------------------
# Core OCR — single page
# ---------------------------------------------------------------------------
def _render_page_rgb(page, dpi: int) -> np.ndarray:
    """Render a PDF page to an RGB numpy array."""
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3
    )


def _ocr_one_page(
    page,
    dpi: int,
    psm: int,
    oem: int,
    lang: str,
    preprocess: str,
) -> tuple[list[dict], int, int, float, str]:
    """
    Render + OCR a single page with Tesseract.

    Returns (blocks, width, height, elapsed_sec, error_msg).
    Each block: {text, confidence, y_center, y_top, y_bottom,
                 x_left, x_right, box}.
    """
    t0 = time.time()

    try:
        arr = _render_page_rgb(page, dpi)
        height, width = arr.shape[0], arr.shape[1]
        img = Image.fromarray(arr)

        if preprocess != "none":
            img = _preprocess_image(img, preprocess)

        config = f"--oem {oem} --psm {psm}"
        data = pytesseract.image_to_data(
            img,
            lang=lang,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        return [], 0, 0, time.time() - t0, str(exc)

    blocks: list[dict] = []
    n = len(data.get("text", []))

    for i in range(n):
        raw_text = data["text"][i]
        if not raw_text or not str(raw_text).strip():
            continue

        try:
            conf_int = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            continue
        # Tesseract returns -1 for structural (non-word) rows
        if conf_int < 0:
            continue

        confidence = conf_int / 100.0
        if confidence < MIN_WORD_CONF:
            continue

        left = int(data["left"][i])
        top = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        right = left + w
        bottom = top + h

        blocks.append({
            "text": str(raw_text).strip(),
            "confidence": round(confidence, 4),
            "y_center": (top + bottom) / 2.0,
            "y_top": float(top),
            "y_bottom": float(bottom),
            "x_left": float(left),
            "x_right": float(right),
            "box": [
                [float(left), float(top)],
                [float(right), float(top)],
                [float(right), float(bottom)],
                [float(left), float(bottom)],
            ],
        })

    return blocks, width, height, time.time() - t0, ""


# ---------------------------------------------------------------------------
# Line reconstruction from OCR blocks (identical logic to RapidOCR version)
# ---------------------------------------------------------------------------
def _blocks_to_lines(blocks: list[dict]) -> list[str]:
    """
    Group OCR blocks into visual lines using y-center proximity.
    Insert tabs at large horizontal gaps so table columns stay aligned.
    """
    if not blocks:
        return []

    heights = sorted(
        b["y_bottom"] - b["y_top"]
        for b in blocks
        if b["y_bottom"] > b["y_top"]
    )
    median_h = heights[len(heights) // 2] if heights else 15.0
    y_tol = max(3.0, median_h * Y_GROUP_FACTOR)

    sorted_blocks = sorted(blocks, key=lambda b: (b["y_center"], b["x_left"]))

    grouped: list[list[dict]] = []
    current: list[dict] = []
    current_yc: float | None = None

    for b in sorted_blocks:
        if current_yc is None or abs(b["y_center"] - current_yc) <= y_tol:
            current.append(b)
            current_yc = sum(bb["y_center"] for bb in current) / len(current)
        else:
            current.sort(key=lambda bb: bb["x_left"])
            grouped.append(current)
            current = [b]
            current_yc = b["y_center"]

    if current:
        current.sort(key=lambda bb: bb["x_left"])
        grouped.append(current)

    out_lines: list[str] = []
    for line in grouped:
        parts: list[str] = []
        prev_x_right: float | None = None
        for b in line:
            if prev_x_right is not None:
                gap = b["x_left"] - prev_x_right
                parts.append("\t" if gap >= TAB_GAP_PIXELS else " ")
            parts.append(b["text"])
            prev_x_right = b["x_right"]
        joined = "".join(parts).rstrip()
        if len(joined) >= MIN_LINE_CHARS:
            out_lines.append(joined)
    return out_lines


# ---------------------------------------------------------------------------
# Per-PDF processing
# ---------------------------------------------------------------------------
def process_one_pdf(
    source: str,
    filename: str,
    downloads_root: Path,
    output_root: Path,
    dpi: int,
    psm: int,
    oem: int,
    lang: str,
    preprocess: str,
) -> dict:
    """Process a single PDF. Returns a status dict for the manifest."""
    pdf_path = downloads_root / source / "important" / filename
    result: dict = {
        "source": source,
        "pdf": filename,
        "status": "error",
        "err": "",
    }

    if not pdf_path.exists():
        result["status"] = "missing"
        result["err"] = "PDF not found on disk"
        return result

    stem = pdf_path.stem
    out_dir = output_root / source
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"{stem}.txt"
    blocks_path = out_dir / f"{stem}.blocks.json"

    t_start = time.time()

    try:
        with fitz.open(pdf_path) as doc:
            page_count = doc.page_count
            txt_chunks: list[str] = []
            all_pages: list[dict] = []
            total_chars = 0
            total_blocks = 0
            total_conf = 0.0
            page_times: list[float] = []
            page_errors: list[str] = []

            for i in range(page_count):
                page = doc.load_page(i)
                blocks, width, height, elapsed, err = _ocr_one_page(
                    page, dpi, psm, oem, lang, preprocess
                )
                lines = _blocks_to_lines(blocks)

                txt_chunks.append(f"===== PAGE {i + 1} =====")
                txt_chunks.append("\n".join(lines))
                txt_chunks.append("")

                all_pages.append({
                    "page": i + 1,
                    "width": width,
                    "height": height,
                    "line_count": len(lines),
                    "block_count": len(blocks),
                    "elapsed_sec": round(elapsed, 3),
                    "error": err,
                    "blocks": blocks,
                })

                total_chars += sum(len(l) for l in lines)
                for b in blocks:
                    total_conf += b["confidence"]
                    total_blocks += 1
                page_times.append(elapsed)
                if err:
                    page_errors.append(f"page {i + 1}: {err}")

        txt = "\n".join(txt_chunks).rstrip() + "\n"
        txt_path.write_text(txt, encoding="utf-8")
        blocks_path.write_text(
            json.dumps(all_pages, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        avg_conf = total_conf / total_blocks if total_blocks else 0.0
        total_elapsed = time.time() - t_start

        result.update({
            "status": "ok",
            "pages": page_count,
            "chars": len(txt),
            "ocr_blocks": total_blocks,
            "avg_confidence": round(avg_conf, 4),
            "elapsed_sec": round(total_elapsed, 2),
            "avg_page_sec": round(
                sum(page_times) / len(page_times), 3
            ) if page_times else 0.0,
            "page_errors": page_errors if page_errors else None,
            "txt": str(txt_path.relative_to(output_root)),
            "blocks_json": str(blocks_path.relative_to(output_root)),
            "ocr_at": utcnow_iso(),
        })
        return result

    except Exception as exc:
        result["err"] = str(exc)
        return result


# ---------------------------------------------------------------------------
# Multiprocessing plumbing
# ---------------------------------------------------------------------------
_WORKER: dict = {}


def _worker_init(
    tesseract_cmd: str,
    psm: int,
    oem: int,
    lang: str,
    preprocess: str,
) -> None:
    """Each worker process sets up its own tesseract path + config."""
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    _WORKER["psm"] = psm
    _WORKER["oem"] = oem
    _WORKER["lang"] = lang
    _WORKER["preprocess"] = preprocess


def _worker_run(task: tuple) -> dict:
    (source, filename, downloads_root_str, output_root_str, dpi) = task
    try:
        return process_one_pdf(
            source,
            filename,
            Path(downloads_root_str),
            Path(output_root_str),
            dpi,
            _WORKER["psm"],
            _WORKER["oem"],
            _WORKER["lang"],
            _WORKER["preprocess"],
        )
    except Exception as exc:
        return {
            "source": source,
            "pdf": filename,
            "status": "error",
            "err": f"worker exception: {exc}",
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="OCR SCANNED PDFs with Tesseract."
    )
    ap.add_argument(
        "--sources", nargs="+", default=None,
        help="Only process these source folders.",
    )
    ap.add_argument(
        "--files", nargs="+", default=None,
        help="Only process these exact PDF filenames "
             "(combined with --sources if given).",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N PDFs (smoke testing).",
    )
    ap.add_argument(
        "--dpi", type=int, default=DEFAULT_DPI,
        help=f"Page render DPI (default {DEFAULT_DPI}).",
    )
    ap.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Worker processes (default {DEFAULT_WORKERS}). "
             f"Use 1 for single-process.",
    )
    ap.add_argument(
        "--psm", type=int, default=DEFAULT_PSM,
        help=f"Tesseract page segmentation mode (default {DEFAULT_PSM}). "
             f"Common: 3=auto, 4=single column, 6=single block, 11=sparse.",
    )
    ap.add_argument(
        "--oem", type=int, default=DEFAULT_OEM,
        help=f"Tesseract OCR engine mode (default {DEFAULT_OEM}). "
             f"1=LSTM only, 3=default, 0=legacy.",
    )
    ap.add_argument(
        "--lang", default=DEFAULT_LANG,
        help=f"Tesseract language (default {DEFAULT_LANG}).",
    )
    ap.add_argument(
        "--preprocess", choices=["none", "auto", "binarize"],
        default=DEFAULT_PREPROCESS,
        help=f"Image preprocessing (default {DEFAULT_PREPROCESS}).",
    )
    ap.add_argument(
        "--tesseract-path", default=None,
        help="Full path to tesseract.exe "
             "(auto-detected if omitted).",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Re-OCR PDFs even if outputs already exist.",
    )
    args = ap.parse_args()

    if not HAS_PYTESSERACT:
        print("[!] pytesseract not installed.")
        print("    Install with: python -m pip install pytesseract pillow")
        sys.exit(1)

    # --- Resolve + verify tesseract binary ---
    tesseract_cmd = resolve_tesseract(args.tesseract_path)
    verify_tesseract(tesseract_cmd)
    print()

    only_sources = set(args.sources) if args.sources else None

    if not ANALYSIS_CSV.exists():
        print(f"[!] Analysis CSV not found: {ANALYSIS_CSV}")
        print("    Run analyze_pdfs.py first.")
        sys.exit(1)

    targets = load_scanned_targets(ANALYSIS_CSV, only_sources)
    targets = filter_targets_by_files(targets, args.files)

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("[!] No SCANNED PDFs found for the given filters.")
        sys.exit(0)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # ---- Filter out already-done PDFs (unless --force) ----
    if not args.force:
        pending: list[dict] = []
        skipped = 0
        for t in targets:
            stem = Path(t["filename"]).stem
            txt = OUTPUT_ROOT / t["source"] / f"{stem}.txt"
            js = OUTPUT_ROOT / t["source"] / f"{stem}.blocks.json"
            if txt.exists() and js.exists():
                skipped += 1
                continue
            pending.append(t)
    else:
        pending = targets
        skipped = 0

    print(f"[*] Repo root        : {REPO_ROOT}")
    print(f"[*] Output root      : {OUTPUT_ROOT}")
    print(f"[*] DPI              : {args.dpi}")
    print(f"[*] Workers          : {args.workers}")
    print(f"[*] PSM / OEM / lang : {args.psm} / {args.oem} / {args.lang}")
    print(f"[*] Preprocess       : {args.preprocess}")
    if args.sources:
        print(f"[*] Sources filter   : {sorted(only_sources)}")
    if args.files:
        print(f"[*] Files filter     : {len(args.files)} filename(s)")
    print(f"[*] SCANNED in CSV   : {len(targets)}")
    print(f"[*] Already done     : {skipped}")
    print(f"[*] To process       : {len(pending)}")
    print()

    if not pending:
        print("[+] Nothing to do.")
        sys.exit(0)

    started = time.time()
    results: list[dict] = []

    # ---------- Single-process path ----------
    if args.workers <= 1:
        _worker_init(
            tesseract_cmd, args.psm, args.oem, args.lang, args.preprocess
        )
        for i, t in enumerate(pending, 1):
            r = _worker_run((
                t["source"], t["filename"],
                str(DOWNLOADS), str(OUTPUT_ROOT), args.dpi,
            ))
            results.append(r)
            _print_progress(i, len(pending), r)
    # ---------- Multi-process path ----------
    else:
        tasks = [
            (
                t["source"], t["filename"],
                str(DOWNLOADS), str(OUTPUT_ROOT), args.dpi,
            )
            for t in pending
        ]
        with mp.Pool(
            processes=args.workers,
            initializer=_worker_init,
            initargs=(
                tesseract_cmd, args.psm, args.oem, args.lang, args.preprocess
            ),
        ) as pool:
            for i, r in enumerate(
                pool.imap_unordered(_worker_run, tasks), 1
            ):
                results.append(r)
                _print_progress(i, len(pending), r)

    elapsed_total = time.time() - started

    # ---------- Aggregate ----------
    per_source: dict[str, dict] = defaultdict(lambda: {
        "total_pdfs": 0,
        "extracted": 0,
        "errors": 0,
        "total_pages": 0,
        "total_chars": 0,
        "total_blocks": 0,
        "total_conf": 0.0,
        "conf_count": 0,
        "total_elapsed": 0.0,
        "files": [],
    })

    for r in results:
        src = r["source"]
        s = per_source[src]
        s["total_pdfs"] += 1
        if r["status"] == "ok":
            s["extracted"] += 1
            s["total_pages"] += r.get("pages", 0)
            s["total_chars"] += r.get("chars", 0)
            s["total_blocks"] += r.get("ocr_blocks", 0)
            if r.get("ocr_blocks"):
                s["total_conf"] += r["avg_confidence"] * r["ocr_blocks"]
                s["conf_count"] += r["ocr_blocks"]
            s["total_elapsed"] += r.get("elapsed_sec", 0.0)
        else:
            s["errors"] += 1
        s["files"].append(r)

    # ---------- Manifests ----------
    generated_at = utcnow_iso()

    global_summary = {
        "generated_at": generated_at,
        "analysis_csv": str(ANALYSIS_CSV.relative_to(REPO_ROOT)),
        "engine": "Tesseract (pytesseract)",
        "tesseract_binary": tesseract_cmd,
        "dpi": args.dpi,
        "workers": args.workers,
        "psm": args.psm,
        "oem": args.oem,
        "lang": args.lang,
        "preprocess": args.preprocess,
        "total_scanned_in_csv": len(targets),
        "already_done": skipped,
        "processed_now": len(pending),
        "elapsed_sec_total": round(elapsed_total, 1),
        "sources": {},
        "totals": {
            "total_pdfs": 0,
            "extracted": 0,
            "errors": 0,
            "total_pages": 0,
            "total_chars": 0,
            "total_blocks": 0,
            "avg_confidence": 0.0,
            "total_elapsed_sec": 0.0,
        },
    }

    for source, s in sorted(per_source.items()):
        src_dir = OUTPUT_ROOT / source
        src_dir.mkdir(parents=True, exist_ok=True)

        avg_conf = (
            s["total_conf"] / s["conf_count"] if s["conf_count"] else 0.0
        )

        manifest = {
            "source": source,
            "generated_at": generated_at,
            "engine": "Tesseract",
            "psm": args.psm,
            "oem": args.oem,
            "lang": args.lang,
            "preprocess": args.preprocess,
            "dpi": args.dpi,
            "total_pdfs": s["total_pdfs"],
            "extracted": s["extracted"],
            "errors": s["errors"],
            "total_pages": s["total_pages"],
            "total_chars": s["total_chars"],
            "total_blocks": s["total_blocks"],
            "avg_confidence": round(avg_conf, 4),
            "total_elapsed_sec": round(s["total_elapsed"], 1),
            "files": s["files"],
        }
        (src_dir / "_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        global_summary["sources"][source] = {
            "total_pdfs": s["total_pdfs"],
            "extracted": s["extracted"],
            "errors": s["errors"],
            "total_pages": s["total_pages"],
            "total_chars": s["total_chars"],
            "total_blocks": s["total_blocks"],
            "avg_confidence": round(avg_conf, 4),
            "manifest_file": f"{source}/_manifest.json",
        }
        t = global_summary["totals"]
        t["total_pdfs"] += s["total_pdfs"]
        t["extracted"] += s["extracted"]
        t["errors"] += s["errors"]
        t["total_pages"] += s["total_pages"]
        t["total_chars"] += s["total_chars"]
        t["total_blocks"] += s["total_blocks"]
        t["total_elapsed_sec"] += s["total_elapsed"]

    if global_summary["totals"]["total_blocks"]:
        num = sum(s["total_conf"] for s in per_source.values())
        den = sum(s["conf_count"] for s in per_source.values())
        global_summary["totals"]["avg_confidence"] = round(num / den, 4)

    (OUTPUT_ROOT / "_manifest.json").write_text(
        json.dumps(global_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---------- Console summary ----------
    print()
    print("=" * 100)
    print(f"OCR COMPLETE   ({elapsed_total:.1f}s / {elapsed_total/60:.1f} min)")
    print("=" * 100)
    print(
        f"{'SOURCE':<18} {'DONE':>5} {'ERR':>4} {'PAGES':>7} "
        f"{'CHARS':>10} {'BLOCKS':>8} {'AVG CONF':>9} {'ELAPSED':>10}"
    )
    print("-" * 100)
    for source in sorted(per_source.keys()):
        s = per_source[source]
        conf = s["total_conf"] / s["conf_count"] if s["conf_count"] else 0.0
        print(
            f"{source:<18} {s['extracted']:>5} {s['errors']:>4} "
            f"{s['total_pages']:>7} {s['total_chars']:>10} "
            f"{s['total_blocks']:>8} {conf:>9.3f} "
            f"{s['total_elapsed']:>9.1f}s"
        )
    print("-" * 100)
    t = global_summary["totals"]
    print(
        f"{'TOTAL':<18} {t['extracted']:>5} {t['errors']:>4} "
        f"{t['total_pages']:>7} {t['total_chars']:>10} "
        f"{t['total_blocks']:>8} {t['avg_confidence']:>9.3f} "
        f"{t['total_elapsed_sec']:>9.1f}s"
    )
    print()
    print(f"[+] Global manifest : {OUTPUT_ROOT / '_manifest.json'}")
    print(f"[+] Per-source      : {OUTPUT_ROOT}/<source>/_manifest.json")


def _print_progress(i: int, total: int, r: dict) -> None:
    pct = 100.0 * i / total
    src = r.get("source", "?")
    pdf = r.get("pdf", "?")
    status = r.get("status")
    short = pdf[:55] + ("…" if len(pdf) > 55 else "")
    if status == "ok":
        print(
            f"[{i:>4}/{total:<4} {pct:>5.1f}%] OK   "
            f"{src:<15} {short} "
            f"pages={r.get('pages', 0)} chars={r.get('chars', 0)} "
            f"conf={r.get('avg_confidence', 0):.3f} "
            f"t={r.get('elapsed_sec', 0):.1f}s"
        )
    else:
        err = (r.get("err") or "")[:80]
        print(
            f"[{i:>4}/{total:<4} {pct:>5.1f}%] {status.upper():<5} "
            f"{src:<15} {short}  err={err}"
        )


if __name__ == "__main__":
    mp.freeze_support()   # required on Windows
    main()