import os
from datetime import datetime, timedelta, timezone

import codec
import constants as c
import display
import service
import storage


def _transactions(store):
    header = storage.data_header(store)
    with open(store["data_path"], "rb") as file:
        file.seek(c.HEADER_SIZE)
        for _ in range(header["total_records"]):
            yield codec.unpack_transaction(file.read(c.TRANSACTION_SIZE))


def _audit(store):
    latest = {}
    edited = set()
    for item in storage.read_logs(store):
        if item["result"] != 1 or item["transaction_id"] == 0:
            continue
        if item["op_code"] in (c.OP_ADD, c.OP_UPDATE, c.OP_DELETE):
            latest[item["transaction_id"]] = c.OPERATION_LABELS[item["op_code"]]
            if item["op_code"] == c.OP_UPDATE:
                edited.add(item["transaction_id"])
    return latest, edited


def _preamble(file, title, generated_at, scope):
    file.write(title + "\n")
    file.write("Generated At : " + generated_at + " (+07:00)\n")
    file.write("Data sources : transactions.dat (current records), transactions.log (successful changes)\n")
    file.write("Scope        : " + scope + "\n")
    file.write("Currency     : THB\n\n")


def _table(file, columns, rows_factory, open_last=False):
    # Keep ASCII columns fixed. Thai category text is unbounded at the right
    # edge, where font-dependent glyph widths cannot shift another border.
    measured = [[name, max(width, display.display_width(name)), align]
                for name, width, align in columns]
    for row in rows_factory():
        for number, value in enumerate(row):
            if open_last and number == len(columns) - 1:
                continue
            measured[number][1] = max(measured[number][1], display.display_width(value))
    columns = [(name, width, align) for name, width, align in measured]
    if open_last:
        heading = display.table_row([name for name, _, _ in columns[:-1]], columns[:-1])
        separator = "-+-".join("-" * width for _, width, _ in columns)
        file.write(heading + " | " + columns[-1][0] + "\n" + separator + "\n")
        count = 0
        for row in rows_factory():
            file.write(display.table_row(row[:-1], columns[:-1]) + " | " + str(row[-1]) + "\n")
            count += 1
        if count == 0:
            empty = ["-"] + [""] * (len(columns) - 2)
            file.write(display.table_row(empty, columns[:-1]) + " | -\n")
        file.write(separator + "\n")
        return
    border = "+" + "+".join("-" * (width + 2) for _, width, _ in columns) + "+"
    heading, _ = display.table_heading(columns)
    file.write(border + "\n| " + heading + " |\n" + border + "\n")
    count = 0
    for row in rows_factory():
        file.write("| " + display.table_row(row, columns) + " |\n")
        count += 1
    if count == 0:
        empty = ["-"] + [""] * (len(columns) - 1)
        file.write("| " + display.table_row(empty, columns) + " |\n")
    file.write(border + "\n")


def _write_atomic(path, writer):
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8-sig", newline="\n") as file:
            writer(file)
            storage.sync_file(file)
        os.replace(temporary, path)
    except Exception:
        if os.path.isfile(temporary):
            os.remove(temporary)
        raise


def _detail_report(file, store, latest, edited, generated_at):
    totals = service.summary(store, log_view=False)
    _preamble(file, "Income & Expense System - Transaction Report", generated_at,
              "All current slots, including deleted records")
    columns = [("ID", 4, "right"),
               ("Date", 10, "left"), ("Time", 5, "left"), ("Type", 7, "left"),
               ("Amount", 6, "right"), ("Status", 7, "left"),
               ("Last Change", 11, "left"), ("Category", 8, "left")]

    def rows():
        for record in _transactions(store):
            yield [record["transaction_id"], record["date"], record["time"] or "--:--",
                   c.TYPE_LABELS[record["type_code"]], f'{record["amount"]:,.2f}',
                   c.STATUS_LABELS[record["status"]],
                   latest.get(record["transaction_id"], "-"), record["category"]]

    _table(file, columns, rows, open_last=True)
    file.write("\nSummary (active records only for money)\n")
    file.write(f'- Total Records   : {totals["total_slots"]}\n')
    file.write(f'- Active Records  : {totals["active_records"]}\n')
    file.write(f'- Deleted Records : {totals["deleted_records"]}\n')
    file.write(f'- Edited Records  : {sum(1 for r in _transactions(store) if r["status"] == c.STATUS_ACTIVE and r["transaction_id"] in edited)}\n')
    file.write(f'- Total Income    : {totals["total_income"]:,.2f} THB\n')
    file.write(f'- Total Expense   : {totals["total_expense"]:,.2f} THB\n')
    file.write(f'- Balance         : {totals["balance"]:,.2f} THB\n')


def _group_report(file, store, edited, generated_at, group_by):
    monthly = group_by == "month"
    title = "Income & Expense System - Monthly Report" if monthly else "Income & Expense System - Category Report"
    scope = "Active records by transaction month" if monthly else "Active records by current category name"
    _preamble(file, title, generated_at, scope + "; Edited counts use the operation log")
    groups = {}
    for record in _transactions(store):
        if record["status"] != c.STATUS_ACTIVE:
            continue
        key = record["date"][:7] if monthly else record["category"]
        row = groups.setdefault(key, {"count": 0, "income": 0, "expense": 0, "edited": 0})
        row["count"] += 1
        row["edited"] += record["transaction_id"] in edited
        satang = round(record["amount"] * 100)
        if record["type_code"] == c.TYPE_INCOME:
            row["income"] += satang
        else:
            row["expense"] += satang

    key_name = "Month" if monthly else "Category"
    if monthly:
        columns = [("Month", 10, "left"), ("Items", 5, "right"),
                   ("Income", 6, "right"), ("Expense", 7, "right"),
                   ("Net", 3, "right"), ("Edited", 6, "right")]
    else:
        columns = [("Items", 5, "right"), ("Income", 6, "right"),
                   ("Expense", 7, "right"), ("Net", 3, "right"),
                   ("Edited", 6, "right"), ("Category", 8, "left")]

    def rows():
        for key in sorted(groups):
            row = groups[key]
            values = [row["count"], f'{row["income"] / 100:,.2f}',
                      f'{row["expense"] / 100:,.2f}',
                      f'{(row["income"] - row["expense"]) / 100:,.2f}', row["edited"]]
            yield [key] + values if monthly else values + [key]

    _table(file, columns, rows, open_last=not monthly)
    count = sum(row["count"] for row in groups.values())
    income = sum(row["income"] for row in groups.values())
    expense = sum(row["expense"] for row in groups.values())
    edit_count = sum(row["edited"] for row in groups.values())
    file.write("\nSummary\n")
    file.write(f'- {key_name} groups : {len(groups)}\n')
    file.write(f'- Active items : {count}\n')
    file.write(f'- Edited items : {edit_count}\n')
    file.write(f'- Income       : {income / 100:,.2f} THB\n')
    file.write(f'- Expense      : {expense / 100:,.2f} THB\n')
    file.write(f'- Net balance  : {(income - expense) / 100:,.2f} THB\n')


def _generate_reports(store, selections):
    """Write only the requested report files from the current data and log."""
    storage.record_operation(store, c.OP_REPORT, True)
    thailand = timezone(timedelta(hours=7))
    generated_at = datetime.now(thailand).strftime("%Y-%m-%d %H:%M:%S")
    try:
        latest, edited = _audit(store)
        paths = []
        for selection in selections:
            if selection == "1":
                name = c.REPORT_FILE_NAME
                writer = lambda file: _detail_report(file, store, latest, edited, generated_at)
            elif selection == "2":
                name = c.MONTHLY_REPORT_FILE_NAME
                writer = lambda file: _group_report(file, store, edited, generated_at, "month")
            else:
                name = c.CATEGORY_REPORT_FILE_NAME
                writer = lambda file: _group_report(file, store, edited, generated_at, "category")
            path = os.path.join(store["data_dir"], name)
            _write_atomic(path, writer)
            paths.append(path)
    except Exception:
        storage.record_operation(store, c.OP_REPORT, False)
        raise
    if len(selections) == 3:
        store["changed_since_report"] = False
    return paths


def generate_selected_report(store, selection):
    """Create one report: 1 transactions, 2 monthly, or 3 category."""
    if selection not in ("1", "2", "3"):
        raise ValueError("กรุณาเลือกรายงาน 1-3")
    return _generate_reports(store, (selection,))[0]


def generate_all_reports(store):
    """Create all three separate text reports."""
    return _generate_reports(store, ("1", "2", "3"))


def generate_report(store):
    """Keep the original entry point for existing callers."""
    return generate_all_reports(store)[0]
