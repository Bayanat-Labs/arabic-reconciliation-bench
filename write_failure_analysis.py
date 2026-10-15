#!/usr/bin/env python3
"""Describe bounded observed errors from the completed published Qwen run.

No inference, answer repair, guessed outputs or causal error explanations.
Categories are overlapping diagnostics, not independent prevalence estimates.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import score

SELECTION_SEED = "arabic-reconciliation-error-examples-v1"
EXPECTED_MODELS = {"qwen2.5:3b"}
CATEGORIES = {
    "schema_invalid": "Invalid schema or missing/invalid response",
    "wrong_decision_valid_schema": "Valid schema, wrong decision",
    "wrong_amount_valid_schema": "Valid schema, wrong nominal amount",
    "wrong_issue_set_valid_schema": "Valid schema, wrong issue set",
    "western_correct_indic_wrong": "Western core-correct, Arabic-Indic core-wrong",
    "western_wrong_indic_correct": "Western core-wrong, Arabic-Indic core-correct",
    "clean_critical_one_core_failure": "Clean/critical pair: exactly one core failure",
    "clean_critical_both_core_failure": "Clean/critical pair: both core failures",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def minhash(model, category, ids):
    return hashlib.sha256("\n".join([SELECTION_SEED, model, category, *ids]).encode()).hexdigest()


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def core_answer(value):
    return {key: value[key] for key in ("decision", "contract_net_minor", "issues") if key in value}


def fenced(text, language=""):
    fence = "`" * max(3, 1 + max((len(match.group()) for match in re.finditer(r"`+", text)), default=0))
    return f"{fence}{language}\n{text}\n{fence}"


def load_cases_and_pairs(release, sample):
    import pyarrow.parquet as pq

    selected_ids = sample["case_ids"]
    require(len(selected_ids) == 168 and len(set(selected_ids)) == 168, "Expected exactly 168 distinct selected cases")
    require(sample["family_count"] == 14 and sample["case_count"] == 168 and sample["split"] == "test",
            "Final analysis is scoped to the preselected 14-family/168-case test sample")
    wanted = set(selected_ids)
    cases, input_hashes = {}, {}
    for inventory in sample["test_files"]:
        path = release / inventory["path"]
        require(path.resolve().is_relative_to(release.resolve()), "Source case path escapes release directory")
        require(sha(path) == inventory["sha256"], f"Source case file changed: {path.name}")
        input_hashes[path.relative_to(release).as_posix()] = inventory["sha256"]
        for batch in pq.ParquetFile(path).iter_batches(batch_size=256):
            for row in batch.to_pylist():
                if row["case_id"] in wanted:
                    require(row["case_id"] not in cases, "Duplicate selected release case")
                    cases[row["case_id"]] = row
    require(set(cases) == wanted, "Some selected cases are absent from the released gold")
    families = defaultdict(list)
    for row in cases.values():
        families[row["family_id"]].append(row)
    expected = {(world, view) for world in ("clean", "critical_edit", "missing_evidence")
                for view in ("ar_western", "ar_eastern", "ar_reordered", "en_control")}
    require(len(families) == 14, "Selected release rows do not cover fourteen families")
    for family, rows in families.items():
        require(len(rows) == 12 and {(row["world"], row["view"]) for row in rows} == expected,
                f"Incomplete family closure: {family}")
        require(len({row["mechanism"] for row in rows}) == 1, "Mechanism changes within a selected family")
    require(len({rows[0]["mechanism"] for rows in families.values()}) == 14,
            "Sample is not exactly one family per mechanism")
    pairs = []
    for path in sorted((release / "data" / "pairs").glob("test-*.parquet")):
        input_hashes[path.relative_to(release).as_posix()] = sha(path)
        for batch in pq.ParquetFile(path).iter_batches(batch_size=2048):
            for pair in batch.to_pylist():
                a, b = pair["case_id_a"], pair["case_id_b"]
                if a in wanted and b in wanted and pair["axis"] in {"digit_script", "critical_fact"}:
                    require(cases[a]["family_id"] == cases[b]["family_id"] == pair["family_id"], "Selected pair crosses families")
                    if pair["axis"] == "digit_script":
                        require(pair["relation"] == "invariant" and cases[a]["view"] == "ar_western" and
                                cases[b]["view"] == "ar_eastern" and cases[a]["world"] == cases[b]["world"],
                                "Unexpected numeral pair direction")
                    else:
                        require(pair["relation"] == "sensitivity" and cases[a]["world"] == "clean" and
                                cases[b]["world"] == "critical_edit" and cases[a]["view"] == cases[b]["view"],
                                "Unexpected critical pair direction")
                    pairs.append(pair)
    counts = Counter(pair["axis"] for pair in pairs)
    require(counts == {"digit_script": 42, "critical_fact": 56}, "Selected comparison-pair denominator differs")
    require(len({pair["pair_id"] for pair in pairs}) == len(pairs), "Duplicate selected comparison pair")
    return cases, pairs, input_hashes


def load_model(run_dir, summary, sample, cases):
    folder = run_dir / summary["run_directory"]
    require(folder.resolve().is_relative_to(run_dir.resolve()), "Model path escapes run directory")
    coverage = summary["coverage"]
    require(coverage["complete"] and coverage["completed_cases"] == coverage["requested_cases"] == 168,
            f"Final model run is incomplete: {summary['model']}")
    require(coverage["requested_families"] == 14, "Model run family denominator differs")
    manifest_path = folder / "run_manifest.json"
    require(sha(manifest_path) == summary["manifest_sha256"], "Model manifest changed after aggregation")
    manifest = read(manifest_path)
    require(manifest["binding"]["model"] == summary["model"] and
            manifest["binding"]["model_digest"] == summary["model_digest"], "Model identity mismatch")
    require(manifest["requested_sample"]["case_ids"] == sample["case_ids"] and
            manifest["binding"]["dataset_fingerprint"] == sample["dataset_fingerprint"], "Model sample fingerprint mismatch")
    prediction_path = folder / "predictions.jsonl"
    require(sha(prediction_path) == coverage["predictions_sha256"], "Prediction file changed after final aggregation")
    predictions = score.read_predictions(prediction_path)
    require(set(predictions) == set(cases), "Predictions do not exactly cover all 168 selected cases")
    latest = {}
    raw_path = folder / "raw_responses.jsonl"
    with raw_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record["case_id"] in cases:
                    latest[record["case_id"]] = record
    require(set(latest) == set(cases), "Raw responses do not cover all selected cases")
    for case_id in cases:
        require(latest[case_id]["model"] == summary["model"] and latest[case_id]["model_digest"] == summary["model_digest"],
                "Raw response model identity differs from final run")
        require(latest[case_id]["prediction"] == predictions[case_id], "Normalized prediction differs from retained raw attempt")
    outcomes = {case_id: score.evaluate_case(cases[case_id], predictions[case_id]) for case_id in cases}
    scored = summary["score_report"]
    require(read(folder / "score_report.json") == scored, "On-disk and aggregated scorer reports differ")
    require(scored and scored["metrics"]["cases"] == 168 and scored["selected_families"] == 14,
            "Existing scorer report has the wrong evaluation universe")
    require(scored["scorer"]["sha256"] == sha(Path(score.__file__)), "Frozen scorer differs from the measured report")
    for metric in ("schema_valid", "decision_exact", "amount_exact", "issues_exact", "core_exact", "strict_joint"):
        observed = sum(value[metric] for value in outcomes.values()) / 168
        require(abs(observed - scored["metrics"][metric]) < 1e-12, f"Recomputed {metric} differs from final scorer")
    return {"summary": summary, "predictions": predictions, "raw": latest, "outcomes": outcomes,
            "artifacts": {name: sha(folder / name) for name in
                          ("run_manifest.json", "raw_responses.jsonl", "predictions.jsonl", "score_report.json")}}


def candidates_for(model, cases, pairs):
    candidates = {category: [] for category in CATEGORIES}
    outcomes = model["outcomes"]
    for case_id, result in outcomes.items():
        if not result["schema_valid"]:
            candidates["schema_invalid"].append((case_id,))
        else:
            for metric, category in (("decision_exact", "wrong_decision_valid_schema"),
                                     ("amount_exact", "wrong_amount_valid_schema"),
                                     ("issues_exact", "wrong_issue_set_valid_schema")):
                if not result[metric]:
                    candidates[category].append((case_id,))
    for pair in pairs:
        a, b = pair["case_id_a"], pair["case_id_b"]
        left, right = outcomes[a]["core_exact"], outcomes[b]["core_exact"]
        if pair["axis"] == "digit_script":
            if left and not right:
                candidates["western_correct_indic_wrong"].append((a, b))
            if right and not left:
                candidates["western_wrong_indic_correct"].append((a, b))
        elif pair["axis"] == "critical_fact":
            failures = int(not left) + int(not right)
            if failures == 1:
                candidates["clean_critical_one_core_failure"].append((a, b))
            if failures == 2:
                candidates["clean_critical_both_core_failure"].append((a, b))
    return candidates


def case_example(case_id, cases, model, input_link):
    row = cases[case_id]
    raw = model["raw"][case_id]
    result = model["outcomes"][case_id]
    response_text = raw.get("response_text")
    excerpt = None
    if not result["schema_valid"] and isinstance(response_text, str):
        excerpt = {"text": response_text[:2000], "original_characters": len(response_text),
                   "excerpt_characters": min(2000, len(response_text)), "truncated": len(response_text) > 2000}
    return {"case_id": case_id, "family_id": row["family_id"], "mechanism": row["mechanism"],
            "world": row["world"], "view": row["view"], "visible_input_file": input_link,
            "gold": {"decision": row["gold_decision"], "contract_net_minor": row["gold_contract_net_minor"],
                     "issues": row["gold_issues"], "evidence_ids": row["gold_evidence_ids"]},
            "prediction": model["predictions"][case_id],
            "observed_metrics": {key: result[key] for key in
                                 ("schema_valid", "decision_exact", "amount_exact", "issues_exact", "core_exact", "strict_joint")},
            "original_response_excerpt_if_schema_invalid": excerpt,
            "runner_parse_error": raw.get("parse_error"), "runner_transport_error": raw.get("transport_error"),
            "retained_attempt": raw.get("attempt"), "prompt_sha256": raw.get("prompt_sha256"),
            "request_sha256": raw.get("request_sha256")}


def run(run_dir: Path, release: Path, output: Path | None = None):
    output = output or run_dir
    source_path = run_dir / "baseline_report.json"
    require(source_path.exists(), "Final Qwen-only baseline_report.json is absent")
    source = read(source_path)
    summaries = source["models"]
    require(len(summaries) == 1 and {model["model"] for model in summaries} == EXPECTED_MODELS,
            "Initial-release analysis requires exactly the completed Qwen run; partial Fanar traces are excluded")
    # Check completion before loading cases or writing any analysis output.
    require(all(model["coverage"]["complete"] and model["coverage"]["completed_cases"] == 168 for model in summaries),
            "The final Qwen run must complete before analysis")
    sample = source["sample"]
    cases, pairs, input_hashes = load_cases_and_pairs(release, sample)
    models = [load_model(run_dir, summary, sample, cases) for summary in summaries]
    example_root = output / "error_examples"
    require(not example_root.exists() or not any(example_root.iterdir()),
            "error_examples is not empty; select a fresh --output-dir rather than mixing analyses")
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "selection_seed": SELECTION_SEED,
              "selection_algorithm": "Minimum SHA256 of seed, model tag, category and ordered case IDs joined by newline, over every qualifying case/pair.",
              "cases_per_model": 168, "families": 14, "split": "test", "numeral_pairs_per_model": 42,
              "clean_critical_pairs_per_model": 56, "categories_overlap": True,
              "source_baseline_report_sha256": sha(source_path), "source_release_sha256": input_hashes,
              "analyzer_sha256": sha(Path(__file__)), "scorer_sha256": sha(Path(score.__file__)), "models": []}
    paragraphs = ["# Observed failure examples", "",
        "This analysis uses the completed published **Qwen2.5 3B run: 168 case views, 14 complete generated test families**. Counts cover that entire fixed sample. Excluded partial Fanar trials contribute no examples or counts. The analysis makes no inference calls, retries, answer repairs or missing-output substitutions.", "",
        "Examples are deterministic illustrations, not cherry-picked narratives: each category selects the minimum named SHA-256 rank among all observed qualifying cases/pairs. Categories overlap; a case can have several wrong components and appear in several examples. Counts and examples are descriptive of this small controlled sample, not independent prevalence estimates, causal evidence, production estimates or a model ranking.", "",
        "`core_exact` requires the decision, nominal amount and issue set. Citation-only strict-joint failures never qualify as core failures. Pair core failures include invalid-schema responses, as in the scorer. The numeral directions describe observed correctness differences and do not establish that numeral script caused a failure. Clean/critical examples likewise do not explain why a model failed.", "",
        f"Selection seed: `{SELECTION_SEED}`. Full exact answers, citation arrays, retained attempt IDs, source hashes and bounded original-response excerpts are in the linked example JSON. Input JSON contains only case ID, public question and document ID/title/text; it can be passed to the fixed original model protocol without gold or mechanism metadata.", ""]
    for model in models:
        summary = model["summary"]
        tag = summary["model"]
        folder = summary["run_directory"]
        require(bool(re.fullmatch(r"[A-Za-z0-9._-]+", folder)), "Unsafe model output directory name")
        candidates = candidates_for(model, cases, pairs)
        valid_cases = sum(result["schema_valid"] for result in model["outcomes"].values())
        model_report = {"model": tag, "model_digest": summary["model_digest"], "artifact_sha256": model["artifacts"],
                        "valid_schema_cases": valid_cases, "category_counts": {}, "examples": []}
        paragraphs += [f"## {tag}", "", f"Population: **168 cases / 14 families**; schema-valid cases: **{valid_cases}/168**.", "",
                       "| Observed category | Count / denominator | Unit |", "|---|---:|---|"]
        for category, label in CATEGORIES.items():
            units = candidates[category]
            pair_category = category.startswith("western_") or category.startswith("clean_critical_")
            denominator = 42 if category.startswith("western_") else 56 if pair_category else 168
            unit = "numeral pairs" if category.startswith("western_") else "clean/critical pairs" if pair_category else "cases"
            model_report["category_counts"][category] = {"count": len(units), "denominator": denominator, "unit": unit,
                                                         "schema_valid_cases_for_valid_only_categories": valid_cases}
            paragraphs.append(f"| {label} | {len(units)} / {denominator} | {unit} |")
        paragraphs += ["", "Valid-schema error counts exclude invalid responses but retain the full 168-case population denominator; the valid-schema total above supplies that additional conditional denominator. Numeral-pair counts use all 42 selected Western/Arabic-Indic pairs; clean/critical counts use all 56 selected pairs.", ""]
        for category, label in CATEGORIES.items():
            units = candidates[category]
            if not units:
                continue
            selected = min(units, key=lambda ids: minhash(tag, category, ids))
            rank = minhash(tag, category, selected)
            examples = []
            for case_id in selected:
                row = cases[case_id]
                json_write(example_root / "inputs" / f"{case_id}.json",
                           {"case_id": case_id, "question": row["question"], "documents": row["documents"]})
                examples.append(case_example(case_id, cases, model, f"../inputs/{case_id}.json"))
            payload = {"model": tag, "model_digest": summary["model_digest"], "category": category,
                       "selection_seed": SELECTION_SEED, "selected_rank_sha256": rank, "candidate_units": len(units),
                       "unit": "pair" if len(selected) == 2 else "case", "cases": examples,
                       "interpretation": "Observed output comparison only; no inferred cause or generalization claim."}
            relative = Path("error_examples") / folder / f"{category}.json"
            json_write(output / relative, payload)
            model_report["examples"].append({"category": category, "case_ids": list(selected), "file": relative.as_posix(), "rank_sha256": rank})
            paragraphs += [f"### {label}", "", f"Selected from {len(units)} qualifying {'pairs' if len(selected) == 2 else 'cases'} by the declared minhash. [Exact example JSON]({relative.as_posix()}).", ""]
            for example in examples:
                case_id = example["case_id"]
                input_file = f"error_examples/inputs/{case_id}.json"
                paragraphs += [f"Case `{case_id}` · mechanism `{example['mechanism']}` · `{example['world']}` / `{example['view']}` · core correct: **{bool(example['observed_metrics']['core_exact'])}**. [Visible input JSON]({input_file}).", "",
                               "Exact core gold and normalized core prediction (full evidence arrays are in the example JSON):", "",
                               fenced(json.dumps({"gold": core_answer(example["gold"]), "prediction": core_answer(example["prediction"])}, ensure_ascii=False, indent=2), "json"), ""]
                excerpt = example["original_response_excerpt_if_schema_invalid"]
                if excerpt is not None:
                    paragraphs += [f"Original response excerpt: first {excerpt['excerpt_characters']} of {excerpt['original_characters']} characters; truncated: {excerpt['truncated']}. No repair applied.", "",
                                   fenced(excerpt["text"], "text"), ""]
                elif not example["observed_metrics"]["schema_valid"]:
                    paragraphs += ["No original response text was recorded for this invalid output; the example JSON preserves the runner's recorded transport/parse error.", ""]
        report["models"].append(model_report)
    paragraphs += ["## Reproduce the selection", "",
                   "Run `python write_failure_analysis.py --run-dir <completed-model-runs> --release-dir <frozen-release> --output-dir <fresh-analysis-directory>`. The command refuses incomplete model runs, changed manifests/data, mismatched final predictions, a changed scorer or an existing nonempty example directory. It does not modify original runs or make inference calls.", "",
                   "The raw-response excerpts and normalized predictions remain evaluation traces, separate from original benchmark facts/gold. Applicable source-model conditions remain in force; see the dataset NOTICE and measured RESULTS report.", ""]
    json_write(example_root / "index.json", report)
    output.mkdir(parents=True, exist_ok=True)
    (output / "FAILURE_ANALYSIS.md").write_text("\n".join(paragraphs), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = run(args.run_dir, args.release_dir, args.output_dir)
    print(json.dumps({"models": len(report["models"]), "cases_per_model": report["cases_per_model"],
                      "examples": sum(len(model["examples"]) for model in report["models"])}))


if __name__ == "__main__":
    main()
