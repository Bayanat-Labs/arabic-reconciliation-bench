#!/usr/bin/env python3
"""Transparent prior and format-aware symbolic reference baselines.

The symbolic reference understands this release's declared controlled rendering
grammar.  It is a software ceiling, not a learned model or a production invoice
parser.  Prediction generation loads ONLY case_id, question and visible
doc_id/title/text; it never loads canonical specs or gold labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

import verify
import score

TITLES = {
    "policy": ("سياسة المطابقة الخاصة بهذه الحالة", "Case-specific matching policy"),
    "po": ("أمر الشراء", "Purchase order"), "invoice": ("فاتورة المورد", "Supplier invoice"),
    "receipts": ("سجل استلام البضائع", "Goods receipt register"), "returns": ("سجل المرتجعات", "Returns register"),
    "history": ("سجل الفواتير السابقة", "Prior invoice register"), "amendments": ("سجل تعديلات الأسعار", "Price amendment register"),
}
LABELS = {
    "price_tolerance_bps": ("التفاوت المسموح في سعر الوحدة", "Allowed unit-price variance"),
    "receipt_cutoff": ("آخر تاريخ يُحتسب للاستلام", "Receipt cutoff"),
    "required_roles": ("المستندات الواجب توافرها", "Required documents"),
    "accepted_only": ("استبعاد الكميات المرفوضة والمرتجعات المعتمدة", "Exclude rejected quantities and approved returns"),
    "cumulative_billing": ("خصم كميات الفواتير السابقة المرحلة", "Deduct previously posted invoice quantities"),
    "approved_amendments_only": ("اعتماد آخر تعديل معتمد ونافذ بتاريخ الفاتورة", "Use latest approved amendment effective on invoice date"),
    "canceled_orders_forbidden": ("منع مطابقة أوامر الشراء الملغاة", "Canceled purchase orders cannot match"),
    "order_id": ("رقم أمر الشراء", "Purchase order ID"), "status": ("الحالة", "Status"), "currency": ("العملة", "Currency"),
    "sku": ("رمز الصنف", "Item code"), "ordered_units": ("الكمية المطلوبة بالقطعة", "Ordered base units"),
    "units_per_pack": ("عدد القطع في العبوة", "Base units per pack"), "unit_price_minor": ("سعر الوحدة النقدية", "Unit price in currency units"),
    "discount_bps": ("خصم البند", "Line discount"), "invoice_id": ("رقم الفاتورة", "Invoice ID"),
    "date": ("التاريخ الميلادي", "Gregorian date"), "stated_net_minor": ("الإجمالي الصافي المدوّن", "Stated net total"),
    "quantity_units": ("الكمية بالقطعة", "Quantity in base units"), "complete": ("السجل كامل للفترة حتى تاريخ الفاتورة", "Register is complete through invoice date"),
    "receipt_id": ("رقم محضر الاستلام", "Receipt ID"), "quantity": ("الكمية المستلمة", "Delivered quantity"),
    "quantity_unit": ("وحدة الاستلام", "Receipt quantity unit"), "rejected_quantity": ("الكمية المرفوضة بوحدة الاستلام نفسها", "Rejected quantity in the same receipt unit"),
    "return_id": ("رقم المرتجع", "Return ID"), "amendment_id": ("رقم التعديل", "Amendment ID"),
    "effective_date": ("تاريخ بدء النفاذ", "Effective date"),
}
ALIASES = {
    "order_id": ("معرّف أمر الشراء", "مرجع أمر التوريد"), "invoice_id": ("معرّف الفاتورة",),
    "status": ("حالة القيد", "حالة المستند", "وضع المستند"),
    "date": ("تاريخ المستند بالميلادي", "تاريخ القيد الميلادي"),
    "quantity_units": ("كمية القطع", "عدد القطع", "العدد بوحدة القطعة"),
    "unit_price_minor": ("السعر لكل قطعة نقداً",), "currency": ("عملة المستند",),
    "stated_net_minor": ("صافي الفاتورة المثبت",), "discount_bps": ("نسبة الخصم للبند",),
}
LABEL_TO_KEY = {label: key for key, labels in LABELS.items() for label in labels}
LABEL_TO_KEY.update({label: key for key, labels in ALIASES.items() for label in labels})
TITLE_TO_ROLE = {title: (role, language) for role, titles in TITLES.items() for language, title in zip(("ar", "en"), titles)}
TO_WESTERN = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
ENUMERATIONS = {"نعم": "true", "yes": "true", "ساري المفعول": "active", "معتمد": "approved", "مسودة": "draft",
                "مرحّل": "posted", "قطعة": "unit", "عبوة": "pack",
                "تاريخ الفاتورة شاملاً ذلك اليوم": "invoice_date", "invoice date, inclusive": "invoice_date"}


def parse_value(key: str, value: str, role: str) -> str:
    value = value.translate(TO_WESTERN)
    if key.endswith("_minor") or key.endswith("_bps"):
        pattern = r"(0|[1-9][0-9]*)\.([0-9]{2})" + ("%" if key.endswith("_bps") else "")
        match = re.fullmatch(pattern, value)
        if not match:
            raise ValueError(f"unrecognized monetary/percentage literal: {key}={value!r}")
        return str(100 * int(match.group(1)) + int(match.group(2)))
    if key == "required_roles":
        titles = value.split("، ") if "،" in value else value.split(", ")
        try:
            return ",".join(TITLE_TO_ROLE[title][0] for title in titles)
        except KeyError as exc:
            raise ValueError(f"unknown required-document name: {value!r}") from exc
    if key == "status" and value == "ملغى":
        if role == "po":
            return "canceled"
        if role == "history":
            return "void"
        raise ValueError("ambiguous canceled status outside declared roles")
    return ENUMERATIONS.get(value, value)


def parse_visible(question: str, documents: list[dict]) -> list[dict]:
    """Parse only visible text. Unknown labels/structures fail without repair."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("missing question")
    parsed = []
    for document in documents:
        if set(document) != {"doc_id", "title", "text"}:
            raise ValueError("parser input must contain only visible document fields")
        if document["title"] not in TITLE_TO_ROLE:
            raise ValueError(f"unknown controlled document title: {document['title']!r}")
        role, _ = TITLE_TO_ROLE[document["title"]]
        current_row, fields = "", []
        for line in document["text"].splitlines():
            if not line.strip():
                continue
            heading = re.fullmatch(r"(?:Record |السجل )([^\s]+)", line)
            if heading:
                current_row = heading.group(1)
                continue
            match = re.fullmatch(r"\[([A-Za-z0-9.]+)\] (.+?): (.*)", line)
            if not match:
                if role == "policy" and not line.startswith("["):
                    continue  # prose is task context, not an undisclosed fact
                raise ValueError(f"unknown visible line grammar in {document['doc_id']}: {line!r}")
            field_id, label, value = match.groups()
            if label not in LABEL_TO_KEY:
                raise ValueError(f"unknown controlled field label: {label!r}")
            key = LABEL_TO_KEY[label]
            if key in verify.HEADER_KEYS[role]:
                row_id = ""
            elif key in verify.ROW_KEYS[role] and current_row:
                row_id = current_row
            else:
                raise ValueError(f"field {key} has no valid visible row context in {role}")
            fields.append({"id": field_id, "key": key, "row_id": row_id,
                           "value": parse_value(key, value, role), "label_ar": LABELS[key][0], "label_en": LABELS[key][1]})
        parsed.append({"doc_id": document["doc_id"], "role": role, "title": TITLES[role][0],
                       "title_en": TITLES[role][1], "fields": fields})
    return parsed


def symbolic_prediction(question: str, documents: list[dict]) -> dict:
    gold = verify.compute_gold(parse_visible(question, documents))
    return {key: gold[key] for key in verify.GOLD_KEYS}


def run(release: Path, output: Path, bootstrap_samples: int = 1000, seed: int = 20261015) -> dict:
    import pyarrow.parquet as pq
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    prior_path = output / "prior-match-zero.predictions.jsonl.gz"
    symbolic_path = output / "format-aware-symbolic.predictions.jsonl.gz"
    failures_path = output / "format-aware-symbolic.failures.jsonl"
    count, failed, inputs = 0, 0, []
    with gzip.open(prior_path, "wt", encoding="utf-8") as prior, gzip.open(symbolic_path, "wt", encoding="utf-8") as symbolic, failures_path.open("w", encoding="utf-8") as failures:
        for path in sorted((release / "data" / "cases").glob("*.parquet")):
            inputs.append({"path": path.relative_to(release).as_posix(), "sha256": verify.file_sha256(path)})
            # No gold, mechanism, world/view, role or canonical field is read.
            for batch in pq.ParquetFile(path).iter_batches(columns=["case_id", "question", "documents"], batch_size=128):
                for row in batch.to_pylist():
                    case_id = row["case_id"]
                    prior.write(json.dumps({"case_id": case_id, "decision": "match", "contract_net_minor": 0,
                                            "issues": [], "evidence_ids": []}) + "\n")
                    try:
                        prediction = {"case_id": case_id, **symbolic_prediction(row["question"], row["documents"])}
                    except (ValueError, KeyError, TypeError) as exc:
                        failed += 1
                        failures.write(json.dumps({"case_id": case_id, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False) + "\n")
                        prediction = {"case_id": case_id}  # explicit schema failure, never silent correction
                    symbolic.write(json.dumps(prediction, ensure_ascii=False, separators=(",", ":")) + "\n")
                    count += 1
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "cases": count,
              "prediction_feature_columns": ["case_id", "question", "documents.doc_id/title/text"],
              "canonical_specs_loaded": False, "gold_labels_loaded_during_prediction": False,
              "code_sha256": {name: verify.file_sha256(Path(__file__).with_name(name)) for name in ("baseline_heuristics.py", "verify.py", "score.py")},
              "case_files": inputs, "symbolic_parse_or_execution_failures": failed,
              "baselines": [], "interpretation": [
                  "Prior: always match, zero nominal amount, empty issues/evidence; no context access and no fitted parameters. Decision classes are tied globally, so match is an explicit fixed tie-break.",
                  "FORMAT-AWARE SYMBOLIC REFERENCE: explicitly recognizes all released controlled labels, synonyms, numeric formats and document titles, then executes the independent formal policy.",
                  "This is an executable format ceiling, not a competitive learned model, OCR system, unrestricted Arabic parser or production procurement tool.",
                  "The parser ignores unmarked policy prose and implements the benchmark's declared fixed policy. All failures are retained as invalid outputs."]}
    for name, path, label in (("prior_match_zero", prior_path, "Fixed context-free prior"),
                              ("format_aware_symbolic_reference", symbolic_path, "FORMAT-AWARE SYMBOLIC REFERENCE")):
        scored = score.score(release, path, bootstrap_samples=bootstrap_samples, seed=seed)
        score_path = output / f"{name}.score.json"
        score_path.write_text(json.dumps(scored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["baselines"].append({"name": name, "label": label, "predictions": path.name,
                                     "prediction_sha256": verify.file_sha256(path), "score_file": score_path.name,
                                     "score_sha256": verify.file_sha256(score_path), "score": scored})
    report["elapsed_seconds"] = time.monotonic() - started
    (output / "heuristic_baselines.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args()
    result = run(args.release, args.output, args.bootstrap_samples, args.seed)
    print(json.dumps({"cases": result["cases"], "symbolic_failures": result["symbolic_parse_or_execution_failures"],
                      "baselines": {entry["name"]: entry["score"]["metrics"]["strict_joint"] for entry in result["baselines"]},
                      "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
