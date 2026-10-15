# Reproducing Arabic Reconciliation Bench

Use Python 3.13 from the source-repository root. The same source is distributed
under `code/` in the Hugging Face dataset; when using that copy, run these
commands from `code/` and adjust the release path accordingly.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python tests/run_tests.py --output test-results
```

The tests use hand-authored cases and tiny temporary files, not the full dataset.
For tests alone, `requirements-ci.txt` is sufficient. They write JSON and JUnit
reports. They do not call the generator's oracle to establish expected outcomes.

## Download a frozen released text dataset

Resolve the current Hub revision once, save its commit, and use that immutable
commit for the download. To reproduce a previous run, replace the resolution of
`revision` below with that run's recorded commit hash.

```python
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

repo = "Bayanat-Labs/arabic-reconciliation-bench"
revision = HfApi().dataset_info(repo, revision="main").sha
snapshot_download(
    repo_id=repo,
    repo_type="dataset",
    revision=revision,
    local_dir="downloaded-release",
    allow_patterns=[
        "data/cases/*", "data/pairs/*", "specs/*", "statistics.json",
        "reports/validation.json", "reports/heuristic_baselines.json",
    ],
)
Path("download-revision.json").write_text(
    json.dumps({"repo_id": repo, "revision": revision}, indent=2) + "\n"
)
```

This deliberately omits the larger optional visual files and model-run
artifacts. Use the recorded dataset commit and source version together; a
floating `main` alone does not identify a reproducible release.

```sh
python verify.py --release downloaded-release \
  --expected-families-per-mechanism 400 --output downloaded-validation.json
```

The independent auditor uses exact integer half-up arithmetic and imports
neither `core.py` nor `generator.py`. It checks all canonical worlds, public
Parquet rows, visible field values, evidence references, single-field edits,
omissions, family split closure and comparison pairs. Its report records input
file SHA-256 hashes. This is validation of the declared synthetic task, not
human, linguistic, accounting or production validation.

## Regenerate the text release

```sh
python generator.py --output generated-release \
  --families-per-mechanism 400 --seed 20261015
python verify.py --release generated-release \
  --expected-families-per-mechanism 400 --output generated-validation.json
```

Expected logical counts are 5,600 families, 67,200 case views and 95,200 pairs.
Regeneration with the same code/dependencies/seed reproduces logical records;
compressed-file bytes can differ because gzip headers include write-time
metadata and Parquet serialization depends on the environment. Compare the
canonical records and audit counts rather than requiring fresh file hashes to
equal the downloaded export. A fresh seed changes values within the same
controlled grammar; it does not create a new policy family or real-world test.

## Score predictions

One JSON object per line:

```json
{"case_id":"<released case ID>","decision":"match","contract_net_minor":12345,"issues":[],"evidence_ids":["D02.F03"]}
```

The example illustrates the schema and is not a real scored answer. Invalid
model responses should retain their identity as `{"case_id":"..."}`; keep raw
text separately. Missing/invalid selected outputs count as wrong, duplicate IDs
are rejected, and nonexistent citation IDs fail strict joint correctness.

```sh
python score.py --release downloaded-release --predictions predictions.jsonl \
  --bootstrap-samples 1000 --seed 20261015 --output scores.json
python score.py --release downloaded-release --predictions subset.jsonl \
  --case-ids-file selected_case_ids.json --output subset-scores.json
```

`selected_case_ids.json` is a JSON list of case IDs or a newline-separated list.
Specify it for a model subset; otherwise the denominator is the entire release
and all omitted cases are wrong. Unknown or unselected prediction IDs raise an
error. Plain or gzip-compressed prediction JSONL is supported.

Report decision, amount, issue-set and `core_exact` alongside evidence metrics.
`strict_joint` adds full reference-read-trace coverage and valid citations;
extra valid fields are allowed. Pair reports include decision/core/joint rates;
`all_view_joint` and `all_family_joint` use strict joint, including evidence.
Confidence intervals resample whole generated families. They characterize this
controlled population rather than customer deployments.

## Reproduce transparent full-suite baselines

```sh
python baseline_heuristics.py --release downloaded-release \
  --output heuristic-baselines --bootstrap-samples 1000 --seed 20261015
```

The fixed prior always emits `match`, zero amount and empty issues/evidence.
The **FORMAT-AWARE SYMBOLIC REFERENCE** reads only the public question and
document ID/title/text, recognizes the declared controlled grammar, and invokes
the independent formal executor. It loads neither gold nor canonical specs to
produce predictions. Unknown labels/formatting produce explicit invalid
predictions and a failure log rather than silent repairs. Its expected perfect
score is a format ceiling, not a learned-model, OCR or production-system result.

Model inference is optional and excluded from CI. See `RUNNER_PROTOCOL.md` for
the local Ollama protocol, fixed decoding/output-schema settings, complete-family
sampling, checkpoints, raw responses and model digests. See `RENDERING.md` for
the separately bounded visual subset. The main dataset is a controlled text
reasoning benchmark, and the visual subset does not add independent transactions.
