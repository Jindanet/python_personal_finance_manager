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
               ("Type", 7, "left"), ("Category", 18, "left"),
               ("Description", 30, "left"), ("Amount", 20, "right"),
               ("Status", 7, "left")]
    heading, separator = table_heading(columns)
    lines = [heading, separator]
    for record in records:
        values = [record["transaction_id"], record["date"],
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
    id_width = 6
    amount_width = 12
    for record in records:
        id_width = max(id_width, len(str(record["transaction_id"])))
        amount_width = max(amount_width, len(f'{record["amount"]:+,.2f}'))
    columns = [("ID", id_width, "left"), ("Date", 10, "left"),
               ("Type", 8, "left"), ("Amount (THB)", amount_width, "right")]
    base_width = 3 * (len(columns) - 1)
    for name, size, align in columns:
        base_width += size
    table_width = base_width
    show_category = width >= table_width + 18
    if show_category:
        columns.insert(3, ("Category", 15, "left"))
        table_width += 18
    show_status = width >= table_width + 10
    if show_status:
        columns.append(("Status", 7, "left"))
        table_width += 10
    show_note = width >= table_width + 11
    note_width = 0
    if show_note:
        note_width = width - table_width - 3
        columns.append(("Note", note_width, "left"))
    lines = []
    if width >= base_width:
        heading, separator = table_heading(columns)
        lines = [terminal.color_text(heading, enabled=use_color, bold=True), separator]
    for record in records:
        if record["type_code"] == c.TYPE_INCOME:
            kind, sign, color = "รายรับ", "+", terminal.GREEN
        else:
            kind, sign, color = "รายจ่าย", "-", terminal.RED
        status = "ใช้งาน"
        if record["status"] == c.STATUS_DELETED:
            status = "ลบแล้ว"
        amount = sign + f'{record["amount"]:,.2f}'
        if width < base_width:
            lines.extend(detail_lines("ID", record["transaction_id"], width))
            lines.extend(detail_lines("วันที่", record["date"], width))
            lines.extend(detail_lines("ประเภท", kind, width))
            lines.extend(detail_lines("จำนวนเงิน", "THB", width))
            lines.append(terminal.color_text(amount.rjust(min(width, amount_width)), color, use_color))
            lines.extend(detail_lines("หมวดหมู่", record["category"], width))
            lines.extend(detail_lines("บันทึก", record["description"], width))
            lines.extend(detail_lines("สถานะ", status, width))
            lines.append("-" * width)
        else:
            values = [record["transaction_id"], record["date"], kind, amount]
            if show_category:
                values.insert(3, record["category"])
            if show_status:
                values.append(status)
            if show_note:
                values.append(record["description"] or "-")
            lines.append(table_row(values, columns, use_color, color))
            if not show_category or display_width(record["category"]) > 15:
                lines.extend(detail_lines("หมวดหมู่", record["category"], width))
            if record["description"] and (not show_note or display_width(record["description"]) > note_width):
                lines.extend(detail_lines("บันทึกช่วยจำ", record["description"], width))
            if not show_status and record["status"] == c.STATUS_DELETED:
                lines.extend(detail_lines("สถานะ", status, width))
            lines.append(separator)
    return "\n".join(lines)
