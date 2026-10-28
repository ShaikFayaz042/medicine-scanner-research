# analysis/scripts/scanned/main.py
import argparse
from .pipeline import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Classify scanned OCR JSONs by taxonomy.")
    ap.add_argument("--dry-run", action="store_true", help="preview, do not write")
    run(ap.parse_args().dry_run)