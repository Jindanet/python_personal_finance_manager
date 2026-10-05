import json
import math
import os
import sys
import tempfile
from datetime import datetime
from main import configure_utf8_console
from tests import stress_lab as lab

PROJECT = os.path.dirname(os.path.abspath(__file__))
MAX_COUNT = 2147483646


def parse_count(value):
    text = str(value).strip().lower().rstrip("+").replace(",", "").replace("_", "")
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1000000
        text = text[:-1]
    try:
        count = float(text) * multiplier
    except ValueError:
        raise ValueError("จำนวนต้องเป็นตัวเลข เช่น 10k, 100k, 1m, 1.5m")
    if not math.isfinite(count) or not count.is_integer() or count < 1 or count > MAX_COUNT:
        raise ValueError(f"จำนวนต้องเป็นจำนวนเต็ม 1–{MAX_COUNT:,}")
    return int(count)


def parse_sizes(value):
    sizes = []
    for part in value.split(","):
        count = parse_count(part)
        if count not in sizes:
            sizes.append(count)
    return sizes


def nonnegative_time(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("เวลาต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป")
    return seconds


def read_options(arguments):
    options = {"scenario": None, "count": 1000, "timeout": None, "seed": 42,
               "samples": 3, "mutations": 2, "sizes": [1000, 10000, 100000, 1000000],
               "output_root": os.path.join(PROJECT, "tests", "test_runs"), "help": False}
    number = 0
    while number < len(arguments):
        argument = arguments[number]
        if argument in ("--help", "-h"):
            options["help"] = True
        else:
            if argument not in ("--scenario", "--count", "--timeout", "--seed", "--samples", "--mutations", "--sizes", "--output-root"):
                raise ValueError("ไม่รู้จัก option: " + argument)
            number += 1
            if number == len(arguments):
                raise ValueError(argument + " ต้องระบุค่า")
            value = arguments[number]
            key = argument[2:].replace("-", "_")
            if key == "count":
                value = parse_count(value)
            elif key == "sizes":
                value = parse_sizes(value)
            elif key == "timeout":
                value = nonnegative_time(value)
            elif key in ("seed", "samples", "mutations"):
                value = int(value)
            options[key] = value
        number += 1
    if options["scenario"] is not None and options["scenario"] not in lab.SCENARIOS:
        raise ValueError("ไม่รู้จักชุดทดสอบ: " + options["scenario"])
    if options["samples"] < 1 or options["mutations"] < 0:
        raise ValueError("samples ต้องมากกว่า 0 และ mutations ต้องไม่ติดลบ")
    return options


def print_result(root, result):
    print("\n" + "=" * 72)
    print(f'ผล: {result["status"]} | เวลารวม {result["elapsed_seconds"]:.3f}s')
    for metric in result["metrics"]:
        print(f'  [{metric["status"]}] {metric["name"]}: '
              f'{metric["completed"]:,}/{metric["target"]:,} ({metric["seconds"]:.3f}s)')
    if result["error"]:
        print("รายละเอียด: " + result["error"])
    print("JSON : " + os.path.join(root, "results.json"))
    print("CSV  : " + os.path.join(root, "metrics.csv"))
    print("=" * 72)


def launch(config, output_root):
    output_root = os.path.abspath(output_root)
    os.makedirs(output_root, exist_ok=True)
    prefix = datetime.now().strftime("%Y%m%d_%H%M%S_") + config["scenario"] + "_"
    root = tempfile.mkdtemp(prefix=prefix, dir=output_root)
    lab.save_json(os.path.join(root, "run.json"), {"kind": lab.RUN_MARKER, "config": config})
    print("\nข้อมูลและผลทดสอบ: " + root, flush=True)
    print(f'Scenario: {config["scenario"]} | count={config["count"]:,} | seed={config["seed"]}')
    if config["scenario"] in ("dataset", "corruption", "report", "scale"):
        print("สร้าง binary fixture ก่อน; เวลาส่วนนี้ไม่ใช่เวลาการเพิ่มข้อมูลผ่านโปรแกรม")
    print("ตรวจเวลาระหว่างคำสั่ง; ถ้าคำสั่งเดียวใช้เวลานาน จะรอคำสั่งนั้นจบก่อน")
    code = lab.execute(root, config)
    with open(os.path.join(root, "results.json"), encoding="utf-8") as file:
        result = json.load(file)
    print_result(root, result)
    return code, root, result


def ask_count():
    choices = {"1": 1000, "2": 10000, "3": 100000, "4": 1000000}
    while True:
        print("\nเลือกจำนวนรายการ (mixed = จำนวนคำสั่งสุ่ม)")
        print("1) 1,000\n2) 10,000\n3) 100,000\n4) 1,000,000\n5) กำหนดเอง เช่น 25k, 2m")
        choice = input("เลือก [2]: ").strip()
        if choice == "":
            choice = "2"
        if choice in choices:
            return choices[choice]
        if choice == "5":
            try:
                return parse_count(input("จำนวน: "))
            except ValueError as error:
                print(error)
        else:
            print("กรุณาเลือก 1-5")


def default_input(prompt, default):
    value = input(prompt).strip()
    if value == "":
        return str(default)
    return value


def menu(output_root):
    choices = {}
    number = 1
    for name in lab.SCENARIOS:
        choices[str(number)] = name
        number += 1
    while True:
        print("\n" + "=" * 72 + "\nPERSONAL FINANCE TEST LAB\n" + "=" * 72)
        for number, name in choices.items():
            print(f"{number}) {lab.SCENARIOS[name]}")
        print("0) ออก")
        try:
            choice = input("เลือกชุดทดสอบ: ").strip()
            if choice == "0":
                return 0
            if choice not in choices:
                print("กรุณาเลือก 0-8")
                continue
            scenario = choices[choice]
            count = 1000
            if scenario in ("insert", "dataset", "mixed", "report", "corruption"):
                count = ask_count()
            sizes = [1000, 10000, 100000, 1000000]
            if scenario == "scale":
                sizes = parse_sizes(default_input("ขนาดที่เปรียบเทียบ [1k,10k,100k,1m]: ", "1k,10k,100k,1m"))
            default_timeout = 300
            if scenario in ("insert", "mixed"):
                default_timeout = 60
            timeout = nonnegative_time(default_input(f"เวลาสูงสุด [{default_timeout}] วินาที; 0 ไม่จำกัด: ", default_timeout))
            seed = int(default_input("Random seed [42]: ", 42))
            config = lab.make_config(scenario, count, seed, timeout, sizes=sizes)
            launch(config, output_root)
            input("\nกด Enter เพื่อกลับเมนู...")
        except ValueError as error:
            print("ข้อมูลไม่ถูกต้อง: " + str(error))
        except (EOFError, KeyboardInterrupt):
            print("\nปิดชุดทดสอบ")
            return 0


def main():
    configure_utf8_console()
    try:
        options = read_options(sys.argv[1:])
        if options["help"]:
            print("python stress_test.py เพื่อเปิดเมนู")
            print("--scenario unit/insert/dataset/mixed/validation/corruption/report/scale")
            print("--count 10k --timeout 300 --seed 42 --samples 3 --mutations 2")
            print("--sizes 1k,10k,100k,1m --output-root folder")
            return 0
        if options["scenario"] is None:
            return menu(options["output_root"])
        config = lab.make_config(options["scenario"], options["count"], options["seed"],
            options["timeout"], options["samples"], options["mutations"], options["sizes"])
        code, root, result = launch(config, options["output_root"])
        return code
    except (ValueError, OSError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
