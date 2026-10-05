import struct
import constants as c
import models


def utf8_size(text):
    return len(text.encode("utf-8"))


def text_fits(text, size):
    return utf8_size(text) <= size


def pack_text(text, size):
    # ตัดทีละตัวอักษรเพื่อไม่ให้ UTF-8 ขาดกลางตัว
    while utf8_size(text) > size:
        text = text[:-1]
    return text.encode("utf-8").ljust(size, b"\x00")


def unpack_text(raw):
    return raw.split(b"\x00", 1)[0].decode("utf-8")


def pack_header(header):
    return struct.pack(c.HEADER_FORMAT, header["magic"], header["version"],
                       header["record_size"], header["total_records"],
                       header["active_records"], header["deleted_records"],
                       header["aux_value"], header["updated_at"])


def unpack_header(raw):
    values = struct.unpack(c.HEADER_FORMAT, raw)
    header = models.make_header(values[0], values[2], values[3], values[4], values[5], values[6])
    header["version"] = values[1]
    header["updated_at"] = values[7]
    return header


def pack_transaction(record):
    return struct.pack(c.TRANSACTION_FORMAT, record["transaction_id"],
                       pack_text(record["date"], c.DATE_BYTES),
                       pack_text(record["time"], c.TIME_BYTES), record["type_code"],
                       pack_text(record["category"], c.CATEGORY_BYTES),
                       pack_text(record["description"], c.DESCRIPTION_BYTES),
                       record["amount"], record["status"], record["next_free"])


def unpack_transaction(raw):
    values = struct.unpack(c.TRANSACTION_FORMAT, raw)
    return models.make_transaction(values[0], unpack_text(values[1]), values[3],
                                   unpack_text(values[4]), unpack_text(values[5]),
                                   values[6], values[7], values[8], unpack_text(values[2]))


def unpack_transaction_v1(raw):
    values = struct.unpack(c.TRANSACTION_FORMAT_V1, raw)
    return models.make_transaction(values[0], unpack_text(values[1]), values[2],
                                   unpack_text(values[3]), unpack_text(values[4]),
                                   values[5], values[6], values[7])


def pack_index(record):
    return struct.pack(c.INDEX_FORMAT, record["transaction_id"], record["slot_no"], record["status"])


def unpack_index(raw):
    values = struct.unpack(c.INDEX_FORMAT, raw)
    return models.make_index(values[0], values[1], values[2])


def pack_log(record):
    return struct.pack(c.LOG_FORMAT, record["log_seq"], record["timestamp"],
                       record["op_code"], record["transaction_id"], record["result"],
                       record["type_after"], record["status_after"], record["amount_after"])


def unpack_log(raw):
    values = struct.unpack(c.LOG_FORMAT, raw)
    return models.make_log(values[0], values[1], values[2], values[3],
                           values[4], values[5], values[6], values[7])
