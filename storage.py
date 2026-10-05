import os
import shutil
import struct
import time
import constants as c
import codec
import models


def sync_file(file):
    file.flush()
    os.fsync(file.fileno())


def create_file(path, magic, record_size, aux, version=c.FILE_VERSION):
    if not os.path.exists(path):
        header = models.make_header(magic, record_size, aux=aux)
        header["version"] = version
        with open(path, "xb") as file:
            file.write(codec.pack_header(header))
            sync_file(file)


def read_header(path, magic, record_size, version=c.FILE_VERSION):
    size = os.path.getsize(path)
    if size < c.HEADER_SIZE:
        raise ValueError("Incomplete header: " + os.path.basename(path))
    with open(path, "rb") as file:
        header = codec.unpack_header(file.read(c.HEADER_SIZE))
    if header["magic"] != magic:
        raise ValueError("Invalid magic: " + os.path.basename(path))
    if header["version"] != version:
        raise ValueError("Unsupported file version")
    if header["record_size"] != record_size:
        raise ValueError("Invalid record size")
    body_size = size - c.HEADER_SIZE
    if body_size % record_size != 0:
        raise ValueError("Partial record: " + os.path.basename(path))
    if body_size // record_size != header["total_records"]:
        raise ValueError("Record count does not match file size")
    if header["active_records"] + header["deleted_records"] != header["total_records"]:
        raise ValueError("Active/deleted counters do not match")
    return header


def write_header(path, header):
    header["updated_at"] = int(time.time())
    with open(path, "r+b") as file:
        file.write(codec.pack_header(header))
        sync_file(file)


def data_header(store):
    return read_header(store["data_path"], c.DATA_MAGIC, c.TRANSACTION_SIZE, c.DATA_FILE_VERSION)


def index_header(store):
    return read_header(store["index_path"], c.INDEX_MAGIC, c.INDEX_SIZE)


def log_header(store):
    return read_header(store["log_path"], c.LOG_MAGIC, c.LOG_SIZE)


def migrate_data_v1(path):
    with open(path, "rb") as file:
        header = codec.unpack_header(file.read(c.HEADER_SIZE))
    if header["magic"] != c.DATA_MAGIC or header["version"] != 1:
        return
    old_size = struct.calcsize(c.TRANSACTION_FORMAT_V1)
    header = read_header(path, c.DATA_MAGIC, old_size, 1)
    backup = path + ".v1.bak"
    temporary = path + ".v2.tmp"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    header["version"] = c.DATA_FILE_VERSION
    header["record_size"] = c.TRANSACTION_SIZE
    try:
        with open(path, "rb") as source, open(temporary, "wb") as target:
            source.seek(c.HEADER_SIZE)
            target.write(codec.pack_header(header))
            for _ in range(header["total_records"]):
                old = codec.unpack_transaction_v1(source.read(old_size))
                target.write(codec.pack_transaction(old))
            sync_file(target)
        os.replace(temporary, path)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def open_storage(data_dir="data"):
    data_dir = os.path.abspath(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    store = {
        "data_dir": data_dir,
        "data_path": os.path.join(data_dir, c.DATA_FILE_NAME),
        "index_path": os.path.join(data_dir, c.INDEX_FILE_NAME),
        "log_path": os.path.join(data_dir, c.LOG_FILE_NAME),
        "changed_since_report": False,
    }
    create_file(store["data_path"], c.DATA_MAGIC, c.TRANSACTION_SIZE,
                c.NO_FREE_SLOT, c.DATA_FILE_VERSION)
    create_file(store["log_path"], c.LOG_MAGIC, c.LOG_SIZE, 1)
    migrate_data_v1(store["data_path"])
    data_header(store)
    log_header(store)
    try:
        if not index_matches_data(store):
            rebuild_index(store)
    except (ValueError, OSError, struct.error):
        rebuild_index(store)
    validate_free_list(store)
    store["next_id"] = find_next_id(store)
    return store


def read_data_slot(store, slot_no):
    header = data_header(store)
    if slot_no < 0 or slot_no >= header["total_records"]:
        raise ValueError("Data slot is outside the file")
    with open(store["data_path"], "rb") as file:
        file.seek(c.HEADER_SIZE + slot_no * c.TRANSACTION_SIZE)
        raw = file.read(c.TRANSACTION_SIZE)
    try:
        return codec.unpack_transaction(raw)
    except (struct.error, UnicodeError):
        raise ValueError("Cannot decode data slot " + str(slot_no))


def write_data_slot(store, slot_no, record):
    with open(store["data_path"], "r+b") as file:
        file.seek(c.HEADER_SIZE + slot_no * c.TRANSACTION_SIZE)
        file.write(codec.pack_transaction(record))
        sync_file(file)


def read_all_transactions(store, include_deleted=False):
    header = data_header(store)
    records = []
    with open(store["data_path"], "rb") as file:
        file.seek(c.HEADER_SIZE)
        for slot_no in range(header["total_records"]):
            try:
                record = codec.unpack_transaction(file.read(c.TRANSACTION_SIZE))
            except (struct.error, UnicodeError):
                raise ValueError("Cannot decode data slot " + str(slot_no))
            if include_deleted or record["status"] == c.STATUS_ACTIVE:
                records.append(record)
    return records


def read_index(store):
    header = index_header(store)
    records = []
    last_id = 0
    with open(store["index_path"], "rb") as file:
        file.seek(c.HEADER_SIZE)
        for number in range(header["total_records"]):
            record = codec.unpack_index(file.read(c.INDEX_SIZE))
            if record["transaction_id"] <= last_id:
                raise ValueError("Index IDs must be sorted and unique")
            last_id = record["transaction_id"]
            records.append(record)
    return records


def write_index(store, records):
    rows = []
    active = 0
    deleted = 0
    for record in records:
        rows.append((record["transaction_id"], record["slot_no"], record["status"]))
        if record["status"] == c.STATUS_ACTIVE:
            active += 1
        else:
            deleted += 1
    rows.sort()
    header = models.make_header(c.INDEX_MAGIC, c.INDEX_SIZE, len(rows), active, deleted, 0)
    temporary = store["index_path"] + ".tmp"
    with open(temporary, "wb") as file:
        file.write(codec.pack_header(header))
        for transaction_id, slot_no, status in rows:
            file.write(codec.pack_index(models.make_index(transaction_id, slot_no, status)))
        sync_file(file)
    os.replace(temporary, store["index_path"])


def index_matches_data(store):
    data = data_header(store)
    index = index_header(store)
    if data["total_records"] != index["total_records"]:
        return False
    if data["active_records"] != index["active_records"]:
        return False
    seen_slots = set()
    last_id = 0
    with open(store["index_path"], "rb") as index_file:
        with open(store["data_path"], "rb") as data_file:
            index_file.seek(c.HEADER_SIZE)
            for number in range(index["total_records"]):
                item = codec.unpack_index(index_file.read(c.INDEX_SIZE))
                slot = item["slot_no"]
                if item["transaction_id"] <= last_id or slot in seen_slots:
                    return False
                if slot >= data["total_records"]:
                    return False
                seen_slots.add(slot)
                last_id = item["transaction_id"]
                data_file.seek(c.HEADER_SIZE + slot * c.TRANSACTION_SIZE)
                record = codec.unpack_transaction(data_file.read(c.TRANSACTION_SIZE))
                if record["transaction_id"] != item["transaction_id"]:
                    return False
                if record["status"] != item["status"]:
                    return False
    return True


def rebuild_index(store):
    records = []
    seen_ids = set()
    data = read_all_transactions(store, include_deleted=True)
    for slot in range(len(data)):
        record = data[slot]
        transaction_id = record["transaction_id"]
        if transaction_id in seen_ids:
            raise ValueError("Cannot rebuild index: duplicate transaction ID")
        seen_ids.add(transaction_id)
        records.append(models.make_index(transaction_id, slot, record["status"]))
    write_index(store, records)


def find_index_record(store, transaction_id):
    # Binary search: เลื่อน seek ไปอ่านเฉพาะระเบียนตรงกลาง
    header = index_header(store)
    left = 0
    right = header["total_records"] - 1
    with open(store["index_path"], "rb") as file:
        while left <= right:
            middle = (left + right) // 2
            file.seek(c.HEADER_SIZE + middle * c.INDEX_SIZE)
            record = codec.unpack_index(file.read(c.INDEX_SIZE))
            if record["transaction_id"] == transaction_id:
                return record
            if record["transaction_id"] < transaction_id:
                left = middle + 1
            else:
                right = middle - 1
    raise LookupError("Transaction ID " + str(transaction_id) + " was not found")


def get_transaction(store, transaction_id, include_deleted=False):
    index = find_index_record(store, transaction_id)
    record = read_data_slot(store, index["slot_no"])
    if record["transaction_id"] != transaction_id or record["status"] != index["status"]:
        raise ValueError("Index entry does not match data")
    if record["status"] == c.STATUS_DELETED and not include_deleted:
        raise LookupError("Transaction ID " + str(transaction_id) + " is deleted")
    return record


def find_next_id(store):
    highest = c.FIRST_TRANSACTION_ID - 1
    header = index_header(store)
    if header["total_records"] > 0:
        with open(store["index_path"], "rb") as file:
            file.seek(c.HEADER_SIZE + (header["total_records"] - 1) * c.INDEX_SIZE)
            highest = codec.unpack_index(file.read(c.INDEX_SIZE))["transaction_id"]
    header = log_header(store)
    with open(store["log_path"], "rb") as file:
        file.seek(c.HEADER_SIZE)
        for number in range(header["total_records"]):
            record = codec.unpack_log(file.read(c.LOG_SIZE))
            # ID ที่ค้นหาไม่พบยังไม่ได้ถูกสร้าง จึงไม่นำมาจองเป็น ID
            if record["op_code"] == c.OP_ADD and record["result"] == 1:
                if record["transaction_id"] > highest:
                    highest = record["transaction_id"]
    return highest + 1


def add_transaction(store, date, type_code, category, description, amount, time_value=""):
    transaction_id = store["next_id"]
    if transaction_id > 4294967295:
        raise ValueError("Transaction IDs are exhausted")
    header = data_header(store)
    record = models.make_transaction(transaction_id, date, type_code, category,
                                     description, amount, time_value=time_value)
    index = read_index(store)
    if header["aux_value"] != c.NO_FREE_SLOT:
        slot = header["aux_value"]
        old = read_data_slot(store, slot)
        if old["status"] != c.STATUS_DELETED:
            raise ValueError("Free-list points to an active record")
        header["aux_value"] = old["next_free"]
        header["deleted_records"] -= 1
        write_data_slot(store, slot, record)
    else:
        slot = header["total_records"]
        with open(store["data_path"], "ab") as file:
            file.write(codec.pack_transaction(record))
            sync_file(file)
        header["total_records"] += 1
    header["active_records"] += 1
    write_header(store["data_path"], header)
    remaining = []
    for item in index:
        if item["slot_no"] != slot:
            remaining.append(item)
    remaining.append(models.make_index(transaction_id, slot, c.STATUS_ACTIVE))
    write_index(store, remaining)
    store["next_id"] += 1
    store["changed_since_report"] = True
    record_operation(store, c.OP_ADD, True, record)
    return record


def update_transaction(store, record):
    index = find_index_record(store, record["transaction_id"])
    get_transaction(store, record["transaction_id"])
    write_data_slot(store, index["slot_no"], record)
    store["changed_since_report"] = True
    record_operation(store, c.OP_UPDATE, True, record)
    return record


def delete_transaction(store, transaction_id):
    index = find_index_record(store, transaction_id)
    record = get_transaction(store, transaction_id)
    header = data_header(store)
    record["status"] = c.STATUS_DELETED
    record["next_free"] = header["aux_value"]
    write_data_slot(store, index["slot_no"], record)
    header["aux_value"] = index["slot_no"]
    header["active_records"] -= 1
    header["deleted_records"] += 1
    write_header(store["data_path"], header)
    records = read_index(store)
    for item in records:
        if item["transaction_id"] == transaction_id:
            item["status"] = c.STATUS_DELETED
            break
    write_index(store, records)
    store["changed_since_report"] = True
    record_operation(store, c.OP_DELETE, True, record)
    return record


def validate_free_list(store):
    header = data_header(store)
    seen = set()
    slot = header["aux_value"]
    while slot != c.NO_FREE_SLOT:
        if slot in seen:
            raise ValueError("Free-list contains a cycle")
        if slot < 0 or slot >= header["total_records"]:
            raise ValueError("Free-list contains an invalid slot")
        seen.add(slot)
        record = read_data_slot(store, slot)
        if record["status"] != c.STATUS_DELETED:
            raise ValueError("Free-list points to an active record")
        slot = record["next_free"]
    if len(seen) != header["deleted_records"]:
        raise ValueError("Free-list count does not match deleted count")
    return len(seen)


def free_slot_count(store):
    return validate_free_list(store)


def record_operation(store, op_code, success, transaction=None, transaction_id=0):
    header = log_header(store)
    type_after = 0
    status_after = 0
    amount_after = 0.0
    if transaction is not None:
        transaction_id = transaction["transaction_id"]
        type_after = transaction["type_code"]
        status_after = transaction["status"]
        amount_after = transaction["amount"]
    result = 0
    if success:
        result = 1
    sequence = max(header["aux_value"], header["total_records"] + 1)
    record = models.make_log(sequence, int(time.time()), op_code, transaction_id,
                             result, type_after, status_after, amount_after)
    with open(store["log_path"], "ab") as file:
        file.write(codec.pack_log(record))
        sync_file(file)
    header["total_records"] += 1
    if success:
        header["active_records"] += 1
    else:
        header["deleted_records"] += 1
    header["aux_value"] = sequence + 1
    write_header(store["log_path"], header)
    return record


def read_logs(store, limit=None):
    header = log_header(store)
    count = header["total_records"]
    start = 0
    if limit is not None and 0 <= limit < count:
        start = count - limit
        count = limit
    records = []
    with open(store["log_path"], "rb") as file:
        file.seek(c.HEADER_SIZE + start * c.LOG_SIZE)
        for number in range(count):
            records.append(codec.unpack_log(file.read(c.LOG_SIZE)))
    return records
