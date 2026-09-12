from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILE = ROOT / "downloads" / "pdf_list.txt"
OUT_DIR = ROOT / "downloads" / "priority_lists"

GROUP_ORDER = ["alerts", "banned_drugs", "fdc", "gazette", "ipc_pvpi", "public_notices"]


def normalize(name: str) -> str:
    s = name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s


def classify(group: str, filename: str) -> str:
    n = normalize(filename)

    if group in {"alerts", "banned_drugs", "ipc_pvpi"}:
        return "important"

    if group == "fdc":
        if any(t in n for t in [
            "prohibited", "banned", "restricted", "restriction", "unapproved",
            "irrational", "section_26a", "prohibition", "manufacturing_and_marketing_of_unapproved",
            "manufacturing_and_marketing_of_certain_fdc", "safety_and_efficacy", "fdc_of",
            "prohibited_fdc", "list_of_02_restricted_fdc_drugs", "list_of_prohibited_fdc_drugs"
        ]):
            return "important"
        return "unimportant"

    if group == "gazette":
        if any(t in n for t in [
            "prohibit", "prohibition", "banned", "ban", "restricted", "restriction",
            "schedule_h1", "schedule_h", "schedule_m", "schedule_k", "section_26a",
            "not_of_standard", "spurious", "adulterated", "misbranded", "oxytocin",
            "antimicrobial", "alcohol_content", "medical_device_rules", "new_drugs",
            "clinical_trial", "labelling", "debarment", "rule_96", "rule_89", "rule_121",
            "rule_31", "rule_43a", "drug_rules", "fda", "medical_devices_rule"
        ]):
            return "important"
        if any(t in n for t in [
            "government_analyst", "appointment", "notification_of", "designation",
            "laboratory", "testing_officer", "airport", "meeting", "circular",
            "draft_notification", "rti", "stakeholder", "form_", "license", "licence",
            "amendment_in", "amendment_of", "inclusion_of", "sugam", "portal"
        ]):
            return "unimportant"
        return "unimportant"

    if group == "public_notices":
        if any(t in n for t in [
            "alert", "recall", "falsified", "prohibit", "prohibition", "banned",
            "restricted", "restriction", "adverse_event", "medical_device_alert",
            "spurious", "safety", "unapproved", "irrational", "not_of_standard",
            "sub_standard", "fdc", "section_26a", "drug"
        ]):
            return "important"
        return "unimportant"

    return "unimportant"


def parse_entries() -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {g: [] for g in GROUP_ORDER}
    current = None

    for raw_line in SOURCE_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if raw_line.startswith("### "):
            group = raw_line.replace("### ", "").strip().split(" (", 1)[0].strip()
            current = group if group in entries else None
            continue

        match = re.match(r"\s*\d+\.\s*(.+?\.pdf)\s*$", raw_line)
        if match and current:
            entries[current].append(match.group(1).strip())

    return entries


def write_group_lists(entries: dict[str, list[str]]) -> dict[str, dict[str, int]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats: dict[str, dict[str, int]] = {}

    for group in GROUP_ORDER:
        files = entries.get(group, [])
        important = [f for f in files if classify(group, f) == "important"]
        unimportant = [f for f in files if classify(group, f) != "important"]

        imp_path = OUT_DIR / f"{group}_important.txt"
        unimp_path = OUT_DIR / f"{group}_unimportant.txt"
        imp_path.write_text("\n".join(important) + ("\n" if important else ""), encoding="utf-8")
        unimp_path.write_text("\n".join(unimportant) + ("\n" if unimportant else ""), encoding="utf-8")

        stats[group] = {"important": len(important), "unimportant": len(unimportant)}

    combined_import = []
    combined_unimport = []
    for group in GROUP_ORDER:
        for f in entries.get(group, []):
            if classify(group, f) == "important":
                combined_import.append(f"[{group}] {f}")
            else:
                combined_unimport.append(f"[{group}] {f}")

    (OUT_DIR / "important_list.txt").write_text(
        "\n".join(combined_import) + ("\n" if combined_import else ""),
        encoding="utf-8",
    )
    (OUT_DIR / "unimportant_list.txt").write_text(
        "\n".join(combined_unimport) + ("\n" if combined_unimport else ""),
        encoding="utf-8",
    )

    summary_lines = [
        "Medicine scanner PDF priority classification",
        "Source: downloads/pdf_list.txt",
        "",
    ]
    for group in GROUP_ORDER:
        s = stats[group]
        summary_lines.append(f"{group}: important={s['important']}, unimportant={s['unimportant']}")
    total_important = sum(s["important"] for s in stats.values())
    total_unimportant = sum(s["unimportant"] for s in stats.values())
    summary_lines.extend(["", f"Total important={total_important}", f"Total unimportant={total_unimportant}"])
    (OUT_DIR / "summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")

    return stats


if __name__ == "__main__":
    entries = parse_entries()
    stats = write_group_lists(entries)
    print("Classification complete")
    for group in GROUP_ORDER:
        print(f"{group}: important={stats[group]['important']}, unimportant={stats[group]['unimportant']}")
