# Bayanat Arabic Reconciliation Bench — private staging

Original controlled synthetic Arabic procurement benchmark, with matched
single-fact interventions, numeral/order/language controls and missing-document
cases. This private source repository is being prepared for a reproducible
release. Model evaluations are still being finalized; no model-performance
claims are made in this staging README.

Intended public destinations:

- [Dataset on Hugging Face](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench)
- [Interactive evidence explorer](https://huggingface.co/spaces/Bayanat-Labs/arabic-reconciliation-bench)

The source tree contains the generator, independent auditor/scorer, transparent
symbolic reference, local model runner, visual-rendering code and small tests.
Large datasets, PDFs/images, full prediction traces and model weights are not
stored in this repository.

```sh
python -m pip install -r requirements-ci.txt
python tests/run_tests.py --output test-results
```

The tests use hand-authored facts and tiny temporary Parquet fixtures. They do
not download the dataset, call models, or require secrets. See [CI.md](CI.md),
[SPEC.md](SPEC.md) and [REPRODUCING.md](REPRODUCING.md).

Original project code: [Apache-2.0](LICENSE). Original generated benchmark
cases/gold: [CC BY 4.0](DATA_LICENSE.txt). Noto fonts retain their included OFL1.1
notice. Separate evaluation-output/model-provider conditions are explained in
[NOTICE.md](NOTICE.md). No human/accountant or production validation is claimed.
