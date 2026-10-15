#!/usr/bin/env python3
"""Run the portable semantic/mutation tests and save JSON + JUnit evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import unittest
import xml.etree.ElementTree as ET


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(root))
    test_ids = list(flatten(suite))
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    elapsed = time.monotonic() - started
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(), "tests_run": result.testsRun,
               "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
               "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
               "successful": result.wasSuccessful(), "elapsed_seconds": elapsed, "test_ids": test_ids,
               "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in [root / "test_verify_score.py"] + [root.parent / name for name in
                                   ("verify.py", "score.py", "baseline_heuristics.py")]}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "test-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    xml = ET.Element("testsuite", name="Arabic reconciliation independent semantic and mutation tests",
                     tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)),
                     skipped=str(len(result.skipped)), time=str(elapsed))
    outcomes = {test.id(): (kind, message) for kind, records in
                (("failure", result.failures), ("error", result.errors), ("skipped", result.skipped)) for test, message in records}
    for test_id in test_ids:
        case = ET.SubElement(xml, "testcase", classname=test_id.rsplit(".", 1)[0], name=test_id.rsplit(".", 1)[1])
        if test_id in outcomes:
            kind, message = outcomes[test_id]
            ET.SubElement(case, kind).text = message
    ET.ElementTree(xml).write(args.output / "tests.junit.xml", encoding="utf-8", xml_declaration=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
