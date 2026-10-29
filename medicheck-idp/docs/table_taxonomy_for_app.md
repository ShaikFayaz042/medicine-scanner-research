# CDSCO Corpus — Table Taxonomy & App Priority Map

Version: 1.0
Generated from: full_corpus_classified.csv + table_types_extraction.json
Raw distinct types detected: 672
Genuine distinct schemas (deduped): ~45–55
High-volume archetypes: ~16

---

# PART 1 — MASTER TABLE CATALOGUE

Legend:

- **ID** = archetype letter (A–AV)
- **Docs** = approx number of source PDFs using this schema
- **Classification** = current MediCheck use (Usable, Future-usable, or Non-usable)
- **Priority** = extraction order within the current app scope (P0 first, then P1); future-use priorities are conditional on a feature expansion

## Classification rules

- **Usable:** directly supports current medicine identification, batch-level quality checks, falsified-product checks, regulatory warnings, recalls, or safety alerts.
- **Future-usable:** retain and classify, but defer extraction until the relevant reference, analytics, device, veterinary, or other feature is in scope.
- **Non-usable:** do not prioritize extraction into the current consumer app database; retain original source documents as needed.
- A missing match is not proof that a medicine is safe, genuine, approved, or unrestricted. Present confirmed findings separately from unsuccessful searches.
- For mixed-product records, classify each record by product type and use medicine-related entries only. Preserve the source reference, publication date, exact regulatory wording, and verification date. Historical approval is not proof of current status.

---

## A. CDSCO Monthly Drug Alert / NSQ List  [Classification: Usable | Priority: P0]

**Docs:** 85+
**Columns:**

| # | Canonical      | Variants seen                          |
| - | -------------- | -------------------------------------- |
| 1 | sno            | S.No, Sr.No, Sl.No, S.NO, S.N o        |
| 2 | product_name   | Name of Drugs/medical device/cosmetics |
| 3 | batch_no       | Batch No.                              |
| 4 | mfg_date       | Date of Manufacture, Mfg Date          |
| 5 | exp_date       | Date of Expiry, Exp Date               |
| 6 | manufacturer   | Manufactured By                        |
| 7 | failure_reason | Reason for failure                     |
| 8 | drawn_by       | Drawn By (From state/CDSCO Zone)       |
| 9 | lab            | From (Name of Laboratory), From        |

**Optional add-on columns:** report_no_form13, remarks, firms_reply
**Composite variant:** `Batch No./Date of Manufacture/Date of Expiry/Manufactured By` (one cell — split into 4)
**Sample files:**

- 10069_Drug_Alert_list_for_month_of_March_2023.pdf
- 10154_Drug_Alert_list_for_month_of_April_2023.pdf
- 10359_Drug_Alert_list_for_month_of_June_2023.pdf
- 10425_Drug_Alert_list_for_month_of_July_2023.pdf
- 10515_Drug_Alert_list_for_month_of_August_2023.pdf
- 10666_Drug_Alert_for_the_Month_of_October_2023.pdf
- 10784_Drug_Alert_for_the_Month_of_November_2023.pdf
- 10851_Drug_Alert_for_the_Month_of_December_2023.pdf
- 10939_Drug_Alert_for_the_Month_of_January_2024.pdf
- 11013_Drug_Alert_for_the_Month_of_February_2024.pdf
- 11115_Drug_Alert_for_the_Month_of_March_2024.pdf
- 12010_Drug_Alert_for_the_Month_of_August_2024.pdf
- 12084_Drug_Alert_for_the_Month_of_September_2024.pdf
- 12204_Drug_Alert_for_the_Month_of_October_2024.pdf
- 12292_Drug_Alert_for_the_Month_of_November_2024.pdf
- 12393_Drug_Alert_for_the_Month_of_December_2024.pdf
- + all 2013–2022 monthly alert PDFs (~60 more)

---

## B. State NSQ Alert  [Classification: Usable | Priority: P0]

**Docs:** 12+
**Columns:** Same as A, but `lab` = State lab, `nsq_result` = free text

| # | Canonical    | Variants                     |
| - | ------------ | ---------------------------- |
| 1 | sno          | S.No, Sr.No                  |
| 2 | product_name | Product/Drug Name            |
| 3 | batch_no     | Batch No.                    |
| 4 | mfg_date     | Manufacturing Date           |
| 5 | exp_date     | Expiry Date                  |
| 6 | manufacturer | Manufactured By              |
| 7 | nsq_result   | NSQ Result                   |
| 8 | lab          | Reported by State Laboratory |

**Sample files:**

- 11467_State_NSQ_ALERT_FOR_THE_MONTH_OF_JUNE_2024.pdf
- 11601_STATE_NSQ_ALERT_FOR_THE_MONTH_OF_July-2024.pdf
- 12012_State_Drug_Alert_for_the_Month_of_August_2024.pdf
- 12083_State_Drug_Alert_for_the_Month_of_September_2024.pdf
- 12202_State_Drug_Alert_for_the_Month_of_October_2024.pdf
- 12290_State_Drug_Alert_for_the_Month_of_November_2024.pdf
- 12394_State_Drug_Alert_for_the_Month_of_December_2024.pdf
- 12556_STATE_NSQ_ALERT_FOR_THE_MONTH_OF_JANUARY-2025.pdf
- 12614_STATE_NSQ_ALERT_FOR_THE_MONTH_OF_FEBRUARY-2025.pdf
- 12668_State_NSQ_Alert_For_The_Month_March-2025.pdf
- 12739_State_NSQ_Alert_For_The_Month_April-2025.pdf
- 12846_STATE_NSQ_ALERT_FOR_THE_MONTH_OF_MAY-2025.pdf
- 12926_STATE_NSQ_ALERT_FOR_THE_MONTH_OF_June_2025.pdf

---

## C. Spurious Drug List  [Classification: Usable | Priority: P0]

**Docs:** 10+
**Columns:**

| #  | Canonical      | Variants                                       |
| -- | -------------- | ---------------------------------------------- |
| 1  | sno            | S.No                                           |
| 2  | product_name   | Name of Drugs/medical device/cosmetics         |
| 3  | batch_no       | Batch No., B.No.                               |
| 4  | mfg_date       | Date of Manufacture                            |
| 5  | exp_date       | Date of Expiry                                 |
| 6  | manufacturer   | Manufactured By (often "Under Investigation")  |
| 7  | failure_reason | Reason for failure                             |
| 8  | drawn_by       | Drawn By                                       |
| 9  | firms_reply    | Firm's reply                                   |
| 10 | remarks        | Remarks (contains "spurious / section 17B(e)") |

**Mixed-document rule:** classify tables and records independently. Individual spurious-sample records with a specific product and batch, manufacturer, sample identifier, and supporting investigation or test findings are Usable for historical batch identification. Brand-level survey summaries and aggregate sample counts are Future-usable only; they must not drive an individual product or batch verdict.

**Sample files:**

- 11255_SPURIOUS_ALERT_FOR_THE_MONTH_OF_APRIL_2024.pdf
- 12011_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_Adulterated_Misbranded_for_the_Month_of_August.pdf
- 12082_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_September_2024.pdf
| C | Spurious Drug List | Official spurious-product and batch checks; use batch-specific survey records, not brand-level aggregate findings | P0 |
- 12291_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_November_2024.pdf
- 12612_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_February-2025.pdf
- 12667_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_March-_2025.pdf
- 12740_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_April-2025.pdf
- 12845_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Spurious_for_the_Month_of_May-2025.pdf
- 12959_List_of_spurious_Drugs_for_the_month_of_June-2025.pdf
- 12737_List_of_Drugs_Medical_Devices_Vaccine_and_Cosmetics_declared_as_Not_of_Standard_QualitySpuriousAdulteratedMisbranded_for.pdf

---

## D. Medical Device Risk Classification  [Classification: Future-usable | Priority: P2 — only if device vertical]

**Docs:** 40+
**Columns:**

| # | Canonical    | Variants                                                                                    |
| - | ------------ | ------------------------------------------------------------------------------------------- |
| 1 | sno          | Sr. No, S. No.                                                                              |
| 2 | device_name  | Device name, Medical Device Name, Name of the Medical Device                                |
| 3 | intended_use | Intended use, Intended Use, General Intended Use                                            |
| 4 | risk_class   | Risk Class, Risk Classification, Classification India as per First Schedule Part-1 MDR 2017 |

**Variant:** Earlier/Revised risk class comparison
| old_class | new_class |

**Sample files:** 13509, 12342, 12623, 13569, 13651, 13753, 4396, 465, 10587, 13508

---

## E. NOC / Clarification Register  [Classification: Future-usable | Priority: P2]

**Docs:** 15+
**Columns:**

| # | Canonical                                     |
| - | --------------------------------------------- |
| 1 | sno                                           |
| 2 | file_no                                       |
| 3 | company_address                               |
| 4 | product_name                                  |
| 5 | intended_use                                  |
| 6 | regulatory_status (Regulated / Not Regulated) |
| 7 | date_of_issue                                 |

**Sample files:** 1872, 2035–2042 (annual NOC lists), 207

---

## F. Laboratory / Testing Facility List  [Classification: Future-usable | Priority: P2]

**Docs:** 10+
**Columns:** `sno | category (IVD/device) | name_of_facility`
**Sample files:** 10187, 10554, 10709, 12797, 13820, 14413, 5636, 8367

---

## G. Gazette Fee Schedule  [Classification: Non-usable | Priority: P3]

**Docs:** 15+
**Columns:** `rule_no | subject | fee_inr | fee_usd`
**Files:** 1009, 13830, 14264, 6774, 2178, 14053

---

## H. Contents / Index  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | title | page_no`

---

## I. Checklist / Form  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | item | yes | no | na`

---

## J. Veterinary Vaccine List  [Classification: Future-usable | Priority: P2 — only if vet vertical]

**Docs:** 15+
**Columns:** `sno | name_of_vaccine | strain | source_of_strain | dosage_form | indication | permission_no | importer_manufacturer`
**File:** 7955

---

## K. FDC Prohibition / Restriction List  [Classification: Usable | Priority: P0]

**Docs:** 12+
**Columns:**

| # | Canonical                           |
| - | ----------------------------------- |
| 1 | sno                                 |
| 2 | name_of_fdc                         |
| 3 | strength                            |
| 4 | dosage_form                         |
| 5 | notification_no_date                |
| 6 | (opt) date_of_central_govt_approval |

**Sample files:**

Keep prohibited, restricted, and conditionally permitted combinations as distinct statuses. The Category C list under the 18-month policy is not a prohibition list; retain its exact legal basis and conditions.

- 12085_List_of_02_Restricted_FDC_drugs_dated_12.08.2024.pdf
- 12086_List_of_Prohibited_FDC_drugs_14_FDCs_dated_02.06.2023.pdf
- 12087_List_of_Prohibited_FDC_drugs_156_FDCs_dated_02.08.2024.pdf
- 12088_List_of_Prohibited_FDC_S_Etodolac_Paracetamol_12.08.2024.pdf
- 11024_LIST_OF_DRUGS_PROHIBITED_FOR_MANUFACTURE_AND_SALE_THROUGH_GAZETTE_NOTIFICATIONS_UNDER_SECTION_26A.pdf
- 11870_2024.08.12_DR_S.O._3266E_to_3267E_Restriction_of_FDC_Naproxen_Esomeprazole_and_Naproxen_Pantoprazole.pdf
- 11871_2024.08.12_DR_S.O._3285E_to_3440E_Prohibition_of_156_FDCs.pdf
- 1951_2018.09.07_S.O._4379E_to_S.O.4712_E_Prohibition_and_Restriction_of_FDC_drugs_Section_26A.pdf
- 3170_2019.01.11_S.O._180E_to_S.O.259E_Prohibition_of_certain_FDCs_appeared_in_the_list_of_294_FDCs_under_Section_26A.pdf
- 10569_2023.06.02_DR_S.O._2394E_to_2407E_Banning_of_14_FDCs.pdf
- 12673_S.O._1717E_dt_15.04.2025_Restriction_of_the_Fixed_Dose_Combination_of_Chlorpheniramine_Maleate_and_Phenylephrine_Hydroch.pdf
- 14656_2026.08.18_S.O._4595E_Prohibition_of_all_formulations_of_FDC_containing_Chlorpheniramine_Maleate_and_Phenylephrine_HCl.pdf
- 14397_2026.06.11_S.O._3068E_to_S.O._3083E_Prohibition_of_16_FDCs.pdf
- 14519_2026.06.11_S.O._3068E_to_S.O._3083E_Prohibition_of_16_FDCs.pdf
- 14514_List_of_16_FDCs_banned_dated_11.06.2026.pdf
- 2237_List_of_FDCs_under_category_c_permitted_for_continued_manufacturing_under_18_month_policy.pdf

---

## L. Abbreviations / Glossary  [Classification: Non-usable | Priority: P3]

**Columns:** `abbr | full_form`

---

## M. COVID / PCR Kit Approval  [Classification: Future-usable | Priority: P2 — if app covers COVID/IVD]

**Columns:** `sno | name_of_firm | type_of_kit | country`
**Files:** 7596, 7966, 8141, 9824, 9825, 13128, 14107

---

## N. Committee Meeting Schedule  [Classification: Non-usable | Priority: P3]

**Columns:** `month | tentative_dates | day`

---

## O. BABE Study Centre Approval  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | file_no | centre_address | valid_upto`

---

## P. Government Analyst / Committee Member Notification  [Classification: Non-usable | Priority: P3]

**Columns:** `sl_no | name_designation | laboratory | class_of_drugs_or_device`

---

## Q. Stability Study Design  [Classification: Non-usable | Priority: P3]

**Columns:** `product | storage_condition | shelf_life | accel_or_realtime_condition | testing_interval`

---

## R. SAE / PSUR Reporting  [Classification: Future-usable | Priority: P2 — analytics only]

**Columns:** `sno | sae | duration_from | duration_to | num_sae | units_sold | lot_batch_no`

---

## S. Cleanroom / ISO Class Requirement  [Classification: Non-usable | Priority: P3]

**Columns:** `device_name | type_of_operation | iso_class_at_rest`

---

## T. Exemption / Condition–Criteria  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | class_of_device | extent_and_conditions`  OR  `sno | condition | criteria`

---

## U. BIS / IS Standard Reference  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | is_no | title`  OR  `sl_no | standard_no_and_year | amendment_no | date_established | date_old_valid_until`

---

## V. Treasury Challan / Payment Form  [Classification: Non-usable | Priority: P3]

**Columns:** `tendered_by | name_address | particulars | amount_rs | amount_ps | head_of_account | order_to_bank`

---

## W. Application Questionnaire / Evaluation Form  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | item_particulars | response`

---

## X. Stakeholder Applicability Matrix  [Classification: Non-usable | Priority: P3]

**Columns:** `document_or_requirement | healthcare_prof | domestic_mfr | importer | govt_program | blood_centre | pathology_lab` with √/– cells

---

## Y. Comparative Study Results  [Classification: Non-usable | Priority: P3]

**Columns:** `parameter | study_a | study_b`  OR  `sno | test | rbc | specification`

---

## Z. PvPI Drug Safety Alert List  [Classification: Usable | Priority: P1]

**Docs:** 1 (unique)
**Columns:**

| # | Canonical             |
| - | --------------------- |
| 1 | sno                   |
| 2 | issue_date            |
| 3 | suspected_drug        |
| 4 | indication            |
| 5 | adverse_drug_reaction |

**File:** `ipc_pvpi/List-of-Drugs-Safety-Alerts-issued-by-PvPI-from-March-2016-to-till-date---27.07.2026.pdf`

---

## AA. Sample Size / Acceptance Criteria  [Classification: Non-usable | Priority: P3]

**Columns:** `type_of_assay | acceptance_criteria | min_samples_needed`

---

## AB. Committee / Staff Roster  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | name | designation | institution`

---

## AC. NLEM Data Tables  [Classification: Future-usable | Priority: P2 — essential-medicine reference]

**Columns (multiple):**

- `sno | drug | therapeutic_category`
- `sno | drug_name_strength | recommendation_of_experts`
- `section | total_nlem2011 | deleted | added | total_nlem2015 | ...`
- `sno | in_nlem2015 | in_nlem2022`
- `sno | medicine | Level of Healthcare | Dosage form and strength`

**Files:** 9012 (Report of NLEM 2022), 9011 (NLEM 2022), 4505 (NLEM 2015)

---

## AD. State-wise Sample Testing Statistics  [Classification: Non-usable | Priority: P3]

**Columns:** `state_zone | total_drawn | total_tested | standard_quality | nsq | steps_taken`

---

## AE. Reference Product List for BE Studies  [Classification: Future-usable | Priority: P2]

**Docs:** 1
**Columns:**

| # | Canonical          |
| - | ------------------ |
| 1 | sno                |
| 2 | drug_name          |
| 3 | bcs_class          |
| 4 | product            |
| 5 | company_trade_name |

**File:** `5492_Notice_regarding_List_of_Reference_Products_for_conduct_of_BE_Study.pdf`

---

## AF. Clinical Trial Site / Investigator Roster  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | pi_name_qualification | site_address | site_type | iec_name | ecr_no`

---

## AG. Cost / Budget Breakdown  [Classification: Non-usable | Priority: P3]

**Columns:** `category | component | no_of_components | rate | total_cost`

---

## AH. Timeline / Milestone / Schedule  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | particular | timeline_days`

---

## AI. Equipment / Calibration Frequency  [Classification: Non-usable | Priority: P3]

**Columns:** `equipment | frequency | ...`

---

## AJ. Post-Approval Change (PAC) Matrix  [Classification: Non-usable | Priority: P3]

**Columns:** `description_of_change | conditions_to_fulfil | supporting_data | reporting_category`
**Note:** ~15 apparent types all from ONE file (10953). Treat as 1 schema.

---

## AK. IVD First-Time Validation Screening  [Classification: Non-usable | Priority: P3]

**Columns:** `company | supplier | kit_batch_no | first_time_validation_yn | last_validation_details`

---

## AL. Feedback / Rating Scale  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | detail | excellent | very_good | good | fair | poor`

---

## AM. Donor / Patient / Cosmetic Registration Data  [Classification: Future-usable | Priority: P2 — classify each record by product type]

**Columns:** multiple variants

- `sno | condition | criteria` (blood donor)
- `serial_no | product_brand | brand_name | variant | pack_size | actual_manufacturer`

---

## AN. IVD Performance Requirement  [Classification: Non-usable | Priority: P3]

**Columns:** `product | technology | specification_criteria | reference`

---

## AO. Contact Directory  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | ministry_or_state | activity_or_lab_name`

---

## AP. Inspection Non-Compliance Observations  [Classification: Non-usable | Priority: P3]

**Columns:** `sno | checklist_category | non_compliance_observed`

---

## AQ. WHO Fraudulent Drug Alert  [Classification: Usable | Priority: P1]

**Docs:** 1–2
**Columns:**

| # | Canonical                                   |
| - | ------------------------------------------- |
| 1 | product_name                                |
| 2 | stated_value (claimed manufacturer / batch) |
| 3 | actual_value                                |

**Sample:** 10505_WHO_Alert_on_falsified_DEFITELIO...pdf

---

## AR. Banned Drugs List  [Classification: Usable | Priority: P0]

**Columns:** `sno | drug_name | notification_no`
**Files:** `banneddrugs.pdf`, `3253_Drugs_banned_in_the_Country.pdf`

---

## AS. Medical Device Alert  [Classification: Future-usable | Priority: P2 — only if device vertical]

**Columns:** device/product identification, issue, and recommended action.

---

## AT. Approved Products for Marketing  [Classification: Future-usable | Priority: P2]

**Columns:** `sno | drug | indication | date_of_issue`
**File:** `3246_Approved_for_Marketing_in_India.pdf`

---

## AU. Registration Certificate Holder Register  [Classification: Future-usable | Priority: P2 — selectively for relevant medicine records]

**Columns:** registration certificate holder, importer/manufacturer, product category, registration number, and validity.

---

## AV. Product Recall / Safety Alert  [Classification: Usable | Priority: P1]

**Columns:** variable recall identifiers, including product, batch, manufacture date, and expiry date.

---

# PART 2 — MEDICHECK CLASSIFICATION AND PRIORITY

## Usable — integrate into current medicine checks

| ID | Dataset | Use | Priority |
| -- | ------- | --- | -------- |
| A | CDSCO Monthly Drug Alert / NSQ List | Batch-level quality failures | P0 |
| B | State NSQ Alert | State-laboratory batch quality failures | P0 |
| C | Spurious Drug List | Officially reported spurious-product and batch checks | P0 |
| K | FDC Prohibition / Restriction List | Check prohibited and restricted FDC status | P0 |
| AR | Banned Drugs List | Check drug prohibitions; retain notification and scope | P0 |
| AV | Product Recall / Safety Alert | Product- and batch-specific recall warnings | P1 |
| AQ | WHO Fraudulent Drug Alert | Falsified medicine/product and lot checks | P1 |
| Z | PvPI Drug Safety Alert List | Suspected-drug and adverse-reaction safety warnings | P1 |

Batch NSQ, spurious-drug, and banned-product findings are distinct from adverse-reaction alerts. A PvPI alert is not a recall or prohibition. Verify the current legal status and scope before displaying regulatory warnings.

## Future-usable — archive and defer extraction

| ID / dataset | Potential later use | Conditions |
| ------------ | ------------------- | ---------- |
| E — NOC / Clarification Register | Product-specific regulatory reference | Select medicine records; exclude device and other out-of-scope records |
| AT — Approved Products for Marketing | Historical approval reference | Preserve date and wording; historical listing does not prove current approval |
| AE — Reference Product List for BE Studies | Reference product and brand enrichment | Not a batch-safety source |
| AC — NLEM Data Tables | Essential-medicine reference badge | Preserve edition and date |
| D, AS — Medical device risk and alerts | Future device verification | Only if MediCheck adds a device vertical |
| F — Laboratory / Testing Facility List | Future laboratory directory | Not product or batch evidence |
| M — COVID / PCR Kit Approval | Future IVD-kit catalogue | Only if IVD kits are in scope |
| J — Veterinary Vaccine List | Future animal-medicine catalogue | Only if veterinary products are in scope |
| R — SAE / PSUR Reporting | Post-marketing safety analytics | Assess record suitability; not a direct consumer batch alert |
| AU — Registration Certificate Holder Register | Imported-product registration reference | Select relevant medicine records; verify current validity |
| AM — Donor / Patient / Cosmetic Registration Data | Potential specialized-product features | Classify each record by product type; cosmetics are outside current medicine scope |
Country-wide survey for spurious drugs (brand-level summary only) | Historical quality-trend analysis | Aggregate sampling and manufacturer-reported findings do not establish the authenticity or safety of an individual scanned batch; specific spurious-sample records are handled under C |
Top-300 QR mandate records | Product identification reference | Not covered by the A–AV archetypes; assess source and current applicability before integration |

## Non-usable — do not prioritize for the current app database

G, H, I, L, N, O, P, Q, S, T, U, V, W, X, Y, AA, AB, AD, AF, AG, AH, AI, AJ, AK, AL, AN, AO, AP

These are administrative, procedural, technical, aggregate, or professional-workflow records without direct consumer-facing medicine verification value. Non-usable does not mean the source document is invalid or unimportant to its issuing authority; retain original files as needed.

## Data handling rules

- Preserve original PDFs and the source reference for every extracted record.
- Maintain an inventory with `document_name`, `category`, `subcategory`, `source_authority`, `publication_date`, `regulatory_status`, `reason_for_classification`, `extraction_status`, and `last_verified_date`.
- For PDFs containing multiple tables or record types, classify and extract each table or record independently; do not force one app classification onto all content in the document.
- Keep prohibited, restricted, and conditionally permitted FDCs as distinct statuses. The Category C list under the 18-month policy is not a prohibition list.
- Treat missing matches as unsuccessful searches, not evidence that a product is safe or genuine.

### Country-wide spurious-drug survey (PDF 3257)

The survey contains two distinct record types. Brand-level summaries with sample counts and manufacturer-reported findings are Future-usable for historical surveillance analysis only. Individual spurious-sample records that identify a product, batch, manufacturer, sample number, and investigation context are Usable under C.

These are historical records from 2007–2009, with some listed expiry dates in 2010–2011. Preserve the original dates and mark the records historical. Use them for historical batch identification and research; do not present them as evidence that a currently sold pack is counterfeit without a sufficiently specific match and appropriate verification. A reported finding for one sample must not be generalized to every pack of the brand.

The following excerpt is from the brand-level summary table and is useful only for aggregate trend context.

3.0Detail of sampling
Table-3
Therapeutic
CategoryGeneric
Name
Brand
Name
Manufactured
By
No. of samples collected
Remark
MCBCDHQTVilTotal
Anti- infec-
tive
Ciprofloxacin
Tablets
CifranRanbaxy
Laboratories Ltd
1048012813368513All samples are
stated to be genuine
by the respective
manufacturer on
the basis of physical
verification
CiploxCipla Ltd1198614012680551Do
CiprobidCadila Health
Care Ltd
907811310154436Do
Amoxycillin
Capsules
MoxRanbaxy
Laboratories Ltd
1167913411468511Do
NovamoxCipla Ltd1368311312576533Do
Sulphamethoxa-
zole & Trim-
ethoprim Tablets
SeptranGlaxo Smith Kline
Pharm Ltd. (GSK)
1237712814097565Do
CiplinCipla Ltd193333208113Do
BactrimNicholas Piramal
(I) Ltd
1237811312269505Do
Steroids
Dexamethasone
Tablets
DexonaCadila Health
Care Ltd.
986911116381522Do
DecdanWockhardt Ltd103709113872474Do
Decdac STNax Par Lab (p)
Ltd.
72019161173Do
Prednisolone
Tablets
WysoloneWyeth Ltd1119113315494583Do
OmnacortilMacleods
Pharmaceuticals
Ltd
868811913479506Do
MedrolPharmacia Italia/
Pfizer Products
India
8273969647394Do
Betamethasone
Tablets
BetnisolGSK Ltd1029212314080537Do
BetnilanGSK Ltd848010111068443Do
Antihistaminic
Loratidine
Tablets
NeoloridinCadila Health
Care Ltd.
4440443810176Do
LorfastCadila
Pharmaceuticals
6465868441340Do
ClaridineMorepen
Laboratories Ltd
72633161193Do
Cetirizine
Tablets
CetzineEmcure
Pharmaceuticals
755886120684077 samples are
stated to be
spurious and rest
are genuine by
the respective
manufacturer
on the basis
of physical
verification
CetrizetSun Pharma Ltd13545330All samples are stated
to be genuine by the
respective manufacturer
on the basis of physical
verification

7
ZyncetUnichem
Laboratories Ltd
4962816843303Do
Pheniramine
Maleate Tablets
AvilAventis Pharma
Ltd.
10176135134104550Do
Cardiovascu-
lar
Amlodipin
Tablets
Amlosafe
Tablet
Aristo
pharmaceuticals
9173839554396Do
