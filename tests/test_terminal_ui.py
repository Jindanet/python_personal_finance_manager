import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
import constants as c
import display
import models
import service
import storage
import terminal
import ui


def interact(action, store, responses):
    output = io.StringIO()
    settings = ui.make_ui(False, False)
    with patch("builtins.input", side_effect=responses) as read, redirect_stdout(output):
        action(store, settings)
    assert read.call_count == len(responses)
    return output.getvalue()


def test_full_menu_workflow():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        responses = [
            "1", "2026-10-02", "1", "1", "25000", "เงินเดือน", "",
            "1", "2026-10-02", "2", "2", "159", "ข้าวเย็น", "",
            "2", "1002", "", "", "", "199", "ข้าวเย็นกับเพื่อน", "",
            "4", "1", "", "2", "1002", "", "3", "2", "", "4", "",
            "5", "อาหาร", "", "6", "2026-10-02", "", "7", "", "8", "", "0",
            "3", "1002", "y", "", "0"]
        output = interact(ui.run_menu, store, responses)
        records = storage.read_all_transactions(store, True)
        assert records[0]["category"] == c.CATEGORIES["1"]
        assert records[1]["category"] == c.CATEGORIES["2"]
        assert records[1]["description"] == "ข้าวเย็นกับเพื่อน"
        assert records[1]["amount"] == 199
        assert records[1]["status"] == c.STATUS_DELETED
        assert service.summary(store, False)["balance"] == 25000
        assert storage.read_logs(store)[-1]["op_code"] == c.OP_EXIT
        assert not store["changed_since_report"]
        with open(os.path.join(directory, c.REPORT_FILE_NAME), encoding="utf-8-sig") as file:
            report_text = file.read()
        assert "อาหาร/เครื่องดื่ม" in report_text
        assert "Deleted" in report_text
        assert "268 Bytes" in output
        assert "+25,000.00" in output
        assert "-199.00" in output
        assert "สร้างรายงานล่าสุดอัตโนมัติ" in output
        assert "\033[" not in output + report_text


def test_blank_update_keeps_fields():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        original = service.add_transaction(store, "2026-10-02", "2", "ค่ารักษา", "ตรวจสุขภาพ", "800")
        interact(ui.update_menu, store, ["1001", "", "", "", "", ""])
        assert storage.get_transaction(store, 1001) == original


def test_delete_cancellation():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        service.add_transaction(store, "2026-10-02", "1", "รายได้", "", "100")
        output = interact(ui.delete_menu, store, ["1001", "n"])
        assert storage.get_transaction(store, 1001)["status"] == c.STATUS_ACTIVE
        assert "ยกเลิกการลบรายการ" in output


def test_custom_category_and_presets():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        interact(ui.add_menu, store, ["2026-10-02", "2", "0", "ค่ารักษา", "1200", ""])
        assert storage.read_all_transactions(store)[0]["category"] == "ค่ารักษา"
        for category in c.CATEGORIES.values():
            assert service.validate_text(category, "Category", c.CATEGORY_BYTES) == category


def test_invalid_input_returns_to_menu():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        output = interact(ui.run_menu, store, ["1", "2026-10-02", "3", "", "0"])
        assert "[ERROR]" in output
        assert "ปิดระบบอย่างปลอดภัย" in output
        assert storage.data_header(store)["total_records"] == 0


def test_file_error_stays_in_view_menu():
    with tempfile.TemporaryDirectory() as directory:
        store = storage.open_storage(directory)
        with patch("service.view_all", side_effect=OSError("read failed")):
            output = interact(ui.view_menu, store, ["1", "", "0"])
        assert "[ERROR] read failed" in output


def test_redirected_output_has_no_color():
    output = io.StringIO()
    with redirect_stdout(output):
        settings = ui.make_ui()
        ui.print_title("MAIN MENU (เมนูหลัก)", settings)
    assert not settings["use_color"]
    assert not settings["clear_screen"]
    assert "\033[" not in output.getvalue()


def test_table_width_and_amounts():
    records = [models.make_transaction(1001, "2026-10-02", 1, "เงินเดือน/รายได้", "รายได้ประจำเดือน", 25000),
               models.make_transaction(4294967295, "2026-10-02", 2, "สาธารณูปโภค/ค่าบ้าน", "ค่าไฟฟ้า", c.MAX_AMOUNT, 0)]
    for width in (100, 80, 66, 40, 20):
        plain = display.terminal_transaction_table(records, width, False)
        colored = display.terminal_transaction_table(records, width, True)
        assert re.sub(r"\x1b\[[0-9;]*m", "", colored) == plain
        assert terminal.GREEN in colored and terminal.RED in colored
        assert "4294967295" in plain
        assert "-999,999,999,999.99" in plain
        assert "ค่าไฟฟ้า" in plain
        for line in plain.splitlines():
            assert display.display_width(line) <= width, line


def test_thai_character_width():
    assert display.display_width("กิน") == 2
    assert display.display_width("ข้าว") == 3


def test_windows_console_enables_ansi_and_keeps_existing_mode():
    console = Mock()
    # ใช้ handle ที่ใหญ่กว่า 32 bits เพื่อป้องกันการตั้งชนิด HANDLE ผิด
    console.GetStdHandle.return_value = 0x123456789

    def read_mode(handle, mode):
        mode._obj.value = 2  # ENABLE_WRAP_AT_EOL_OUTPUT ที่มีอยู่เดิม
        return 1

    console.GetConsoleMode.side_effect = read_mode
    console.SetConsoleMode.return_value = 1
    with patch("ctypes.WinDLL", return_value=console, create=True):
        assert terminal.enable_windows_ansi()
    console.GetStdHandle.assert_called_once_with(-11)
    console.SetConsoleMode.assert_called_once_with(0x123456789, 7)
    import ctypes
    from ctypes import wintypes
    assert console.GetStdHandle.restype is wintypes.HANDLE
    assert console.GetConsoleMode.argtypes == [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


def test_windows_color_without_terminal_environment_flags():
    with patch.dict(os.environ, {}, clear=True), patch("terminal.os.name", "nt"), \
            patch("terminal.sys.stdout.isatty", return_value=True), \
            patch("terminal.enable_windows_ansi", return_value=True) as enable:
        settings = ui.make_ui()
        assert settings["use_color"]
        enable.assert_called_once()
        os.environ["NO_COLOR"] = "1"
        assert not ui.make_ui()["use_color"]
        os.environ["TERM"] = "dumb"
        assert not terminal.supports_ansi()


def test_windows_console_failure_and_redirected_output():
    console = Mock()
    console.GetConsoleMode.return_value = 0
    with patch("ctypes.WinDLL", return_value=console, create=True):
        assert not terminal.enable_windows_ansi()
    console.SetConsoleMode.assert_not_called()
    with patch("ctypes.WinDLL", side_effect=OSError("no console"), create=True):
        assert not terminal.enable_windows_ansi()
    with patch.dict(os.environ, {}, clear=True), patch("terminal.os.name", "nt"), \
            patch("terminal.sys.stdout.isatty", return_value=True), \
            patch("terminal.enable_windows_ansi", return_value=False):
        assert not terminal.supports_ansi()
    with patch("terminal.sys.stdout.isatty", return_value=False), \
            patch("terminal.enable_windows_ansi") as enable:
        assert not terminal.supports_ansi()
        enable.assert_not_called()


def load_tests(loader, tests, pattern):
    functions = [test_full_menu_workflow, test_blank_update_keeps_fields, test_delete_cancellation,
                 test_custom_category_and_presets, test_invalid_input_returns_to_menu,
                 test_file_error_stays_in_view_menu, test_redirected_output_has_no_color,
                 test_table_width_and_amounts, test_thai_character_width,
                 test_windows_console_enables_ansi_and_keeps_existing_mode,
                 test_windows_color_without_terminal_environment_flags,
                 test_windows_console_failure_and_redirected_output]
    suite = unittest.TestSuite()
    for function in functions:
        suite.addTest(unittest.FunctionTestCase(function))
    return suite


if __name__ == "__main__":
    unittest.main()
