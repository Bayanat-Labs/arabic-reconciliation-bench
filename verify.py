#!/usr/bin/env python3
"""Independent canonical-fact oracle and release auditor.

This module deliberately does not import core.py or generator.py.  It interprets
the published canonical document contract and uses exact integer arithmetic
rather than sharing the generator's Decimal implementation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import gzip
import itertools
import json
from pathlib import Path
import re
from typing import Any

ROLES = ("policy", "po", "invoice", "receipts", "returns", "history", "amendments")
WORLDS = ("clean", "critical_edit", "missing_evidence")
VIEWS = ("ar_western", "ar_eastern", "ar_reordered", "en_control")
MECHANISMS = ("receipt_quantity", "rejected_quantity", "return_quantity", "pack_conversion",
              "cumulative_billing", "price_tolerance", "discount", "invoice_total", "currency",
              "duplicate_invoice", "amendment_date", "amendment_status", "receipt_date", "cancellation")
GOLD_KEYS = ("decision", "contract_net_minor", "issues", "evidence_ids")
ISSUES = {"order_canceled", "currency_mismatch", "duplicate_invoice", "quantity_shortfall",
          "price_mismatch", "discount_mismatch", "invoice_arithmetic", "missing_evidence"}
HEADER_KEYS = {
    "policy": {"price_tolerance_bps", "receipt_cutoff", "required_roles", "accepted_only",
               "cumulative_billing", "approved_amendments_only", "canceled_orders_forbidden"},
    "po": {"order_id", "status", "currency"},
    "invoice": {"invoice_id", "order_id", "date", "currency", "stated_net_minor"},
    "receipts": {"complete"}, "returns": {"complete"}, "history": {"complete"}, "amendments": {"complete"},
}
ROW_KEYS = {
    "policy": set(),
    "po": {"sku", "ordered_units", "units_per_pack", "unit_price_minor", "discount_bps"},
    "invoice": {"sku", "quantity_units", "unit_price_minor", "discount_bps"},
    "receipts": {"receipt_id", "sku", "date", "quantity", "quantity_unit", "rejected_quantity"},
    "returns": {"return_id", "sku", "date", "quantity_units", "status"},
    "history": {"invoice_id", "order_id", "sku", "quantity_units", "status"},
    "amendments": {"amendment_id", "sku", "effective_date", "status", "unit_price_minor"},
}


class AuditError(ValueError):
    """A canonical packet or release violates the benchmark contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_net(quantity: int, price: int, discount_bps: int) -> int:
    """Round one nonnegative line, never the accumulated invoice."""
    numerator = quantity * price * (10000 - discount_bps)
    quotient, remainder = divmod(numerator, 10000)
    return quotient + int(remainder >= 5000)


class Packet:
    def __init__(self, documents: list[dict]):
        require(isinstance(documents, list), "documents must be a list")
        self.docs: dict[str, dict] = {}
        self.headers: dict[str, dict[str, dict]] = {}
        self.rows: dict[str, dict[str, dict[str, dict]]] = {}
        self.used: set[str] = set()
        self.ids: set[str] = set()
        doc_ids = set()
        for doc in documents:
            require(isinstance(doc, dict), "document must be an object")
            role = doc.get("role")
            require(role in ROLES and role not in self.docs, f"unknown or duplicate role: {role}")
            require(isinstance(doc.get("doc_id"), str) and doc["doc_id"] not in doc_ids, "invalid or duplicate doc_id")
            doc_ids.add(doc["doc_id"])
            self.docs[role] = doc
            self.headers[role] = {}
            self.rows[role] = {}
            require(isinstance(doc.get("fields"), list), f"{role}: fields must be a list")
            for field in doc["fields"]:
                require(isinstance(field, dict), f"{role}: invalid field")
                for key in ("id", "key", "row_id", "value", "label_ar", "label_en"):
                    require(isinstance(field.get(key), str), f"{role}: field {key} must be a string")
                require(field["id"] and field["id"] not in self.ids, "empty or duplicate field ID")
                self.ids.add(field["id"])
                target = (self.rows[role].setdefault(field["row_id"], {}) if field["row_id"]
                          else self.headers[role])
                require(field["key"] not in target, f"{role}/{field['row_id']}: duplicate field key")
                target[field["key"]] = field
            require(set(self.headers[role]) == HEADER_KEYS[role], f"{role}: header schema mismatch")
            for row_id, fields in self.rows[role].items():
                require(set(fields) == ROW_KEYS[role], f"{role}/{row_id}: row schema mismatch")
            if role in ("po", "invoice"):
                require(bool(self.rows[role]), f"{role}: at least one line is required")

    def get(self, role: str, key: str, row_id: str = "") -> str:
        fields = self.rows[role][row_id] if row_id else self.headers[role]
        field = fields[key]
        self.used.add(field["id"])
        return field["value"]

    def integer(self, role: str, key: str, row_id: str = "", minimum: int = 0,
                maximum: int | None = None) -> int:
        value = self.get(role, key, row_id)
        require(bool(re.fullmatch(r"0|[1-9][0-9]*", value)), f"{role}/{key}: noncanonical nonnegative integer")
        result = int(value)
        require(result >= minimum and (maximum is None or result <= maximum), f"{role}/{key}: out of range")
        return result

    def day(self, role: str, key: str, row_id: str = "") -> date:
        value = self.get(role, key, row_id)
        try:
            result = date.fromisoformat(value)
        except ValueError as exc:
            raise AuditError(f"{role}/{key}: invalid ISO date") from exc
        require(result.isoformat() == value, f"{role}/{key}: date must be YYYY-MM-DD")
        return result

    def enum(self, role: str, key: str, choices: set[str], row_id: str = "") -> str:
        value = self.get(role, key, row_id)
        require(value in choices, f"{role}/{key}: invalid enum {value}")
        return value

    def sku_map(self, role: str) -> dict[str, str]:
        result = {}
        for row_id in self.rows[role]:
            sku = self.get(role, "sku", row_id)
            require(bool(sku) and sku not in result, f"{role}: empty or duplicate SKU")
            result[sku] = row_id
        return result


def compute_gold(documents: list[dict]) -> dict:
    """Recompute gold from canonical fields; return public gold plus audit trace.

    Reference evidence follows explicit reads (not a minimal-proof claim).
    Identifiers merely naming a receipt/return/amendment are not read by the
    numeric policy. Filtering rows reads SKU, date/status before numeric values.
    """
    packet = Packet(documents)
    trace: dict[str, Any] = {"lines": [], "checks": {}, "missing_roles": sorted(set(ROLES) - packet.docs.keys())}
    if "policy" in packet.docs:
        tolerance = packet.integer("policy", "price_tolerance_bps")
        require(packet.get("policy", "receipt_cutoff") == "invoice_date", "unsupported receipt cutoff")
        required = packet.get("policy", "required_roles").split(",")
        require(set(required) == set(ROLES) - {"policy"} and len(required) == 6, "unsupported required_roles")
        for key in ("accepted_only", "cumulative_billing", "approved_amendments_only", "canceled_orders_forbidden"):
            require(packet.get("policy", key) == "true", f"unsupported policy {key}")
    else:
        tolerance = None

    contract = None
    amount_ready = {"po", "invoice", "amendments"}.issubset(packet.docs)
    line_data = []
    if amount_ready:
        invoice_date = packet.day("invoice", "date")
        po_rows = packet.sku_map("po")
        invoice_rows = packet.sku_map("invoice")
        require(set(invoice_rows).issubset(po_rows), "invoice SKU not in PO")
        require(packet.get("amendments", "complete") == "true", "incomplete amendments register")
        amendments = defaultdict(list)
        for row_id in packet.rows["amendments"]:
            sku = packet.get("amendments", "sku", row_id)
            effective_date = packet.day("amendments", "effective_date", row_id)
            status = packet.enum("amendments", "status", {"approved", "draft"}, row_id)
            if status == "approved" and effective_date <= invoice_date:
                amendments[sku].append((effective_date, row_id))
        contract = 0
        for sku, invoice_row in invoice_rows.items():
            po_row = po_rows[sku]
            quantity = packet.integer("invoice", "quantity_units", invoice_row, 1)
            base_price = packet.integer("po", "unit_price_minor", po_row, 1)
            discount = packet.integer("po", "discount_bps", po_row, maximum=10000)
            eligible = amendments.get(sku, [])
            require(len({day for day, _ in eligible}) == len(eligible), "ambiguous amendment dates")
            if eligible:
                _, amendment_row = max(eligible)
                price = packet.integer("amendments", "unit_price_minor", amendment_row)
            else:
                price = base_price
            net = line_net(quantity, price, discount)
            contract += net
            line_data.append((sku, invoice_row, po_row, quantity, price, discount))
            trace["lines"].append({"sku": sku, "invoice_quantity": quantity, "contract_unit_price_minor": price,
                                   "contract_discount_bps": discount, "contract_line_net_minor": net})

    if trace["missing_roles"]:
        return {"decision": "insufficient_evidence", "contract_net_minor": contract,
                "issues": ["missing_evidence"], "evidence_ids": sorted(packet.used), "trace": trace}

    require(amount_ready, "internal completeness error")
    po_order = packet.get("po", "order_id")
    invoice_order = packet.get("invoice", "order_id")
    require(invoice_order == po_order, "order references differ; outside benchmark contract")
    current_invoice = packet.get("invoice", "invoice_id")
    canceled = packet.enum("po", "status", {"active", "canceled"}) == "canceled"
    currency_mismatch = packet.get("po", "currency") != packet.get("invoice", "currency")
    for role in ("receipts", "returns", "history"):
        require(packet.get(role, "complete") == "true", f"incomplete {role} register")

    posted = Counter()
    duplicate = False
    for row_id in packet.rows["history"]:
        order = packet.get("history", "order_id", row_id)
        status = packet.enum("history", "status", {"posted", "void"}, row_id)
        historical_invoice = packet.get("history", "invoice_id", row_id)
        if status != "posted":
            continue
        duplicate = duplicate or historical_invoice == current_invoice
        if order == invoice_order:
            sku = packet.get("history", "sku", row_id)
            posted[sku] += packet.integer("history", "quantity_units", row_id)

    accepted, returned = Counter(), Counter()
    for row_id in packet.rows["receipts"]:
        sku = packet.get("receipts", "sku", row_id)
        receipt_date = packet.day("receipts", "date", row_id)
        if receipt_date > invoice_date or sku not in po_rows:
            continue
        quantity = packet.integer("receipts", "quantity", row_id)
        rejected = packet.integer("receipts", "rejected_quantity", row_id)
        require(rejected <= quantity, "rejected receipt quantity exceeds receipt quantity")
        unit = packet.enum("receipts", "quantity_unit", {"unit", "pack"}, row_id)
        pack = packet.integer("po", "units_per_pack", po_rows[sku], 1) if unit == "pack" else 1
        accepted[sku] += (quantity - rejected) * pack
    for row_id in packet.rows["returns"]:
        sku = packet.get("returns", "sku", row_id)
        return_date = packet.day("returns", "date", row_id)
        status = packet.enum("returns", "status", {"approved", "draft"}, row_id)
        if status == "approved" and return_date <= invoice_date:
            returned[sku] += packet.integer("returns", "quantity_units", row_id)

    quantity_bad = price_bad = discount_bad = False
    invoice_total = 0
    for line, (sku, invoice_row, po_row, quantity, price, discount) in zip(trace["lines"], line_data):
        ordered = packet.integer("po", "ordered_units", po_row, 1)
        invoice_price = packet.integer("invoice", "unit_price_minor", invoice_row, 1)
        invoice_discount = packet.integer("invoice", "discount_bps", invoice_row, maximum=10000)
        remaining_ordered = ordered - posted[sku]
        available_received = accepted[sku] - returned[sku] - posted[sku]
        shortfall = quantity > remaining_ordered or quantity > available_received
        price_fail = abs(invoice_price - price) * 10000 > price * tolerance
        discount_fail = invoice_discount != discount
        invoice_net = line_net(quantity, invoice_price, invoice_discount)
        quantity_bad |= shortfall
        price_bad |= price_fail
        discount_bad |= discount_fail
        invoice_total += invoice_net
        line.update({"ordered_units": ordered, "posted_units": posted[sku], "accepted_units": accepted[sku],
                     "approved_returned_units": returned[sku], "remaining_ordered_units": remaining_ordered,
                     "available_received_units": available_received, "quantity_shortfall": shortfall,
                     "invoice_unit_price_minor": invoice_price, "invoice_discount_bps": invoice_discount,
                     "price_mismatch": price_fail, "discount_mismatch": discount_fail,
                     "invoice_line_net_minor": invoice_net})
    stated = packet.integer("invoice", "stated_net_minor")
    trace["invoice_calculated_net_minor"] = invoice_total
    trace["invoice_stated_net_minor"] = stated
    trace["checks"] = {"order_canceled": canceled, "currency_mismatch": currency_mismatch,
                       "duplicate_invoice": duplicate, "quantity_shortfall": quantity_bad,
                       "price_mismatch": price_bad, "discount_mismatch": discount_bad,
                       "invoice_arithmetic": stated != invoice_total}
    issues = sorted(key for key, failed in trace["checks"].items() if failed)
    return {"decision": "mismatch" if issues else "match", "contract_net_minor": contract,
            "issues": issues, "evidence_ids": sorted(packet.used), "trace": trace}


def compare_gold(actual: dict, expected: dict, context: str = "gold") -> None:
    for key in GOLD_KEYS:
        require(actual.get(key) == expected[key], f"{context}: {key} mismatch: {actual.get(key)!r} != {expected[key]!r}")


def flatten_documents(documents: list[dict]) -> dict[str, Any]:
    """Order-independent canonical leaves, retaining metadata as well as values."""
    leaves = {}
    for doc in documents:
        doc_id = doc["doc_id"]
        for key, value in doc.items():
            if key != "fields":
                leaves[f"{doc_id}/{key}"] = value
        for field in doc["fields"]:
            for key, value in field.items():
                leaves[f"{doc_id}/fields/{field['id']}/{key}"] = value
    return leaves


def leaf_deltas(before: list[dict], after: list[dict]) -> list[dict]:
    left, right = flatten_documents(before), flatten_documents(after)
    return [{"path": key, "before": left.get(key), "after": right.get(key)}
            for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)]


def check_critical_edit(before: list[dict], after: list[dict], edit: dict) -> None:
    deltas = leaf_deltas(before, after)
    require(len(deltas) == 1 and deltas[0]["path"].endswith("/value"), "critical edit is not exactly one canonical value leaf")
    doc_id, _, field_id, _ = deltas[0]["path"].split("/")
    expected = {"path": f"documents.{doc_id}.fields.{field_id}.value", "doc_id": doc_id,
                "field_id": field_id, "before": deltas[0]["before"], "after": deltas[0]["after"]}
    require(edit == expected, f"recorded critical edit differs from actual delta: {edit!r} != {expected!r}")


def check_missing_document(before: list[dict], after: list[dict], edit: dict) -> None:
    left = {doc["doc_id"]: doc for doc in before}
    right = {doc["doc_id"]: doc for doc in after}
    removed = left.keys() - right.keys()
    require(len(removed) == 1 and not right.keys() - left.keys(), "missing world must omit exactly one document")
    removed_id = next(iter(removed))
    require(flatten_documents([doc for doc in before if doc["doc_id"] != removed_id]) == flatten_documents(after),
            "missing world also changes retained evidence")
    require(edit == {"removed_doc_id": removed_id, "removed_role": left[removed_id]["role"]}, "incorrect omission metadata")


def _spec_rows(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AuditError(f"{path.name}:{number}: invalid JSON") from exc


def _parquet_rows(paths: list[Path], kind: str):
    import pyarrow as pa
    import pyarrow.parquet as pq

    required = ({"case_id", "family_id", "world", "view", "language", "digit_script", "mechanism", "style",
                 "question", "documents", "gold_decision", "gold_contract_net_minor", "gold_issues", "gold_evidence_ids"}
                if kind == "cases" else {"pair_id", "family_id", "case_id_a", "case_id_b", "relation", "axis", "edit_json"})
    for path in paths:
        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        require(set(schema.names) == required, f"{path.name}: {kind} column schema differs")
        for field in schema:
            if kind == "cases" and field.name == "style":
                require(pa.types.is_integer(field.type), f"{path.name}: style is not an integer")
            elif field.name == "gold_contract_net_minor":
                require(pa.types.is_integer(field.type), f"{path.name}: amount is not an integer")
            elif field.name in ("gold_issues", "gold_evidence_ids"):
                require(pa.types.is_list(field.type) and pa.types.is_string(field.type.value_type), f"{path.name}: invalid {field.name} type")
            elif field.name == "documents":
                require(pa.types.is_list(field.type) and pa.types.is_struct(field.type.value_type), f"{path.name}: documents type")
                children = field.type.value_type
                require(set(child.name for child in children) == {"doc_id", "title", "text"} and
                        all(pa.types.is_string(child.type) for child in children), f"{path.name}: visible document schema")
            else:
                require(pa.types.is_string(field.type), f"{path.name}: {field.name} must be a string")
        for batch in parquet.iter_batches(batch_size=128):
            yield from batch.to_pylist()


def _visible_check(spec: dict, row: dict) -> None:
    """Check exact marker grounding, display order, labels and literal identities.

    Numeric/date rendering is checked within each field's marked span. Enum
    translations are deliberately not inferred from the oracle's hidden roles.
    """
    documents = spec["documents"]
    visible = row["documents"]
    expected_docs = list(reversed(documents)) if spec["view"] == "ar_reordered" else documents
    require([doc["doc_id"] for doc in visible] == [doc["doc_id"] for doc in expected_docs], "visible document order/IDs differ")
    canonical = {doc["doc_id"]: doc for doc in documents}
    all_markers = []
    eastern = str.maketrans("0123456789.,", "٠١٢٣٤٥٦٧٨٩٫٬")
    enum_ar = {"true": "نعم", "active": "ساري المفعول", "canceled": "ملغى", "approved": "معتمد",
               "draft": "مسودة", "posted": "مرحّل", "void": "ملغى", "unit": "قطعة", "pack": "عبوة",
               "invoice_date": "تاريخ الفاتورة شاملاً ذلك اليوم"}
    enum_en = {"true": "yes", "invoice_date": "invoice date, inclusive"}
    titles = {"policy": ("سياسة المطابقة الخاصة بهذه الحالة", "Case-specific matching policy"),
              "po": ("أمر الشراء", "Purchase order"), "invoice": ("فاتورة المورد", "Supplier invoice"),
              "receipts": ("سجل استلام البضائع", "Goods receipt register"), "returns": ("سجل المرتجعات", "Returns register"),
              "history": ("سجل الفواتير السابقة", "Prior invoice register"), "amendments": ("سجل تعديلات الأسعار", "Price amendment register")}
    synonyms = {
        1: {"الحالة": "حالة القيد", "التاريخ الميلادي": "تاريخ المستند بالميلادي", "الكمية بالقطعة": "كمية القطع",
            "رقم الفاتورة": "معرّف الفاتورة", "رقم أمر الشراء": "معرّف أمر الشراء"},
        2: {"الحالة": "حالة المستند", "التاريخ الميلادي": "تاريخ القيد الميلادي", "الكمية بالقطعة": "عدد القطع",
            "سعر الوحدة النقدية": "السعر لكل قطعة نقداً", "رقم أمر الشراء": "مرجع أمر التوريد"},
        3: {"الحالة": "وضع المستند", "العملة": "عملة المستند", "الكمية بالقطعة": "العدد بوحدة القطعة",
            "الإجمالي الصافي المدوّن": "صافي الفاتورة المثبت", "خصم البند": "نسبة الخصم للبند"},
    }
    for doc in visible:
        original = canonical[doc["doc_id"]]
        expected_title = original.get("title_en", original["title"]) if spec["view"] == "en_control" else original["title"]
        require(doc["title"] == expected_title, "visible title mismatch")
        text = doc["text"]
        markers = list(re.finditer(r"\[([^\[\]\n]+)\]", text))
        ids = [match.group(1) for match in markers]
        groups = defaultdict(list)
        for field in original["fields"]:
            groups[field["row_id"]].append(field)
        ordered_groups = list(groups.values())
        if spec["view"] == "ar_reordered":
            ordered_groups = [list(reversed(group)) for group in reversed(ordered_groups)]
        expected_ids = [field["id"] for group in ordered_groups for field in group]
        require(ids == expected_ids, "missing, duplicated, reordered or unexpected visible field marker")
        all_markers.extend(ids)
        spans = {match.group(1): text[match.end():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
                 for index, match in enumerate(markers)}
        for field in original["fields"]:
            span = spans[field["id"]]
            label = field["label_en"] if spec["view"] == "en_control" else field["label_ar"]
            if spec["view"] != "en_control":
                label = synonyms.get(spec["style"], {}).get(label, label)
            value = field["value"]
            if field["key"].endswith("_minor"):
                value = f"{int(value) // 100}.{int(value) % 100:02d}"
            elif field["key"].endswith("_bps"):
                value = f"{int(value) // 100}.{int(value) % 100:02d}%"
            elif field["key"] == "required_roles":
                value = (", " if spec["view"] == "en_control" else "، ").join(
                    titles[role][spec["view"] == "en_control"] for role in value.split(","))
            else:
                value = (enum_en if spec["view"] == "en_control" else enum_ar).get(value, value)
            if spec["view"] == "ar_eastern" and not field["key"].endswith("_id") and field["key"] != "sku":
                value = value.translate(eastern)
            require(span.splitlines()[0].strip() == f"{label}: {value}", f"visible field label/value differs for {field['id']}")
    require(len(all_markers) == len(set(all_markers)), "visible field IDs are not globally unique")
    require(set(row["gold_evidence_ids"]).issubset(all_markers), "gold cites nonexistent visible evidence")
    require(isinstance(row["question"], str) and row["question"].strip(), "question is empty")


def audit_release(release: str | Path, expected_families_per_mechanism: int | None = None) -> dict:
    """Audit every canonical fact, public row and pair; stream family packets."""
    release = Path(release)
    case_index: dict[str, dict] = {}
    family_index: dict[str, dict] = {}
    counts = {axis: Counter() for axis in ("split", "world", "view", "mechanism", "decision", "families_by_split")}
    evidence_sum, evidence_min, evidence_max = 0, None, 0
    spec_paths = sorted((release / "specs").glob("*.jsonl")) + sorted((release / "specs").glob("*.jsonl.gz"))
    require(bool(spec_paths), "no canonical spec files")
    for path in spec_paths:
        split = path.name.split(".")[0]
        require(split in {"train", "validation", "test", "challenge"}, f"unknown split {split}")
        parquet_paths = sorted((release / "data" / "cases").glob(f"{split}-*.parquet"))
        require(bool(parquet_paths), f"{split}: no case parquet")
        public_rows = iter(_parquet_rows(parquet_paths, "cases"))
        for family_id, family_rows in itertools.groupby(_spec_rows(path), key=lambda item: item["family_id"]):
            specs = list(family_rows)
            require(family_id not in family_index, f"family recurs or crosses splits: {family_id}")
            require(bool(re.fullmatch(r"(?:[0-9a-f]{24}|[0-9a-f]{64})", family_id)), "family_id is not an opaque SHA256 prefix/digest")
            require(len(specs) == 12, f"family {family_id}: expected twelve world-view rows")
            combinations = {(spec["world"], spec["view"]) for spec in specs}
            require(combinations == set(itertools.product(WORLDS, VIEWS)), "family world-view closure failure")
            mechanism = specs[0]["mechanism"]
            require(mechanism in MECHANISMS and all(spec["mechanism"] == mechanism for spec in specs), "family mechanism changes")
            styles = {spec["style"] for spec in specs}
            allowed = {0, 1} if split in {"train", "validation"} else ({2} if split == "test" else {3})
            require(len(styles) == 1 and styles.issubset(allowed), "style/split separation fails")
            by_world = {world: [spec for spec in specs if spec["world"] == world] for world in WORLDS}
            world_docs, world_gold, world_edit = {}, {}, {}
            for world, siblings in by_world.items():
                canonical_hashes = {stable_hash(flatten_documents(spec["documents"])) for spec in siblings}
                require(len(canonical_hashes) == 1, "representation view changes canonical facts")
                reference = compute_gold(siblings[0]["documents"])
                expected_decision = {"clean": "match", "critical_edit": "mismatch", "missing_evidence": "insufficient_evidence"}[world]
                require(reference["decision"] == expected_decision, f"{family_id}/{world}: construction decision is {reference['decision']}")
                world_docs[world] = siblings[0]["documents"]
                world_gold[world] = {key: reference[key] for key in GOLD_KEYS}
                world_edit[world] = siblings[0].get("edit")
                for sibling in siblings:
                    compare_gold(sibling["gold"], reference, f"{sibling['case_id']} spec gold")
                    require(sibling.get("edit") == world_edit[world], "edit metadata changes across views")
            check_critical_edit(world_docs["clean"], world_docs["critical_edit"], world_edit["critical_edit"])
            check_missing_document(world_docs["clean"], world_docs["missing_evidence"], world_edit["missing_evidence"])
            family_index[family_id] = {"split": split, "mechanism": mechanism, "edits": world_edit,
                                       "ids": {(spec["world"], spec["view"]): spec["case_id"] for spec in specs}}
            counts["families_by_split"][split] += 1
            for spec in specs:
                case_id = spec["case_id"]
                require(case_id not in case_index and bool(re.fullmatch(r"(?:[0-9a-f]{24}|[0-9a-f]{64})", case_id)), "duplicate or nonopaque case_id")
                row = next(public_rows, None)
                require(row is not None and row["case_id"] == case_id, f"{split}: spec/parquet row order or membership differs at {case_id}")
                for key in ("case_id", "family_id", "world", "view", "mechanism", "style"):
                    require(row[key] == spec[key], f"{case_id}: public {key} differs from spec")
                require(row["language"] == ("en" if spec["view"] == "en_control" else "ar"), "language metadata mismatch")
                expected_digits = "arabic_indic" if spec["view"] == "ar_eastern" else "western"
                require(row["digit_script"] == expected_digits, "digit_script metadata mismatch")
                actual_gold = {"decision": row["gold_decision"], "contract_net_minor": row["gold_contract_net_minor"],
                               "issues": row["gold_issues"], "evidence_ids": row["gold_evidence_ids"]}
                compare_gold(actual_gold, world_gold[spec["world"]], f"{case_id} parquet gold")
                _visible_check(spec, row)
                evidence_count = len(actual_gold["evidence_ids"])
                evidence_sum += evidence_count
                evidence_min = evidence_count if evidence_min is None else min(evidence_min, evidence_count)
                evidence_max = max(evidence_max, evidence_count)
                case_index[case_id] = {"split": split, "family_id": family_id, "world": spec["world"], "view": spec["view"]}
                for axis in ("world", "view", "mechanism"):
                    counts[axis][spec[axis]] += 1
                counts["split"][split] += 1
                counts["decision"][actual_gold["decision"]] += 1
        require(next(public_rows, None) is None, f"{split}: parquet has extra rows absent from specs")
    all_public_paths = list((release / "data" / "cases").glob("*.parquet"))
    require(all(path.name.split("-")[0] in counts["split"] for path in all_public_paths), "case parquet has no corresponding spec split")
    expected_pairs = {}
    axes = {"ar_eastern": "digit_script", "ar_reordered": "document_order", "en_control": "language_control"}
    for family_id, family in family_index.items():
        ids = family["ids"]
        for world in WORLDS:
            for view, axis in axes.items():
                expected_pairs[(ids[(world, "ar_western")], ids[(world, view)])] = (family_id, "invariant", axis, None)
        for view in VIEWS:
            for world, axis in (("critical_edit", "critical_fact"), ("missing_evidence", "missing_document")):
                expected_pairs[(ids[("clean", view)], ids[(world, view)])] = (family_id, "sensitivity", axis, family["edits"][world])
    pair_ids, seen_pairs, pair_counts = set(), set(), Counter()
    pair_paths = sorted((release / "data" / "pairs").glob("*.parquet"))
    require(bool(pair_paths), "no pair parquet files")
    for path in pair_paths:
        split = path.name.split("-")[0]
        for pair in _parquet_rows([path], "pairs"):
            pair_id = pair["pair_id"]
            require(pair_id not in pair_ids and bool(re.fullmatch(r"(?:[0-9a-f]{24}|[0-9a-f]{64})", pair_id)), "duplicate or nonopaque pair_id")
            pair_ids.add(pair_id)
            key = (pair["case_id_a"], pair["case_id_b"])
            require(key in expected_pairs and key not in seen_pairs, "unexpected or duplicate pair relation")
            seen_pairs.add(key)
            family, relation, axis, edit = expected_pairs[key]
            require((pair["family_id"], pair["relation"], pair["axis"]) == (family, relation, axis), "pair metadata mismatch")
            require(family_index[family]["split"] == split, "pair crosses or misstates split")
            parsed_edit = json.loads(pair["edit_json"])
            require(parsed_edit == edit or (edit is None and parsed_edit == {}), "pair edit metadata differs")
            pair_counts[f"{relation}/{axis}"] += 1
    require(seen_pairs == expected_pairs.keys(), "missing expected sibling pairs")
    mechanism_family_counts = Counter(family["mechanism"] for family in family_index.values())
    if expected_families_per_mechanism is not None:
        require(set(mechanism_family_counts) == set(MECHANISMS) and
                all(value == expected_families_per_mechanism for value in mechanism_family_counts.values()), "unexpected mechanism family counts")
        if expected_families_per_mechanism == 400:
            split_mechanisms = Counter((family["split"], family["mechanism"]) for family in family_index.values())
            require(all(split_mechanisms[(split, mechanism)] == expected for split, expected in
                        (("train", 280), ("validation", 40), ("test", 40), ("challenge", 40)) for mechanism in MECHANISMS),
                    "published split proportions differ")
    statistics_path = release / "statistics.json"
    if statistics_path.exists():
        statistics = json.loads(statistics_path.read_text(encoding="utf-8"))
        require(statistics["families"] == len(family_index), "statistics family count differs")
        require(statistics["counts"]["cases"] == len(case_index) and statistics["counts"]["pairs"] == len(pair_ids), "statistics case/pair counts differ")
        if "family_counts" in statistics:
            require(statistics["family_counts"] == dict(counts["families_by_split"]), "statistics family split counts differ")
        if "split_counts" in statistics:
            require(statistics["split_counts"]["cases"] == dict(counts["split"]), "statistics case split counts differ")
        if "mechanism_case_counts" in statistics:
            require(statistics["mechanism_case_counts"] == dict(counts["mechanism"]), "statistics mechanism counts differ")
        if "evidence_field_count" in statistics:
            require(statistics["evidence_field_count"] == {"min": evidence_min, "max": evidence_max,
                                                           "mean": evidence_sum / len(case_index)}, "statistics evidence counts differ")
    inputs = spec_paths + all_public_paths + pair_paths + ([statistics_path] if statistics_path.exists() else [])
    return {"status": "passed", "independent_oracle": "Exact integer quotient/remainder half-up, no generator/core import",
            "verifier_sha256": file_sha256(Path(__file__)),
            "input_sha256": {str(path.relative_to(release)): file_sha256(path) for path in sorted(inputs)},
            "cases": len(case_index), "families": len(family_index), "pairs": len(pair_ids),
            "counts": {axis: dict(sorted(values.items())) for axis, values in counts.items()},
            "families_by_mechanism": dict(sorted(mechanism_family_counts.items())), "pair_counts": dict(sorted(pair_counts.items())),
            "checks": ["every canonical world independently recomputed", "every public gold equals recomputed spec",
                       "typed parquet schema", "visible field markers/labels/numeric values and opaque identities",
                       "four-view canonical invariance", "one recorded critical value leaf per family",
                       "one recorded missing document, all retained facts unchanged", "family split closure",
                       "complete expected world-view and pair membership", "no nonexistent gold citations"],
            "limitations": ["Checks generated policy semantics, not real-world accounting correctness.",
                            "No human or expert validation; controlled Arabic/English wording is not natural document coverage.",
                            "Reference evidence agreement is not a minimal-proof or semantic faithfulness guarantee."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-families-per-mechanism", type=int)
    args = parser.parse_args()
    report = audit_release(args.release, args.expected_families_per_mechanism)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
