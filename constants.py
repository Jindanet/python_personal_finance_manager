import struct

APP_NAME = "Personal Income and Expense Management System"
APP_VERSION = "1.0"
FILE_VERSION = 1

# ขนาดและลำดับ field ต้องตรงกันทั้งตอน pack และ unpack
HEADER_FORMAT = "<8sHHIIIiq"
TRANSACTION_FORMAT = "<I10sB60s180sdBi"
INDEX_FORMAT = "<IIB3x"
LOG_FORMAT = "<IqBIBBBd4x"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
TRANSACTION_SIZE = struct.calcsize(TRANSACTION_FORMAT)
INDEX_SIZE = struct.calcsize(INDEX_FORMAT)
LOG_SIZE = struct.calcsize(LOG_FORMAT)

DATA_MAGIC = b"FINDAT01"
INDEX_MAGIC = b"FINIDX01"
LOG_MAGIC = b"FINLOG01"
DATA_FILE_NAME = "transactions.dat"
INDEX_FILE_NAME = "transactions.idx"
LOG_FILE_NAME = "transactions.log"
REPORT_FILE_NAME = "report.txt"

DATE_BYTES = 10
CATEGORY_BYTES = 60
DESCRIPTION_BYTES = 180
TYPE_NONE = 0
TYPE_INCOME = 1
TYPE_EXPENSE = 2
STATUS_DELETED = 0
STATUS_ACTIVE = 1
OP_ADD = 1
OP_UPDATE = 2
OP_DELETE = 3
OP_VIEW = 4
OP_REPORT = 5
OP_EXIT = 6
FIRST_TRANSACTION_ID = 1001
NO_FREE_SLOT = -1
MAX_AMOUNT = 999999999999.99

TYPE_LABELS = {0: "N/A", 1: "Income", 2: "Expense"}
STATUS_LABELS = {0: "Deleted", 1: "Active"}
OPERATION_LABELS = {1: "ADD", 2: "UPDATE", 3: "DELETE", 4: "VIEW", 5: "REPORT", 6: "EXIT"}
CATEGORIES = {
    "1": "เงินเดือน/รายได้",
    "2": "อาหาร/เครื่องดื่ม",
    "3": "เดินทาง/น้ำมัน",
    "4": "สาธารณูปโภค/ค่าบ้าน",
    "5": "ช้อปปิ้ง/บันเทิง",
    "6": "อื่นๆ",
}
