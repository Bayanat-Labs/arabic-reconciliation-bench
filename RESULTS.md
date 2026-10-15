# Measured local-model results

The sole published language-model baseline is a completed local Qwen2.5 3B run on **14 deterministic test families, 168 case views**, with one family from each of the 14 mechanisms. Each family supplies three worlds and four controlled views. The effective number of independent generated family clusters is 14, not 168; this is a small diagnostic sample, not a leaderboard, model ranking or production accuracy estimate.

Qwen used **fixed, gold-independent JSON-schema constrained decoding**. Consequently, schema-valid output measures operation under that constraint, not unconstrained JSON compliance. No answer repair or repeat request for a wrong/schema-invalid answer was used. All original responses remain available. A separate gold-independent Fanar smoke control requested the literal amount `12345` with the same schema/options and returned it exactly, confirming numeric representability in that separate Fanar runtime call. This was a Fanar control, not a Qwen control or a completed Fanar benchmark. This single control is excluded from all benchmark counts and scores; its exact record is `protocol_smoke.json` in the local-model bundle. It does not test document reasoning.

## Decision and numeric results

Core exact requires the decision, nominal contract amount and complete issue set all to be correct. It has no evidence-citation requirement. Amount exact is evaluated against the selected nominal contract targets; it is not payable-amount accuracy. All 168 selected targets are numeric; this subset contains no `null` amount targets and does not measure correct abstention on unknown amounts. Omitted required documents in the selected families are history: 5 families, policy: 4 families, returns: 5 families. This composition is a consequence of the preselected deterministic sample, not a result-dependent replacement. Brackets are 95% family-cluster percentile-bootstrap intervals in percentage points (1,000 resamples, seed 20261015); the point estimates use all selected case views. These intervals describe resampling of this small synthetic sample and do not establish population or deployment validity. One selected family per mechanism cannot estimate within-mechanism variation.

| Local model | Decision exact [95% CI] | Amount exact | Issue-set exact | Core exact [95% CI] |
|---|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | 31.5% [27.4, 35.7] | 0.0% | 24.4% | 0.0% [0.0, 0.0] |

## Evidence diagnostics

Evidence precision/recall/F1 below are means of per-case agreement with the executable reference read trace. The trace is not a human-certified or uniquely minimal proof. Reference coverage can be inflated by citing every field. Strict joint combines core exact, full reference coverage and no nonexistent citations; extra valid citations are allowed. Citation and core correctness should therefore be inspected separately.

| Local model | Mean ref. precision | Mean ref. recall | Mean ref. F1 | Full ref. coverage | Strict joint |
|---|---:|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | 47.4% | 26.6% | 27.4% | 1.8% | 0.0% |

## Decision classes

All metrics use the explicitly selected Qwen case universe. An undefined precision is shown as an em dash when the model never predicts that class.

| Local model | Gold class | Support | Predicted | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | `insufficient_evidence` | 56 | 96 | 32.3% | 55.4% | 40.8% |
| Qwen2.5 3B (local GGUF) | `match` | 56 | 63 | 33.3% | 37.5% | 35.3% |
| Qwen2.5 3B (local GGUF) | `mismatch` | 56 | 5 | 20.0% | 1.8% | 3.3% |

## Controlled views

Each view contains the same 42 family-world combinations. English is an aligned controlled rendering; this is not a natural-language distribution comparison or a general Arabic-vs-English performance claim.

| Local model | View | Cases | Decision exact | Core exact |
|---|---|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | `ar_eastern` | 42 | 38.1% | 0.0% |
| Qwen2.5 3B (local GGUF) | `ar_reordered` | 42 | 35.7% | 0.0% |
| Qwen2.5 3B (local GGUF) | `ar_western` | 42 | 21.4% | 0.0% |
| Qwen2.5 3B (local GGUF) | `en_control` | 42 | 31.0% | 0.0% |

## Matched comparisons

Paired-both correctness requires both members to be correct; unchanged wrong answers do not count as robust correctness. Sensitivity pairs compare clean packets with a changed fact or omitted document. Invariance pairs compare controlled representations of the same facts. All pairs share the same small set of family clusters.

| Local model | Pair axis | Pairs | Both decisions correct | Both core answers correct | Both strict-joint correct |
|---|---|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | `invariant/digit_script` | 42 | 16.7% | 0.0% | 0.0% |
| Qwen2.5 3B (local GGUF) | `invariant/document_order` | 42 | 9.5% | 0.0% | 0.0% |
| Qwen2.5 3B (local GGUF) | `invariant/language_control` | 42 | 4.8% | 0.0% | 0.0% |
| Qwen2.5 3B (local GGUF) | `sensitivity/critical_fact` | 56 | 1.8% | 0.0% | 0.0% |
| Qwen2.5 3B (local GGUF) | `sensitivity/missing_document` | 56 | 12.5% | 0.0% | 0.0% |

## Context scope and model provenance

The published Qwen run uses a configured `num_ctx=8192`, within the **32,768-token** context declared by its official model card and local GGUF metadata. Reported prompt tokens plus generated tokens are audited below. No Qwen request exceeds that source-model limit. This controlled run does not establish general model capability.

| Local model | Official source context | Local GGUF declaration | Configured context | Max reported prompt + output | Requests above source context |
|---|---:|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | 32768 | 32768 | 8192 | 5096 | 0 / 168 |

An exploratory Fanar GGUF run was stopped after 8 requests because its local 8,192-token metadata conflicts with the official [4,096-token source context](https://huggingface.co/QCRI/Fanar-1-9B-Instruct/blob/main/config.json); 2 reported prompt-plus-output totals exceeded 4,096. It is excluded from the published benchmark aggregate and has no published aggregate score. Partial inference checkpoints are preserved locally outside this release. The separate literal Fanar control and source provenance remain explicitly labeled as controls. See `EXCLUDED_EXPLORATION.md` in the local-model bundle.

The source [Qwen2.5 3B Instruct card](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) and exact [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) apply; this 3B model is not Apache-2.0. The separate Fanar control used the [yasserrmd GGUF conversion](https://huggingface.co/yasserrmd/Fanar-1-9B-Instruct-gguf) of [QCRI/Fanar-1-9B-Instruct](https://huggingface.co/QCRI/Fanar-1-9B-Instruct), whose official card identifies Apache-2.0. Source metadata is separately recorded in `model_source_info.json`.

No weights or model implementation are distributed. These responses are research/evaluation traces, excluded from the benchmark gold and training tables. Downstream model/output use must follow source-model terms, including Qwen conditions for creating, training or improving a distributed AI model with its outputs. Dataset and code licenses do not replace model-specific terms.

## Reproducible execution

Selection uses `reconciliation-model-test-v1`: SHA-256 family ranking within each mechanism and mechanism round-robin ordering. The complete-family sample was chosen before outputs were inspected and was not replaced after observing results. Prompts contain only the public question and visible document `doc_id`, `title` and `text`, plus the standard answer contract. Gold answers, mechanism, view, world and canonical fields are excluded. Weights were already installed locally; the runner did not pull models or call paid/cloud inference.

Saved requests, weight digests and options reproduce the disclosed setup; seeded GPU inference need not be bit-identical across hardware or Ollama versions.

Fixed options: temperature 0; seed 20261015; context 8192; maximum generated tokens 2048; `truncate=false`; `shift=false`; Ollama 0.32.5. Context/transport failures and invalid/missing outputs count as failures. Model weights are not distributed and retain their original licenses.

| Local model | Completed / requested | Valid under schema constraint | Latest-attempt transport failures | Mean / median request seconds | Prompt token range | Output token range |
|---|---:|---:|---:|---:|---:|---:|
| Qwen2.5 3B (local GGUF) | 168 / 168 | 164 / 168 | 0 | 10.41 / 7.40 | 1921–3741 | 54–2048 |

The execution table uses the latest retained attempt per case for timings and transport failures; raw checkpoints preserve every earlier attempt, if any. Request timings include local desktop contention and model loading where applicable; they are not a controlled hardware-throughput benchmark. Machine metadata, when recorded, is available in `machine_info.json` and the compact JSON.

Exact model tags and digests:

- `qwen2.5:3b` — `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`; artifacts in `qwen2.5-3b-442789f4/`.

The machine-readable [compact_results.json](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/baselines/local_models/compact_results.json) includes exact hashes, protocol bindings, confusion matrices, per-view scores and cluster intervals. [baseline_report.json](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/baselines/local_models/baseline_report.json) contains complete scorer reports. Each model directory contains its exact `run_manifest.json`, `raw_responses.jsonl`, `predictions.jsonl`, and `score_report.json`. The scorer hash is recorded in every score report. Earlier transport/protocol pilots and pre-freeze runs are excluded from these results.

The dataset uses original controlled synthetic templates without native-speaker/accountant validation. These measurements cannot establish real-record reconciliation accuracy, fraud detection, accounting compliance, or business readiness. No model ranking or claim about general model quality follows from this small sample.

[Inspect deterministic error examples and exact visible inputs](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/baselines/local_models/FAILURE_ANALYSIS.md).
