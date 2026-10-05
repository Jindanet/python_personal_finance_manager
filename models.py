import time
from constants import FILE_VERSION


# ใช้ dictionary เก็บชื่อ field จะได้ไม่ต้องจำตำแหน่งของ tuple


def make_header(magic, record_size, total=0, active=0, deleted=0, aux=-1):
    return {
        "magic": magic,
        "version": FILE_VERSION,
        "record_size": record_size,
        "total_records": total,
        "active_records": active,
        "deleted_records": deleted,
        "aux_value": aux,
        "updated_at": int(time.time()),
    }


def make_transaction(transaction_id, date, type_code, category, description, amount,
                     status=1, next_free=-1, time_value=""):
    return {
        "transaction_id": transaction_id,
        "date": date,
        "time": time_value,
        "type_code": type_code,
        "category": category,
        "description": description,
        "amount": amount,
        "status": status,
        "next_free": next_free,
    }


def make_index(transaction_id, slot_no, status):
    return {"transaction_id": transaction_id, "slot_no": slot_no, "status": status}


def make_log(log_seq, timestamp, op_code, transaction_id, result,
             type_after, status_after, amount_after):
    return {
        "log_seq": log_seq,
        "timestamp": timestamp,
        "op_code": op_code,
        "transaction_id": transaction_id,
        "result": result,
        "type_after": type_after,
        "status_after": status_after,
        "amount_after": amount_after,
    }
