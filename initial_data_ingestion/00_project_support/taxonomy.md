# Controlled Vocabularies & Taxonomy Specification — Frozen

This document specifies the frozen controlled vocabularies and enums for `event_type`, `status`, `scope`, `review_reason`, `document_type`, `product_category`, `product_organization_role`, `normalization_status`, and `validation_status`.

---

## 📋 Active Ingestion Scope (Locked)

### Accepted Document Types (Active Ingestion)

| Doc Type ID | Document Category Name | Group Type | Ingestion Scope |
|---|---|---|---|
| `Doc 1` | Banned Drugs | Banned Drugs | 🔴 Prohibited Drug Lists (Section 26A) |
| `Doc 2` | List of Drugs Safety Alerts issued by PvPI | Pharmacovigilance | ⚠️ Adverse Drug Reaction (ADR) Alerts |
| `Doc 3` | NSQ Drugs (State Lab Format) | Quality Failures | 🟠 Not of Standard Quality (State DTLs) |
| `Doc 4` | Spurious Drugs Alerts | Quality Failures | 🔴 Spurious / Counterfeit Alerts |
| `Doc 5` | CDSCO Drug Alerts (CDSCO Lab Format) | Quality Failures | 🟠 Not of Standard Quality (CDSCO Labs) |
| `Doc 6` | Legacy CDSCO Monthly Drug Alerts (2013-2018) | Quality Failures | 🟠 Legacy Quality Failure Alerts |
| `Doc 7` | Medical Device & IVD Safety Alerts | Device Alerts | ⚠️ Medical Device Recalls & Alerts |
| `Doc 8` | Approved New Drugs & Marketing Authorizations | Approvals & NOCs | 🟢 Approved New Drug Approvals |
| `Doc 11` | NOC & Import Permissions Tracking | Approvals & NOCs | 🟢 Permitted FDCs (Category C / 2237) |

### 🚫 Excluded / Ignored Document Types, Folders & Files

The following folders, document types, and files are **strictly ignored** during database ingestion:
- **Excluded Folders:** `08_json_conversion/output/gazette`, `08_json_conversion/output/public_notices`
- **Excluded Specific Files:**
  - ❌ `514_Notice_Order_regarding_Examination_of_Safety_and_efficacy_of_FDCs...`
  - ❌ `8616_Medical_Device_Alert_date_14_June_2022.json`
  - ❌ `7684_Alert_FSN-Medtronic_Heartware_HVAD.json`
- **Excluded Doc Types:**
  - ❌ `Doc 9`: FDC Evaluation & Committee Status List
  - ❌ `Doc 10`: Subject Expert Committee (SEC) & NDAC Meeting Schedules
  - ❌ `Doc 12`: Vaccine Manufacturing Facility Inspection Status
  - ❌ `Doc 13`: Approved Diagnostic / PCR Testing Kits List
  - ❌ `Doc 14`: Performance Evaluation Laboratories for IVD Analyzers & Software
  - ❌ `Doc 15`: Regulatory Fee Schedule & Checklist
  - ❌ `Doc 16`: Gazette Notification Drug Prohibition Extraordinaries

---

## 1. `event_type` Taxonomy

| Event Type | Description / Intended Use | Typical Source Examples |
|---|---|---|
| `BANNED` | Record identifying a banned/prohibited drug or formulation. | Gazette notification, banned drug list |
| `PROHIBITED` | Explicit prohibition/restriction action by regulatory authority. | Section 26A prohibition, restricted FDC |
| `NSQ` | Not of Standard Quality / sub-standard quality finding. | State FDA, CDSCO drug alert |
| `SPURIOUS` | Spurious / counterfeit / fake medicine alert or report. | Spurious drug alert |
| `ADR` | Pharmacovigilance / adverse drug reaction alert. | PvPI safety alert |
| `RECALL` | Market recall or withdrawal action against a product/batch. | Recall notice |
| `APPROVAL` | Marketing authorization or drug approval decision. | CDSCO approved new drugs list |
| `NOC` | No Objection Certificate or permission event. | CDSCO NOC list |
| `IMPORT_PERMISSION` | Permission relating to import of drug/product. | Import permission records |
| `SAFETY_ADVISORY` | General safety advisory or communication. | Safety advisory |
| `SUSPENSION` | Temporary regulatory suspension of sale/manufacture/approval. | Suspension order |
| `WITHDRAWAL` | Permanent withdrawal action when distinct from recall. | Withdrawal notice |
| `UNDER_INVESTIGATION` | Record indicates ongoing regulatory investigation. | Regulatory investigation notice |
| `OTHER` | Controlled escape hatch for unmapped actions (logged for review). | Exceptional document action |

---

## 2. `review_reason` Controlled Vocabulary

The allowed `review_reason` values for `normalization_manifest.csv`:

```text
missing_product_name   — Product name missing or completely unparseable
missing_batch_number   — Batch number missing on a BATCH-scoped event (e.g. NSQ)
nsq_without_batch      — NSQ alert row missing lot/batch identification
ambiguous_organization — Manufacturer/organization could match multiple candidates
ambiguous_product      — Product formulation matches multiple candidate catalog items
invalid_date_format    — Manufacturing, expiry, or event date cannot be standardized
unparseable_row        — Source row structure corrupted or unparseable
duplicate_fingerprint  — Duplicate content fingerprint detected across source pages
excluded_document_type — Document type is in the locked exclusion list (Doc 9, 10, 12-16)
```

---

## 3. Staging Control Vocabularies

### `normalization_status`
```text
COMPLETE     — Successfully extracted and canonicalized
NEEDS_REVIEW — Requires human inspection or review queue action
IGNORED      — Non-actionable header / excluded document type intentionally skipped
FAILED       — Fatal normalization error
```

### `validation_status`
```text
PENDING — Staging generated; awaiting validation run
VALID   — All integrity and reconciliation constraints passed
INVALID — Validation failure detected; load blocked
```
