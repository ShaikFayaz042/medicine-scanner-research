"""
Staging Module: Outputs resolved entity and event records into staging CSV files
and generates normalization_manifest.csv for audit lineage and validation.
"""

import os
import json
import csv
from typing import Dict, Any, List


def write_staging_csvs(
    header_metadata: Dict[str, Any],
    resolved_records: List[Dict[str, Any]],
    output_dir: str
) -> Dict[str, str]:
    """
    Write resolved records into staging CSV files in output_dir.
    Returns dictionary mapping CSV name to absolute file path.
    """
    os.makedirs(output_dir, exist_ok=True)
    created_files = {}

    doc_id = header_metadata.get("source_document_id") or header_metadata["filename"]

    # 1. regulatory_documents.csv
    doc_path = os.path.join(output_dir, "regulatory_documents.csv")
    with open(doc_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_organization", "source_document_id", "filename",
            "document_title", "publication_date", "reporting_period",
            "source_url", "file_hash", "document_type"
        ])
        writer.writerow([
            header_metadata.get("source_organization"),
            doc_id,
            header_metadata.get("filename"),
            header_metadata.get("document_title"),
            header_metadata.get("publication_date") or "",
            header_metadata.get("reporting_period") or "",
            header_metadata.get("source_url"),
            header_metadata.get("file_hash"),
            header_metadata.get("document_type")
        ])
    created_files["regulatory_documents.csv"] = doc_path

    # Deduplicate entities for staging files
    unique_orgs = {}
    unique_products = {}
    unique_batches = {}
    unique_ingredients = {}
    product_ingredients = set()
    product_orgs = set()
    
    raw_records_rows = []
    events_rows = []
    manifest_rows = []

    for r in resolved_records:
        src_rec_id = r["source_record_id"]

        # Raw source records
        raw_json_str = json.dumps(r["raw_json"], ensure_ascii=False) if isinstance(r["raw_json"], (dict, list)) else str(r["raw_json"])
        raw_records_rows.append([
            doc_id,
            src_rec_id,
            r["page_number"],
            r["source_location"],
            r["extraction_method"],
            r["source_text"],
            raw_json_str
        ])

        # Organizations
        if r["manufacturer_organization_key"] and r["manufacturer_name"]:
            m_key = r["manufacturer_organization_key"]
            if m_key not in unique_orgs:
                unique_orgs[m_key] = [
                    m_key,
                    r["manufacturer_name"],
                    r["normalized_manufacturer_name"],
                    r["manufacturer_address"] or "",
                    r["manufacturer_state"] or "",
                    r["country"] or "India"
                ]

        if r["reporting_organization_key"] and r["reporting_organization_name"]:
            rep_key = r["reporting_organization_key"]
            if rep_key not in unique_orgs:
                unique_orgs[rep_key] = [
                    rep_key,
                    r["reporting_organization_name"],
                    r["normalized_reporting_organization_name"],
                    r["reporting_organization_address"] or "",
                    r["reporting_organization_state"] or "",
                    r["country"] or "India"
                ]

        for details in r.get("organization_role_details", {}).values():
            if details["key"] and details["name"] and details["key"] not in unique_orgs:
                unique_orgs[details["key"]] = [
                    details["key"],
                    details["name"],
                    details["name"].lower(),
                    details["address"],
                    details["state"],
                    r["country"] or "India",
                ]

        # Products
        if r["product_key"] and r["product_name"]:
            p_key = r["product_key"]
            if p_key not in unique_products:
                unique_products[p_key] = [
                    p_key,
                    r["product_name"],
                    r["normalized_product_name"],
                    r["brand_name"] or "",
                    r["dosage_form"] or "",
                    r["strength"] or "",
                    r["product_category"]
                ]

            for ingredient in r.get("ingredients", []):
                if ingredient.get("ingredient_key") and ingredient.get("name"):
                    i_key = ingredient["ingredient_key"]
                    unique_ingredients[i_key] = [
                        i_key,
                        ingredient["name"],
                        ingredient["name"].lower(),
                        ingredient.get("cas_number") or "",
                    ]
                    product_ingredients.add((p_key, i_key, ingredient.get("strength") or ""))

            # Product-organization relationships from explicit source roles.
            for role, organization_key_value in r.get("organization_roles", {}).items():
                if organization_key_value:
                    product_orgs.add((p_key, organization_key_value, role))

        # Batches
        if r["batch_key"] and r["batch_number"]:
            b_key = r["batch_key"]
            if b_key not in unique_batches:
                unique_batches[b_key] = [
                    b_key,
                    r["product_key"] or "",
                    r["manufacturer_organization_key"] or "",
                    r["batch_number"],
                    r["manufacturing_date"] or "",
                    r["expiry_date"] or ""
                ]

        # Regulatory Events
        add_data_str = json.dumps(r["additional_data"], ensure_ascii=False)
        events_rows.append([
            r["event_key"],
            doc_id,
            src_rec_id,
            r["event_type"],
            r["event_date"] or "",
            r["scope"],
            r["product_key"] or "",
            r["batch_key"] or "",
            r["manufacturer_organization_key"] or "",
            r["reporting_organization_key"] or "",
            r["status"] or "",
            r["reason"] or "",
            r["action"] or "",
            r["legal_status"] or "",
            add_data_str
        ])

        # Normalization Manifest
        manifest_rows.append([
            src_rec_id,
            doc_id,
            header_metadata["filename"],
            r["page_number"],
            r["source_location"],
            header_metadata["document_type"],
            r["manufacturer_organization_key"] or "",
            r["product_key"] or "",
            r["batch_key"] or "",
            r["event_key"],
            r["normalization_status"],
            r["validation_status"],
            r["review_reason"] or "",
            r["error_message"] or ""
        ])

    # 2. raw_source_records.csv
    rs_path = os.path.join(output_dir, "raw_source_records.csv")
    with open(rs_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_document_id", "source_record_id", "page_number",
            "source_location", "extraction_method", "source_text", "raw_json"
        ])
        writer.writerows(raw_records_rows)
    created_files["raw_source_records.csv"] = rs_path

    # 3. organizations.csv
    org_path = os.path.join(output_dir, "organizations.csv")
    with open(org_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "organization_key", "organization_name", "normalized_name",
            "address", "state", "country"
        ])
        writer.writerows(unique_orgs.values())
    created_files["organizations.csv"] = org_path

    # 4. ingredients.csv
    ing_path = os.path.join(output_dir, "ingredients.csv")
    with open(ing_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["ingredient_key", "ingredient_name", "normalized_name", "cas_number"])
        writer.writerows(unique_ingredients.values())
    created_files["ingredients.csv"] = ing_path

    # 5. products.csv
    prod_path = os.path.join(output_dir, "products.csv")
    with open(prod_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "product_key", "product_name", "normalized_name",
            "brand_name", "dosage_form", "strength", "product_category"
        ])
        writer.writerows(unique_products.values())
    created_files["products.csv"] = prod_path

    # 6. product_ingredients.csv
    pi_path = os.path.join(output_dir, "product_ingredients.csv")
    with open(pi_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["product_key", "ingredient_key", "ingredient_strength"])
        writer.writerows(product_ingredients)
    created_files["product_ingredients.csv"] = pi_path

    # 7. product_organizations.csv
    po_path = os.path.join(output_dir, "product_organizations.csv")
    with open(po_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["product_key", "organization_key", "role"])
        writer.writerows(product_orgs)
    created_files["product_organizations.csv"] = po_path

    # 8. batches.csv
    b_path = os.path.join(output_dir, "batches.csv")
    with open(b_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "batch_key", "product_key", "organization_key",
            "batch_number", "manufacturing_date", "expiry_date"
        ])
        writer.writerows(unique_batches.values())
    created_files["batches.csv"] = b_path

    # 9. regulatory_events.csv
    ev_path = os.path.join(output_dir, "regulatory_events.csv")
    with open(ev_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "event_key", "source_document_id", "source_record_id",
            "event_type", "event_date", "scope",
            "product_key", "batch_key", "manufacturer_organization_key",
            "reporting_organization_key", "status", "reason",
            "action", "legal_status", "additional_data"
        ])
        writer.writerows(events_rows)
    created_files["regulatory_events.csv"] = ev_path

    # 10. normalization_manifest.csv
    m_path = os.path.join(output_dir, "normalization_manifest.csv")
    with open(m_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_record_id", "source_document_id", "source_file",
            "source_page", "source_row", "source_document_type",
            "organization_key", "product_key", "batch_key", "event_key",
            "normalization_status", "validation_status", "review_reason",
            "error_message"
        ])
        writer.writerows(manifest_rows)
    created_files["normalization_manifest.csv"] = m_path

    return created_files
