import os
import tempfile
import unittest
import codec
import constants as c
import report
import service
import storage


def expect_error(error_type, function, parameters):
    try:
        function(*parameters)
    except error_type:
        return
    raise AssertionError("Expected " + error_type.__name__)


def test_thai_text():
    original = "ข้าวเย็นกับเพื่อน"
    packed = codec.pack_text(original, 180)
    assert len(packed) == 180
    assert codec.unpack_text(packed) == original
    assert codec.unpack_text(codec.pack_text("ก" * 20, 10)) == "ก" * 3


def test_record_sizes():
    assert c.HEADER_SIZE == 36
    assert c.TRANSACTION_SIZE == 268
    assert c.INDEX_SIZE == 12
    assert c.LOG_SIZE == 32


def test_crud_and_slot_reuse():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        first = service.add_transaction(store, "2026-09-13", "2", "อาหาร", "ข้าวเย็น", "159")
        second = service.add_transaction(store, "2026-09-13", "1", "ขายสินค้า", "ยอดขายออนไลน์", "1500")
        assert (first["transaction_id"], second["transaction_id"]) == (1001, 1002)
        assert storage.get_transaction(store, 1001) == first
        updated = service.update_transaction(store, 1001, description="ข้าวเย็นกับเพื่อน", amount="199")
        assert updated["description"] == "ข้าวเย็นกับเพื่อน"
        assert storage.get_transaction(store, 1001)["amount"] == 199
        service.delete_transaction(store, 1001)
        header = storage.data_header(store)
        assert header["total_records"] == 2
        assert header["deleted_records"] == 1
        expect_error(LookupError, storage.get_transaction, (store, 1001))
        replacement = service.add_transaction(store, "2026-09-13", "2", "ค่าเดินทาง", "เติมน้ำมัน", "800")
        assert replacement["transaction_id"] == 1003
        assert storage.data_header(store)["total_records"] == 2
        assert storage.free_slot_count(store) == 0
        expect_error(LookupError, storage.get_transaction, (store, 1001, True))
        totals = service.summary(store, log_view=False)
        assert totals["total_income"] == 1500
        assert totals["total_expense"] == 800
        assert totals["balance"] == 700


def test_file_lengths_and_logs():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-09-13", "1", "เงินเดือน", "รายได้ประจำ", "25000")
        assert os.path.getsize(store["data_path"]) == 36 + 268
        assert os.path.getsize(store["index_path"]) == 36 + 12
        assert os.path.getsize(store["log_path"]) == 36 + 32
        log = storage.read_logs(store)[0]
        assert log["op_code"] == c.OP_ADD
        assert log["transaction_id"] == 1001
        assert log["amount_after"] == 25000


def test_fifty_records():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        for number in range(50):
            type_value = "1"
            if number % 2 == 1:
                type_value = "2"
            service.add_transaction(store, "2026-09-13", type_value, "ทดสอบ",
                                    f"รายการที่ {number + 1}", str(number + 1))
        assert storage.data_header(store)["total_records"] == 50
        assert len(storage.read_all_transactions(store)) == 50
        assert os.path.getsize(store["data_path"]) == 36 + 50 * 268
        reopened = storage.open_storage(directory)
        assert storage.get_transaction(reopened, 1050)["amount"] == 50


def test_filters_and_summary():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-10-01", "1", "รายรับ", "", "100.01")
        service.add_transaction(store, "2026-10-02", "2", "อาหาร/เครื่องดื่ม", "", "30.02")
        service.add_transaction(store, "2026-10-01", "2", "เดินทาง", "", "10.03")
        assert len(service.filter_by_type(store, "2")) == 2
        assert service.filter_by_category(store, "อาหาร")[0]["transaction_id"] == 1002
        assert len(service.filter_by_date(store, "2026-10-01")) == 2
        assert service.summary(store, False)["balance"] == 59.96


def test_report_and_thai_data():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-09-13", "2", "ค่าเดินทาง", "รถโดยสาร", "80")
        path = report.generate_report(store)
        with open(path, encoding="utf-8-sig") as file:
            content = file.read()
        assert "ค่าเดินทาง" in content
        assert "Income & Expense System - Summary Report" in content
        assert "Encoding     : UTF-8 (fixed-length)" in content
        assert "80.00 THB" in content
        assert not store["changed_since_report"]
        assert storage.read_logs(store)[-1]["op_code"] == c.OP_REPORT


def test_index_recovery():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-09-13", "1", "รายรับ", "ทดสอบดัชนี", "100")
        with open(store["index_path"], "wb") as file:
            file.write(b"broken index")
        reopened = storage.open_storage(directory)
        assert storage.get_transaction(reopened, 1001)["description"] == "ทดสอบดัชนี"
        os.remove(reopened["index_path"])
        reopened = storage.open_storage(directory)
        assert storage.index_matches_data(reopened)


def test_partial_data_is_not_overwritten():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-09-13", "2", "อาหาร", "ไฟล์เสีย", "50")
        with open(store["data_path"], "ab") as file:
            file.write(b"X")
        with open(store["data_path"], "rb") as file:
            damaged = file.read()
        expect_error(ValueError, storage.open_storage, (directory,))
        with open(store["data_path"], "rb") as file:
            assert file.read() == damaged


def test_invalid_inputs_leave_data_unchanged():
    invalid = [("2026-02-30", "2", "อาหาร", "", "100"),
               ("2026-09-13", "2", "อาหาร", "", "NaN"),
               ("2026-09-13", "2", "อาหาร", "", "0.001"),
               ("2026-09-13", "2", "ก" * 21, "", "100"),
               ("2026-09-13", "2", "อาหาร\x00ซ่อน", "", "100")]
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        for values in invalid:
            expect_error(ValueError, service.add_transaction, (store,) + values)
        assert storage.data_header(store)["total_records"] == 0
        assert storage.log_header(store)["total_records"] == 0


def test_multiple_free_slots():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        for number in range(4):
            service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "1")
        service.delete_transaction(store, 1002)
        service.delete_transaction(store, 1004)
        assert storage.free_slot_count(store) == 2
        store = storage.open_storage(directory)
        fifth = service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "2")
        sixth = service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "3")
        assert (fifth["transaction_id"], sixth["transaction_id"]) == (1005, 1006)
        assert storage.data_header(store)["total_records"] == 4
        assert storage.free_slot_count(store) == 0
        assert storage.index_matches_data(store)


def test_failed_lookup_does_not_change_next_id():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "1")
        expect_error(LookupError, service.view_by_id, (store, "4294967295"))
        store = storage.open_storage(directory)
        record = service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "1")
        assert record["transaction_id"] == 1002


def test_deleted_id_not_reused_after_restart():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "1")
        service.delete_transaction(store, 1001)
        store = storage.open_storage(directory)
        second = service.add_transaction(store, "2026-10-04", "1", "รายรับ", "", "2")
        assert second["transaction_id"] == 1002
        assert storage.data_header(store)["total_records"] == 1


def test_invalid_update_preserves_original_record():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        original = service.add_transaction(store, "2026-10-04", "1", "รายรับ", "เดิม", "1")
        try:
            service.update_transaction(store, 1001, description="ใหม่", amount="-1")
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid update was accepted")
        assert storage.get_transaction(store, 1001) == original


def load_tests(loader, tests, pattern):
    functions = [test_thai_text, test_record_sizes, test_crud_and_slot_reuse,
                 test_file_lengths_and_logs, test_fifty_records, test_filters_and_summary,
                 test_report_and_thai_data, test_index_recovery, test_partial_data_is_not_overwritten,
                 test_invalid_inputs_leave_data_unchanged, test_multiple_free_slots,
                 test_failed_lookup_does_not_change_next_id, test_deleted_id_not_reused_after_restart,
                 test_invalid_update_preserves_original_record]
    suite = unittest.TestSuite()
    for function in functions:
        suite.addTest(unittest.FunctionTestCase(function))
    return suite


if __name__ == "__main__":
    unittest.main()
