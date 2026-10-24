# CDSCO Paragraph Corpus — Paragraph Taxonomy & MediCheck Priority Map

Version: 1.0  
Generated from: `medicheck_semantic_labels_clustered.csv`, `medicheck_document_clusters.csv`, `medicheck_document_app_classification.csv`, `medicheck_cluster_overview.csv`, and `medicheck_clustering_report.md`  
Corpus represented in the current results: 3,029 paragraph/chunk records across 343 Markdown source paths; 14 exploratory document clusters.

---

## Purpose and scope

This taxonomy classifies **paragraph-level records and operative passages** for MediCheck. It complements, rather than replaces, the table taxonomy in `table_taxonomy_for_app.md`:

- A paragraph record that is structurally a table/list row should use the applicable A–AV table archetype and its extraction schema.
- A prose passage that independently states a finding, restriction, warning, or regulatory status may use a P-series archetype.
- A document may contain several independently classifiable records, and may contain both table and prose records. Never force one classification onto every page, chunk, or record in a document.

The 14 clusters in the results are exploratory, document-level topic groupings. They are useful for routing review, **not legal or app taxonomies**. In particular, a cluster can contain usable product actions, future references, procedural material, and administrative notices together. The `app_classification` and cluster fields in the CSV are triage annotations, not legal determinations.

## Classification rules

- **Usable:** directly supports one of the three current checks: spurious/NSQ findings, prohibition/banned-drug status, or PvPI adverse-reaction alerts. A record must also meet the evidence requirements below before it is ready for direct matching.
- **Future-usable:** retain and classify, but defer user-facing extraction until the relevant reference, analytics, device, IVD, veterinary, recall/fraud, advisory, or rule-monitoring feature is in scope.
- **Non-usable:** do not prioritize for the current consumer app database. Retain the source document for provenance or research as appropriate.
- Use exactly these three values in `app_classification`. Labels such as `Direct usable`, `Archive / context`, or `Operational` are not additional class values. Record priority and retention separately.
- Legal status, app relevance, and priority are independent. A final administrative notice is still Non-usable; a proposed product-specific restriction may be Usable only when clearly shown as proposed, never as binding.
- A missing match is not evidence that a medicine is safe, genuine, approved, or unrestricted. Show confirmed findings separately from unsuccessful searches.
- For mixed medicine/device/veterinary/cosmetic records, classify each record by product type and include only in-scope medicine records in current medicine checks.

### Current app-scope gate

The P-series archetype describes what a passage says; it does not by itself make that passage directly usable. Apply this gate at the paragraph or record level. Keep `app_classification` to Usable, Future-usable, or Non-usable; track direct-matching readiness separately. A record that does not meet its direct-use conditions remains retained, but is not ready for direct matching.

| Paragraph IDs | Decision for current app | Direct-use condition |
| --- | --- | --- |
| **P1–P2** | Direct usable | Require medicine name, batch number, manufacturer, and failure reason/result. If any required field is missing, retain as not yet ready for direct matching. |
| **P3–P4** | Direct usable | The source must support the named medicine/FDC and the operative prohibition. Preserve exact product scope and legal status. |
| **P3b–P3c** | Direct usable | The source must support the named medicine/FDC and operative restriction or conditional permission. Preserve every condition; never turn it into a blanket ban. |
| **P5–P6** | Conditional | Direct only when the record satisfies one of the three current app checks above; otherwise classify as Future-usable. |
| **P7** | Direct usable | Suspected drug and adverse reaction must be present. Batch is optional. Do not present an adverse-reaction alert as a recall or prohibition. |
| **P8** | Future-usable by default | General product warnings and labeling advice are outside the three current schemas. Promote only if a specific record independently satisfies a current check. |
| **P9–P19, P29–P30** | Future-usable by default | Reference, device, veterinary, analytics, policy-monitoring, or historical material remains deferred unless a specific actionable record independently satisfies a current check. |
| **P20–P28** | Non-usable by default | Generic procedures, administrative notices, meetings, and informational documents are not current app findings. Extract any independently actionable product finding separately. |

## PART 1 — P-Series taxonomy

### Usable — current medicine checks

| ID | Paragraph archetype | App use | Priority | Table mapping |
| --- | --- | --- | --- | --- |
| **P1** | Batch/sample-specific prose finding that a named medicine is spurious, falsified, adulterated, or misbranded; retain product and available batch, sample, manufacturer, test/investigation details | Historical batch-level falsified-product check | **P0** | C; AQ for WHO-origin alerts classified under P6 |
| **P2** | Batch-specific NSQ / not-of-standard-quality narrative finding outside a structured table | Batch quality-failure check | **P0** | A, B |
| **P3** | Operative prohibition of a named medicine, formulation, or FDC for manufacture, sale, distribution, import, or use | Prohibited-status check | **P0** | K, AR |
| **P3b** | Operative restriction on a named medicine/FDC, including indication, age, dose, population, or other stated conditions; not an outright prohibition | Restricted-status check; preserve scope and conditions | **P0** | K |
| **P3c** | Explicit conditional permission or continued-use/manufacture pathway, including Category C / 18-month policy status | Conditional-status check; preserve conditions and legal basis | **P0** | K |
| **P4** | Prose banned-drug list or explicit Section 26A prohibition record | Banned-status check | **P0** | AR; K for FDC entries |
| **P5** | Product recall or safety communication that identifies the affected product and, where available, batch/lot | Conditional; direct only if it satisfies a current app check, otherwise future recall feature | **P1** | AV |
| **P6** | WHO or other international authority alert identifying a falsified medicine, claimed/actual product details, or lot | Conditional; direct only if it satisfies a current app check, otherwise future fraud-alert feature | **P1** | AQ |
| **P7** | PvPI / pharmacovigilance alert with suspected drug and adverse drug reaction; batch is optional | Adverse-reaction check; not a recall or prohibition | **P1** | Z |
| **P8** | Product- or class-specific warning, advisory, or labeling requirement that informs safe use but is not itself a ban, batch finding, or recall | Future-usable by default; no general advisory feature in the current three checks | **P1** | No direct A–AV equivalent; applicable rule context may be P29 |

**Status updates:** A rescission, supersession, correction, or amendment to a product-specific P3/P3b/P3c/P4 record belongs to that same usable product-status record. Link the source chain and update the current status; do not create a conflicting parallel alert.

### Future-usable — retain and defer

| ID | Paragraph archetype | Later use and guardrail | Table mapping |
| --- | --- | --- | --- |
| **P9** | Medical-device safety alert or device classification/risk information | Device verification only if a device vertical is in scope | D, AS |
| **P10** | Approved-products-for-marketing list | Historical approval reference; a past listing does not prove current approval | AT |
| **P11** | Registration-certificate holder/importer register | Imported-product reference; verify validity and product match | AU |
| **P12** | NOC / clarification register or product-specific regulatory reference | Select medicine records; exclude out-of-scope product types | E |
| **P13** | Reference-product list for bioequivalence studies | Product/brand enrichment only; not a safety source | AE |
| **P14** | NLEM / essential-medicines prose or list | Badge/reference only; preserve edition and date | AC |
| **P15** | Laboratory or testing-facility listing | Directory only; not product/batch evidence | F |
| **P16** | Veterinary medicine, vaccine, or animal-use restriction/list | Veterinary vertical only; an animal-use prohibition is not a human-medicine prohibition | J; no direct mapping for all animal-use restrictions |
| **P17** | IVD / COVID kit approval or product listing | IVD scope only | M |
| **P18** | SAE / PSUR / aggregate pharmacovigilance analytics | Analytics only; not a consumer batch alert | R |
| **P19** | Country-wide or aggregate survey prose, brand-level sample counts, or manufacturer-reported aggregate findings | Historical surveillance only; must never drive an individual pack verdict. Split any batch/sample-specific record to P1 | C for separately identified batch/sample records |
| **P29** | General drug-rule amendment, formal draft proposal (including a proposed product-specific action), or regulatory-policy change that merits change monitoring but does not establish a current product-specific finding | Regulatory watch; preserve proposed/final/commencement status and later links. A proposed action is not a current restriction; after it takes effect, link or update the applicable P3/P3b/P3c/P4/P8 record | No single A–AV equivalent; K/AR only for independently actionable effective product records |
| **P30** | Historical/emergency regulatory measures retained for provenance or precedent | Archive/context only; check dates, expiry, repeal, and supersession before any current use | No direct A–AV equivalent; route any current product-status action to P3/P3b/P3c/P4 |

### Non-usable — do not prioritize for current app extraction

| ID | Paragraph archetype | Handling |
| --- | --- | --- |
| **P20** | BE / BABE / NOC procedural guidance, application requirements, submission checklists, forms, or fees | Non-usable; do not promote to Future-usable merely because it concerns a medicine or regulated workflow |
| **P21** | BA/BE centre approval document checklists | Non-usable |
| **P22** | Generic FAQ or public-awareness material without a product-specific actionable warning | Non-usable |
| **P23** | Expert committee / policy report or recommendation | Non-usable as a consumer finding; cite an enacting product notification as the source of truth if one exists |
| **P24** | Meeting minutes, consultation notes, meeting schedules, and participant lists | Non-usable; substantive product-specific outcomes must be separately sourced and classified |
| **P25** | Enforcement/prosecution procedure, including generic Category A/B/C handling and compounding guidance | Non-usable as a product verdict. Category definitions may be retained as a Future-usable internal reference taxonomy, not extracted as findings |
| **P26** | Administrative Gazette notice: ports, fees, appointments, analyst/inspector qualifications, authority rosters, debarment, administrative compounding, or cosmetic procedure | Non-usable even when final/effective. Route a separately stated medicine restriction or safety finding to its applicable P-series ID |
| **P27** | Corrigendum to procedural or administrative rules | Non-usable. If it corrects a product-specific P3/P3b/P3c/P4 action, incorporate it into that status record instead |
| **P28** | Informational public notice, circular, or press note without a product-specific actionable finding or rule change requiring monitoring | Non-usable |

### Classification and priority summary

| Class | IDs | Priority | Meaning |
| --- | --- | --- | --- |
| **Usable** | P1, P2, P3, P3b, P3c, P4, P7, and qualifying P5-P6 | P0 for direct quality/status findings; P1 for qualifying P5-P7 alerts | P5-P6 are Usable only when they satisfy a current check; P1-P2 records must also meet the required-field gate before direct matching |
| **Future-usable** | P5-P6 when they do not qualify for a current check; P8-P19, P29-P30 | P2 by default when deferred | Retain and defer to future recall/fraud, advisory, reference, analytics, device/IVD/veterinary, regulatory-watch, or archive workflows |
| **Non-usable** | P20-P28 | P3 | Do not prioritize for the current consumer app database |

---

## PART 2 — Cluster routing guide

Use this table to choose where to review first. The routing is intentionally conditional: it does not override record-level classification.

| Cluster | Exploratory cluster topic | Default route | Required record-level split / override |
| --- | --- | --- | --- |
| **0** | General Drugs & Cosmetics Rules, amendments and licensing | P29 Future-usable for rule-change monitoring | Fees, ports, appointments, and administrative provisions are P26 Non-usable. Product-specific restrictions or labeling actions route to P3/P3b/P3c/P4/P8 with legal status retained. |
| **1** | Medical Devices Rules and device compliance | P9 Future-usable | Device authority appointments/qualifications are P26 Non-usable. Keep device records separate from human-medicine findings. |
| **2** | FDC prohibitions and restrictions | P3/P3b/P3c Usable when the passage states a specific product action | Draft/general FDC policy is P29 Future-usable. Separate prohibition, restriction, conditional permission, proposal, and superseding notice. |
| **3** | Clinical trials, new drugs and expert-committee guidance | P29 Future-usable for formal rule changes | Committee reports/recommendations are P23 Non-usable; operative product-status passages are classified by action, not by cluster. |
| **4** | Drugs Rules, 1945 draft amendments and proposals | P29 Future-usable; explicitly proposed, not binding | Product-specific proposed restrictions remain P29 until effective; do not display them as current restrictions. Administrative-only draft provisions remain P26. |
| **5** | Medical-device classification as drugs | P9 Future-usable | Classification as a drug does not itself establish an individual medicine safety finding. Separate device/product-scope reference from medicine alerts. |
| **6** | COVID-19 and emergency drug/vaccine measures | P30 Future-usable archive/context by default | Check time limits, expiry, repeal, and supersession. A still-operative product-specific action routes to P3/P3b/P3c/P4 and must be verified. |
| **7** | Rule-specific amendments and consultation/public-comment cycles | P29 Future-usable | Distinguish draft, final publication, commencement, correction, and product-specific effect. Corrigenda to procedure are P27; product corrections update the product record. |
| **8** | CDSCO notices, stakeholder meetings, implementation circulars and alerts | No cluster-wide class; classify each record | Device alerts are P9; product safety/recall/prohibition/advisory records route to P3–P8; meetings are P24; generic notices are P28. |
| **9** | Government analysts, laboratories and authority appointments | P26 Non-usable for appointments/rosters | A separately listed lab directory may be P15 Future-usable. Neither is a medicine verdict. |
| **10** | Export permissions, BA/BE NOC, bioequivalence and manufacturer lists | P20/P21 Non-usable for guidance and checklists | A genuine product/importer/registration/reference list may be P11/P12/P13 Future-usable. Do not classify procedural guidance as usable merely because it is operationally useful. |
| **11** | Drug-quality enforcement, spurious/NSQ guidance, compounding offences and compliance FAQs | No cluster-wide class; split records | Specific batch/sample findings are P1/P2; FAQs are P22; enforcement procedure is P25; administrative or compounding notices are P26; product-specific revocation/corrigendum updates P3/P3b/P3c/P4. |
| **12** | Expert committees, vaccine PSUR review and safety-review meetings | P24 Non-usable for meeting records | Committee reports are P23; aggregate PSUR analytics are P18 Future-usable; a separately enacted drug action routes to P3/P3b/P3c/P4. |
| **13** | Special product restrictions, supply/import controls, animal-use controls and traceability notices | No cluster-wide class; split by product and action | Human-medicine prohibitions/restrictions route to P3/P3b/P3c/P4. Veterinary actions are P16 Future-usable. Product/class labeling is P8; broad traceability/rule mandates are P29 unless a consumer-facing product record is independently extractable. |

### Known classification corrections from the current CSV

The following rows should be aligned to this taxonomy when the document-level classifications are revised:

- `3235`, `3237`: P20 Non-usable, not Future-usable.
- `3238`: P21 Non-usable, not Future-usable.
- `3240`: P22 Non-usable, not Future-usable.
- `3248`: P23 Non-usable as a report; any enacted prohibition must be linked to its notification.
- `3258`: P25 Non-usable as enforcement procedure. Retain category definitions only as an internal Future-usable reference, separate from procedural passages.
- `4473`: P24 Non-usable meeting minutes.
- `10567`, `11451`, `12848`, `13551`: classify the cosmetics/procedural, compounding, or debarment content as P26 Non-usable unless a separate product-specific medicine action is present.
- `13589`: P27 Non-usable corrigendum to a draft procedural notice; do not treat it as an independent product finding.
- `10980`, `1353`, and `3771`: inspect the underlying text and parent notice. If they rescind/correct a medicine prohibition, update the linked P3/P3b/P3c/P4 status record, rather than classifying the passage as generic administration.
- `13750`: the Nimesulide immediate-release dosage-form action is a human-medicine product-status record; classify by exact action and conditions under P3 or P3b, not as veterinary scope merely because it shares cluster 13.
- `2373`: the Buclizine use-specific restriction is product-specific; classify under P3b, not as an expert-meeting record based on cluster 12.

These are routing corrections based on the names and semantic summaries in the results. Verify operative wording, product scope, and legal status from the source before treating an item as a confirmed finding.

---

## PART 3 — Record-level decision procedure

For every candidate paragraph/chunk, apply in this order:

1. **Is it an independent record or operative passage?** If it is only a heading, publication mark, repeated boilerplate, or fragment without enough context, retain for provenance but do not classify as a finding; mark for context/re-extraction.
2. **Does it state a specific product/sample and an actionable quality, status, recall, or safety finding?** Route by finding type, then apply the app-scope gate. P1–P2 require medicine name, batch, manufacturer, and failure reason/result; P3–P4 require source-supported named product and operative prohibition; P3b–P3c preserve exact conditions; P5–P6 are conditional; P7 requires suspected drug and adverse reaction, with batch optional.
3. **Is it a product-specific advisory or labeling requirement rather than a ban or batch verdict?** Route to P8 as Future-usable by default. Do not turn advisory wording into a quality or counterfeit finding.
4. **Is it a register, directory, reference list, aggregate analysis, device/IVD/veterinary record, or historical reference?** Route to P9–P19 or P30 as appropriate and default to Future-usable; never infer a consumer verdict from aggregate data.
5. **Is it a formal general rule change or proposed regulatory amendment?** Route to P29 unless a specific product action can be extracted independently. Draft/proposed text remains proposed.
6. **Is it procedure, administration, meeting material, generic guidance, or informational notice?** Route to P20–P28; do not prioritize for consumer app extraction.
7. **Does it correct, revoke, or supersede an existing product record?** Update and link the parent P3/P3b/P3c/P4 record; do not retain contradictory parallel statuses.

## PART 4 — Status, evidence, and display semantics

Keep `app_classification`, `priority`, `legal_status`, and currentness/supersession as separate fields.

| Legal status | Display rule |
| --- | --- |
| `final_or_effective_explicitly_stated` + Usable archetype | May be displayed as a confirmed finding only after scope and source verification. |
| `draft_or_proposed_explicitly_stated` | Show only as proposed/under consultation; never imply binding effect. |
| `administrative_or_informational` | Context only; never a product verdict. |
| `banned` | Accept only when the exact evidence quote supports the stated legal prohibition and scope. |
| `repealed`, `rescinded`, `superseded`, or corrected | Link to the parent record and reflect the current operative status; retain history for audit. |
| `unclear_from_excerpt` or missing | Do not display as a finding; queue for source-context review or re-extraction. |

**Minimum evidence to promote a Usable record:** exact `evidence_quote`; source document and page/section; publication/effective date where present; named product and scope; action/status and conditions; `legal_status`; and a review of any linked corrigendum, revocation, or superseding notice. Never substitute a generated summary for the operative wording.

## PART 5 — Data-handling and known limitations

- Preserve original PDFs/Markdown, source paths, publication metadata, and verbatim operative wording.
- Keep table extraction and paragraph extraction distinct but link them to the same source document when they describe related evidence.
- For monthly alerts, extract both qualifying table rows (A/B/C) and independent prose findings (P1/P2); do not double-count a table row as a separate paragraph alert without distinct evidence.
- Historical records must carry their original dates and a historical flag. The 2007–2009 survey is not evidence that a currently sold pack is counterfeit.
- Aggregate survey findings (P19) must never be promoted to an individual batch verdict. Use a sufficiently specific product/batch/sample match and verification.
- The current clustering assigns one dominant cluster per source document, and the current report states that some documents contain multiple topics. Use chunk/record-level evidence and source review to override cluster-level recommendations.
- The semantic outputs, classifications, and cluster names are generated annotations. Treat them as review aids; do not infer legal effect solely from titles, labels, or model confidence.
- A paragraph taxonomy classifies app relevance; it does not provide legal advice or verify whether a notification remains in force.
