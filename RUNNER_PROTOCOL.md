# Local model evaluation protocol

`run_models.py` evaluates pre-existing local Ollama weights. It never pulls a
model, calls a cloud inference provider, reads credentials, or sends prompts
through an environment-configured proxy. The default endpoint is loopback
HTTP. Models run sequentially and each is unloaded after its run. The initial release's sole completed language-model baseline is Qwen2.5 3B; an exploratory Fanar run
was excluded for source-context ambiguity and is not a comparative result.

## Fixed evaluation conditions

- Test families are ranked by SHA-256 within each mechanism, then selected in
  mechanism round-robin order. The default 14 families include one from every
  mechanism. All 12 sibling cases are retained: 168 rows per model.
- `core.model_input` receives only the question and visible document
  `doc_id`, `title`, and `text`. Gold answers, canonical facts, world, view and
  mechanism labels are not passed to the prompt formatter or model.
- The default protocol uses the same fixed, gold-independent JSON schema for
  every model and case. Schema-constrained decoding is explicitly recorded;
  these results should not be presented as unconstrained JSON compliance.
- Defaults are temperature `0`, seed `20261015`, context `8192`, maximum output
  `2048` tokens, `truncate=false`, and `shift=false`. Context errors are retained
  instead of silently clipping the packet.
- Parsing accepts only a complete JSON object matching the output contract.
  There is no code-fence stripping, regex extraction, numeric coercion, missing
  field completion, answer repair, or second model request for an invalid or
  incorrect answer. Citation arrays remain unchanged.

The local API's `/api/tags` result supplies the exact model digest and model
metadata; the Ollama server version is recorded too. Saved requests, digests
and options reproduce the disclosed setup; seeded GPU inference need not be
bit-identical across hardware or Ollama versions. No missing model is
automatically installed.

## Run and resume

```bash
python run_models.py \
  --release-dir /path/to/release \
  --output-dir /path/to/model-runs \
  --max-families 14 \
  --models qwen2.5:3b \
  --format schema --num-ctx 8192 --num-predict 2048
```

For an initial complete-family pilot, use `--max-families 1`. Running the same
command later with `14` expands the deterministic prefix without repeating
completed requests. Run identity binds test-file hashes, exact model digest,
Ollama version, prompt formatter code, schema hash and generation options.
Changes require a fresh output directory. A successfully returned but wrong or
schema-invalid answer is a completed request and is never silently retried.

`--max-new-requests N` bounds new requests per model. An incomplete run retains
missing cases in the score denominator and labels coverage as incomplete; its
score is not a completed benchmark result. Three consecutive transport errors
stop that model's generation loop. `--retry-errors` explicitly retries transport
failures only and retains all original attempts.

To pause at the next request boundary, create `OUTPUT_DIR/PAUSE`. The current
request finishes and checkpoints; the runner then stops before another request
or model. Remove that file before resuming. `--pause-file` can choose another
path. Interruptions also retain every fully written row checkpoint.

## Published evidence

Each model directory contains:

- `run_manifest.json`: identity binding, fixed schema/options, source model
  metadata, sample definition and completion/schema/transport coverage.
- `raw_responses.jsonl`: exact public requests, response text and API response,
  model digest, family/case identifiers, prompt/request hashes, timestamps,
  timings, parser status and normalized prediction.
- `predictions.jsonl`: one scorer-compatible record per completed selected
  case. Invalid output is represented by its case ID only and counts wrong.
- `score_report.json`: independent `score.py` results over the explicit selected
  case universe, including missing outputs and family-cluster intervals.

The root `selected_cases.json` identifies the selected families and cases.
`baseline_report.json` aggregates model reports only when their selected case
universe and source fingerprints agree. It is safe to run the two models in
separate sequential invocations with the same selection and output directory.

These are small-sample results on controlled synthetic procurement packets.
Correlated views are not independent cases. Citation metrics compare with an
explicit reference set, not a human-certified semantic proof. Neither the
reference oracle nor a hardcoded truth lookup is a competing language-model
baseline.

## Model provenance, context and source terms

The evaluated local tags identify quantized conversions, rather than a hosted
vendor endpoint. Exact Ollama digests remain the run identity. The source models
and source terms were checked on 2026-10-15:

- Qwen2.5 3B Instruct: [official model card](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)
  and [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE).
  This 3B model uses the Qwen Research License; it is not covered by a generic
  Apache-2.0 claim. The source card declares a 32,768-token context, consistent
  with the local GGUF metadata.
- Fanar-1 9B Instruct: [official QCRI model card](https://huggingface.co/QCRI/Fanar-1-9B-Instruct)
  (Apache-2.0) and [source configuration](https://huggingface.co/QCRI/Fanar-1-9B-Instruct/blob/main/config.json).
  The local tag references the [yasserrmd GGUF conversion](https://huggingface.co/yasserrmd/Fanar-1-9B-Instruct-gguf).
  The official card and source configuration declare 4,096 tokens; the local
  GGUF declares 8,192. The fixed evaluation context remains 8,192. Final measured
  reports distinguish this configuration from source-model context and count
  requests whose reported prompt-token plus generated-token total exceeds
  4,096. Such requests must be identified as context extrapolation rather than
  native-context performance.

No weights or model implementation are redistributed. Qwen use here is a
research/evaluation run; its responses are retained as evaluation traces and
are not benchmark gold or training-table content. Downstream use of model
weights or outputs must respect source-model terms. In particular, the Qwen
license contains conditions for creating, training or improving a distributed
AI model using its outputs. Dataset/documentation and implementation licenses
do not replace those model-specific terms.

A single separately logged, gold-independent literal schema control asked the
loaded Fanar to return the integer `12345` with the same schema and generation
options. It returned the exact requested object. `protocol_smoke.json` preserves
that request/response; it is excluded from benchmark selection, predictions and
all scores. This checks numeric representability under the runtime grammar, not
document reasoning or benchmark answer correctness.
