import csv
import hashlib
import io
import json
import os
import random
import shutil
import time
import traceback
import unittest
from datetime import date, datetime, timedelta
import constants as c
import codec
import models
import report
import service
import storage

RUN_MARKER = "personal-finance-test-run-v2"
SCENARIOS = {
    "unit": "ชุดทดสอบอัตโนมัติทั้งหมด (รวม UI)",
    "insert": "เพิ่มข้อมูลผ่านโปรแกรมจริง",
    "dataset": "เตรียมข้อมูลใหญ่ แล้วทดสอบอ่าน/ค้นหา/กรอง/แก้ไข/ลบ",
    "mixed": "สุ่มเพิ่ม/แก้ไข/ลบ/ค้นหา เทียบกับข้อมูลคาดหวัง",
    "validation": "ข้อมูลผิดรูปแบบและขอบเขตข้อความ/จำนวนเงิน",
    "corruption": "ดัชนีเสีย/สูญหาย และตรวจจับไฟล์ข้อมูลเสีย",
    "report": "สร้างรายงาน ตรวจจำนวนแถว/ID/ยอดเงิน",
    "scale": "เปรียบเทียบความเร็วหลายขนาดข้อมูล",
}


class CheckFailure(Exception):
    pass


class DeadlineExceeded(Exception):
    pass


def make_config(scenario, count=1000, seed=42, timeout=None, samples=3,
                mutations=2, sizes=None):
    if scenario not in SCENARIOS:
        raise ValueError("ไม่รู้จักชุดทดสอบ: " + str(scenario))
    if timeout is None:
        timeout = 300
        if scenario in ("insert", "mixed"):
            timeout = 60
    if sizes is None:
        sizes = [1000, 10000, 100000, 1000000]
    if count < 1 or samples < 1 or mutations < 0 or timeout < 0:
        raise ValueError("จำนวนต้องมากกว่า 0 และเวลา/จำนวนแก้ไขต้องไม่ติดลบ")
    return {"scenario": scenario, "count": count, "seed": seed, "timeout": timeout,
            "samples": samples, "mutations": mutations, "sizes": list(sizes)}


def save_json(path, value):
    temporary_path = str(path) + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, path)


def make_run(root, config):
    root = os.path.abspath(root)
    with open(os.path.join(root, "run.json"), encoding="utf-8") as file:
        marker = json.load(file)
    if marker.get("kind") != RUN_MARKER or marker.get("config") != config:
        raise ValueError("Folder นี้ไม่ได้เป็นของรอบทดสอบที่กำหนด")
    result = {"status": "RUNNING", "started_at": str(datetime.now()),
              "config": config, "run_dir": root, "metrics": [], "checks": [],
              "current_phase": None}
    run = {"root": root, "config": config, "started": time.perf_counter(),
           "next_progress": 0, "result": result}
    checkpoint(run)
    return run


def checkpoint(run):
    run["result"]["elapsed_seconds"] = round(time.perf_counter() - run["started"], 6)
    save_json(os.path.join(run["root"], "results.json"), run["result"])


def check_deadline(run):
    timeout = run["config"]["timeout"]
    if timeout and time.perf_counter() - run["started"] >= timeout:
        raise DeadlineExceeded(f"ถึงเวลาที่กำหนด {timeout:g} วินาที")


def begin_step(run, name, target=1):
    check_deadline(run)
    print(f"\n[RUN] {name} ({target:,})", flush=True)
    run["result"]["current_phase"] = {
        "name": name, "target": target, "completed": 0, "status": "RUNNING",
        "started_elapsed_seconds": time.perf_counter() - run["started"]}
    checkpoint(run)


def progress(run, completed):
    run["result"]["current_phase"]["completed"] = completed
    check_deadline(run)
    now = time.perf_counter()
    if now >= run["next_progress"]:
        phase = run["result"]["current_phase"]
        print(f'  {phase["name"]}: {completed:,}/{phase["target"]:,}', flush=True)
        checkpoint(run)
        run["next_progress"] = now + 5


def end_step(run, completed=None, status="PASS"):
    phase = run["result"]["current_phase"]
    if completed is None:
        completed = phase["target"]
    phase["completed"] = completed
    phase["status"] = status
    seconds = time.perf_counter() - run["started"] - phase["started_elapsed_seconds"]
    phase["seconds"] = round(seconds, 6)
    phase["units_per_second"] = 0
    if seconds > 0:
        phase["units_per_second"] = round(completed / seconds, 3)
    run["result"]["metrics"].append(phase)
    run["result"]["current_phase"] = None
    checkpoint(run)
    if status == "PASS":
        check_deadline(run)


def check(run, name, passed, detail=""):
    run["result"]["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        raise CheckFailure(name + ": " + detail)


def dataset_directory(run, name):
    path = os.path.abspath(os.path.join(run["root"], "datasets", name))
    if os.path.commonpath([run["root"], path]) != run["root"] or path == run["root"]:
        raise ValueError("ข้อมูลทดสอบต้องอยู่ใน folder ของรอบนี้")
    os.makedirs(path, exist_ok=False)
    return path


def sample_numbers(count, samples, seed):
    # ตรวจต้นไฟล์ กลางไฟล์ ท้ายไฟล์ แล้วค่อยสุ่มตำแหน่งเพิ่ม
    numbers = []
    for number in (0, count // 2, count - 1):
        if number not in numbers:
            numbers.append(number)
    generator = random.Random(seed)
    while len(numbers) < min(count, samples):
        number = generator.randrange(count)
        if number not in numbers:
            numbers.append(number)
    return numbers


def sample_record(number, seed):
    categories = ["เงินเดือน", "อาหาร", "ค่าเดินทาง", "ขายสินค้า"]
    record_date = str(date(2026, 1, 1) + timedelta(days=number % 365))
    type_code = c.TYPE_INCOME
    if number % 2 == 1:
        type_code = c.TYPE_EXPENSE
    satang = (number * 37 + seed * 101) % 1000000 + 1
    return models.make_transaction(c.FIRST_TRANSACTION_ID + number, record_date,
        type_code, categories[number % 4], f"ข้อมูลทดสอบลำดับที่ {number + 1}", satang / 100)


def track(totals, record, direction=1):
    key = "income_satang"
    if record["type_code"] == c.TYPE_EXPENSE:
        key = "expense_satang"
    totals[key] += direction * round(record["amount"] * 100)


def make_fixture(run, directory, count, label="fixture"):
    begin_step(run, label + ": write binary fixture", count)
    totals = {"income_satang": 0, "expense_satang": 0}
    data_path = os.path.join(directory, c.DATA_FILE_NAME)
    index_path = os.path.join(directory, c.INDEX_FILE_NAME)
    log_path = os.path.join(directory, c.LOG_FILE_NAME)
    data_header = models.make_header(c.DATA_MAGIC, c.TRANSACTION_SIZE, count, count)
    index_header = models.make_header(c.INDEX_MAGIC, c.INDEX_SIZE, count, count, aux=0)
    log_header = models.make_header(c.LOG_MAGIC, c.LOG_SIZE, count, count, aux=count + 1)
    with open(data_path, "xb") as data_file, open(index_path, "xb") as index_file, open(log_path, "xb") as log_file:
        data_file.write(codec.pack_header(data_header))
        index_file.write(codec.pack_header(index_header))
        log_file.write(codec.pack_header(log_header))
        for number in range(count):
            record = sample_record(number, run["config"]["seed"])
            data_file.write(codec.pack_transaction(record))
            index_file.write(codec.pack_index(models.make_index(record["transaction_id"], number, 1)))
            log = models.make_log(number + 1, int(time.time()), c.OP_ADD,
                record["transaction_id"], 1, record["type_code"], 1, record["amount"])
            log_file.write(codec.pack_log(log))
            track(totals, record)
            if (number + 1) % 1000 == 0 or number + 1 == count:
                progress(run, number + 1)
        storage.sync_file(data_file)
        storage.sync_file(index_file)
        storage.sync_file(log_file)
    end_step(run)
    return totals


def check_files(run, store, slots):
    for key, record_size, expected_count in (
        ("data_path", c.TRANSACTION_SIZE, slots), ("index_path", c.INDEX_SIZE, slots),
        ("log_path", c.LOG_SIZE, storage.log_header(store)["total_records"])):
        expected_size = c.HEADER_SIZE + expected_count * record_size
        check(run, key + " length", os.path.getsize(store[key]) == expected_size)
    check(run, "index agrees with data", storage.index_matches_data(store))


def check_summary(run, store, expected, active):
    begin_step(run, "financial summary scan", storage.data_header(store)["total_records"])
    actual = service.summary(store, log_view=False)
    check(run, "active count", actual["active_records"] == active)
    check(run, "income total", round(actual["total_income"] * 100) == expected["income_satang"])
    check(run, "expense total", round(actual["total_expense"] * 100) == expected["expense_satang"])
    balance = expected["income_satang"] - expected["expense_satang"]
    check(run, "balance", round(actual["balance"] * 100) == balance)
    end_step(run)


def reopen(run, directory):
    begin_step(run, "reopen and validate storage")
    store = storage.open_storage(directory)
    end_step(run)
    return store


def lookup_samples(run, store, count, label=""):
    numbers = sample_numbers(count, run["config"]["samples"], run["config"]["seed"])
    begin_step(run, label + "indexed ID lookup via service", len(numbers))
    for number in numbers:
        expected = sample_record(number, run["config"]["seed"])
        actual = service.view_by_id(store, expected["transaction_id"])
        check(run, "lookup ID " + str(expected["transaction_id"]), actual == expected)
        progress(run, numbers.index(number) + 1)
    end_step(run)


def scenario_insert(run):
    count = run["config"]["count"]
    directory = dataset_directory(run, "insert")
    store = storage.open_storage(directory)
    totals = {"income_satang": 0, "expense_satang": 0}
    begin_step(run, "add via program (includes index and log writes)", count)
    for number in range(count):
        expected = sample_record(number, run["config"]["seed"])
        actual = service.add_transaction(store, expected["date"], expected["type_code"],
            expected["category"], expected["description"], expected["amount"])
        check(run, "insert ID " + str(number), actual == expected)
        track(totals, actual)
        progress(run, number + 1)
    end_step(run)
    store = reopen(run, directory)
    check_files(run, store, count)
    check_summary(run, store, totals, count)
    lookup_samples(run, store, count)


def scenario_dataset(run):
    count = run["config"]["count"]
    directory = dataset_directory(run, "dataset")
    totals = make_fixture(run, directory, count)
    store = reopen(run, directory)
    check_files(run, store, count)
    check_summary(run, store, totals, count)
    lookup_samples(run, store, count)
    begin_step(run, "read all records", count)
    records = service.view_all(store)
    check(run, "read count", len(records) == count)
    check(run, "first and last record", records[0] == sample_record(0, run["config"]["seed"])
          and records[-1] == sample_record(count - 1, run["config"]["seed"]))
    del records
    end_step(run)
    begin_step(run, "filter income", count)
    records = service.filter_by_type(store, "1")
    check(run, "income count", len(records) == (count + 1) // 2)
    del records
    end_step(run)
    begin_step(run, "filter category and date", count)
    records = service.filter_by_category(store, "อาหาร")
    check(run, "category count", len(records) == (count + 2) // 4)
    del records
    records = service.filter_by_date(store, "2026-01-01")
    check(run, "date count", len(records) == (count + 364) // 365)
    del records
    end_step(run)
    mutations = min(count, run["config"]["mutations"])
    begin_step(run, "update/delete/add and reuse slots", mutations)
    for number in range(mutations):
        old = sample_record(number, run["config"]["seed"])
        track(totals, old, -1)
        updated = service.update_transaction(store, old["transaction_id"], amount="123.45", description="แก้ไขทดสอบ")
        check(run, "updated persisted", storage.get_transaction(store, old["transaction_id"]) == updated)
        service.delete_transaction(store, old["transaction_id"])
        check(run, "one free slot", storage.free_slot_count(store) == 1)
        replacement = service.add_transaction(store, "2026-10-04", "1", "รายรับ", "ใช้ช่องที่ลบ", "456.78")
        check(run, "next ID after reuse", replacement["transaction_id"] == c.FIRST_TRANSACTION_ID + count + number)
        track(totals, replacement)
        progress(run, number + 1)
    end_step(run)
    store = reopen(run, directory)
    check_files(run, store, count)
    check(run, "no free slots after replacement", storage.free_slot_count(store) == 0)
    check_summary(run, store, totals, count)


def scenario_mixed(run):
    directory = dataset_directory(run, "mixed")
    store = storage.open_storage(directory)
    expected = {}
    generator = random.Random(run["config"]["seed"])
    counts = {"add": 0, "update": 0, "delete": 0, "view": 0}
    run["result"]["operation_counts"] = counts
    begin_step(run, "random operations", run["config"]["count"])
    for number in range(run["config"]["count"]):
        operation = generator.choice(["add", "update", "delete", "view"])
        if not expected:
            operation = "add"
        if operation == "add":
            sample = sample_record(number, run["config"]["seed"])
            record = service.add_transaction(store, sample["date"], sample["type_code"],
                sample["category"], sample["description"], sample["amount"])
            check(run, "sequential add ID", record["transaction_id"] == c.FIRST_TRANSACTION_ID + counts["add"])
            expected[record["transaction_id"]] = record.copy()
        else:
            transaction_id = generator.choice(list(expected))
            if operation == "update":
                record = service.update_transaction(store, transaction_id, amount="99.99", description="สุ่มแก้ไข")
                expected[transaction_id]["amount"] = 99.99
                expected[transaction_id]["description"] = "สุ่มแก้ไข"
                check(run, "update matches expected", record == expected[transaction_id])
            elif operation == "delete":
                service.delete_transaction(store, transaction_id)
                del expected[transaction_id]
            else:
                check(run, "view matches expected", service.view_by_id(store, transaction_id) == expected[transaction_id])
        counts[operation] += 1
        progress(run, number + 1)
    end_step(run)
    store = reopen(run, directory)
    actual = {}
    totals = {"income_satang": 0, "expense_satang": 0}
    for record in storage.read_all_transactions(store):
        actual[record["transaction_id"]] = record
        track(totals, record)
    check(run, "all persisted records match expected", actual == expected)
    check_files(run, store, storage.data_header(store)["total_records"])
    check_summary(run, store, totals, len(expected))


def scenario_validation(run):
    store = storage.open_storage(dataset_directory(run, "validation"))
    # แต่ละ tuple คือวันที่ ประเภท หมวดหมู่ รายละเอียด และจำนวนเงินที่ต้องปฏิเสธ
    invalid = [
        ("2026-02-30", "1", "รายรับ", "", "100"),
        ("invalid", "1", "รายรับ", "", "100"),
        ("2026-10-04", "0", "รายรับ", "", "100"),
        ("2026-10-04", "3", "รายรับ", "", "100"),
        ("2026-10-04", "x", "รายรับ", "", "100"),
        ("2026-10-04", "1", "", "", "100"),
        ("2026-10-04", "1", "ก" * 21, "", "100"),
        ("2026-10-04", "1", "a" * 61, "", "100"),
        ("2026-10-04", "1", "อาหาร\x00ซ่อน", "", "100"),
        ("2026-10-04", "1", "รายรับ", "ก" * 61, "100"),
        ("2026-10-04", "1", "รายรับ", "a" * 181, "100"),
        ("2026-10-04", "1", "รายรับ", "a\x00b", "100")]
    for amount in ("0", "-1", "0.001", "NaN", "inf", "-inf", "abc", "", "1000000000000"):
        invalid.append(("2026-10-04", "1", "รายรับ", "", amount))
    begin_step(run, "validation and boundaries", len(invalid) + 6)
    for number in range(len(invalid)):
        rejected = False
        date_value, type_value, category, description, amount = invalid[number]
        try:
            service.add_transaction(store, date_value, type_value, category, description, amount)
        except ValueError:
            rejected = True
        check(run, "invalid input " + str(number + 1), rejected)
        progress(run, number + 1)
    check(run, "invalid inputs leave data empty", storage.data_header(store)["total_records"] == 0)
    for amount in ("0.01", "1,234.56", str(c.MAX_AMOUNT)):
        record = service.add_transaction(store, "2024-02-29", "1", "ก" * 20, "ก" * 60, amount)
        check(run, "valid amount " + amount, storage.get_transaction(store, record["transaction_id"]) == record)
    rejected = False
    try:
        service.view_by_id(store, "4294967295")
    except LookupError:
        rejected = True
    check(run, "missing ID is rejected", rejected)
    store = storage.open_storage(store["data_dir"])
    record = service.add_transaction(store, "2026-10-04", "2", "อาหาร", "", "1")
    check(run, "failed lookup does not reserve an ID", record["transaction_id"] == 1004)
    end_step(run)


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as file:
        chunk = file.read(1024 * 1024)
        while chunk:
            value.update(chunk)
            chunk = file.read(1024 * 1024)
    return value.hexdigest()


def scenario_corruption(run):
    count = run["config"]["count"]
    source = dataset_directory(run, "original")
    make_fixture(run, source, count)
    begin_step(run, "recover index and reject damaged files", 5)
    for number, name in enumerate(("missing-index", "broken-index", "partial-data", "bad-magic", "partial-log")):
        directory = dataset_directory(run, name)
        for file_name in (c.DATA_FILE_NAME, c.INDEX_FILE_NAME, c.LOG_FILE_NAME):
            shutil.copyfile(os.path.join(source, file_name), os.path.join(directory, file_name))
        if name == "missing-index":
            os.remove(os.path.join(directory, c.INDEX_FILE_NAME))
        elif name == "broken-index":
            with open(os.path.join(directory, c.INDEX_FILE_NAME), "wb") as file:
                file.write(b"broken index")
        else:
            file_name = c.DATA_FILE_NAME
            if name == "partial-log":
                file_name = c.LOG_FILE_NAME
            path = os.path.join(directory, file_name)
            mode = "ab"
            if name == "bad-magic":
                mode = "r+b"
            with open(path, mode) as file:
                file.write(b"X")
            before = digest(path)
        if name in ("missing-index", "broken-index"):
            store = storage.open_storage(directory)
            check(run, name + " recovered", storage.index_matches_data(store))
        else:
            rejected = False
            try:
                storage.open_storage(directory)
            except ValueError:
                rejected = True
            check(run, name + " rejected", rejected)
            check(run, name + " unchanged", digest(path) == before)
        progress(run, number + 1)
    end_step(run)


def scenario_report(run):
    count = run["config"]["count"]
    directory = dataset_directory(run, "report")
    totals = make_fixture(run, directory, count)
    store = reopen(run, directory)
    begin_step(run, "generate report", count)
    path = report.generate_report(store)
    end_step(run)
    begin_step(run, "verify every report ID and totals", count)
    row_count = 0
    expected_income = f'{totals["income_satang"] / 100:,.2f} THB'
    expected_expense = f'{totals["expense_satang"] / 100:,.2f} THB'
    income_found = False
    expense_found = False
    with open(path, encoding="utf-8-sig") as file:
        for line in file:
            if " | " in line and "ID" not in line:
                cells = line.strip().split(" | ")
                expected_id = str(c.FIRST_TRANSACTION_ID + row_count)
                if cells[0].strip() != expected_id:
                    check(run, "report row " + str(row_count + 1), False,
                          "expected ID " + expected_id + ", got " + cells[0].strip())
                row_count += 1
                if row_count % 1000 == 0:
                    progress(run, row_count)
            if line.startswith("- Total Income"):
                income_found = expected_income in line
            if line.startswith("- Total Expense"):
                expense_found = expected_expense in line
    check(run, "report row count", row_count == count)
    check(run, "report income", income_found)
    check(run, "report expense", expense_found)
    end_step(run)


def scenario_scale(run):
    for count in run["config"]["sizes"]:
        directory = dataset_directory(run, "scale-" + str(count))
        totals = make_fixture(run, directory, count, str(count))
        store = reopen(run, directory)
        lookup_samples(run, store, count, str(count) + ": ")
        check_summary(run, store, totals, count)
        check_files(run, store, count)


def scenario_unit(run):
    begin_step(run, "unit tests")
    output = io.StringIO()
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    suite = unittest.defaultTestLoader.discover(os.path.join(project, "tests"), top_level_dir=project)
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    with open(os.path.join(run["root"], "unit_tests.txt"), "w", encoding="utf-8") as file:
        file.write(output.getvalue())
    check(run, "unit tests successful", result.wasSuccessful(), output.getvalue())
    end_step(run, result.testsRun)


def file_inventory(root):
    files = []
    for directory, subdirectories, names in os.walk(root):
        for name in sorted(names):
            extension = os.path.splitext(name)[1]
            if extension not in (".dat", ".idx", ".log", ".txt"):
                continue
            path = os.path.join(directory, name)
            item = {"path": os.path.relpath(path, root), "bytes": os.path.getsize(path)}
            if extension in (".dat", ".idx", ".log"):
                try:
                    with open(path, "rb") as file:
                        header = codec.unpack_header(file.read(c.HEADER_SIZE))
                    item["total"] = header["total_records"]
                    item["record_bytes"] = header["record_size"]
                    item["length_matches_header"] = item["bytes"] == c.HEADER_SIZE + header["total_records"] * header["record_size"]
                except Exception as error:
                    item["header_error"] = str(error)
            files.append(item)
    return files


def write_metrics_csv(root, result):
    with open(os.path.join(root, "metrics.csv"), "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["name", "status", "target", "completed", "seconds", "units_per_second"])
        for metric in result["metrics"]:
            writer.writerow([metric["name"], metric["status"], metric["target"],
                metric["completed"], metric["seconds"], metric["units_per_second"]])


def execute(root, config):
    run = make_run(root, config)
    code = 0
    status = "PASS"
    error_text = ""
    try:
        scenario = config["scenario"]
        if scenario == "unit":
            scenario_unit(run)
        elif scenario == "insert":
            scenario_insert(run)
        elif scenario == "dataset":
            scenario_dataset(run)
        elif scenario == "mixed":
            scenario_mixed(run)
        elif scenario == "validation":
            scenario_validation(run)
        elif scenario == "corruption":
            scenario_corruption(run)
        elif scenario == "report":
            scenario_report(run)
        elif scenario == "scale":
            scenario_scale(run)
    except DeadlineExceeded as error:
        status, code, error_text = "TIMEOUT", 2, str(error)
    except KeyboardInterrupt:
        status, code, error_text = "CANCELLED", 2, "ผู้ใช้หยุดการทดสอบ"
    except Exception as error:
        status, code, error_text = "FAIL", 1, str(error)
        with open(os.path.join(run["root"], "failure.txt"), "w", encoding="utf-8") as file:
            file.write(traceback.format_exc())
    if run["result"]["current_phase"] is not None:
        phase = run["result"]["current_phase"]
        end_step(run, phase["completed"], "INTERRUPTED")
    run["result"]["status"] = status
    run["result"]["error"] = error_text
    run["result"]["finished_at"] = str(datetime.now())
    run["result"]["files"] = file_inventory(run["root"])
    checkpoint(run)
    write_metrics_csv(run["root"], run["result"])
    return code
