"""Hand-authored edge cases and adversarial release mutations.

These fixtures do not call the release generator or its oracle.  Their amounts
and expected policy outcomes are calculated explicitly in the assertions.
"""
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import verify
import score
import baseline_heuristics


def fixture():
    definitions = [
        ("policy", [("", {"price_tolerance_bps": "0", "receipt_cutoff": "invoice_date",
                          "required_roles": "po,invoice,receipts,returns,history,amendments", "accepted_only": "true",
                          "cumulative_billing": "true", "approved_amendments_only": "true", "canceled_orders_forbidden": "true"})]),
        ("po", [("", {"order_id": "PO-A", "status": "active", "currency": "SAR"}),
                ("A", {"sku": "ITEM-A", "ordered_units": "20", "units_per_pack": "5", "unit_price_minor": "101", "discount_bps": "250"})]),
        ("invoice", [("", {"invoice_id": "INV-A", "order_id": "PO-A", "date": "2026-01-15", "currency": "SAR", "stated_net_minor": "985"}),
                     ("A", {"sku": "ITEM-A", "quantity_units": "10", "unit_price_minor": "101", "discount_bps": "250"})]),
        ("receipts", [("", {"complete": "true"}),
                      ("R1", {"receipt_id": "REC-A", "sku": "ITEM-A", "date": "2026-01-14", "quantity": "10", "quantity_unit": "unit", "rejected_quantity": "0"}),
                      ("R2", {"receipt_id": "REC-B", "sku": "ITEM-A", "date": "2026-02-01", "quantity": "100", "quantity_unit": "pack", "rejected_quantity": "0"})]),
        ("returns", [("", {"complete": "true"}),
                     ("T1", {"return_id": "RET-A", "sku": "ITEM-A", "date": "2026-01-14", "quantity_units": "20", "status": "draft"})]),
        ("history", [("", {"complete": "true"}),
                     ("H1", {"invoice_id": "OLD-A", "order_id": "PO-A", "sku": "ITEM-A", "quantity_units": "12", "status": "void"})]),
        ("amendments", [("", {"complete": "true"})]),
    ]
    documents = []
    for index, (role, groups) in enumerate(definitions, 1):
        fields = []
        doc_id = f"D{index:02d}"
        for row_id, values in groups:
            for key, value in values.items():
                fields.append({"id": f"{doc_id}.F{len(fields) + 1:02d}", "key": key, "row_id": row_id, "value": value,
                               "label_ar": "حقل " + key, "label_en": "Field " + key})
        documents.append({"doc_id": doc_id, "role": role, "title": "وثيقة " + role,
                          "title_en": "Document " + role, "fields": fields})
    return documents


def doc(documents, role):
    return next(item for item in documents if item["role"] == role)


def field(documents, role, key, row_id=""):
    return next(item for item in doc(documents, role)["fields"] if item["key"] == key and item["row_id"] == row_id)


def change(documents, role, key, value, row_id=""):
    field(documents, role, key, row_id)["value"] = str(value)


def append_row(documents, role, row_id, values):
    target = doc(documents, role)
    for key, value in values.items():
        target["fields"].append({"id": f"{target['doc_id']}.F{len(target['fields']) + 1:02d}", "key": key,
                                 "row_id": row_id, "value": str(value), "label_ar": "حقل " + key, "label_en": "Field " + key})


def public_row(documents=None):
    documents = fixture() if documents is None else documents
    gold = verify.compute_gold(documents)
    return {"gold_decision": gold["decision"], "gold_contract_net_minor": gold["contract_net_minor"],
            "gold_issues": gold["issues"], "gold_evidence_ids": gold["evidence_ids"],
            "documents": [{"doc_id": item["doc_id"], "title": item["title"],
                           "text": "\n".join(f"[{value['id']}] x" for value in item["fields"])} for item in documents]}


class OracleTests(unittest.TestCase):
    def test_clean_filters_future_draft_void_and_half_up(self):
        documents = fixture()
        gold = verify.compute_gold(documents)
        self.assertEqual((gold["decision"], gold["contract_net_minor"], gold["issues"]), ("match", 985, []))
        self.assertEqual(len(gold["evidence_ids"]), 40)
        self.assertNotIn(field(documents, "receipts", "quantity", "R2")["id"], gold["evidence_ids"])
        self.assertNotIn(field(documents, "returns", "quantity_units", "T1")["id"], gold["evidence_ids"])
        self.assertIn(field(documents, "history", "invoice_id", "H1")["id"], gold["evidence_ids"])
        self.assertNotIn(field(documents, "history", "quantity_units", "H1")["id"], gold["evidence_ids"])
        self.assertNotIn(field(documents, "po", "units_per_pack", "A")["id"], gold["evidence_ids"])

    def test_round_per_line_instead_of_invoice_total(self):
        self.assertEqual(verify.line_net(1, 1, 5000), 1)
        self.assertEqual(verify.line_net(1, 1, 5001), 0)
        self.assertEqual(verify.line_net(1, 1, 4999), 1)
        self.assertEqual(sum(verify.line_net(1, 1, 5000) for _ in range(2)), 2)
        self.assertEqual(verify.line_net(2, 1, 5000), 1)
        self.assertEqual(verify.line_net(999999999999, 999999999999, 3333), 666699999998666600000001)

    def test_pack_conversion_uses_rejected_same_unit(self):
        documents = fixture()
        change(documents, "receipts", "quantity", 3, "R1")
        change(documents, "receipts", "quantity_unit", "pack", "R1")
        change(documents, "receipts", "rejected_quantity", 1, "R1")
        self.assertEqual(verify.compute_gold(documents)["decision"], "match")
        change(documents, "po", "units_per_pack", 4, "A")
        gold = verify.compute_gold(documents)
        self.assertEqual(gold["issues"], ["quantity_shortfall"])
        self.assertEqual(gold["contract_net_minor"], 985)

    def test_cumulative_order_and_receipt_limits(self):
        documents = fixture()
        change(documents, "history", "status", "posted", "H1")
        change(documents, "history", "quantity_units", 1, "H1")
        self.assertEqual(verify.compute_gold(documents)["issues"], ["quantity_shortfall"])
        change(documents, "receipts", "quantity", 100, "R1")
        change(documents, "po", "ordered_units", 10, "A")
        self.assertEqual(verify.compute_gold(documents)["issues"], ["quantity_shortfall"])

    def test_approved_returns_and_cutoff(self):
        documents = fixture()
        change(documents, "returns", "status", "approved", "T1")
        change(documents, "returns", "quantity_units", 1, "T1")
        self.assertEqual(verify.compute_gold(documents)["issues"], ["quantity_shortfall"])
        change(documents, "returns", "date", "2026-01-16", "T1")
        self.assertEqual(verify.compute_gold(documents)["decision"], "match")
        change(documents, "receipts", "date", "2026-01-16", "R1")
        self.assertEqual(verify.compute_gold(documents)["issues"], ["quantity_shortfall"])

    def test_tolerance_boundary_is_inclusive(self):
        documents = fixture()
        change(documents, "po", "unit_price_minor", 100, "A")
        change(documents, "invoice", "unit_price_minor", 103, "A")
        change(documents, "policy", "price_tolerance_bps", 300)
        change(documents, "invoice", "stated_net_minor", 1004)
        self.assertEqual(verify.compute_gold(documents)["issues"], [])
        change(documents, "policy", "price_tolerance_bps", 299)
        self.assertEqual(verify.compute_gold(documents)["issues"], ["price_mismatch"])

    def test_latest_eligible_approved_amendment_and_contract_not_payable(self):
        documents = fixture()
        for row, day, status, price in (("A1", "2026-01-10", "approved", 102), ("A2", "2026-01-15", "approved", 105),
                                        ("A3", "2026-01-14", "draft", 900), ("A4", "2026-01-16", "approved", 800)):
            append_row(documents, "amendments", row, {"amendment_id": row, "sku": "ITEM-A", "effective_date": day,
                                                      "status": status, "unit_price_minor": price})
        gold = verify.compute_gold(documents)
        self.assertEqual(gold["contract_net_minor"], 1024)
        self.assertEqual(gold["issues"], ["price_mismatch"])
        self.assertIn(field(documents, "amendments", "unit_price_minor", "A2")["id"], gold["evidence_ids"])
        for row in ("A1", "A3", "A4"):
            self.assertNotIn(field(documents, "amendments", "unit_price_minor", row)["id"], gold["evidence_ids"])

    def test_posted_duplicate_even_if_other_order(self):
        documents = fixture()
        change(documents, "history", "status", "posted", "H1")
        change(documents, "history", "invoice_id", "INV-A", "H1")
        change(documents, "history", "order_id", "OTHER-ORDER", "H1")
        self.assertEqual(verify.compute_gold(documents)["issues"], ["duplicate_invoice"])

    def test_discount_currency_cancel_and_stated_arithmetic(self):
        documents = fixture()
        change(documents, "invoice", "discount_bps", 0, "A")
        change(documents, "invoice", "currency", "AED")
        change(documents, "po", "status", "canceled")
        gold = verify.compute_gold(documents)
        self.assertEqual(gold["issues"], ["currency_mismatch", "discount_mismatch", "invoice_arithmetic", "order_canceled"])
        self.assertEqual(gold["contract_net_minor"], 985)

    def test_missing_evidence_amount_dependency_and_policy_trace(self):
        for removed in verify.ROLES:
            with self.subTest(removed=removed):
                documents = [item for item in fixture() if item["role"] != removed]
                gold = verify.compute_gold(documents)
                self.assertEqual(gold["decision"], "insufficient_evidence")
                self.assertEqual(gold["issues"], ["missing_evidence"])
                self.assertEqual(gold["contract_net_minor"], None if removed in {"po", "invoice", "amendments"} else 985)
                if removed not in {"invoice", "po", "amendments"}:
                    self.assertNotIn(field(documents, "invoice", "stated_net_minor")["id"], gold["evidence_ids"])

    def test_malformed_canonical_values_rejected(self):
        for value in ("-1", "1.0", "01", "١", "true"):
            documents = fixture()
            change(documents, "invoice", "quantity_units", value, "A")
            with self.assertRaises(verify.AuditError):
                verify.compute_gold(documents)

    def test_gold_mutations_and_unrecorded_second_fact_rejected(self):
        documents = fixture()
        expected = verify.compute_gold(documents)
        for key, value in (("decision", "mismatch"), ("contract_net_minor", 984),
                           ("evidence_ids", expected["evidence_ids"][1:]),
                           ("evidence_ids", expected["evidence_ids"] + ["NONEXISTENT"])):
            actual = {**expected, key: value}
            with self.assertRaises(verify.AuditError):
                verify.compare_gold(actual, expected)
        after = copy.deepcopy(documents)
        target = field(after, "receipts", "quantity", "R1")
        before = target["value"]
        target["value"] = "9"
        edit = {"path": f"documents.D04.fields.{target['id']}.value", "doc_id": "D04", "field_id": target["id"], "before": before, "after": "9"}
        verify.check_critical_edit(documents, after, edit)
        change(after, "invoice", "stated_net_minor", 984)
        with self.assertRaises(verify.AuditError):
            verify.check_critical_edit(documents, after, edit)


class ScorerTests(unittest.TestCase):
    def test_joint_allows_extra_valid_citation_but_not_invented(self):
        documents = fixture()
        row = public_row(documents)
        gold = verify.compute_gold(documents)
        prediction = {key: gold[key] for key in verify.GOLD_KEYS}
        prediction["evidence_ids"] = gold["evidence_ids"] + [field(documents, "po", "units_per_pack", "A")["id"]]
        result = score.evaluate_case(row, prediction)
        self.assertEqual(result["strict_joint"], 1)
        self.assertLess(result["evidence_precision"], 1)
        prediction["evidence_ids"].append("D99.F99")
        result = score.evaluate_case(row, prediction)
        self.assertEqual(result["strict_joint"], 0)
        self.assertEqual(result["core_exact"], 1)
        self.assertEqual(result["invalid_citations"], 1)

    def test_missing_reference_citation_and_invalid_outputs(self):
        row = public_row()
        gold = verify.compute_gold(fixture())
        prediction = {key: gold[key] for key in verify.GOLD_KEYS}
        prediction["evidence_ids"] = prediction["evidence_ids"][1:]
        self.assertEqual(score.evaluate_case(row, prediction)["strict_joint"], 0)
        for invalid in (None, {"case_id": "A"}, {**prediction, "contract_net_minor": True},
                        {**prediction, "issues": ["invented_issue"]}, {**prediction, "evidence_ids": ["x", "x"]}):
            result = score.evaluate_case(row, invalid)
            self.assertEqual(result["schema_valid"], 0)
            self.assertEqual(result["decision_exact"], 0)

    def test_duplicate_prediction_ids_rejected(self):
        with self.assertRaises(ValueError):
            score.read_predictions([{"case_id": "A"}, {"case_id": "A"}])

    def test_family_cluster_bootstrap_deterministic_and_not_case_independent(self):
        values = {"family1": {"x": (12, 12)}, "family2": {"x": (0, 12)}}
        first = score.cluster_intervals(values, 500, 17)
        self.assertEqual(first, score.cluster_intervals(values, 500, 17))
        self.assertEqual(first["x"], {"low": 0.0, "high": 1.0})


class VisibleParserTests(unittest.TestCase):
    def test_minor_units_percentages_and_arabic_digits(self):
        self.assertEqual(baseline_heuristics.parse_value("unit_price_minor", "1.01", "po"), "101")
        self.assertEqual(baseline_heuristics.parse_value("stated_net_minor", "١٢٣٫٤٥", "invoice"), "12345")
        self.assertEqual(baseline_heuristics.parse_value("discount_bps", "٢٫٥٠%", "po"), "250")
        self.assertEqual(baseline_heuristics.parse_value("date", "٢٠٢٦-٠١-١٥", "invoice"), "2026-01-15")
        self.assertEqual(baseline_heuristics.parse_value("status", "ملغى", "po"), "canceled")
        self.assertEqual(baseline_heuristics.parse_value("status", "ملغى", "history"), "void")
        for literal in ("1", "1.000", "-1.00", "USD 1.00", "1.00%"):
            with self.assertRaises(ValueError):
                baseline_heuristics.parse_value("unit_price_minor", literal, "invoice")

    def test_reordered_visible_header_does_not_inherit_last_row(self):
        document = {"doc_id": "D03", "title": "Supplier invoice", "text": "\n".join([
            "Record R01", "[D03.F09] Line discount: 2.50%", "[D03.F08] Unit price in currency units: 1.01",
            "[D03.F07] Quantity in base units: 10", "[D03.F06] Item code: ITEM-A", "[D03.F05] Stated net total: 9.85",
            "[D03.F04] Currency: SAR", "[D03.F03] Gregorian date: 2026-01-15", "[D03.F02] Purchase order ID: PO-A",
            "[D03.F01] Invoice ID: INV-A"])}
        parsed = baseline_heuristics.parse_visible("Reconcile this fictional packet", [document])
        headers = {value["key"]: value["value"] for value in parsed[0]["fields"] if not value["row_id"]}
        row = {value["key"]: value["value"] for value in parsed[0]["fields"] if value["row_id"] == "R01"}
        self.assertEqual(headers, {"stated_net_minor": "985", "currency": "SAR", "date": "2026-01-15", "order_id": "PO-A", "invoice_id": "INV-A"})
        self.assertEqual(row, {"discount_bps": "250", "unit_price_minor": "101", "quantity_units": "10", "sku": "ITEM-A"})
        corrupted = copy.deepcopy(document)
        corrupted["text"] = corrupted["text"].replace("Line discount", "Unrecognized discount")
        with self.assertRaises(ValueError):
            baseline_heuristics.parse_visible("Reconcile", [corrupted])
        leaked = {**document, "role": "invoice"}
        with self.assertRaises(ValueError):
            baseline_heuristics.parse_visible("Reconcile", [leaked])


def release_fixture(folder):
    """A tiny physical release, authored independently of generator.py."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    folder = Path(folder)
    for name in ("specs", "data/cases", "data/pairs"):
        (folder / name).mkdir(parents=True)
    base = fixture()
    critical = copy.deepcopy(base)
    target = field(critical, "receipts", "quantity", "R1")
    target["value"] = "9"
    edit = {"path": f"documents.D04.fields.{target['id']}.value", "doc_id": "D04", "field_id": target["id"], "before": "10", "after": "9"}
    missing = [item for item in copy.deepcopy(base) if item["role"] != "receipts"]
    worlds = [("clean", base, None), ("critical_edit", critical, edit),
              ("missing_evidence", missing, {"removed_doc_id": "D04", "removed_role": "receipts"})]
    family = hashlib.sha256(b"fixture-family").hexdigest()
    specs, rows, ids = [], [], {}
    translated = {"true": "نعم", "active": "ساري المفعول", "canceled": "ملغى", "approved": "معتمد", "draft": "مسودة",
                  "posted": "مرحّل", "void": "ملغى", "unit": "قطعة", "pack": "عبوة", "invoice_date": "تاريخ الفاتورة شاملاً ذلك اليوم"}
    role_titles = [("أمر الشراء", "Purchase order"), ("فاتورة المورد", "Supplier invoice"), ("سجل استلام البضائع", "Goods receipt register"),
                   ("سجل المرتجعات", "Returns register"), ("سجل الفواتير السابقة", "Prior invoice register"), ("سجل تعديلات الأسعار", "Price amendment register")]
    for world, documents, metadata in worlds:
        gold = verify.compute_gold(documents)
        for view in verify.VIEWS:
            english, reverse = view == "en_control", view == "ar_reordered"
            rendered = []
            for item in (list(reversed(documents)) if reverse else documents):
                groups = {}
                for entry in item["fields"]:
                    groups.setdefault(entry["row_id"], []).append(entry)
                fields = [entry for group in (list(reversed(list(groups.values()))) if reverse else groups.values())
                          for entry in (list(reversed(group)) if reverse else group)]
                lines = []
                for entry in fields:
                    key, value = entry["key"], entry["value"]
                    if key.endswith("_minor"):
                        value = format(int(value) / 100, ".2f")
                    elif key.endswith("_bps"):
                        value = format(int(value) / 100, ".2f") + "%"
                    elif key == "required_roles":
                        value = (", " if english else "، ").join(title[english] for title in role_titles)
                    elif english:
                        value = {"true": "yes", "invoice_date": "invoice date, inclusive"}.get(value, value)
                    else:
                        value = translated.get(value, value)
                    if view == "ar_eastern" and not key.endswith("_id") and key != "sku":
                        value = value.translate(str.maketrans("0123456789.,", "٠١٢٣٤٥٦٧٨٩٫٬"))
                    label = entry["label_en"] if english else entry["label_ar"]
                    lines.append(f"[{entry['id']}] {label}: {value}")
                rendered.append({"doc_id": item["doc_id"], "title": item["title_en"] if english else item["title"], "text": "\n".join(lines)})
            case_id = hashlib.sha256(f"fixture:{world}:{view}".encode()).hexdigest()
            ids[(world, view)] = case_id
            spec = {"case_id": case_id, "family_id": family, "world": world, "view": view,
                    "mechanism": "receipt_quantity", "style": 2, "documents": documents, "gold": gold, "edit": metadata}
            specs.append(spec)
            rows.append({"case_id": case_id, "family_id": family, "world": world, "view": view,
                         "language": "en" if english else "ar", "digit_script": "arabic_indic" if view == "ar_eastern" else "western",
                         "mechanism": "receipt_quantity", "style": 2, "question": "Reconcile the supplied fictional packet.",
                         "documents": rendered, "gold_decision": gold["decision"], "gold_contract_net_minor": gold["contract_net_minor"],
                         "gold_issues": gold["issues"], "gold_evidence_ids": gold["evidence_ids"]})
    case_schema = pa.schema([(key, pa.string()) for key in ("case_id", "family_id", "world", "view", "language", "digit_script", "mechanism")] +
                            [("style", pa.int32()), ("question", pa.string()),
                             ("documents", pa.list_(pa.struct([(key, pa.string()) for key in ("doc_id", "title", "text")]))),
                             ("gold_decision", pa.string()), ("gold_contract_net_minor", pa.int64()),
                             ("gold_issues", pa.list_(pa.string())), ("gold_evidence_ids", pa.list_(pa.string()))])
    pq.write_table(pa.Table.from_pylist(rows, schema=case_schema), folder / "data/cases/test-00000.parquet")
    with gzip.open(folder / "specs/test.jsonl.gz", "wt", encoding="utf-8") as handle:
        for spec in specs:
            handle.write(json.dumps(spec, ensure_ascii=False) + "\n")
    pairs = []
    def pair(a, b, relation, axis, metadata):
        pairs.append({"pair_id": hashlib.sha256((a+b).encode()).hexdigest(), "family_id": family,
                      "case_id_a": a, "case_id_b": b, "relation": relation, "axis": axis, "edit_json": json.dumps(metadata)})
    for world in verify.WORLDS:
        for view, axis in (("ar_eastern", "digit_script"), ("ar_reordered", "document_order"), ("en_control", "language_control")):
            pair(ids[(world, "ar_western")], ids[(world, view)], "invariant", axis, {})
    for world, _, metadata in worlds[1:]:
        for view in verify.VIEWS:
            pair(ids[("clean", view)], ids[(world, view)], "sensitivity", "critical_fact" if world == "critical_edit" else "missing_document", metadata)
    pq.write_table(pa.Table.from_pylist(pairs), folder / "data/pairs/test-00000.parquet")
    return rows


@unittest.skipUnless(importlib.util.find_spec("pyarrow"), "pyarrow required for physical-release tests")
class ReleaseTests(unittest.TestCase):
    def test_complete_release_audit_and_perfect_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            rows = release_fixture(temporary)
            report = verify.audit_release(temporary)
            self.assertEqual((report["cases"], report["families"], report["pairs"]), (12, 1, 17))
            predictions = [{"case_id": row["case_id"], "decision": row["gold_decision"],
                            "contract_net_minor": row["gold_contract_net_minor"], "issues": row["gold_issues"],
                            "evidence_ids": row["gold_evidence_ids"]} for row in rows]
            scored = score.score(temporary, predictions, bootstrap_samples=10)
            self.assertEqual(scored["metrics"]["strict_joint"], 1)
            self.assertEqual(scored["paired_both_joint"]["all"], {"pairs": 17, "rate": 1})
            self.assertEqual(scored["all_view_joint"]["complete_worlds"], 3)
            subset = score.score(temporary, predictions[:4], [row["case_id"] for row in rows[:4]], bootstrap_samples=10)
            self.assertEqual(subset["metrics"]["cases"], 4)
            self.assertEqual(subset["metrics"]["strict_joint"], 1)
            self.assertEqual(subset["paired_both_joint"]["all"]["pairs"], 3)
            self.assertEqual(subset["all_family_joint"]["complete_families"], 0)

    def test_cross_split_sibling_packet_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            release_fixture(folder)
            shutil.copyfile(folder / "specs/test.jsonl.gz", folder / "specs/validation.jsonl.gz")
            shutil.copyfile(folder / "data/cases/test-00000.parquet", folder / "data/cases/validation-00000.parquet")
            with self.assertRaisesRegex(verify.AuditError, "crosses splits"):
                verify.audit_release(folder)

    def test_public_gold_corruption_and_display_corruption_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        for mutation in ("decision", "amount", "missing_reference", "invalid_citation", "visible_value"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                release_fixture(temporary)
                path = Path(temporary) / "data/cases/test-00000.parquet"
                table = pq.read_table(path)
                rows = table.to_pylist()
                if mutation == "decision":
                    rows[0]["gold_decision"] = "mismatch"
                elif mutation == "amount":
                    rows[0]["gold_contract_net_minor"] -= 1
                elif mutation == "missing_reference":
                    rows[0]["gold_evidence_ids"] = rows[0]["gold_evidence_ids"][1:]
                elif mutation == "invalid_citation":
                    rows[0]["gold_evidence_ids"] += ["D99.F99"]
                else:
                    invoice = next(item for item in rows[0]["documents"] if item["doc_id"] == "D03")
                    invoice["text"] = invoice["text"].replace(": 1.01", ": 1.010")
                pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
                with self.assertRaises(verify.AuditError):
                    verify.audit_release(temporary)


if __name__ == "__main__":
    unittest.main()
