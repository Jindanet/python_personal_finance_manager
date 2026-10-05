import sys
from datetime import date, timedelta
import constants as c
import display
import report
import service
import storage
import ui


def configure_utf8_console():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def seed_thai_demo(store):
    if storage.data_header(store)["total_records"] > 0:
        return False
    today = date.today()
    service.add_transaction(store, str(today), "1", "เงินเดือน", "เงินเดือนประจำเดือน", "25000", "09:00")
    service.add_transaction(store, str(today), "2", "อาหาร", "ข้าวเย็นกับเพื่อน", "159", "20:00")
    service.add_transaction(store, str(today - timedelta(days=1)), "2", "ค่าเดินทาง", "เติมน้ำมันรถ", "800", "18:30")
    service.add_transaction(store, str(today - timedelta(days=2)), "1", "ขายสินค้า", "รายได้จากการขายสินค้าออนไลน์", "1500", "14:15")
    service.add_transaction(store, str(today), "2", "ของใช้", "ซื้อสบู่และยาสระผม", "245.50", "16:45")
    return True


def run_demo(store):
    if seed_thai_demo(store):
        print("Thai demo data was created.")
    else:
        print("Existing demo data was used.")
    print(display.transaction_table(storage.read_all_transactions(store)))
    totals = service.summary(store, log_view=False)
    print(f'Total Income  : {totals["total_income"]:,.2f} THB')
    print(f'Total Expense : {totals["total_expense"]:,.2f} THB')
    print(f'Balance       : {totals["balance"]:,.2f} THB')
    print("Reports generated:\n" + "\n".join(report.generate_all_reports(store)))
    print("Thai UTF-8 round-trip completed successfully.")


def read_options(arguments):
    options = {"data_dir": "data", "demo": False, "version": False, "help": False}
    number = 0
    while number < len(arguments):
        argument = arguments[number]
        if argument == "--data-dir":
            number += 1
            if number == len(arguments):
                raise ValueError("--data-dir ต้องระบุชื่อ folder")
            options["data_dir"] = arguments[number]
        elif argument == "--demo":
            options["demo"] = True
        elif argument == "--version":
            options["version"] = True
        elif argument in ("--help", "-h"):
            options["help"] = True
        else:
            raise ValueError("ไม่รู้จัก option: " + argument)
        number += 1
    return options


def main():
    configure_utf8_console()
    try:
        options = read_options(sys.argv[1:])
        if options["help"]:
            print("python main.py [--data-dir folder] [--demo] [--version]")
            return 0
        if options["version"]:
            print(c.APP_VERSION)
            return 0
        store = storage.open_storage(options["data_dir"])
        if options["demo"]:
            run_demo(store)
        else:
            ui.run_menu(store)
        return 0
    except (ValueError, LookupError, OSError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nหยุดรับคำสั่ง ข้อมูลที่บันทึกแล้วอยู่ในไฟล์")
        return 0


if __name__ == "__main__":
    sys.exit(main())
