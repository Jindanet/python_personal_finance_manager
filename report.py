import os
from datetime import datetime, timedelta, timezone
import constants as c
import codec
import display
import service
import storage


def report_columns(store):
    # ไม่ตัด ID เมื่อมีข้อมูลเกิน 10,000 รายการ
    id_width = max(4, len(str(store["next_id"] - 1)))
    return [("ID", id_width, "right"), ("Date", 10, "left"),
            ("Type", 7, "left"), ("Category", 20, "left"),
            ("Amount", 20, "right"), ("Status", 7, "left")]


def generate_report(store):
    storage.record_operation(store, c.OP_REPORT, True)
    report_path = os.path.join(store["data_dir"], c.REPORT_FILE_NAME)
    temporary_path = report_path + ".tmp"
    try:
        totals = service.summary(store, log_view=False)
        logs = storage.read_logs(store, limit=10)
        thailand = timezone(timedelta(hours=7))
        generated_at = datetime.now(thailand).strftime("%Y-%m-%d %H:%M:%S")
        columns = report_columns(store)
        heading, separator = display.table_heading(columns)
        with open(temporary_path, "w", encoding="utf-8-sig", newline="\n") as report:
            report.write("Income & Expense System - Summary Report\n")
            report.write("Generated At : " + generated_at + " (+07:00)\n")
            report.write("App Version  : " + c.APP_VERSION + "\n")
            report.write("Endianness   : Little-Endian\n")
            report.write("Encoding     : UTF-8 (fixed-length)\n\n")
            report.write(heading + "\n" + separator + "\n")
            # อ่านทีละระเบียน จะได้ไม่เก็บข้อความรายงานทั้งไฟล์ไว้ใน list
            with open(store["data_path"], "rb") as data_file:
                data_file.seek(c.HEADER_SIZE)
                for number in range(totals["total_slots"]):
                    record = codec.unpack_transaction(data_file.read(c.TRANSACTION_SIZE))
                    values = [record["transaction_id"], record["date"],
                              c.TYPE_LABELS[record["type_code"]], record["category"],
                              f'{record["amount"]:,.2f}', c.STATUS_LABELS[record["status"]]]
                    report.write(display.table_row(values, columns) + "\n")
            report.write(separator + "\n\nSummary\n")
            report.write(f'- Total Records     : {totals["total_slots"]}\n')
            report.write(f'- Active Records    : {totals["active_records"]}\n')
            report.write(f'- Deleted Records   : {totals["deleted_records"]}\n')
            report.write(f'- Free Slots        : {totals["free_slots"]}\n')
            report.write("\nFinancial Summary\n")
            report.write(f'- Total Income      : {totals["total_income"]:,.2f} THB\n')
            report.write(f'- Total Expense     : {totals["total_expense"]:,.2f} THB\n')
            report.write(f'- Balance           : {totals["balance"]:,.2f} THB\n')
            report.write("\nRecent Operations\n")
            for log in logs:
                shown_id = str(log["transaction_id"])
                if log["transaction_id"] == 0:
                    shown_id = "-"
                failed = ""
                if log["result"] == 0:
                    failed = " [Failed]"
                label = c.OPERATION_LABELS[log["op_code"]]
                report.write(f"- {label:<7} ID {shown_id}{failed}\n")
            storage.sync_file(report)
        os.replace(temporary_path, report_path)
    except Exception:
        storage.record_operation(store, c.OP_REPORT, False)
        if os.path.isfile(temporary_path):
            os.remove(temporary_path)
        raise
    store["changed_since_report"] = False
    return report_path
