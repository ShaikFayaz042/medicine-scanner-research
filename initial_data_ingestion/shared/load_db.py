"""
Database Loader Module: Idempotently loads validated CSV staging data into PostgreSQL,
mapping canonical keys to surrogate BIGSERIAL IDs within atomic transactions.
"""

import os
import csv
import json
import re
from typing import Dict, Any, List, Optional

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def load_dotenv_file(env_path: str = ".env"):
    """Simple zero-dependency .env file loader."""
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val


def get_db_connection(db_uri: str = "postgresql://localhost:5432/medicine_regulatory_db"):
    """Get psycopg2 connection from DB URI or environment variables / .env file."""
    if not HAS_PSYCOPG2:
        raise ImportError("psycopg2-binary is required for PostgreSQL loading. Install with `pip install psycopg2-binary`.")
    
    # Auto-load .env file if present
    load_dotenv_file(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    load_dotenv_file(".env")

    # Environment variable fallbacks
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    dbname = os.getenv("PGDATABASE", "medicine_regulatory_db")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "postgres")
    
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )


def parse_db_date(val: Optional[str]) -> Optional[str]:
    """Safely parse date strings into ISO YYYY-MM-DD for PostgreSQL DATE columns."""
    if not val or not str(val).strip():
        return None
    s = str(val).strip()

    # 1. Standard YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s

    # 2. MM/YYYY or MM-YYYY
    m = re.match(r'^(\d{1,2})[-/](\d{4})$', s)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}-01"

    # 3. YYYY/MM or YYYY-MM
    m = re.match(r'^(\d{4})[-/](\d{1,2})$', s)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}-01"

    # 4. DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$', s)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}-{day:02d}"

    # 5. Extract date inside strings (e.g. "08/2022")
    m = re.search(r'\b(\d{1,2})[-/](\d{4})\b', s)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return f"{year:04d}-{month:02d}-01"

    return None


def load_staging_to_db(staging_dir: str, db_connection=None, db_uri: Optional[str] = None) -> Dict[str, int]:
    """
    Load validated staging CSV files into PostgreSQL in dependency order.
    Returns dictionary with counts of loaded records per table.
    """
    owns_connection = db_connection is None
    conn = db_connection or get_db_connection(db_uri or "postgresql://localhost:5432/medicine_regulatory_db")
    if owns_connection:
        conn.autocommit = False

    counts = {}

    def progress(table: str, loaded: int) -> None:
        if loaded and loaded % 1000 == 0:
            print(f"[load] {table}: {loaded} rows", flush=True)

    try:
        with conn.cursor() as cur:
            # 1. regulatory_documents
            doc_path = os.path.join(staging_dir, "regulatory_documents.csv")
            doc_map = {}
            if os.path.exists(doc_path):
                with open(doc_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        cur.execute("""
                            INSERT INTO regulatory_documents (
                                source_organization, source_document_id, filename,
                                document_title, publication_date, reporting_period,
                                source_url, file_hash, document_type
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (source_organization, source_document_id) DO NOTHING;
                        """, (
                            row["source_organization"],
                            row["source_document_id"],
                            row["filename"],
                            row["document_title"] or None,
                            parse_db_date(row["publication_date"]),
                            row["reporting_period"] or None,
                            row["source_url"],
                            row["file_hash"] or None,
                            row["document_type"] or None
                        ))

                        cur.execute("""
                            SELECT document_id FROM regulatory_documents
                            WHERE source_organization = %s AND source_document_id = %s;
                        """, (row["source_organization"], row["source_document_id"]))
                        res = cur.fetchone()
                        if res:
                            doc_map[row["source_document_id"]] = res[0]
            counts["regulatory_documents"] = len(doc_map)

            # 2. organizations
            org_path = os.path.join(staging_dir, "organizations.csv")
            org_map = {}
            if os.path.exists(org_path):
                with open(org_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        if not row["organization_key"]:
                            continue
                        cur.execute("""
                            INSERT INTO organizations (
                                organization_key, organization_name, normalized_name, address, state, country
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (organization_key) DO NOTHING;
                        """, (
                            row["organization_key"],
                            row["organization_name"],
                            row["normalized_name"] or None,
                            row["address"] or None,
                            row["state"] or None,
                            row["country"] or 'India'
                        ))

                        cur.execute("""
                            SELECT organization_id FROM organizations WHERE organization_key = %s;
                        """, (row["organization_key"],))
                        res = cur.fetchone()
                        if res:
                            org_map[row["organization_key"]] = res[0]
                        progress("organizations", len(org_map))
            counts["organizations"] = len(org_map)

            # 3. ingredients
            ing_path = os.path.join(staging_dir, "ingredients.csv")
            ing_map = {}
            if os.path.exists(ing_path):
                with open(ing_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        if not row["ingredient_key"]:
                            continue
                        cur.execute("""
                            INSERT INTO ingredients (
                                ingredient_key, ingredient_name, normalized_name, cas_number
                            ) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (ingredient_key) DO NOTHING;
                        """, (
                            row["ingredient_key"],
                            row["ingredient_name"],
                            row["normalized_name"] or None,
                            row["cas_number"] or None
                        ))

                        cur.execute("""
                            SELECT ingredient_id FROM ingredients WHERE ingredient_key = %s;
                        """, (row["ingredient_key"],))
                        res = cur.fetchone()
                        if res:
                            ing_map[row["ingredient_key"]] = res[0]
                        progress("ingredients", len(ing_map))
            counts["ingredients"] = len(ing_map)

            # 4. products
            prod_path = os.path.join(staging_dir, "products.csv")
            prod_map = {}
            if os.path.exists(prod_path):
                with open(prod_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        if not row["product_key"]:
                            continue
                        cur.execute("""
                            INSERT INTO products (
                                product_key, product_name, normalized_name, brand_name, dosage_form, strength, product_category
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (product_key) DO NOTHING;
                        """, (
                            row["product_key"],
                            row["product_name"],
                            row["normalized_name"] or None,
                            row["brand_name"] or None,
                            row["dosage_form"] or None,
                            row["strength"] or None,
                            row["product_category"]
                        ))

                        cur.execute("""
                            SELECT product_id FROM products WHERE product_key = %s;
                        """, (row["product_key"],))
                        res = cur.fetchone()
                        if res:
                            prod_map[row["product_key"]] = res[0]
                        progress("products", len(prod_map))
            counts["products"] = len(prod_map)

            # 5. product_ingredients
            pi_path = os.path.join(staging_dir, "product_ingredients.csv")
            pi_count = 0
            if os.path.exists(pi_path):
                with open(pi_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        p_id = prod_map.get(row["product_key"])
                        i_id = ing_map.get(row["ingredient_key"])
                        if p_id and i_id:
                            cur.execute("""
                                INSERT INTO product_ingredients (product_id, ingredient_id, ingredient_strength)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (product_id, ingredient_id) DO NOTHING;
                            """, (p_id, i_id, row["ingredient_strength"] or None))
                            pi_count += 1
                            progress("product_ingredients", pi_count)
            counts["product_ingredients"] = pi_count

            # 6. product_organizations
            po_path = os.path.join(staging_dir, "product_organizations.csv")
            po_count = 0
            if os.path.exists(po_path):
                with open(po_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        p_id = prod_map.get(row["product_key"])
                        o_id = org_map.get(row["organization_key"])
                        if p_id and o_id:
                            cur.execute("""
                                INSERT INTO product_organizations (product_id, organization_id, role)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (product_id, organization_id, role) DO NOTHING;
                            """, (p_id, o_id, row["role"]))
                            po_count += 1
                            progress("product_organizations", po_count)
            counts["product_organizations"] = po_count

            # 7. batches
            b_path = os.path.join(staging_dir, "batches.csv")
            batch_map = {}
            if os.path.exists(b_path):
                with open(b_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        if not row["batch_key"]:
                            continue
                        p_id = prod_map.get(row["product_key"])
                        o_id = org_map.get(row["organization_key"])
                        cur.execute("""
                            INSERT INTO batches (
                                batch_key, product_id, organization_id, batch_number, manufacturing_date, expiry_date
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (batch_key) DO NOTHING;
                        """, (
                            row["batch_key"],
                            p_id,
                            o_id,
                            row["batch_number"],
                            parse_db_date(row["manufacturing_date"]),
                            parse_db_date(row["expiry_date"])
                        ))

                        cur.execute("""
                            SELECT batch_id FROM batches WHERE batch_key = %s;
                        """, (row["batch_key"],))
                        res = cur.fetchone()
                        if res:
                            batch_map[row["batch_key"]] = res[0]
                        progress("batches", len(batch_map))
            counts["batches"] = len(batch_map)

            # 8. raw_source_records
            rs_path = os.path.join(staging_dir, "raw_source_records.csv")
            rs_count = 0
            if os.path.exists(rs_path):
                with open(rs_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        d_id = doc_map.get(row["source_document_id"])
                        if d_id:
                            cur.execute("""
                                INSERT INTO raw_source_records (
                                    document_id, source_record_id, page_number, source_location,
                                    extraction_method, source_text, raw_json
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (document_id, source_record_id) DO NOTHING;
                            """, (
                                d_id,
                                row["source_record_id"],
                                int(row["page_number"]) if row["page_number"] else None,
                                row["source_location"] or None,
                                row["extraction_method"] or None,
                                row["source_text"] or None,
                                row["raw_json"] or None
                            ))
                            rs_count += 1
                            progress("raw_source_records", rs_count)
            counts["raw_source_records"] = rs_count

            # 9. regulatory_events
            ev_path = os.path.join(staging_dir, "regulatory_events.csv")
            ev_count = 0
            if os.path.exists(ev_path):
                with open(ev_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        d_id = doc_map.get(row["source_document_id"])
                        p_id = prod_map.get(row["product_key"])
                        b_id = batch_map.get(row["batch_key"])
                        mfg_o_id = org_map.get(row["manufacturer_organization_key"])
                        rep_o_id = org_map.get(row["reporting_organization_key"])

                        if d_id:
                            cur.execute("""
                                INSERT INTO regulatory_events (
                                    event_key, document_id, source_record_id, event_type, event_date,
                                    scope, product_id, batch_id, manufacturer_organization_id,
                                    reporting_organization_id, status, reason, action, legal_status, additional_data
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (event_key) DO NOTHING;
                            """, (
                                row["event_key"],
                                d_id,
                                row["source_record_id"],
                                row["event_type"],
                                parse_db_date(row["event_date"]),
                                row["scope"],
                                p_id,
                                b_id,
                                mfg_o_id,
                                rep_o_id,
                                row["status"] or None,
                                row["reason"] or None,
                                row["action"] or None,
                                row["legal_status"] or None,
                                row["additional_data"] or None
                            ))
                            ev_count += 1
                            progress("regulatory_events", ev_count)
            counts["regulatory_events"] = ev_count

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        if owns_connection:
            conn.close()

    return counts
