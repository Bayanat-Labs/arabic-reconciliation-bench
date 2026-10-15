[Dataset on Hugging Face](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench) · [Interactive evidence explorer](https://huggingface.co/spaces/Bayanat-Labs/arabic-reconciliation-bench) · [Reproduce the release](REPRODUCING.md)

# Bayanat Arabic Reconciliation Bench

**Can a model change its answer when one business fact changes—and keep it when only the numeral script or document order changes?**

An original synthetic Arabic-first procurement benchmark for comparing purchase orders, invoices, receipt records, returns, prior invoices and price amendments under explicit fictional policies. The model must decide `match`, `mismatch` or `insufficient_evidence`, calculate the nominal contractual net amount, identify issue codes and cite visible evidence fields.

**5,600 generated case families · 14 intervention mechanisms · 67,200 controlled case views · 95,200 matched comparisons.** Repeated worlds and views are related observations, not independent transactions or human annotations.

[Interactive challenge and evidence explorer](https://huggingface.co/spaces/Bayanat-Labs/arabic-reconciliation-bench) · [Source and evaluation code](https://github.com/Bayanat-Labs/arabic-reconciliation-bench)

**بيانات اصطناعية أصلية:** حالات مطابقة مستندات مشتريات بالعربية، مع تغييرات محددة في الحقائق وصيغ متكافئة للأرقام وترتيب المستندات. الإجابات محسوبة وفق سياسات افتراضية معلنة؛ ليست سجلات شركات حقيقية ولا أحكام خبراء محاسبين.

## Why this resource

An extraction system can read every number correctly and still combine the wrong receipt, apply an unapproved price amendment, double-count a prior invoice or overlook returned units. This benchmark isolates such cross-document decisions from outside accounting knowledge. Complete packets state the fixed policy; the task contract defines abstention when a required document is missing. No real tax, FX or jurisdictional rules are needed.

Use it to regression-test Arabic document reasoning pipelines, compare numeral/order/language sensitivity, inspect evidence-use failures, and experiment with training on controlled cases. Performance here does not establish production accuracy, fraud detection, general Arabic fluency or compliance with any accounting standard.

## Load and evaluate

```python
from datasets import load_dataset
cases = load_dataset("Bayanat-Labs/arabic-reconciliation-bench", "cases", split="test", streaming=True)
row = next(iter(cases))
model_visible = {"question": row["question"], "documents": row["documents"]}
# Pass only model_visible through core.py:model_input.
# Never include gold_*, mechanism, world, view, family_id or canonical specs.
```

The `pairs` configuration links case IDs and declares either invariant representations or sensitivity interventions. Optional `pages` contains images and field boxes from the bounded visual subset; it does not add independent business cases. PDFs and visual manifests are under `visual_subset/`.

The visual subset contains **28 generated families, 168 PDF packets, 1,120 Arabic image pages and 21,042 field-container boxes** across test/challenge and two numeral views. Boxes are mechanically derived from rendered field containers, not human text-region annotations. All 56 clean-to-critical visual comparisons change exactly one document image. See the [visual subset description](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/visual_subset/README.md), [audit](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/visual_subset/validation_report.json), and [rendering instructions](RENDERING.md).

The downloadable source includes a local Ollama runner, a strict JSONL scorer and an independent validator:

```sh
python -m pip install -r requirements.txt
python verify.py --release . --expected-families-per-mechanism 400 --output ../validation.json
python score.py --help
python tests/run_tests.py --output ../test-results
python run_models.py --release-dir . --output-dir ../model-runs --max-families 14 --models qwen2.5:3b
```

See [REPRODUCING.md](REPRODUCING.md) for frozen Hub downloads, regeneration, explicit subset scoring and transparent baselines. The source repository includes a small independent semantic/mutation-test CI; it does not download this dataset or run models.

`run_models.py` uses installed local weights only and never downloads a model or calls a paid/cloud API. Results bind the exact weight digest, input hashes, prompt protocol and decoding settings. The provided model example names must exist in your own Ollama installation; choose `--models` explicitly otherwise.

## Size and splits

| Split | Generated families | Case views | Comparison pairs |
|---|---:|---:|---:|
| train | 3,920 | 47,040 | 66,640 |
| validation | 560 | 6,720 | 9,520 |
| test | 560 | 6,720 | 9,520 |
| challenge | 560 | 6,720 | 9,520 |

Each family has three worlds: a matching packet, a one-field critical edit causing mismatch, and an omitted required document causing insufficient evidence. Each world is represented as Arabic with Western digits, Arabic with Arabic-Indic digits, Arabic with reordered documents/fields, and an aligned English control. Opaque identifiers remain ASCII in every view. These are controlled MSA/English renderings; no dialect or natural user-query coverage is claimed.

All siblings stay in one split. Families, order/invoice/item IDs and packet values are generated separately. Case/family/pair IDs are 24-character truncated SHA256 identifiers; visible document/field and business IDs use the documented shorter formats. Training/validation use two label styles; test and challenge introduce specified label synonyms. Challenge also uses four invoice lines and more applicable amendments. This is a narrow controlled holdout, not evidence of general out-of-distribution performance. All 14 mechanisms are present in every split.

The same formal policy and rendering grammar span all splits. Families and their siblings are assigned to disjoint splits, while individual numerical values, currency codes and controlled phrases can recur. Test/challenge change specified label synonyms and line complexity; there is no held-out policy, workflow, institution, natural-document source or language variety. The format-aware reference baseline is explicitly programmed for all released styles.

## Covered interventions

- `receipt_quantity` — نقص الكمية المستلمة
- `rejected_quantity` — كمية مرفوضة
- `return_quantity` — مرتجعات معتمدة
- `pack_conversion` — تحويل العبوات إلى قطع
- `cumulative_billing` — الفواتير السابقة التراكمية
- `price_tolerance` — حد تفاوت السعر
- `discount` — اختلاف الخصم
- `invoice_total` — إجمالي حسابي خاطئ
- `currency` — اختلاف العملة
- `duplicate_invoice` — فاتورة مكررة
- `amendment_date` — تاريخ نفاذ التعديل
- `amendment_status` — حالة اعتماد التعديل
- `receipt_date` — تاريخ الاستلام
- `cancellation` — أمر شراء ملغى

Every critical pair changes exactly one canonical field value while holding all other fields fixed. For example, a pack-size definition can reduce received base units below the invoiced quantity. An invoice-total edit deliberately introduces arithmetic inconsistency; dependent totals are not silently recomputed. The omission world starts from the clean packet and removes one required document.

Invariant pairs isolate numeric/date field rendering (including amounts, quantities and percentages), document/field order or aligned language rendering. Sensitivity pairs join clean to critical-edit or missing-document worlds. English controls are authored controlled counterparts, not a machine-translation quality benchmark.

## Formal answer contract

```json
{"decision":"match","contract_net_minor":12345,"issues":[],"evidence_ids":["D02.F03"]}
```

The snippet illustrates the schema only and is not a scored dataset answer. The amount is the nominal contract net for **all requested invoice quantities**, using the effective contract price and PO discount, rounded HALF_UP per line to integer minor units. It is not a payable amount. It can remain calculable even when matching fails or a receipt register is missing. Missing PO, invoice or amendment register makes that amount unknown (`null`).

The task explicitly requires complete documents before a matching decision. Missing policy or a required register therefore yields `insufficient_evidence`; it does not invite the model to guess a plausible missing value. See [SPEC.md](SPEC.md) for exact formulas, precedence and issue semantics.

In v0.1, omissions are sampled from policy, PO, receipts, returns, history and amendments; invoice omission is supported by the formal contract and unit tests but is not sampled in this release. Every omission removes one whole document: complete packets have seven documents and omission packets six. Missing-evidence decision accuracy therefore includes a document-presence shortcut; it does not measure ambiguity detection or difficult open-world uncertainty.

## Evidence and scoring

Visible fields have stable bracketed IDs. The independent oracle records the fields read by its specified checks and amount computation. This reference is an auditable software read trace, **not a uniquely minimal human proof**. Reference coverage and F1 measure agreement with that trace; citing every visible field can inflate coverage, so assess precision and over-citation as well. With otherwise correct answers, citing every visible field passes the documented joint evidence requirement. Extra valid citations are allowed. Valid citation IDs alone do not establish correct reasoning or faithful evidence use.

Report decision accuracy and per-class precision/recall, exact amount, exact issue set, reference-evidence precision/recall, and the strict joint criterion separately. Paired-both-correct measures correctness on both members of each invariant or sensitivity comparison; all-controlled-views-correct measures robust correctness. Merely producing unchanged answers across views is insufficient because the same wrong answer is also invariant. Cluster uncertainty estimates by generated family, never repeated row.

`core_exact` requires the decision, nominal amount and issue set to match. `strict_joint` additionally requires full reference-evidence coverage and no nonexistent citations. Paired reports provide decision, core and strict-joint rates; `all_view_joint` and `all_family_joint` require strict joint on all four controlled views of a world or all twelve cases of a family. These strict metrics can be dominated by read-trace citation requirements, so inspect decision/amount/issues and evidence diagnostics separately. All-view scores include the aligned English control. Family bootstrap intervals quantify variation within this generated population, not uncertainty about real deployments.

## Checks and actual baselines

Independent structural/semantic-contract auditor status: **passed**. See [reports/validation.json](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/reports/validation.json) for exact scope and counts. This is an independent software implementation, not a human or accountant review.

Actual local-model results and exact evaluation scope are in [reports/model_results.json](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/reports/model_results.json). Interpret these as a small reproducible diagnostic sample, not a population leaderboard or production certification. Per-model manifests, raw responses and normalized predictions are included under `baselines/`.

The direct-answer, tool-free local GGUF baseline was run on **14 preselected test families, 168 correlated case views**, one family per intervention mechanism. Fixed JSON-schema constrained decoding was used; no wrong or schema-invalid answer was repaired or retried. Core exact requires decision, nominal amount and issue set together, without evidence requirements.

| Local model | Case views | Decision exact [95% CI] | Amount exact | Core exact [95% CI] |
|---|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | 168 | 31.5% [27.4, 35.7] | 0.0% | 0.0% [0.0, 0.0] |

Brackets are 95% family-cluster bootstrap intervals in percentage points (1,000 resamples). There are 14 generated family clusters, not 168 independent observations. Selected omissions cover returns, history and policy only; all 168 amount targets are numeric, with no null-target coverage. This small synthetic diagnostic does not rank general model quality or estimate deployment accuracy. Exact model licenses, digests, token/context limitations, original responses and paired/evidence scores are disclosed in [RESULTS.md](RESULTS.md).


The readable actual-model report is [RESULTS.md](RESULTS.md), with the precise evaluation sample and decoding protocol; results are diagnostic measurements rather than deployment claims.
Deterministically selected [error examples](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/baselines/local_models/FAILURE_ANALYSIS.md) include exact visible inputs, reference answers and predictions. They illustrate observed errors without establishing their cause or prevalence in real documents.


Full-suite transparent baselines use only case IDs and, for the symbolic reference, the public question/documents. The fixed prior always returns `match`, amount `0`, and empty issues/evidence. Classes are tied, so `match` is an explicit fixed tie-break, not a fitted majority estimate.

| Baseline | Case views | Decision exact | Amount exact | Issue set exact | Strict joint |
|---|---:|---:|---:|---:|---:|
| Fixed context-free prior | 67,200 | 33.33% | 0.00% | 33.33% | 0.00% |
| FORMAT-AWARE SYMBOLIC REFERENCE | 67,200 | 100.00% | 100.00% | 100.00% | 100.00% |

The **FORMAT-AWARE SYMBOLIC REFERENCE** explicitly recognizes every declared controlled title, label synonym, numeral format and row layout, then executes the independently implemented policy. It had **0 parsing/execution failures**. Its score demonstrates an executable controlled-format ceiling; it is not a learned-model result, unrestricted Arabic parser, OCR benchmark result, or production invoice system. It does not interpret arbitrary policy prose. See [reports/heuristic_baselines.json](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/reports/heuristic_baselines.json) for hashes, scope, metrics and family-cluster intervals; normalized predictions and failures are under `baselines/`.


The reference oracle uses canonical structured fields and is a generation/validation ceiling. It is not a competitive model. The model runner sees only the published question and document ID/title/text, with a fixed output-schema contract; it cannot access canonical fields, labels or intervention metadata. Model failures and invalid outputs remain in the published record.

## Provenance, rights and limitations

All business facts, document strings and controlled templates are newly generated for this release with AI assistance. No customer invoices, personal identifiers, real bank details, external document prose or third-party benchmark examples were republished. Terminology and task design were informed by the primary sources listed in [RELATED_WORK.md](RELATED_WORK.md). This is not a translation or subset of FinBalance or another benchmark.

Original generated cases, gold annotations and project documentation: **CC BY 4.0**. Original project code: **Apache-2.0**. Bundled Noto fonts retain their **SIL Open Font License 1.1**, separately included. Actual-model evaluation responses are packaged separately from gold; this dataset license does not override applicable model-provider terms, including conditions on downstream training from those responses. Model weights and model implementation source are not redistributed. See [NOTICE.md](NOTICE.md) for exact model provenance/license links, `DATA_LICENSE.txt`, `LICENSE` and the visual font notice.

Key limitations: synthetic template language; no native-speaker/accountant validation; simplified fixed policies; exact shared item/order identifiers; clean rendered documents rather than real scans; limited layout variety; public answers and generator allow contamination; controlled test populations do not estimate customer incident frequency. Header roles, whole-document omissions and fixed templates admit structural shortcuts. Training benefit on real documents and production usefulness have not been measured. Do not use benchmark decisions to approve actual payments or make claims about real vendors.

The generator permits fresh seeds and values for additional controlled tests. Such generated tests share the same formal task and template biases; a new seed does not establish real-world validity.
