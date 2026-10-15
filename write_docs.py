"""Write measured dataset documentation; no publication (Apache-2.0)."""
from pathlib import Path
import argparse,json,shutil
from datetime import date

MECHANISM_AR={
 'receipt_quantity':'نقص الكمية المستلمة','rejected_quantity':'كمية مرفوضة','return_quantity':'مرتجعات معتمدة',
 'pack_conversion':'تحويل العبوات إلى قطع','cumulative_billing':'الفواتير السابقة التراكمية',
 'price_tolerance':'حد تفاوت السعر','discount':'اختلاف الخصم','invoice_total':'إجمالي حسابي خاطئ',
 'currency':'اختلاف العملة','duplicate_invoice':'فاتورة مكررة','amendment_date':'تاريخ نفاذ التعديل',
 'amendment_status':'حالة اعتماد التعديل','receipt_date':'تاريخ الاستلام','cancellation':'أمر شراء ملغى'}
SOURCES=[
 ('Microsoft: invoice matching workflow','https://learn.microsoft.com/ar-sa/dynamics365/finance/accounts-payable/accounts-payable-invoice-matching','Operational terminology and the relationship between PO, invoice, receipts and tolerances. No vendor examples or documents copied.'),
 ('Oracle: match approval levels','https://docs.oracle.com/en/cloud/saas/procurement/26b/oapro/match-approval-level-options.html','Operational relevance of two/three-way matching. Our fictional policy is not an implementation of all Oracle rules.'),
 ('FinBalance','https://arxiv.org/abs/2606.15949','Closest accounting benchmark: multi-document synthetic bundles, deterministic accounting oracle and contradictions already exist. Our contribution is not this general concept.'),
 ('SAHM','https://aclanthology.org/2026.acl-long.1593/','Arabic financial and Sharia reasoning benchmark; broader Arabic finance benchmarks already exist.'),
 ('KITAB-Bench','https://github.com/mbzuai-oryx/KITAB-Bench','Arabic OCR and document understanding; we make no claim to be the first Arabic document benchmark.'),
 ('AraTable','https://arxiv.org/abs/2507.18442','Arabic table QA, reasoning and fact verification.'),
 ('AMuRD','https://arxiv.org/abs/2309.09800','Arabic-English receipt extraction and classification.'),
 ('Synthetic bilingual invoices','https://huggingface.co/datasets/HV09/synthetic-bilingual-invoices-200','Rendered Arabic/English invoice field-extraction data already exists.'),
 ('Ciru invoice sandbox','https://github.com/ciru-ai/invoice-sandbox-benchmark','Existing synthetic invoice workflow fixtures; not copied into this resource.')]

def main():
 p=argparse.ArgumentParser();p.add_argument('--release-dir',type=Path,required=True);p.add_argument('--validation',type=Path);p.add_argument('--models',type=Path);p.add_argument('--heuristics',type=Path);args=p.parse_args();r=args.release_dir
 stats=json.loads((r/'statistics.json').read_text());meta=['---','pretty_name: Bayanat Arabic Reconciliation Bench','language:','- ar','- en','license: cc-by-4.0','task_categories:','- question-answering','- text-classification','size_categories:','- 10K<n<100K','annotations_creators:','- machine-generated','language_creators:','- machine-generated','tags:','- arabic','- procurement','- document-understanding','- counterfactual-evaluation','- synthetic','- accounting','configs:']
 configs=['cases','pairs']+(['pages'] if (r/'data/pages').exists() else [])
 for config in configs:
  meta+=['- config_name: '+config]
  if config=='cases':meta+=['  default: true']
  meta+=['  data_files:']
  for split in ('train','validation','test','challenge'):
   if list((r/'data'/config).glob(split+'-*.parquet')):meta+=['  - split: '+split,'    path: data/'+config+'/'+split+'-*.parquet']
 meta+=['---']
 table='\n'.join(f"| {s} | {stats['family_counts'][s]:,} | {stats['split_counts']['cases'][s]:,} | {stats['split_counts']['pairs'][s]:,} |" for s in stats['family_counts'])
 mechanisms='\n'.join(f"- `{key}` — {MECHANISM_AR[key]}" for key in stats['mechanisms'])
 reportdir=r/'reports';reportdir.mkdir(exist_ok=True)
 validation='Full-release validation has not yet been supplied to this documentation build.'
 if args.validation:
  value=json.loads(args.validation.read_text());shutil.copyfile(args.validation,reportdir/'validation.json')
  validation=f"Independent structural/semantic-contract auditor status: **{value.get('status','see report')}**. See [reports/validation.json](reports/validation.json) for exact scope and counts. This is an independent software implementation, not a human or accountant review."
 baseline='No measured model results have been supplied to this documentation build.'
 if args.models and args.models.exists():
  model=json.loads(args.models.read_text());shutil.copyfile(args.models,reportdir/'model_results.json')
  baseline='Actual local-model results and exact evaluation scope are in [reports/model_results.json](reports/model_results.json). Interpret these as a small reproducible diagnostic sample, not a population leaderboard or production certification. Per-model manifests, raw responses and normalized predictions are included under `baselines/`.'
 heuristics=''
 if args.heuristics:
  heuristic_report=json.loads(args.heuristics.read_text());shutil.copyfile(args.heuristics,reportdir/'heuristic_baselines.json')
  heuristic_rows=[]
  for entry in heuristic_report['baselines']:
   measured=entry['score']['metrics']
   heuristic_rows.append('| '+entry['label']+' | '+f"{measured['cases']:,}"+' | '+' | '.join(f"{100*measured[key]:.2f}%" for key in ('decision_exact','amount_exact','issues_exact','strict_joint'))+' |')
  heuristics='''
Full-suite transparent baselines use only case IDs and, for the symbolic reference, the public question/documents. The fixed prior always returns `match`, amount `0`, and empty issues/evidence. Classes are tied, so `match` is an explicit fixed tie-break, not a fitted majority estimate.

| Baseline | Case views | Decision exact | Amount exact | Issue set exact | Strict joint |
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(heuristic_rows)+f'''

The **FORMAT-AWARE SYMBOLIC REFERENCE** explicitly recognizes every declared controlled title, label synonym, numeral format and row layout, then executes the independently implemented policy. It had **{heuristic_report['symbolic_parse_or_execution_failures']:,} parsing/execution failures**. Its score demonstrates an executable controlled-format ceiling; it is not a learned-model result, unrestricted Arabic parser, OCR benchmark result, or production invoice system. It does not interpret arbitrary policy prose. See [reports/heuristic_baselines.json](reports/heuristic_baselines.json) for hashes, scope, metrics and family-cluster intervals; normalized predictions and failures are under `baselines/`.
'''
 text='\n'.join(meta)+f'''

# Bayanat Arabic Reconciliation Bench

**Can a model change its answer when one business fact changes—and keep it when only the numeral script or document order changes?**

An original synthetic Arabic-first procurement benchmark for comparing purchase orders, invoices, receipt records, returns, prior invoices and price amendments under explicit fictional policies. The model must decide `match`, `mismatch` or `insufficient_evidence`, calculate the nominal contractual net amount, identify issue codes and cite visible evidence fields.

**{stats['families']:,} generated case families · 14 intervention mechanisms · {stats['counts']['cases']:,} controlled case views · {stats['counts']['pairs']:,} matched comparisons.** Repeated worlds and views are related observations, not independent transactions or human annotations.

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
model_visible = {{"question": row["question"], "documents": row["documents"]}}
# Pass only model_visible through code/core.py:model_input.
# Never include gold_*, mechanism, world, view, family_id or canonical specs.
```

The `pairs` configuration links case IDs and declares either invariant representations or sensitivity interventions. Optional `pages` contains images and field boxes from the bounded visual subset; it does not add independent business cases. PDFs and visual manifests are under `visual_subset/`.

The downloadable source includes a local Ollama runner, a strict JSONL scorer and an independent validator:

```sh
python -m pip install -r code/requirements.txt
python code/verify.py --release . --expected-families-per-mechanism 400 --output ../validation.json
python code/score.py --help
python code/tests/run_tests.py --output ../test-results
python code/run_models.py --release-dir . --output-dir ../model-runs --max-families 14
```

See [code/REPRODUCING.md](code/REPRODUCING.md) for frozen Hub downloads, regeneration, explicit subset scoring and transparent baselines. The source repository includes a small independent semantic/mutation-test CI; it does not download this dataset or run models.

`run_models.py` uses installed local weights only and never downloads a model or calls a paid/cloud API. Results bind the exact weight digest, input hashes, prompt protocol and decoding settings. The provided model example names must exist in your own Ollama installation; choose `--models` explicitly otherwise.

## Size and splits

| Split | Generated families | Case views | Comparison pairs |
|---|---:|---:|---:|
{table}

Each family has three worlds: a matching packet, a one-field critical edit causing mismatch, and an omitted required document causing insufficient evidence. Each world is represented as Arabic with Western digits, Arabic with Arabic-Indic digits, Arabic with reordered documents/fields, and an aligned English control. Opaque identifiers remain ASCII in every view. These are controlled MSA/English renderings; no dialect or natural user-query coverage is claimed.

All siblings stay in one split. Families, order/invoice/item IDs and packet values are generated separately. Case/family/pair IDs are 24-character truncated SHA256 identifiers; visible document/field and business IDs use the documented shorter formats. Training/validation use two label styles; test and challenge introduce specified label synonyms. Challenge also uses four invoice lines and more applicable amendments. This is a narrow controlled holdout, not evidence of general out-of-distribution performance. All 14 mechanisms are present in every split.

The same formal policy and rendering grammar span all splits. Families and their siblings are assigned to disjoint splits, while individual numerical values, currency codes and controlled phrases can recur. Test/challenge change specified label synonyms and line complexity; there is no held-out policy, workflow, institution, natural-document source or language variety. The format-aware reference baseline is explicitly programmed for all released styles.

## Covered interventions

{mechanisms}

Every critical pair changes exactly one canonical field value while holding all other fields fixed. For example, a pack-size definition can reduce received base units below the invoiced quantity. An invoice-total edit deliberately introduces arithmetic inconsistency; dependent totals are not silently recomputed. The omission world starts from the clean packet and removes one required document.

Invariant pairs isolate numeric/date field rendering (including amounts, quantities and percentages), document/field order or aligned language rendering. Sensitivity pairs join clean to critical-edit or missing-document worlds. English controls are authored controlled counterparts, not a machine-translation quality benchmark.

## Formal answer contract

```json
{{"decision":"match","contract_net_minor":12345,"issues":[],"evidence_ids":["D02.F03"]}}
```

The snippet illustrates the schema only and is not a scored dataset answer. The amount is the nominal contract net for **all requested invoice quantities**, using the effective contract price and PO discount, rounded HALF_UP per line to integer minor units. It is not a payable amount. It can remain calculable even when matching fails or a receipt register is missing. Missing PO, invoice or amendment register makes that amount unknown (`null`).

The task explicitly requires complete documents before a matching decision. Missing policy or a required register therefore yields `insufficient_evidence`; it does not invite the model to guess a plausible missing value. See [code/SPEC.md](code/SPEC.md) for exact formulas, precedence and issue semantics.

In v0.1, omissions are sampled from policy, PO, receipts, returns, history and amendments; invoice omission is supported by the formal contract and unit tests but is not sampled in this release. Every omission removes one whole document: complete packets have seven documents and omission packets six. Missing-evidence decision accuracy therefore includes a document-presence shortcut; it does not measure ambiguity detection or difficult open-world uncertainty.

## Evidence and scoring

Visible fields have stable bracketed IDs. The independent oracle records the fields read by its specified checks and amount computation. This reference is an auditable software read trace, **not a uniquely minimal human proof**. Reference coverage and F1 measure agreement with that trace; citing every visible field can inflate coverage, so assess precision and over-citation as well. With otherwise correct answers, citing every visible field passes the documented joint evidence requirement. Extra valid citations are allowed. Valid citation IDs alone do not establish correct reasoning or faithful evidence use.

Report decision accuracy and per-class precision/recall, exact amount, exact issue set, reference-evidence precision/recall, and the strict joint criterion separately. Paired-both-correct measures correctness on both members of each invariant or sensitivity comparison; all-controlled-views-correct measures robust correctness. Merely producing unchanged answers across views is insufficient because the same wrong answer is also invariant. Cluster uncertainty estimates by generated family, never repeated row.

`core_exact` requires the decision, nominal amount and issue set to match. `strict_joint` additionally requires full reference-evidence coverage and no nonexistent citations. Paired reports provide decision, core and strict-joint rates; `all_view_joint` and `all_family_joint` require strict joint on all four controlled views of a world or all twelve cases of a family. These strict metrics can be dominated by read-trace citation requirements, so inspect decision/amount/issues and evidence diagnostics separately. All-view scores include the aligned English control. Family bootstrap intervals quantify variation within this generated population, not uncertainty about real deployments.

## Checks and actual baselines

{validation}

{baseline}

The readable actual-model report is [RESULTS.md](RESULTS.md), with the precise evaluation sample and decoding protocol; results are diagnostic measurements rather than deployment claims.

{heuristics}

The reference oracle uses canonical structured fields and is a generation/validation ceiling. It is not a competitive model. The model runner sees only the published question and document ID/title/text, with a fixed output-schema contract; it cannot access canonical fields, labels or intervention metadata. Model failures and invalid outputs remain in the published record.

## Provenance, rights and limitations

All business facts, document strings and controlled templates are newly generated for this release with AI assistance. No customer invoices, personal identifiers, real bank details, external document prose or third-party benchmark examples were republished. Terminology and task design were informed by the primary sources listed in [RELATED_WORK.md](RELATED_WORK.md). This is not a translation or subset of FinBalance or another benchmark.

Original generated cases, gold annotations and project documentation: **CC BY 4.0**. Original project code: **Apache-2.0**. Bundled Noto fonts retain their **SIL Open Font License 1.1**, separately included. Actual-model evaluation responses are packaged separately from gold; this dataset license does not override applicable model-provider terms, including conditions on downstream training from those responses. Model weights and model implementation source are not redistributed. See [NOTICE.md](NOTICE.md) for exact model provenance/license links, `LICENSE`, `code/LICENSE` and the visual font notice.

Key limitations: synthetic template language; no native-speaker/accountant validation; simplified fixed policies; exact shared item/order identifiers; clean rendered documents rather than real scans; limited layout variety; public answers and generator allow contamination; controlled test populations do not estimate customer incident frequency. Header roles, whole-document omissions and fixed templates admit structural shortcuts. Training benefit on real documents and production usefulness have not been measured. Do not use benchmark decisions to approve actual payments or make claims about real vendors.

The generator permits fresh seeds and values for additional controlled tests. Such generated tests share the same formal task and template biases; a new seed does not establish real-world validity.
'''
 (r/'README.md').write_text(text,encoding='utf-8')
 related='# Related work and research basis\n\nResearch checked on 2026-10-15. This is a selected related-work list, not an exhaustive systematic review. No absence-of-search-results claim establishes that this is the first Arabic procurement benchmark. The contribution is the released combination and implementation, not ownership of reconciliation, counterfactual evaluation, synthetic invoices or Arabic OCR. No novelty ranking, superiority over these resources, or user-demand/adoption evidence is established.\n\n'
 for title,url,note in SOURCES:related+=f'- [{title}]({url}) — {note}\n'
 (r/'RELATED_WORK.md').write_text(related,encoding='utf-8')
 (r/'NOTICE.md').write_text('''# Provenance and licensing notice

Original synthetic benchmark and project software by Bayanat Labs, 2026,
created with AI assistance. Generated case facts, document templates and gold
answers are original Python/template/arithmetic outputs. Local Qwen and Fanar
evaluation responses did not create the benchmark gold or training cases.
No human/accountant validation or third-party endorsement is claimed. Source
papers/vendor documentation informed research; their examples or prose were
not copied into the cases.

The original generated cases, gold annotations and project documentation use
CC BY 4.0. Original project software uses Apache-2.0. Bundled Noto fonts retain
their separately included SIL Open Font License 1.1. Model weights and model
implementation source are not redistributed.

## Separately packaged evaluation outputs

Actual local-model responses, prompts, manifests and normalized predictions
are under `baselines/local_models/` for evaluation reproducibility. They are
separate from generated case facts and gold annotations. Exact installed
weight digests and quantizations are recorded in the run manifests and
`RESULTS.md`.

- **Qwen2.5-3B-Instruct**: Alibaba Cloud's official repository supplies the
  [Qwen Research License Agreement](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/raw/main/LICENSE),
  rather than Apache-2.0. The agreement limits the model materials to
  non-commercial research/evaluation without a separate commercial license,
  and contains conditions for using model outputs/results to train or improve
  a distributed model. The actual evaluation used the installed local
  `qwen2.5:3b` GGUF artifact identified by its manifest digest.
- **Fanar-1-9B-Instruct**: the
  [official QCRI model card](https://huggingface.co/QCRI/Fanar-1-9B-Instruct)
  declares Apache-2.0. The evaluation used the community
  [yasserrmd GGUF quantization](https://huggingface.co/yasserrmd/Fanar-1-9B-Instruct-gguf),
  with the exact local digest recorded in its manifest. This records upstream
  provenance; it does not redistribute those model materials.

These upstream notices were checked on 2026-10-15. CC BY 4.0 for the original
benchmark does not replace model-provider terms or grant additional rights
to use model materials or evaluation outputs for inference, downstream model
training, or other purposes. Consult the linked upstream terms for those uses.
''',encoding='utf-8')
 (r/'CITATION.cff').write_text('cff-version: 1.2.0\nmessage: "Please cite this dataset when using it."\ntitle: "Bayanat Arabic Reconciliation Bench"\nauthors:\n  - name: Bayanat Labs\nversion: 0.1.0\ndate-released: 2026-10-15\nurl: https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench\nlicense: CC-BY-4.0\n')
 (r/'research_sources.json').write_text(json.dumps([{'title':t,'url':u,'use':n,'accessed':'2026-10-15'} for t,u,n in SOURCES],indent=2)+'\n')
 print(json.dumps({'documentation_written':True,'configs':configs,'validation_supplied':bool(args.validation),'models_supplied':bool(args.models)}))

if __name__=='__main__':main()
