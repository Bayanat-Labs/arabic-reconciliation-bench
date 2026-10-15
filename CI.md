# Independent test CI

The published source repository installs `.github/workflows/tests.yml`. In the
unpackaged development tree its template is `github/workflows/tests.yml`; the
release packager places it in `.github/`. It assumes `verify.py`, `score.py`, `baseline_heuristics.py`,
`requirements-ci.txt` and `tests/` are at the repository root.

The workflow installs only the pinned PyArrow test dependency and runs
`python tests/run_tests.py --output test-results`. The tests use hand-authored
facts and tiny temporary Parquet/JSONL fixtures. They exercise rounding,
quantity/status/date filters, amendment precedence, duplicate detection,
missing evidence, reference citations, cross-split siblings, corrupted public
gold/text, subset scoring, clustering and visible-text parsing.

CI downloads neither the released dataset nor model weights. It makes no
inference calls, does not render the visual subset and uses no repository
secrets. JSON and JUnit results are retained as a short-lived Actions artifact.
This verifies software behavior; full-release data validation remains the
separate `verify.py --release ...` command described in `REPRODUCING.md`.

Action majors were checked against the official
[checkout](https://github.com/actions/checkout),
[setup-python](https://github.com/actions/setup-python), and
[upload-artifact](https://github.com/actions/upload-artifact) documentation on
2026-10-15. This template has been tested locally through its test command;
an actual GitHub Actions run is required to verify the hosted workflow.
