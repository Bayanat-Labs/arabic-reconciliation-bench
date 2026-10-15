# Provenance and licensing notice

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
  declares Apache-2.0. A separately logged non-benchmark numeric-format control used the community
  [yasserrmd GGUF quantization](https://huggingface.co/yasserrmd/Fanar-1-9B-Instruct-gguf),
  with the exact local digest recorded in `model_source_info.json`. An exploratory
  benchmark run was stopped and excluded from the published baseline because
  some requests exceeded the original model's documented 4,096-token context;
  the conversion/runtime declared 8,192. No partial Fanar aggregate score or
  partial benchmark responses are included. This records upstream provenance;
  it does not redistribute those model materials.

These upstream notices were checked on 2026-10-15. CC BY 4.0 for the original
benchmark does not replace model-provider terms or grant additional rights
to use model materials or evaluation outputs for inference, downstream model
training, or other purposes. Consult the linked upstream terms for those uses.
