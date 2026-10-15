#!/usr/bin/env python3
"""Resumable, local-only Ollama evaluation for Arabic Reconciliation Bench.

No model is pulled, no cloud provider is called, and no credentials are read.
Only the public question/documents and output contract reach the model. Every
request/response is checkpointed; parsing never repairs a model's answer.

Example: python run_models.py --release-dir .../release --output-dir .../models
Requires pyarrow and the neighboring core.py / score.py modules.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pyarrow.parquet as pq


PROTOCOL_VERSION = "arabic-reconciliation-ollama-v1"
SAMPLE_SEED = "reconciliation-model-test-v1"
DEFAULT_MODELS = ["qwen2.5:3b", "hf.co/yasserrmd/Fanar-1-9B-Instruct-gguf:Q4_K_M"]
CONTRACT_KEYS = {"decision", "contract_net_minor", "issues", "evidence_ids"}
DECISIONS = {"match", "mismatch", "insufficient_evidence"}
ISSUES = {"order_canceled", "currency_mismatch", "duplicate_invoice", "quantity_shortfall",
          "price_mismatch", "discount_mismatch", "invoice_arithmetic", "missing_evidence"}
OUTPUT_SCHEMA = {"type": "object", "additionalProperties": False,
                 "required": sorted(CONTRACT_KEYS), "properties": {
                     "decision": {"type": "string", "enum": sorted(DECISIONS)},
                     "contract_net_minor": {"type": ["integer", "null"], "minimum": 0},
                     "issues": {"type": "array", "items": {"type": "string", "enum": sorted(ISSUES)}},
                     "evidence_ids": {"type": "array", "items": {"type": "string"}}}}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LocalOllama:
    def __init__(self, base_url):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama base URL must be plain local HTTP without credentials, query or fragment")
        host = parsed.hostname or ""
        if host != "localhost":
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = False
            if not local:
                raise ValueError("Only loopback Ollama endpoints are allowed; cloud inference is not supported")
        if parsed.path not in {"", "/"}:
            raise ValueError("Ollama base URL must not contain a path")
        self.base_url = base_url.rstrip("/")

    def request(self, path, body=None, timeout=20):
        request = urllib.request.Request(self.base_url + path,
                                         data=encoded(body) if body is not None else None,
                                         headers={"Content-Type": "application/json"})
        # Disable environment-configured HTTP proxies even for the loopback
        # endpoint, ensuring prompts cannot be sent to a remote proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body_text[:4000]}") from exc

    def stop(self, model):
        return self.request("/api/generate", {"model": model, "prompt": "", "stream": False, "keep_alive": 0}, timeout=60)


def case_paths(release):
    paths = sorted((release / "data" / "cases").glob("test-*.parquet"))
    if not paths:
        raise ValueError(f"No test case Parquet files in {release / 'data' / 'cases'}")
    return paths


def parquet_rows(paths, columns):
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=4096, columns=columns):
            yield from batch.to_pylist()


def select_cases(release, max_families):
    paths = case_paths(release)
    families = {}
    for row in parquet_rows(paths, ["case_id", "family_id", "mechanism"]):
        family = row["family_id"]
        if family in families and families[family] != row["mechanism"]:
            raise ValueError("A test family appears under multiple mechanisms")
        families[family] = row["mechanism"]
    by_mechanism = defaultdict(list)
    for family, mechanism in families.items():
        rank = hashlib.sha256((SAMPLE_SEED + ":" + family).encode()).hexdigest()
        by_mechanism[mechanism].append((rank, family))
    ordered = []
    queues = {k: [family for _, family in sorted(v)] for k, v in by_mechanism.items()}
    depth = 0
    while any(depth < len(values) for values in queues.values()):
        for mechanism in sorted(queues):
            if depth < len(queues[mechanism]):
                ordered.append((queues[mechanism][depth], mechanism))
        depth += 1
    selected = ordered[:max_families]
    wanted = {family for family, _ in selected}
    records = []
    columns = ["case_id", "family_id", "mechanism", "world", "view", "question", "documents"]
    for row in parquet_rows(paths, columns):
        if row["family_id"] in wanted:
            records.append(row)
    family_order = {family: index for index, (family, _) in enumerate(selected)}
    records.sort(key=lambda row: (family_order[row["family_id"]], row["case_id"]))
    sizes = Counter(row["family_id"] for row in records)
    if any(value != 12 for value in sizes.values()) or set(sizes) != wanted:
        raise ValueError(f"Every selected family must contain all 12 views: {dict(sizes)}")
    ids = [row["case_id"] for row in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate selected case IDs")
    inventory = [{"path": p.relative_to(release).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in paths]
    return records, {"sample_seed": SAMPLE_SEED, "method": "Round-robin mechanisms, then lowest SHA-256 family rank within each mechanism; complete 12-row families.",
                     "split": "test", "families": [{"family_id": f, "mechanism": m} for f, m in selected],
                     "family_count": len(selected), "case_count": len(records), "case_ids": ids,
                     "test_files": inventory, "dataset_fingerprint": hashlib.sha256(encoded(inventory)).hexdigest()}


def public_prompt(row, model_input):
    # Gold and experimental metadata are unavailable to model_input itself.
    public = {"question": row["question"], "documents": [
        {key: document[key] for key in ("doc_id", "title", "text")} for document in row["documents"]]}
    prompt = model_input(public)
    if isinstance(prompt, str):
        messages = [{"role": "user", "content": prompt}]
    elif isinstance(prompt, dict) and set(prompt) == {"question", "documents"}:
        messages = [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]
    elif isinstance(prompt, list) and all(isinstance(item, dict) and set(item) <= {"role", "content"} and item.get("role") in {"system", "user"} and isinstance(item.get("content"), str) for item in prompt):
        messages = prompt
    else:
        raise ValueError("core.model_input must return a string, public question/documents object, or system/user message list")
    if not messages or not all(message.get("content") for message in messages):
        raise ValueError("Empty public model prompt")
    return messages


def reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key}")
        value[key] = item
    return value


def parse_prediction(case_id, content):
    try:
        obj = json.loads(content, object_pairs_hook=reject_duplicate_keys)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return {"case_id": case_id}, f"invalid_json: {exc}"
    if not isinstance(obj, dict) or set(obj) != CONTRACT_KEYS:
        return {"case_id": case_id}, "contract_keys"
    if not isinstance(obj["decision"], str) or obj["decision"] not in DECISIONS:
        return {"case_id": case_id}, "decision_enum"
    amount = obj["contract_net_minor"]
    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int) or amount < 0):
        return {"case_id": case_id}, "amount_not_integer_or_null"
    for field in ("issues", "evidence_ids"):
        values = obj[field]
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values) or len(values) != len(set(values)):
            return {"case_id": case_id}, field + "_not_unique_string_array"
    if any(issue not in ISSUES for issue in obj["issues"]):
        return {"case_id": case_id}, "issue_enum"
    # Preserve array ordering. The scorer may compare set-valued fields, but
    # the runner never fills missing fields or coerces/corrects model values.
    return {"case_id": case_id, **obj}, None


def read_checkpoint(path):
    if not path.exists():
        return [], {}
    data = path.read_bytes()
    records, latest = [], {}
    position = 0
    lines = data.splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if index != len(lines) - 1 or line.endswith(b"\n"):
                raise ValueError(f"Corrupt checkpoint record {index+1} in {path}")
            # A killed process may leave a partial final line. Preserve it
            # before repairing the append-only checkpoint at its last boundary.
            path.with_name(path.name + ".recovered-tail-" + str(time.time_ns())).write_bytes(data[position:])
            with path.open("r+b") as handle:
                handle.truncate(position)
            break
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise ValueError(f"Invalid checkpoint record {index+1} in {path}")
        records.append(record)
        latest[record["case_id"]] = record
        position += len(line)
    return records, latest


def write_predictions(path, selected, latest):
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in selected:
            record = latest.get(row["case_id"])
            if record:
                handle.write(json.dumps(record["prediction"], ensure_ascii=False) + "\n")
    temporary.replace(path)


def model_folder(model):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")[-70:]
    return safe + "-" + hashlib.sha256(model.encode()).hexdigest()[:8]


def ensure_single_model(api, target, unload_existing):
    running = api.request("/api/ps").get("models", [])
    others = [item.get("name", item.get("model")) for item in running if item.get("name", item.get("model")) != target]
    if others and not unload_existing:
        raise ValueError(f"Other models are loaded: {others}. Refusing concurrent model memory use; explicitly pass --unload-existing to stop them.")
    for model in others:
        api.stop(model)


def score_model(release, predictions_path, case_ids, output, bootstrap_samples):
    path = Path(__file__).with_name("score.py")
    if not path.exists():
        raise ValueError("score.py is not present yet; use --no-score for an initial run, then --aggregate-only")
    module = load_module("reconciliation_baseline_score", path)
    report = module.score(release, predictions_path, case_ids=case_ids,
                          bootstrap_samples=bootstrap_samples, seed=20261015)
    write_json(output, report)
    return report


def evaluate_model(args, api, model_tag, rows, sample, model_input, input_code_hash, version):
    model = model_tag["name"]
    folder = args.output_dir / model_folder(model)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path, raw_path = folder / "run_manifest.json", folder / "raw_responses.jsonl"
    options = {"temperature": 0, "seed": 20261015, "num_ctx": args.num_ctx, "num_predict": args.num_predict}
    binding = {"protocol_version": PROTOCOL_VERSION, "model": model, "model_digest": model_tag["digest"],
               "dataset_fingerprint": sample["dataset_fingerprint"], "model_input_code_sha256": input_code_hash,
               "options": options, "format": args.format, "truncate": False, "shift": False,
               "output_schema_sha256": hashlib.sha256(encoded(OUTPUT_SCHEMA)).hexdigest() if args.format == "schema" else None,
               "sample_seed": SAMPLE_SEED, "ollama_version": version}
    existing_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if existing_manifest and existing_manifest.get("binding") != binding:
        raise ValueError(f"Run identity changed for {model}; use a different output directory rather than mixing results")
    records, latest = read_checkpoint(raw_path)
    selected_ids = set(sample["case_ids"])
    prompts = {row["case_id"]: public_prompt(row, model_input) for row in rows}
    prompt_hashes = {case_id: hashlib.sha256(encoded(messages)).hexdigest() for case_id, messages in prompts.items()}
    for case_id in selected_ids & latest.keys():
        if latest[case_id].get("prompt_sha256") != prompt_hashes[case_id]:
            raise ValueError(f"Public prompt changed for resumed case {case_id}")
    manifest = {"binding": binding, "model_tag": model_tag, "source": "Local Ollama; pre-existing weights only; no model pull",
                "created_at": existing_manifest.get("created_at") if existing_manifest else utc_now(),
                "updated_at": utc_now(), "requested_sample": sample,
                "runner_code_sha256": sha256_file(Path(__file__)),
                "prompt_input": "core.model_input receives only question and documents containing doc_id/title/text; no gold, world, mechanism, view or canonical fields.",
                "parsing": "Strict whole-response JSON with duplicate-key rejection; no markdown stripping, coercion, repair or second attempt on semantic/schema failure.",
                "context_policy": "Explicit truncate=false and shift=false; HTTP/context errors recorded, never silently truncated by the client.",
                "fixed_output_schema": OUTPUT_SCHEMA if args.format == "schema" else None,
                "constrained_decoding": args.format != "none"}
    write_json(manifest_path, manifest)
    new_requests = 0
    if not args.aggregate_only and not args.dry_run:
        ensure_single_model(api, model, args.unload_existing)
        attempts = Counter(record["case_id"] for record in records)
        done_count = sum(case_id in latest for case_id in selected_ids)
        new_requests = 0
        consecutive_transport_errors = 0
        try:
            with raw_path.open("a", encoding="utf-8", buffering=1) as handle:
                for row in rows:
                    pause_path = getattr(args, "pause_file", None) or (args.output_dir / "PAUSE")
                    if pause_path.exists():
                        print(json.dumps({"paused_at_request_boundary": True, "pause_file": str(pause_path), "model": model}), flush=True)
                        break
                    case_id = row["case_id"]
                    previous = latest.get(case_id)
                    if previous and not (args.retry_errors and previous.get("transport_error")):
                        continue
                    if args.max_new_requests and new_requests >= args.max_new_requests:
                        break
                    payload = {"model": model, "messages": prompts[case_id], "stream": False,
                               "keep_alive": "2m", "options": options, "truncate": False, "shift": False}
                    if args.format == "json":
                        payload["format"] = "json"
                    elif args.format == "schema":
                        payload["format"] = OUTPUT_SCHEMA
                    started_at, started = utc_now(), time.monotonic()
                    response, transport_error = None, None
                    try:
                        response = api.request("/api/chat", payload, timeout=args.request_timeout)
                    except (OSError, ValueError, RuntimeError) as exc:
                        transport_error = type(exc).__name__ + ": " + str(exc)
                    elapsed = round(time.monotonic() - started, 4)
                    content = response.get("message", {}).get("content", "") if isinstance(response, dict) else ""
                    prediction, parse_error = parse_prediction(case_id, content) if not transport_error else ({"case_id": case_id}, "transport_failure")
                    if isinstance(response, dict) and (not response.get("done") or response.get("done_reason") == "length"):
                        prediction, parse_error = {"case_id": case_id}, "incomplete_generation"
                    attempts[case_id] += 1
                    record = {"case_id": case_id, "family_id": row["family_id"], "split": "test",
                              "mechanism": row["mechanism"], "world": row["world"], "view": row["view"],
                              "model": model, "model_digest": model_tag["digest"], "attempt": attempts[case_id],
                              "started_at": started_at, "completed_at": utc_now(), "wall_seconds": elapsed,
                              "prompt_sha256": prompt_hashes[case_id], "request_sha256": hashlib.sha256(encoded(payload)).hexdigest(),
                              "request": payload, "response": response, "response_text": content,
                              "transport_error": transport_error, "parse_error": parse_error, "prediction": prediction}
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    latest[case_id] = record
                    new_requests += 1
                    consecutive_transport_errors = consecutive_transport_errors + 1 if transport_error else 0
                    if previous is None:
                        done_count += 1
                    print(json.dumps({"model": model, "completed": done_count, "requested": len(rows), "case_id": case_id,
                                      "wall_seconds": elapsed, "schema_valid": parse_error is None, "error": parse_error}, ensure_ascii=False), flush=True)
                    if consecutive_transport_errors >= 3:
                        print(json.dumps({"stopped_for_transport_errors": True, "model": model,
                                          "consecutive_errors": consecutive_transport_errors, "last_error": transport_error}), flush=True)
                        break
        finally:
            # Only stop the model managed by this run. No system process or
            # unrelated running inference service is terminated.
            try:
                api.stop(model)
            except (OSError, ValueError, RuntimeError) as exc:
                print(json.dumps({"model_unload_warning": str(exc)}), flush=True)
    predictions_path = folder / "predictions.jsonl"
    write_predictions(predictions_path, rows, latest)
    selected_records = [latest[row["case_id"]] for row in rows if row["case_id"] in latest]
    coverage = {"requested_families": sample["family_count"], "requested_cases": len(rows), "completed_cases": len(selected_records),
                "complete": len(selected_records) == len(rows), "schema_valid_outputs": sum(record["parse_error"] is None for record in selected_records),
                "transport_failures": sum(bool(record.get("transport_error")) for record in selected_records),
                "parse_failures": dict(Counter(record.get("parse_error") for record in selected_records if record.get("parse_error"))),
                "wall_seconds_latest_attempts": round(sum(record["wall_seconds"] for record in selected_records), 3),
                "all_attempt_count": len(records) + new_requests,
                "predictions_sha256": sha256_file(predictions_path)}
    manifest["updated_at"] = utc_now()
    manifest["coverage"] = coverage
    write_json(manifest_path, manifest)
    report = None
    if not args.no_score and not args.dry_run:
        report = score_model(args.release_dir, predictions_path, sample["case_ids"], folder / "score_report.json", args.bootstrap_samples)
    return {"model": model, "model_digest": model_tag["digest"], "run_directory": folder.name,
            "coverage": coverage, "score_report": report, "manifest_sha256": sha256_file(manifest_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--max-families", type=int, default=14)
    parser.add_argument("--max-new-requests", type=int, default=0, help="Per model; 0 means no cap. Useful for a resumable transport pilot.")
    parser.add_argument("--pause-file", type=Path, help="Stop after the current request if this file appears; default: OUTPUT_DIR/PAUSE")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=2048)
    parser.add_argument("--request-timeout", type=float, default=240)
    parser.add_argument("--format", choices=("none", "json", "schema"), default="schema")
    parser.add_argument("--retry-errors", action="store_true", help="Retry transport failures only, retaining every original attempt; never retry a wrong/invalid model answer")
    parser.add_argument("--unload-existing", action="store_true", help="Explicitly stop other already loaded Ollama models before loading this run's model")
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--no-score", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Select cases/write manifests only; no inference")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()
    if args.max_families < 1 or args.num_ctx < 512 or args.num_predict < 1 or args.num_predict >= args.num_ctx or args.max_new_requests < 0:
        parser.error("Invalid family/request count or context/output token limits")
    if len(args.models) != len(set(args.models)):
        parser.error("Model list contains duplicates")
    try:
        api = LocalOllama(args.base_url)
        tags = {item["name"]: item for item in api.request("/api/tags")["models"]}
        missing = [model for model in args.models if model not in tags]
        if missing:
            raise ValueError(f"Models are not already installed: {missing}; this runner never pulls models")
        version = api.request("/api/version")["version"]
        core_path = Path(__file__).with_name("core.py")
        module = load_module("reconciliation_public_core", core_path)
        selected, sample = select_cases(args.release_dir, args.max_families)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.output_dir / "selected_cases.json", sample)
        existing_report = args.output_dir / "baseline_report.json"
        summaries = {}
        if existing_report.exists():
            previous = json.loads(existing_report.read_text(encoding="utf-8"))
            if previous.get("sample", {}).get("case_ids") == sample["case_ids"] and previous.get("sample", {}).get("dataset_fingerprint") == sample["dataset_fingerprint"]:
                summaries = {item["model"]: item for item in previous.get("models", [])}
        for model in args.models:
            pause_path = args.pause_file or (args.output_dir / "PAUSE")
            if pause_path.exists() and not args.aggregate_only:
                print(json.dumps({"paused_before_model": model, "pause_file": str(pause_path)}), flush=True)
                break
            summaries[model] = evaluate_model(args, api, tags[model], selected, sample, module.model_input, sha256_file(core_path), version)
            write_json(args.output_dir / "baseline_report.json", {"protocol_version": PROTOCOL_VERSION,
                       "updated_at": utc_now(), "sample": sample, "models": [summaries[key] for key in sorted(summaries)],
                       "limitations": ["Small deterministic stratified sample of synthetic test families, not full-release deployment performance.",
                                       "The same family supplies correlated views and counterfactuals; confidence intervals cluster by family.",
                                       "Model outputs are strictly parsed; all original responses and transport failures are retained.",
                                       "Only local already-installed models were evaluated; no model was pulled and no paid API was used."]})
        print(json.dumps({"output_dir": str(args.output_dir.resolve()), "families": sample["family_count"], "cases_per_model": len(selected),
                          "models": [{"model": row["model"], "coverage": row["coverage"]} for row in summaries.values()]}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, KeyError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
