import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import constants as c
import service
import storage
import stress_test
from tests import stress_lab as lab
from tests.test_finance_app import expect_error


def run_scenario(root, config):
    lab.save_json(os.path.join(root, "run.json"), {"kind": lab.RUN_MARKER, "config": config})
    with redirect_stdout(io.StringIO()):
        code = lab.execute(root, config)
    with open(os.path.join(root, "results.json"), encoding="utf-8") as file:
        return code, json.load(file)


def test_count_presets_and_options():
    for text, expected in (("10k+", 10000), ("100K", 100000), ("1m", 1000000),
                           ("1.5m", 1500000), ("1,000", 1000)):
        assert stress_test.parse_count(text) == expected
    assert stress_test.parse_sizes("1k,10k,1k") == [1000, 10000]
    for text in ("0", "-1", "0.2", "nan", "inf", "2147483647", "abc"):
        expect_error(ValueError, stress_test.parse_count, (text,))
    options = stress_test.read_options(["--scenario", "dataset", "--count", "100k", "--timeout", "0"])
    assert options["count"] == 100000 and options["timeout"] == 0
    expect_error(ValueError, stress_test.read_options, (["--count"],))
    expect_error(ValueError, stress_test.read_options, (["--samples", "0"],))


def test_unmarked_directory_is_protected():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "transactions.dat")
        with open(path, "wb") as file:
            file.write(b"user data")
        expect_error(FileNotFoundError, lab.execute, (root, lab.make_config("insert", count=10)))
        with open(path, "rb") as file:
            assert file.read() == b"user data"


def test_insert_and_durability():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("insert", count=3, timeout=30))
        assert code == 0, result["error"]
        assert result["status"] == "PASS"
        store = storage.open_storage(os.path.join(root, "datasets", "insert"))
        totals = service.summary(store, False)
        expected_income = lab.sample_record(0, 42)["amount"] + lab.sample_record(2, 42)["amount"]
        assert round(totals["total_income"], 2) == round(expected_income, 2)
        for item in result["files"]:
            assert item.get("length_matches_header", True)


def test_dataset_crud_and_slot_reuse():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("dataset", count=32, timeout=30, mutations=2))
        assert code == 0, result["error"]
        store = storage.open_storage(os.path.join(root, "datasets", "dataset"))
        assert storage.data_header(store)["total_records"] == 32
        assert storage.data_header(store)["active_records"] == 32
        assert store["next_id"] == 1035
        assert storage.free_slot_count(store) == 0
        for item in result["checks"]:
            assert item["passed"], item["name"]


def test_mixed_operations_match_expected():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("mixed", count=40, timeout=30))
        assert code == 0, result["error"]
        counts = result["operation_counts"]
        assert sum(counts.values()) == 40
        assert counts["delete"] > 0 and counts["update"] > 0


def test_validation_boundaries():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("validation", timeout=30))
        assert code == 0, result["error"]
        assert len(result["checks"]) >= 25


def test_corruption_and_recovery():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("corruption", count=12, timeout=30))
        assert code == 0, result["error"]
        assert os.path.isfile(os.path.join(root, "datasets", "partial-data", c.DATA_FILE_NAME))
        assert os.path.isfile(os.path.join(root, "datasets", "missing-index", c.INDEX_FILE_NAME))


def test_timeout_is_not_pass():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("insert", count=10000, timeout=0.000001))
        assert code == 2 and result["status"] == "TIMEOUT"
        assert os.path.isfile(os.path.join(root, "metrics.csv"))


def clipped_report(store):
    path = os.path.join(store["data_dir"], c.REPORT_FILE_NAME)
    with open(path, "w", encoding="utf-8-sig") as file:
        file.write("ID | Date\n100… | 2026-10-02\n")
    return path


def test_report_checker_detects_truncated_id():
    with tempfile.TemporaryDirectory() as root:
        with patch("report.generate_report", clipped_report):
            code, result = run_scenario(root, lab.make_config("report", count=1, timeout=30))
        assert code == 1 and result["status"] == "FAIL"
        assert "expected ID 1001" in result["error"]
        assert os.path.isfile(os.path.join(root, "failure.txt"))


def test_report_large_ids_are_complete():
    # เริ่ม fixture ที่ ID 1001; 9,002 แถวจะมี ID 10000 และ 10001
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("report", count=9002, timeout=30))
        assert code == 0, result["error"]
        path = os.path.join(root, "datasets", "report", c.REPORT_FILE_NAME)
        with open(path, encoding="utf-8-sig") as file:
            content = file.read()
        assert "10001 |" in content and "100…" not in content


def test_scale_separate_datasets():
    with tempfile.TemporaryDirectory() as root:
        code, result = run_scenario(root, lab.make_config("scale", sizes=[3, 12], timeout=30))
        assert code == 0, result["error"]
        for count in (3, 12):
            store = storage.open_storage(os.path.join(root, "datasets", "scale-" + str(count)))
            assert storage.data_header(store)["total_records"] == count
        names = []
        for metric in result["metrics"]:
            names.append(metric["name"])
        assert "3: indexed ID lookup via service" in names
        assert "12: indexed ID lookup via service" in names


def test_cancel_is_not_pass():
    with tempfile.TemporaryDirectory() as root:
        with patch("service.add_transaction", side_effect=KeyboardInterrupt):
            code, result = run_scenario(root, lab.make_config("insert", count=10, timeout=30))
        assert code == 2 and result["status"] == "CANCELLED"
        assert result["metrics"][0]["status"] == "INTERRUPTED"
        assert result["metrics"][0]["completed"] == 0


def test_launch_always_creates_new_directory():
    with tempfile.TemporaryDirectory() as root:
        config = lab.make_config("validation", timeout=30)
        with redirect_stdout(io.StringIO()):
            first_code, first_path, first_result = stress_test.launch(config, root)
            second_code, second_path, second_result = stress_test.launch(config, root)
        assert first_code == 0 and second_code == 0
        assert first_path != second_path


def load_tests(loader, tests, pattern):
    functions = [test_count_presets_and_options, test_unmarked_directory_is_protected,
                 test_insert_and_durability, test_dataset_crud_and_slot_reuse,
                 test_mixed_operations_match_expected, test_validation_boundaries,
                 test_corruption_and_recovery, test_timeout_is_not_pass,
                 test_report_checker_detects_truncated_id, test_report_large_ids_are_complete,
                 test_scale_separate_datasets, test_cancel_is_not_pass,
                 test_launch_always_creates_new_directory]
    suite = unittest.TestSuite()
    for function in functions:
        suite.addTest(unittest.FunctionTestCase(function))
    return suite


if __name__ == "__main__":
    unittest.main()
