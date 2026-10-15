# Arabic Reconciliation Bench v0.1.0 — implementation contract

Original synthetic Arabic-first procurement evidence benchmark. No real customer
records, no current tax rules, no claim of expert/human validation, and no claim
to be the first accounting/document benchmark. Closest related work includes
FinBalance, SAHM, KITAB-Bench, AMuRD, and synthetic invoice resources. The target
contribution is matched fact-sensitivity, representation invariance and missing
evidence in a scoped Arabic procurement task.

## Core cases

Generate 400 families for each of 14 mechanisms (5,600 families). Per mechanism:
280 train, 40 validation, 40 test, 40 challenge. Challenge uses more simultaneous
benign complexities, not unseen accounting law. All sibling cases stay together.
Every family has three worlds: clean, critical_edit, missing_evidence. Each world
has ar_western, ar_eastern, ar_reordered, en_control views. Total 67,200 rows;
these are repeated controlled views of 5,600 generated families, not independent
human examples. Train/validation use wording/layout styles 0/1; test style 2;
challenge style 3. Report this precise scope rather than claiming general OOD.

Input facts consist of these document objects (roles are internal; titles and
contents are visible). Each document has opaque ID, role, Arabic title, English
title_en and fields.
A field has id, key, row_id (empty for header), value (string), label_ar,label_en.
Field IDs are globally unique within a packet, e.g. D03.F08. IDs are stable across
views. Public model input exposes only doc_id,title,text (with [field IDs]) and
question. The canonical facts/roles/gold/phenomenon/world are never in prompts.
All IDs are opaque random/hash strings or plain D01 etc, never encode labels.

Roles and canonical fact keys:

- policy: price_tolerance_bps, receipt_cutoff (always invoice_date),
  required_roles (comma-separated po,invoice,receipts,returns,history,amendments),
  accepted_only=true, cumulative_billing=true, approved_amendments_only=true,
  canceled_orders_forbidden=true. All semantics are stated in original text.
- po: order_id,status (active/canceled),currency; per row_id/SKU: sku,
  ordered_units,units_per_pack,unit_price_minor,discount_bps.
- invoice: invoice_id,order_id,date,currency,stated_net_minor; per SKU row:
  sku,quantity_units,unit_price_minor,discount_bps.
- receipts: complete=true; per receipt row: receipt_id,sku,date,quantity,
  quantity_unit (unit/pack),rejected_quantity. Rejected quantity uses the same
  unit as quantity. Eligible rows have date<=invoice date. Accepted base units
  are (quantity-rejected_quantity)*pack size when unit=pack, else that difference.
- returns: complete=true; per row: return_id,sku,date,quantity_units,status
  (approved/draft). Only approved rows dated<=invoice date reduce accepted units.
- history: complete=true; per row: invoice_id,order_id,sku,quantity_units,status
  (posted/void). Posted rows of this order consume received and ordered units.
  A posted invoice_id identical to the current invoice is also a duplicate.
- amendments: complete=true; per row: amendment_id,sku,effective_date,status
  (approved/draft),unit_price_minor. Latest approved effective_date<=invoice
  date replaces PO unit price. Eligible amendments have unique effective dates
  within each SKU to avoid tie semantics.

All quantities and minor-unit prices are nonnegative integers; ordered and
invoice quantities/prices are positive. Currency is symbolic (e.g. SAR/AED),
and no FX or tax conversion is permitted or needed. Documents state that these
are fictional net-amount policies, not legal or tax advice.

## Deterministic task

Return JSON: decision (match/mismatch/insufficient_evidence),
contract_net_minor (integer or null), issues (sorted unique codes),
evidence_ids (sorted unique visible field IDs).

Contract net is the sum, over current invoice rows, of invoice quantity times
effective contractual unit price times (10000-PO discount_bps)/10000, rounded
HALF_UP to an integer minor unit PER LINE. It uses requested invoice quantities,
not min(received,ordered); this is a nominal contract value, not a payable amount.
It may be known even when the decision is mismatch or evidence is missing.
It is null only if the PO, invoice or amendments register is missing.

Checks (when all required documents plus policy exist):
1. order_canceled if PO status is canceled.
2. currency_mismatch if invoice/PO currencies differ.
3. duplicate_invoice if a posted history row invoice_id equals current invoice_id.
4. quantity_shortfall if any invoice quantity exceeds either ordered-minus-posted
   or accepted-minus-approved-returns-minus-posted base-unit quantity.
5. price_mismatch if abs(invoice_price-effective_price)*10000 >
   effective_price*price_tolerance_bps for any line.
6. discount_mismatch if invoice/PO discount_bps differ for any line.
7. invoice_arithmetic if stated_net_minor differs from the sum of rounded invoice
   quantity*invoice_price*(10000-invoice_discount_bps)/10000 per line.

If any role is absent, decision=insufficient_evidence, issues=[missing_evidence]
(the benchmark explicitly requires a complete packet before a decision), while
the nominal contract amount may remain computable as above. Otherwise decision
is mismatch iff any check fails, else match. Every generated clean world must
match; every critical_edit world must mismatch; every missing world must be
insufficient. Reject families whose construction does not satisfy that.

Critical mechanisms (one canonical field edit, no dependent total updates):
receipt_quantity, rejected_quantity, return_quantity, pack_conversion,
cumulative_billing, price_tolerance, discount, invoice_total, currency,
duplicate_invoice, amendment_date, amendment_status, receipt_date, cancellation.
Single-field edits are chosen to leave all other evidence fixed; deliberately
inconsistent invoice totals are a task, not a generation bug. Original invoice
price/discount totals are recomputed only in clean creation, never after an edit.

As-built v0.1 omissions sample policy, PO, receipts, returns, history or amendments;
invoice omission is supported by the contract/tests but is not sampled. Complete
packets have seven documents and omissions six, so missing-document decisions
have a document-presence shortcut. All splits share the same fixed formal policy
and controlled grammar; disjoint families and specified style changes do not establish policy/workflow
generalization. Structural shortcuts and template memorization are limitations.

## Reference evidence

Gold audit trace supplies checks, intermediate integer quantities/prices/amounts,
and field IDs actually read. Gold evidence is an explicit reference set, NOT a
claim of a uniquely minimal human proof. Score reference precision/recall/F1 and
coverage separately; never call that proof correctness. Joint success requires
correct decision, contract amount, issue set, all reference evidence covered,
and no invalid/nonexistent citations. Extra valid citations are allowed in joint
success (but diagnostic precision records them). All fields used to compute the
contract amount and each relevant check are in the reference. Missing-role cases
include every visible field read by the amount computation and task policy.

## Views and pairs

ar_eastern changes numeric/date field rendering, including monetary amounts and
percentages; opaque IDs stay ASCII. ar_reordered uses Western digits and reverses
document, row-group and within-group field order. It retains the marked-line
grammar. en_control is an aligned English controlled
rendering, not naturally occurring English. Original Arabic is controlled MSA,
not dialect speech or expert-authored business documents.

Publish invariance pairs from ar_western to ar_eastern/ar_reordered/en_control
within each world. Publish sensitivity pairs clean->critical_edit and
clean->missing_evidence within each view, with the exact canonical path+before+
after for critical edits and missing role/doc ID for omissions. Family clustering
is the unit for confidence intervals and pair-level metrics.

## Files/interfaces

Parent owns generator.py + core.py + public schema/docs and publication.
Independent reviewer owns verify.py + score.py + tests and validator report.
Model runner owner owns run_models.py + baseline report generation.
Renderer owner owns render_packets.* + fonts/licenses + visual subset.

generator.py creates release/data/cases/<split>-*.parquet plus
release/data/pairs/<split>-*.parquet, release/specs/<split>.jsonl.gz (gzip JSONL,
one row per case: case_id,family_id,world,view,mechanism,style,split,documents canonical field data,
gold,edit metadata) and statistics.json. Parquet cases expose:
case_id,family_id,world,view,language,digit_script,mechanism,style,
question,documents(list doc_id/title/text),gold_decision,gold_contract_net_minor,
gold_issues(list),gold_evidence_ids(list). Pair table has pair_id,family_id,
case_id_a,case_id_b,relation,axis,edit_json. Family/case/pair IDs are opaque
24-character prefixes of SHA256 digests (96 bits), not complete 64-character
digests. Business and document/field identifiers have their own visible formats.

core.py exports model_input(row): only question+visible documents, plus standard
output contract instructions, never gold/world/view/mechanism/canonical fields.
Scorer accepts predictions JSONL {case_id,decision,contract_net_minor,issues,
evidence_ids}; invalid/missing outputs count as wrong, duplicates are rejected.
Reports split/view/mechanism/decision, paired-both-correct, all-view-correct,
strict joint, schema rate, amount exact, issue exact, evidence reference metrics,
missing-evidence precision/recall. CIs cluster bootstrap by family; report seed.
The scorer treats issue/evidence arrays as sets and rejects duplicate entries.
core_exact requires decision, amount and issue set; strict_joint additionally
requires complete reference coverage and no nonexistent citations. Paired
diagnostics separately report decision/core/joint correctness. all_view_joint
and all_family_joint use strict_joint over four views or twelve family cases;
the four views include the aligned English control.

Independent verify.py must recompute from canonical fields WITHOUT importing
generator.py or its oracle, and verify visible string/evidence/critical field
delta and split closure. Compare every output, verify pair relations and each
typed Parquet row against corresponding spec. Test adversarial mutations:
mislabel decision, wrong amount, missing required evidence, extra invalid ID,
cross-split sibling and unrecorded multi-fact mutation. A hardcoded truth lookup
or generator-fed oracle is not a meaningful competitive baseline.

Baselines: full-suite label/amount-prior baselines; model evaluations on a
deterministic stratified subset of complete families (initially14 families,
168views/model), at least Qwen2.5:3b and locally available Arabic Fanar9B if
feasible, with exact digests/prompts/options/raw responses/timings. Resume from
row checkpoints; one model active at a time. Publish numbers only after actual
runs. A parser/executable reference is a ceiling, not an LLM.

Visual subset: select one test and one challenge family per mechanism by hash
(28 families), render three worlds x two Arabic digit views =168 packets as
multi-page PDFs, per-page PNGs, exact field boxes, matching canonical text. Keep
these as a bounded separately counted controlled visual subset, not 168
independent transactions. Bundle Noto Arabic Regular/Bold under verified OFL1.1.
Mark every page 'synthetic benchmark / بيانات اصطناعية'. No hidden gold or
mechanism/world label in images/documents. Visual review and glyph/box checks
before publishing. Final counts may change only for concrete validation reasons.
