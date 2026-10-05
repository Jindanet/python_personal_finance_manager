import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
import constants as c
import display
import report
import service
import storage
import terminal


def make_ui(use_color=None, clear_screen=None):
    ansi = terminal.supports_ansi()
    if use_color is None:
        use_color = ansi and "NO_COLOR" not in os.environ
    if clear_screen is None:
        clear_screen = ansi and sys.stdin.isatty()
    return {"use_color": use_color, "clear_screen": clear_screen}


def screen_width():
    return max(20, min(shutil.get_terminal_size((66, 24)).columns, 66))


def pause(prompt="\nกด Enter เพื่อกลับเมนูหลัก..."):
    input(prompt)


def print_title(title, settings):
    if settings["clear_screen"]:
        print("\033[2J\033[H", end="")
    else:
        print()
    width = screen_width()
    print("=" * width)
    banner = display.fit_cell("INCOME & EXPENSE SYSTEM", width - 2, "center")
    print("|" + terminal.color_text(banner, terminal.BG_GREEN, settings["use_color"], True) + "|")
    print("=" * width)
    print("-" * width)
    title = display.fit_cell(" << " + title + " >>", width)
    print(terminal.color_text(title, terminal.GREEN, settings["use_color"], True))
    print("-" * width)


def message(text, settings, label="SUCCESS", color=terminal.GREEN):
    label = terminal.color_text(label, color, settings["use_color"], True)
    print("\n[" + label + "] " + str(text))


def show_error(error, settings):
    message(str(error), settings, "ERROR", terminal.RED)


def ask_type(settings, default=None):
    print("\nเลือกประเภทธุรกรรม:")
    print(terminal.color_text(" 1) รายรับ (Income)", terminal.GREEN, settings["use_color"]))
    print(terminal.color_text(" 2) รายจ่าย (Expense)", terminal.RED, settings["use_color"]))
    suffix = ""
    if default is not None:
        suffix = f" [{default}; Enter เพื่อคงค่าเดิม]"
    value = input("เลือก (1-2)" + suffix + ": ").strip()
    if value == "" and default is not None:
        return None
    service.validate_type(value)
    return value


def ask_category(default=None):
    print("\nหมวดหมู่รายการ:")
    for number, label in c.CATEGORIES.items():
        print(f" {number}) {label}")
    print(" 0) ระบุหมวดหมู่เอง")
    suffix = ""
    if default is not None:
        suffix = f" [{default}; Enter เพื่อคงค่าเดิม]"
    value = input("เลือกหมวดหมู่ (เลขหรือชื่อ)" + suffix + ": ").strip()
    if value == "" and default is not None:
        return None
    if value == "0":
        category = input("ชื่อหมวดหมู่: ").strip()
        if category == "":
            raise ValueError("กรุณาระบุชื่อหมวดหมู่")
        return category
    if value in c.CATEGORIES:
        return c.CATEGORIES[value]
    if value == "" or value.isdecimal():
        raise ValueError("กรุณาเลือกหมวดหมู่ที่แสดง หรือเลือก 0 เพื่อระบุเอง")
    return value


def show_records(records, settings):
    if not records:
        message("ไม่พบรายการที่ตรงกับเงื่อนไข", settings, "INFO", terminal.YELLOW)
        return
    print(display.terminal_transaction_table(records, screen_width(), settings["use_color"]))
    print(f"\nแสดงทั้งหมด {len(records)} รายการ")


def add_menu(store, settings):
    print_title("ADD TRANSACTION (บันทึกรายรับ-รายจ่าย)", settings)
    print("ระบบจะสร้างรหัสรายการ (ID) ให้อัตโนมัติ")
    default_date = str(date.today())
    date_value = input(f"ป้อนวันที่ (YYYY-MM-DD) [เว้นว่างใช้ {default_date}]: ").strip()
    if date_value == "":
        date_value = default_date
    service.validate_date(date_value)
    time_value = input("ป้อนเวลาที่เกิดรายการ (HH:MM, เว้นว่างใช้เวลาปัจจุบัน): ").strip()
    service.validate_time(time_value)
    type_value = ask_type(settings)
    category = ask_category()
    amount = input("\nป้อนจำนวนเงิน (บาท): ").strip()
    service.validate_amount(amount)
    description = input("บันทึกช่วยจำ (Note, เว้นว่างได้): ").strip()
    record = service.add_transaction(store, date_value, type_value, category,
                                     description, amount, time_value)
    message(f'บันทึกรายการ ID {record["transaction_id"]} สำเร็จ', settings)


def keep_old_value(value):
    if value == "":
        return None
    return value


def update_menu(store, settings):
    print_title("UPDATE TRANSACTION (แก้ไขรายการ)", settings)
    transaction_id = input("ป้อนรหัสรายการที่ต้องการแก้ไข: ").strip()
    current = service.view_by_id(store, transaction_id, include_deleted=False)
    print("\nข้อมูลรายการปัจจุบัน:")
    show_records([current], settings)
    print("\nกด Enter เพื่อคงค่าเดิมในแต่ละช่อง")
    new_date = input(f'วันที่ [{current["date"]}]: ').strip()
    new_time = input(f'เวลา HH:MM [{current["time"] or "ไม่ระบุ"}]: ').strip()
    new_type = ask_type(settings, current["type_code"])
    new_category = ask_category(current["category"])
    new_amount = input(f'ป้อนจำนวนเงินใหม่ (บาท) [{current["amount"]:,.2f}]: ').strip()
    new_description = input(f'ป้อนบันทึกช่วยจำใหม่ [{current["description"]}]: ').strip()
    record = service.update_transaction(store, transaction_id,
        date=keep_old_value(new_date), time_value=keep_old_value(new_time),
        type_value=new_type, category=new_category,
        description=keep_old_value(new_description), amount=keep_old_value(new_amount))
    message(f'แก้ไขรายการ ID {record["transaction_id"]} สำเร็จ', settings)


def delete_menu(store, settings):
    print_title("DELETE TRANSACTION (ลบรายการ)", settings)
    transaction_id = input("ป้อนรหัสรายการที่ต้องการลบ: ").strip()
    current = service.view_by_id(store, transaction_id, include_deleted=False)
    show_records([current], settings)
    confirmation = input(f'\nยืนยันการลบรายการ ID {current["transaction_id"]}? (y/n): ').strip().lower()
    if confirmation not in ("y", "yes", "delete"):
        message("ยกเลิกการลบรายการ", settings, "INFO", terminal.YELLOW)
        return
    record = service.delete_transaction(store, transaction_id)
    message(f'ลบรายการ ID {record["transaction_id"]} สำเร็จ', settings)


def view_id_menu(store, settings):
    print_title("SEARCH BY ID (ค้นหาจากรหัสรายการ)", settings)
    transaction_id = input("\nป้อนรหัสรายการที่ต้องการค้นหา: ").strip()
    record = service.view_by_id(store, transaction_id)
    show_records([record], settings)


def summary_menu(store, settings):
    print_title("FINANCIAL SUMMARY (สรุปการเงิน)", settings)
    totals = service.summary(store)
    print(f'จำนวนรายการในไฟล์  : {totals["total_slots"]}')
    print(f'รายการที่ใช้งาน     : {totals["active_records"]}')
    print(f'รายการที่ลบ         : {totals["deleted_records"]}')
    print(f'ช่องว่างที่ใช้ซ้ำได้ : {totals["free_slots"]}')
    print("-" * screen_width())
    print(terminal.color_text(f'รายรับรวม  : +{totals["total_income"]:,.2f} THB', terminal.GREEN, settings["use_color"]))
    print(terminal.color_text(f'รายจ่ายรวม : -{totals["total_expense"]:,.2f} THB', terminal.RED, settings["use_color"]))
    color = terminal.GREEN
    if totals["balance"] < 0:
        color = terminal.RED
    print(terminal.color_text(f'คงเหลือ    : {totals["balance"]:,.2f} THB', color, settings["use_color"], True))


def file_statistics(store, settings):
    print_title("FILE & BINARY STATISTICS (สถิติไฟล์)", settings)
    totals = service.summary(store)
    print("ชื่อไฟล์ไบนารี                 : " + store["data_path"])
    print(f"ขนาดต่อระเบียน (Record Size)   : {c.TRANSACTION_SIZE} Bytes")
    print(f'จำนวน Record ทั้งหมดในดิสก์    : {totals["total_slots"]}')
    print(f'จำนวน Record ที่ใช้งาน (Active): {totals["active_records"]}')
    print(f'จำนวน Record ที่ถูกลบ          : {totals["deleted_records"]}')
    print(f'ช่องว่างที่ใช้ซ้ำได้ (Free-list): {totals["free_slots"]}')


def view_log_menu(store, settings):
    print_title("OPERATION LOG (ประวัติการทำงาน)", settings)
    value = input("จำนวนรายการล่าสุด [Enter = 20, 0 = ทั้งหมด]: ").strip()
    if value == "":
        limit = 20
    elif value.isdecimal():
        limit = int(value)
    else:
        raise ValueError("กรุณาใส่จำนวนเต็มตั้งแต่ 0 ขึ้นไป")
    records = storage.read_logs(store, None if limit == 0 else limit)
    if not records:
        message("ยังไม่มีประวัติการทำงาน", settings, "INFO", terminal.YELLOW)
        return
    columns = [("Seq", 8, "right"), ("Time (+07)", 19, "left"),
               ("Action", 6, "left"), ("ID", 10, "right"), ("Result", 7, "left")]
    heading, separator = display.table_heading(columns)
    print(heading)
    print(separator)
    local_time = timezone(timedelta(hours=7))
    for record in reversed(records):
        timestamp = datetime.fromtimestamp(record["timestamp"], local_time).strftime("%Y-%m-%d %H:%M:%S")
        operation = c.OPERATION_LABELS.get(record["op_code"], str(record["op_code"]))
        transaction_id = record["transaction_id"] or "-"
        result = "SUCCESS" if record["result"] else "FAIL"
        print(display.table_row((record["log_seq"], timestamp, operation,
                                 transaction_id, result), columns))
        if record["type_after"]:
            type_name = c.TYPE_LABELS.get(record["type_after"], str(record["type_after"]))
            status_name = c.STATUS_LABELS.get(record["status_after"], str(record["status_after"]))
            print(f'    หลังทำรายการ: {type_name}, {status_name}, {record["amount_after"]:,.2f} THB')
    print(f"\nแสดงล่าสุด {len(records)} จากทั้งหมด {storage.log_header(store)['total_records']} รายการ")


def view_index_menu(store, settings):
    print_title("TRANSACTION INDEX (ดัชนีรายการ)", settings)
    value = input("จำนวน ID ล่าสุด [Enter = 20, 0 = ทั้งหมด]: ").strip()
    if value == "":
        limit = 20
    elif value.isdecimal():
        limit = int(value)
    else:
        raise ValueError("กรุณาใส่จำนวนเต็มตั้งแต่ 0 ขึ้นไป")
    records = storage.read_index(store)
    if not records:
        message("ยังไม่มีรายการในดัชนี", settings, "INFO", terminal.YELLOW)
        return
    selected = records if limit == 0 else records[-limit:]
    columns = [("ID", 10, "right"), ("Slot", 8, "right"),
               ("Status", 8, "left"), ("DAT Offset", 12, "right")]
    heading, separator = display.table_heading(columns)
    print(heading)
    print(separator)
    for record in reversed(selected):
        status = c.STATUS_LABELS.get(record["status"], str(record["status"]))
        offset = c.HEADER_SIZE + record["slot_no"] * c.TRANSACTION_SIZE
        print(display.table_row((record["transaction_id"], record["slot_no"],
                                 status, offset), columns))
    print(f"\nแสดง ID ล่าสุด {len(selected)} จากทั้งหมด {len(records)} รายการ")


def view_data_file_menu(store, settings):
    print_title("DATA FILE CONTENTS (transactions.dat)", settings)
    header = storage.data_header(store)
    print("ไฟล์          : " + store["data_path"])
    print("ชนิดไฟล์      : Binary (ถอดรหัสเพื่อแสดงผล)")
    print(f'Header magic  : {header["magic"].decode("ascii")}')
    print(f'Format version: {header["version"]}')
    print(f'Header        : {c.HEADER_SIZE} bytes; record ละ {header["record_size"]} bytes')
    print(f'จำนวนระเบียน  : {header["total_records"]} (Active {header["active_records"]}, Deleted {header["deleted_records"]})')
    print(f'Free-list head: {header["aux_value"]}')
    updated = datetime.fromtimestamp(header["updated_at"], timezone(timedelta(hours=7)))
    print(f'Header update : {updated:%Y-%m-%d %H:%M:%S} (+07:00)')
    print("-" * screen_width())
    if not header["total_records"]:
        print("ยังไม่มีรายการใน transactions.dat")
        return
    for slot in range(header["total_records"]):
        record = storage.read_data_slot(store, slot)
        offset = c.HEADER_SIZE + slot * c.TRANSACTION_SIZE
        print(f'Slot {slot} | DAT Offset {offset} | ID {record["transaction_id"]} | Status {c.STATUS_LABELS[record["status"]]}')
        print(f'  Date/Time   : {record["date"]} {record["time"] or "--:--"}')
        print(f'  Type        : {c.TYPE_LABELS[record["type_code"]]} (code {record["type_code"]})')
        print(f'  Category    : {record["category"]}')
        print(f'  Description : {record["description"] or "-"}')
        print(f'  Amount      : {record["amount"]:,.2f} THB')
        print(f'  Next free   : {record["next_free"]} (slot; -1 = ไม่มี)')
        if slot < header["total_records"] - 1:
            print("-" * screen_width())


def view_menu(store, settings):
    while True:
        print_title("VIEW TRANSACTIONS (ดูรายการ/สถิติการเงิน)", settings)
        print("1) ดูรายการทั้งหมด")
        print("2) ค้นหาจาก ID (รวมรายการที่ลบ)")
        print("3) กรองเฉพาะ รายรับ/รายจ่าย")
        print("4) สถิติไฟล์")
        print("5) กรองตามหมวดหมู่")
        print("6) กรองตามวันที่")
        print("7) สรุปการเงิน")
        print("8) ดูรายการทั้งหมดรวมรายการที่ลบ")
        print("9) ดูประวัติการทำงาน (transactions.log)")
        print("10) ดูดัชนีรายการ (transactions.idx)")
        print("11) ดูข้อมูลทุกฟิลด์ในไฟล์ (transactions.dat)")
        print("0) ย้อนกลับ")
        print("-" * screen_width())
        choice = input("เลือกเมนูย่อย (0-11): ").strip()
        try:
            if choice == "1":
                print_title("TRANSACTIONS LIST (รายการทั้งหมด)", settings)
                show_records(service.view_all(store), settings)
            elif choice == "2":
                view_id_menu(store, settings)
            elif choice == "3":
                type_value = ask_type(settings)
                show_records(service.filter_by_type(store, type_value), settings)
            elif choice == "4":
                file_statistics(store, settings)
            elif choice == "5":
                keyword = input("คำค้นในชื่อหมวดหมู่: ").strip()
                show_records(service.filter_by_category(store, keyword), settings)
            elif choice == "6":
                date_value = input("วันที่ YYYY-MM-DD: ").strip()
                show_records(service.filter_by_date(store, date_value), settings)
            elif choice == "7":
                summary_menu(store, settings)
            elif choice == "8":
                show_records(service.view_all(store, include_deleted=True), settings)
            elif choice == "9":
                view_log_menu(store, settings)
            elif choice == "10":
                view_index_menu(store, settings)
            elif choice == "11":
                view_data_file_menu(store, settings)
            elif choice == "0":
                return
            else:
                raise ValueError("กรุณาเลือกเมนู 0-11")
        except (ValueError, LookupError, OSError) as error:
            show_error(error, settings)
        pause("\nกด Enter เพื่อตกลง...")


def generate_report_menu(store, settings):
    while True:
        print_title("GENERATE REPORTS (เลือกรายงาน .txt)", settings)
        print("1) รายการธุรกรรม       report.txt")
        print("2) สรุปรายเดือน         monthly_report.txt")
        print("3) สรุปตามหมวดหมู่     category_report.txt")
        print("4) สร้างทั้งหมด 3 ไฟล์")
        print("0) กลับเมนูหลัก")
        print("-" * screen_width())
        choice = input("เลือกรายงาน (0-4): ").strip()
        if choice == "0":
            return
        try:
            if choice in ("1", "2", "3"):
                paths = [report.generate_selected_report(store, choice)]
            elif choice == "4":
                paths = report.generate_all_reports(store)
            else:
                raise ValueError("กรุณาเลือกเมนู 0-4")
            message("สร้างรายงานสำเร็จ:\n" + "\n".join(os.path.abspath(path) for path in paths), settings)
        except (ValueError, LookupError, OSError) as error:
            show_error(error, settings)
        pause("\nกด Enter เพื่อเลือกรายงานต่อ...")


def run_menu(store, settings=None):
    if settings is None:
        settings = make_ui()
    while True:
        print_title("MAIN MENU (เมนูหลัก)", settings)
        print("=" * screen_width())
        print("(1) [Add]  (บันทึกรายรับ-รายจ่าย)")
        print("(2) [Update]  (แก้ไขข้อมูลรายการ)")
        print("(3) [Delete]  (ลบรายการ)")
        print("(4) [View]  (ดูรายการ)")
        print("(5) [Generate Reports] (เลือก 1 ไฟล์ หรือทั้งหมด)")
        print("(0) [Exit]  (ออกจากโปรแกรม)")
        print("=" * screen_width())
        choice = input("เลือกทำรายการ (0-5): ").strip()
        try:
            if choice == "1":
                add_menu(store, settings)
            elif choice == "2":
                update_menu(store, settings)
            elif choice == "3":
                delete_menu(store, settings)
            elif choice == "4":
                view_menu(store, settings)
                continue
            elif choice == "5":
                generate_report_menu(store, settings)
                continue
            elif choice == "0":
                if store["changed_since_report"]:
                    message("มีข้อมูลเปลี่ยนหลังสร้างรายงานบางไฟล์ เมื่อต้องการรายงานล่าสุดให้ใช้เมนู 5", settings, "INFO", terminal.YELLOW)
                service.record_exit(store)
                message("ปิดระบบอย่างปลอดภัย บันทึกข้อมูลเรียบร้อยแล้ว", settings, "SYSTEM")
                return
            else:
                raise ValueError("กรุณาเลือกเมนู 0-5")
        except (ValueError, LookupError, OSError) as error:
            show_error(error, settings)
        pause()
