#!/usr/bin/env python3
"""Score explicit predictions; never infer or manufacture missing model output."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import gzip
import json
import math
from pathlib import Path
import random
import re
from typing import Any

DECISIONS = {"match", "mismatch", "insufficient_evidence"}
ISSUES = {"order_canceled", "currency_mismatch", "duplicate_invoice", "quantity_shortfall",
          "price_mismatch", "discount_mismatch", "invoice_arithmetic", "missing_evidence"}
METRICS = ("schema_valid", "decision_exact", "amount_exact", "issues_exact", "core_exact",
           "evidence_reference_coverage", "citations_valid", "strict_joint")


def read_predictions(source: Any) -> dict[str, dict]:
    """Reject duplicate/unknown identities; retain malformed outputs as failures."""
    if isinstance(source, (str, Path)):
        records = []
        opener = gzip.open if Path(source).suffix == ".gz" else open
        with opener(source, "rt", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"prediction line {number}: invalid JSON; preserve invalid model output as a case_id-only record") from exc
    elif isinstance(source, dict):
        records = [{"case_id": key, **value} for key, value in source.items()]
    else:
        records = source
    output = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise ValueError("every prediction must identify its case_id, including invalid model responses")
        case_id = record["case_id"]
        if case_id in output:
            raise ValueError(f"duplicate prediction case_id: {case_id}")
        output[case_id] = record
    return output


def prediction_valid(prediction: dict | None) -> bool:
    if not isinstance(prediction, dict) or prediction.get("decision") not in DECISIONS:
        return False
    if set(prediction) - {"case_id", "decision", "contract_net_minor", "issues", "evidence_ids"}:
        return False
    if "contract_net_minor" not in prediction:
        return False
    amount = prediction["contract_net_minor"]
    if amount is not None and (type(amount) is not int or amount < 0):
        return False
    for key in ("issues", "evidence_ids"):
        values = prediction.get(key)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            return False
        if len(values) != len(set(values)):
            return False
    return set(prediction["issues"]).issubset(ISSUES)


def evaluate_case(row: dict, prediction: dict | None) -> dict:
    """Evaluate one row. Invalid schema makes every task metric a failure."""
    valid = prediction_valid(prediction)
    reference = set(row["gold_evidence_ids"])
    visible = set()
    for document in row["documents"]:
        visible.update(re.findall(r"\[([^\[\]\n]+)\]", document["text"]))
    predicted = set(prediction["evidence_ids"]) if valid else set()
    intersection = len(reference & predicted)
    precision = intersection / len(predicted) if predicted else (1.0 if not reference else 0.0)
    recall = intersection / len(reference) if reference else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    decision = valid and prediction["decision"] == row["gold_decision"]
    amount = valid and prediction["contract_net_minor"] == row["gold_contract_net_minor"]
    issues = valid and set(prediction["issues"]) == set(row["gold_issues"])
    coverage = valid and reference.issubset(predicted)
    citations = valid and predicted.issubset(visible)
    result = {
        "schema_valid": int(valid), "decision_exact": int(decision), "amount_exact": int(amount),
        "issues_exact": int(issues), "core_exact": int(decision and amount and issues),
        "evidence_reference_coverage": int(coverage), "citations_valid": int(citations),
        "strict_joint": int(decision and amount and issues and coverage and citations),
        "evidence_precision": precision if valid else 0.0,
        "evidence_recall": recall if valid else 0.0, "evidence_f1": f1 if valid else 0.0,
        "evidence_tp": intersection, "evidence_predicted": len(predicted), "evidence_reference": len(reference),
        "invalid_citations": len(predicted - visible), "missing_prediction": int(prediction is None),
        "gold_missing": int(row["gold_decision"] == "insufficient_evidence"),
        "predicted_missing": int(valid and prediction["decision"] == "insufficient_evidence"),
        "gold_decision": row["gold_decision"], "predicted_decision": prediction["decision"] if valid else "invalid_or_missing",
    }
    return result


def _summary(results: list[dict]) -> dict:
    count = len(results)
    if not count:
        return {"cases": 0}
    summary = {"cases": count}
    for metric in METRICS + ("evidence_precision", "evidence_recall", "evidence_f1"):
        summary[metric] = sum(result[metric] for result in results) / count
    totals = {key: sum(result[key] for result in results) for key in
              ("evidence_tp", "evidence_predicted", "evidence_reference", "invalid_citations", "missing_prediction")}
    micro_precision = totals["evidence_tp"] / totals["evidence_predicted"] if totals["evidence_predicted"] else 0.0
    micro_recall = totals["evidence_tp"] / totals["evidence_reference"] if totals["evidence_reference"] else 1.0
    summary["evidence_micro"] = {"precision": micro_precision, "recall": micro_recall,
                                  "f1": 2 * micro_precision * micro_recall / (micro_precision + micro_recall)
                                  if micro_precision + micro_recall else 0.0, **totals}
    actual = sum(result["gold_missing"] for result in results)
    predicted = sum(result["predicted_missing"] for result in results)
    true_positive = sum(result["gold_missing"] and result["predicted_missing"] for result in results)
    summary["missing_evidence"] = {"actual": actual, "predicted": predicted, "true_positive": true_positive,
                                     "precision": true_positive / predicted if predicted else None,
                                     "recall": true_positive / actual if actual else None}
    confusion = Counter((result["gold_decision"], result["predicted_decision"]) for result in results)
    per_class = {}
    for label in sorted(DECISIONS):
        support = sum(result["gold_decision"] == label for result in results)
        predicted_count = sum(result["predicted_decision"] == label for result in results)
        true_positive = confusion[(label, label)]
        per_class[label] = {"support": support, "predicted": predicted_count,
                            "precision": true_positive / predicted_count if predicted_count else None,
                            "recall": true_positive / support if support else None,
                            "f1": 2 * true_positive / (support + predicted_count) if support + predicted_count else None}
    summary["decision_classification"] = {
        "per_class": per_class,
        "confusion": {gold: {predicted: confusion[(gold, predicted)] for predicted in sorted(DECISIONS | {"invalid_or_missing"})}
                      for gold in sorted(DECISIONS)},
    }
    return summary


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def cluster_intervals(family_records: dict[str, dict[str, tuple[float, int]]],
                      samples: int, seed: int) -> dict:
    """Resample entire families; ratio estimators preserve per-case weighting."""
    if samples <= 0 or not family_records:
        return {}
    families = sorted(family_records)
    metrics = sorted({metric for record in family_records.values() for metric in record})
    data = [[family_records[family].get(metric, (0, 0)) for family in families] for metric in metrics]
    rng = random.Random(seed)
    draws = {metric: [] for metric in metrics}
    for _ in range(samples):
        selected = [rng.randrange(len(families)) for _ in families]
        for metric, values in zip(metrics, data):
            numerator = sum(values[index][0] for index in selected)
            denominator = sum(values[index][1] for index in selected)
            if denominator:
                draws[metric].append(numerator / denominator)
    return {metric: {"low": _percentile(values, .025), "high": _percentile(values, .975)}
            for metric, values in draws.items() if values}


def score(release: str | Path, predictions: Any, case_ids: set[str] | list[str] | None = None,
          bootstrap_samples: int = 1000, seed: int = 20261015) -> dict:
    """Score a full release or explicit subset; missing selected cases are wrong."""
    import pyarrow.parquet as pq

    release = Path(release)
    prediction_map = read_predictions(predictions)
    selected = set(case_ids) if case_ids is not None else None
    records, results, all_ids = {}, {}, set()
    columns = ["case_id", "family_id", "world", "view", "mechanism", "gold_decision",
               "gold_contract_net_minor", "gold_issues", "gold_evidence_ids", "documents"]
    for path in sorted((release / "data" / "cases").glob("*.parquet")):
        split = path.name.split("-")[0]
        for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=512):
            for row in batch.to_pylist():
                case_id = row["case_id"]
                if case_id in all_ids:
                    raise ValueError(f"duplicate release case_id: {case_id}")
                all_ids.add(case_id)
                if selected is not None and case_id not in selected:
                    continue
                result = evaluate_case(row, prediction_map.get(case_id))
                results[case_id] = result
                records[case_id] = {key: row[key] for key in
                                    ("family_id", "world", "view", "mechanism", "gold_decision")}
                records[case_id]["split"] = split
    if selected is not None and selected - all_ids:
        raise ValueError(f"unknown selected case IDs: {sorted(selected - all_ids)[:3]}")
    if set(prediction_map) - all_ids:
        raise ValueError(f"unknown prediction case IDs: {sorted(set(prediction_map) - all_ids)[:3]}")
    if selected is not None and set(prediction_map) - selected:
        raise ValueError("predictions contain unselected cases; pass the intended evaluation universe explicitly")
    if not results:
        raise ValueError("evaluation universe contains no cases")

    grouped = {}
    for axis in ("split", "view", "mechanism", "gold_decision"):
        groups = defaultdict(list)
        for case_id, record in records.items():
            groups[record[axis]].append(results[case_id])
        grouped[axis] = {name: _summary(values) for name, values in sorted(groups.items())}
    family_stats = defaultdict(dict)
    family_cases = defaultdict(list)
    world_cases = defaultdict(list)
    for case_id, record in records.items():
        family_cases[record["family_id"]].append(case_id)
        world_cases[(record["family_id"], record["world"])].append(case_id)
    for family, ids in family_cases.items():
        for metric in METRICS + ("evidence_precision", "evidence_recall", "evidence_f1"):
            family_stats[family][metric] = (sum(results[case_id][metric] for case_id in ids), len(ids))
        missing_tp = sum(results[case_id]["gold_missing"] and results[case_id]["predicted_missing"] for case_id in ids)
        family_stats[family]["missing_evidence_precision"] = (missing_tp, sum(results[case_id]["predicted_missing"] for case_id in ids))
        family_stats[family]["missing_evidence_recall"] = (missing_tp, sum(results[case_id]["gold_missing"] for case_id in ids))

    pair_groups = defaultdict(list)
    pair_decision = defaultdict(list)
    pair_core = defaultdict(list)
    pair_family = defaultdict(lambda: defaultdict(list))
    for path in sorted((release / "data" / "pairs").glob("*.parquet")):
        for batch in pq.ParquetFile(path).iter_batches(batch_size=2048):
            for pair in batch.to_pylist():
                a, b = pair["case_id_a"], pair["case_id_b"]
                if a not in results or b not in results:
                    continue
                key = f"{pair['relation']}/{pair['axis']}"
                outcome = int(results[a]["strict_joint"] and results[b]["strict_joint"])
                pair_groups[key].append(outcome)
                pair_groups["all"].append(outcome)
                for target, metric in ((pair_decision, "decision_exact"), (pair_core, "core_exact")):
                    value = int(results[a][metric] and results[b][metric])
                    target[key].append(value)
                    target["all"].append(value)
                    pair_family[pair["family_id"]][f"{metric}:{key}"].append(value)
                    pair_family[pair["family_id"]][f"{metric}:all"].append(value)
                pair_family[pair["family_id"]][key].append(outcome)
                pair_family[pair["family_id"]]["all"].append(outcome)
    for family, groups in pair_family.items():
        for key, values in groups.items():
            prefix = "paired_both_joint"
            for source, name in (("decision_exact:", "paired_both_decision"), ("core_exact:", "paired_both_core")):
                if key.startswith(source):
                    prefix, key = name, key[len(source):]
                    break
            family_stats[family][f"{prefix}:{key}"] = (sum(values), len(values))

    world_joint = []
    world_family = defaultdict(list)
    partial_worlds = 0
    for (family, _), ids in world_cases.items():
        if len(ids) != 4 or len({records[case_id]["view"] for case_id in ids}) != 4:
            partial_worlds += 1
            continue
        outcome = int(all(results[case_id]["strict_joint"] for case_id in ids))
        world_joint.append(outcome)
        world_family[family].append(outcome)
    for family, values in world_family.items():
        family_stats[family]["all_view_joint"] = (sum(values), len(values))
    complete_family_joint = []
    for family, ids in family_cases.items():
        if len(ids) == 12 and len({(records[case_id]["world"], records[case_id]["view"]) for case_id in ids}) == 12:
            outcome = int(all(results[case_id]["strict_joint"] for case_id in ids))
            complete_family_joint.append(outcome)
            family_stats[family]["all_family_joint"] = (outcome, 1)
    return {
        "schema_version": "1.0", "scorer": {"version": "1.0.0", "file": "score.py",
                                                "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "case_universe_sha256": hashlib.sha256("\n".join(sorted(results)).encode()).hexdigest(),
        "evaluation_scope": "explicit_subset" if selected is not None else "full_release",
        "prediction_records": len(prediction_map), "selected_families": len(family_cases),
        "metrics": _summary(list(results.values())), "by": grouped,
        "paired_both_joint": {key: {"pairs": len(values), "rate": sum(values) / len(values)}
                              for key, values in sorted(pair_groups.items())},
        "paired_both_decision": {key: {"pairs": len(values), "rate": sum(values) / len(values)}
                                 for key, values in sorted(pair_decision.items())},
        "paired_both_core": {key: {"pairs": len(values), "rate": sum(values) / len(values)}
                             for key, values in sorted(pair_core.items())},
        "all_view_joint": {"complete_worlds": len(world_joint), "partial_worlds_excluded": partial_worlds,
                           "rate": sum(world_joint) / len(world_joint) if world_joint else None},
        "all_family_joint": {"complete_families": len(complete_family_joint),
                             "rate": sum(complete_family_joint) / len(complete_family_joint) if complete_family_joint else None},
        "confidence_intervals": {"method": "percentile bootstrap, families sampled with replacement",
                                 "confidence_level": .95, "samples": bootstrap_samples, "seed": seed,
                                 "families": len(family_cases),
                                 "intervals": cluster_intervals(family_stats, bootstrap_samples, seed)},
        "interpretation": {"strict_joint": "Decision, nominal contract amount, issue set exact; all reference evidence covered; no nonexistent citations. Extra valid citations allowed.",
                           "evidence_metrics": "Reference-set agreement, not semantic proof correctness.",
                           "paired_both_joint": "Both members pass strict_joint; incomplete selected pairs excluded.",
                           "all_view_joint": "All four controlled views pass strict_joint for one family-world; incomplete groups excluded."},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--case-ids-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args()
    selected = None
    if args.case_ids_file:
        text = args.case_ids_file.read_text(encoding="utf-8")
        selected = json.loads(text) if text.lstrip().startswith("[") else text.splitlines()
        if not isinstance(selected, list) or not all(isinstance(case_id, str) for case_id in selected):
            raise ValueError("case-ids-file must be a JSON list or one ID per line")
        if len(selected) != len(set(selected)):
            raise ValueError("duplicate selected case IDs")
    report = score(args.release, args.predictions, selected, args.bootstrap_samples, args.seed)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
