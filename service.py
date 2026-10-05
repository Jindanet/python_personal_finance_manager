import math
from datetime import datetime
import constants as c
import codec
import storage


def validate_transaction_id(value):
    try:
        transaction_id = int(str(value).strip())
    except ValueError:
        raise ValueError("Transaction ID must be an integer")
    if transaction_id < 1 or transaction_id > 4294967295:
        raise ValueError("Transaction ID is outside the supported range")
    return transaction_id


def validate_date(value):
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError("Date must be a real date in YYYY-MM-DD format")
    return parsed.strftime("%Y-%m-%d")


def validate_type(value):
    value = str(value).strip().lower()
    if value in ("1", "income", "in"):
        return c.TYPE_INCOME
    if value in ("2", "expense", "out"):
        return c.TYPE_EXPENSE
    raise ValueError("Type must be 1 (Income) or 2 (Expense)")


def validate_text(value, field_name, byte_limit, required=True):
    value = value.strip()
    if required and value == "":
        raise ValueError(field_name + " cannot be empty")
    if "\x00" in value:
        raise ValueError(field_name + " cannot contain a null character")
    size = codec.utf8_size(value)
    if size > byte_limit:
        raise ValueError(f"{field_name} uses {size} UTF-8 bytes; limit is {byte_limit}")
    return value


def validate_amount(value):
    try:
        amount = float(str(value).strip().replace(",", ""))
    except ValueError:
        raise ValueError("Amount must be a valid number")
    if not math.isfinite(amount):
        raise ValueError("Amount cannot be NaN or infinity")
    if amount <= 0 or amount > c.MAX_AMOUNT:
        raise ValueError(f"Amount must be between 0.01 and {c.MAX_AMOUNT:,.2f}")
    amount = round(amount, 2)
    if amount < 0.01:
        raise ValueError("Amount must be at least 0.01")
    return amount


def add_transaction(store, date, type_value, category, description, amount):
    date = validate_date(date)
    type_code = validate_type(type_value)
    category = validate_text(category, "Category", c.CATEGORY_BYTES)
    description = validate_text(description, "Description", c.DESCRIPTION_BYTES, False)
    amount = validate_amount(amount)
    return storage.add_transaction(store, date, type_code, category, description, amount)


def update_transaction(store, transaction_id, date=None, type_value=None,
                       category=None, description=None, amount=None):
    transaction_id = validate_transaction_id(transaction_id)
    record = storage.get_transaction(store, transaction_id)
    if date is not None:
        record["date"] = validate_date(date)
    if type_value is not None:
        record["type_code"] = validate_type(type_value)
    if category is not None:
        record["category"] = validate_text(category, "Category", c.CATEGORY_BYTES)
    if description is not None:
        record["description"] = validate_text(description, "Description", c.DESCRIPTION_BYTES, False)
    if amount is not None:
        record["amount"] = validate_amount(amount)
    return storage.update_transaction(store, record)


def delete_transaction(store, transaction_id):
    return storage.delete_transaction(store, validate_transaction_id(transaction_id))


def view_by_id(store, transaction_id, include_deleted=True):
    transaction_id = validate_transaction_id(transaction_id)
    try:
        record = storage.get_transaction(store, transaction_id, include_deleted)
    except (ValueError, LookupError, OSError):
        storage.record_operation(store, c.OP_VIEW, False, transaction_id=transaction_id)
        raise
    storage.record_operation(store, c.OP_VIEW, True, record)
    return record


def view_all(store, include_deleted=False):
    records = storage.read_all_transactions(store, include_deleted)
    storage.record_operation(store, c.OP_VIEW, True)
    return records


def filter_by_type(store, type_value):
    type_code = validate_type(type_value)
    records = []
    for record in storage.read_all_transactions(store):
        if record["type_code"] == type_code:
            records.append(record)
    storage.record_operation(store, c.OP_VIEW, True)
    return records


def filter_by_category(store, keyword):
    keyword = validate_text(keyword, "Category keyword", c.CATEGORY_BYTES).lower()
    records = []
    for record in storage.read_all_transactions(store):
        if keyword in record["category"].lower():
            records.append(record)
    storage.record_operation(store, c.OP_VIEW, True)
    return records


def filter_by_date(store, date):
    date = validate_date(date)
    records = []
    for record in storage.read_all_transactions(store):
        if record["date"] == date:
            records.append(record)
    storage.record_operation(store, c.OP_VIEW, True)
    return records


def summary(store, log_view=True):
    header = storage.data_header(store)
    income_satang = 0
    expense_satang = 0
    # อ่านทีละระเบียนและรวมเป็นสตางค์ ไม่ต้องเก็บข้อมูลทั้งหมดไว้ใน list
    with open(store["data_path"], "rb") as file:
        file.seek(c.HEADER_SIZE)
        for number in range(header["total_records"]):
            record = codec.unpack_transaction(file.read(c.TRANSACTION_SIZE))
            if record["status"] == c.STATUS_DELETED:
                continue
            satang = round(record["amount"] * 100)
            if record["type_code"] == c.TYPE_INCOME:
                income_satang += satang
            else:
                expense_satang += satang
    if log_view:
        storage.record_operation(store, c.OP_VIEW, True)
    return {
        "total_slots": header["total_records"],
        "active_records": header["active_records"],
        "deleted_records": header["deleted_records"],
        "free_slots": storage.free_slot_count(store),
        "total_income": income_satang / 100,
        "total_expense": expense_satang / 100,
        "balance": (income_satang - expense_satang) / 100,
    }


def record_exit(store):
    storage.record_operation(store, c.OP_EXIT, True)
