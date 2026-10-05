import unicodedata
from textwrap import wrap
import constants as c
import terminal


def display_width(text):
    width = 0
    for character in str(text):
        if unicodedata.category(character) in ("Mn", "Me"):
            continue
        if unicodedata.east_asian_width(character) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def fit_cell(value, width, align="left"):
    original = str(value)
    text = original
    while display_width(text) > width and text:
        text = text[:-1]
    if text != original and width > 0:
        while display_width(text + "…") > width and text:
            text = text[:-1]
        text += "…"
    padding = max(0, width - display_width(text))
    if align == "right":
        return " " * padding + text
    if align == "center":
        left = padding // 2
        return " " * left + text + " " * (padding - left)
    return text + " " * padding


def table_row(values, columns, use_color=False, amount_color=""):
    cells = []
    for number in range(len(columns)):
        name, width, align = columns[number]
        cell = fit_cell(values[number], width, align)
        if name == "Amount (THB)" and amount_color:
            cell = terminal.color_text(cell, amount_color, use_color)
        cells.append(cell)
    return " | ".join(cells)


def table_heading(columns):
    names = []
    separators = []
    for name, width, align in columns:
        names.append(name)
        separators.append("-" * width)
    return table_row(names, columns), "-+-".join(separators)


def transaction_table(records):
    id_width = 6
    for record in records:
        id_width = max(id_width, len(str(record["transaction_id"])))
    columns = [("ID", id_width, "right"), ("Date", 10, "left"),
               ("Time", 5, "left"),
               ("Type", 7, "left"), ("Category", 18, "left"),
               ("Description", 30, "left"), ("Amount", 20, "right"),
               ("Status", 7, "left")]
    heading, separator = table_heading(columns)
    lines = [heading, separator]
    for record in records:
        values = [record["transaction_id"], record["date"], record["time"] or "-",
                  c.TYPE_LABELS[record["type_code"]], record["category"],
                  record["description"], f'{record["amount"]:,.2f}',
                  c.STATUS_LABELS[record["status"]]]
        lines.append(table_row(values, columns))
    return "\n".join(lines)


def detail_lines(label, value, width):
    if value == "":
        value = "-"
    lines = []
    for line in wrap(label + ": " + str(value), width=max(10, width - 2)):
        lines.append("  " + line)
    return lines


def terminal_transaction_table(records, width=66, use_color=False):
    if not records:
        return "ไม่พบรายการที่ตรงกับเงื่อนไข"
    id_width = max(6, *(len(str(record["transaction_id"])) for record in records))
    amount_width = max(12, *(len(f'{record["amount"]:,.2f}') + 1 for record in records))
    category_width = max(16, *(display_width(record["category"]) for record in records))
    # The sign carries Income/Expense, leaving room for the full category name.
    fixed_width = id_width + 16 + amount_width + 9
    available_category = width - fixed_width
    as_table = available_category >= 8
    if as_table:
        category_width = min(category_width, available_category)
        columns = [("ID", id_width, "left"), ("Date / Time", 16, "left"),
                   ("Category", category_width, "left"),
                   ("Amount (THB)", amount_width, "right")]
        show_status = fixed_width + category_width + 10 <= width
        if show_status:
            columns.append(("Status", 7, "left"))
        heading, separator = table_heading(columns)
        lines = [terminal.color_text(heading, enabled=use_color, bold=True), separator]
    else:
        lines = []
    for number, record in enumerate(records):
        income = record["type_code"] == c.TYPE_INCOME
        sign = "+" if income else "-"
        color = terminal.GREEN if income else terminal.RED
        status = c.STATUS_LABELS[record["status"]]
        amount = sign + f'{record["amount"]:,.2f}'
        when = record["date"] + " " + (record["time"] or "--:--")
        if as_table:
            values = [record["transaction_id"], when, record["category"], amount]
            if show_status:
                values.append(status)
            lines.append(table_row(values, columns,
                                   use_color, color))
            if display_width(record["category"]) > category_width:
                lines.extend(detail_lines("หมวดหมู่", record["category"], width))
            if record["description"]:
                lines.extend(detail_lines("บันทึก", record["description"], width))
            if not show_status and status == "Deleted":
                lines.extend(detail_lines("สถานะ", "ลบแล้ว", width))
        else:
            lines.extend(detail_lines("ID", record["transaction_id"], width))
            lines.extend(detail_lines("วันที่", record["date"], width))
            lines.extend(detail_lines("เวลา", record["time"] or "ไม่ระบุ", width))
            lines.extend(detail_lines("ประเภท", "รายรับ" if income else "รายจ่าย", width))
            lines.append(terminal.color_text(amount.rjust(min(width, amount_width)), color, use_color))
            lines.extend(detail_lines("หมวดหมู่", record["category"], width))
            if record["description"]:
                lines.extend(detail_lines("บันทึก", record["description"], width))
            lines.extend(detail_lines("สถานะ", "ลบแล้ว" if status == "Deleted" else "ใช้งาน", width))
            if number < len(records) - 1:
                lines.append("")
    if as_table:
        lines.append(separator)
        lines.append("+ รายรับ   - รายจ่าย")
    return "\n".join(lines)
