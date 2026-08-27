#!/usr/bin/env python3
"""Adds a --define option to both flash_espnow_{rx,tx}.sh scripts so the
Feature 6 test hooks (and TEST_INJECT_MALFORMED) can be enabled via the
script:  ./flash_espnow_tx.sh --define -DTEST_DELAYED_FRAGMENT

Each replacement asserts exactly one occurrence per file.
"""
import os
import sys

def apply(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        print(f"ABORT [{label}]: pattern occurred {n} times (expected 1)")
        sys.exit(1)
    return src.replace(old, new)

for PATH in ("flash_espnow_rx.sh", "flash_espnow_tx.sh"):
    NAME = os.path.basename(PATH)           # e.g. flash_espnow_rx.sh
    OTHER = "tx" if "rx" in PATH else "rx"  # the sibling script's test hook
    HOOK = "TEST_DELAYED_FRAGMENT" if "tx" in PATH else "TEST_INJECT_MALFORMED"

    with open(PATH, "r") as f:
        s = f.read()

    # 1. Usage comment: document the new option.
    s = apply(
        s,
        f'#   ./{NAME} --port "/dev/ttyUSB1" -f\n',
        f'#   ./{NAME} --port "/dev/ttyUSB1" -f\n'
        f'#   ./{NAME} --define -D{HOOK}          # enable a test hook (Feature 6)\n',
        f"{PATH}: usage comment",
    )

    # 2. Defaults: initialize the flags array.
    s = apply(
        s,
        'PORT="/dev/ttyUSB0"\nFLASH=false\n',
        'PORT="/dev/ttyUSB0"\nFLASH=false\nEXTRA_FLAGS=()   # extra -D defines (e.g. Feature 6 test hooks)\n',
        f"{PATH}: EXTRA_FLAGS default",
    )

    # 3. Arg parsing: accept --define VALUE and --define=VALUE.
    s = apply(
        s,
        "        --)\n            shift\n            break\n            ;;\n",
        "        --define)\n            if [[ $# -lt 2 ]]; then\n"
        "                echo \"Error: --define requires a value\" >&2\n"
        "                exit 1\n"
        "            fi\n"
        "\n"
        "            EXTRA_FLAGS+=(\"$2\")\n"
        "            shift 2\n"
        "            ;;\n"
        "\n"
        "        --define=*)\n"
        "            EXTRA_FLAGS+=(\"${1#--define=}\")\n"
        "            shift\n"
        "            ;;\n"
        "\n"
        "        --)\n            shift\n            break\n            ;;\n",
        f"{PATH}: arg parsing",
    )

    # 4. Banner: show the active defines.
    s = apply(
        s,
        'echo "Flash after compile: ${FLASH}"\necho "=============================================="\n',
        'echo "Flash after compile: ${FLASH}"\n'
        'if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then\n'
        '    echo "Extra defines: ${EXTRA_FLAGS[*]}"\n'
        'fi\necho "=============================================="\n',
        f"{PATH}: banner",
    )

    # 5. Compile command: inject build.extra_flags only when defines are set.
    s = apply(
        s,
        'COMPILE_CMD=(\n    "$ARDUINO_CLI"\n    compile\n    -b "esp8266:esp8266:generic"\n'
        '    --library "$LIBRARY_DIR"\n    --library "$PROTOCOL_LIB"\n'
        '    "$SKETCH_DIR"\n    -e\n)\n',
        'COMPILE_CMD=(\n    "$ARDUINO_CLI"\n    compile\n    -b "esp8266:esp8266:generic"\n'
        '    --library "$LIBRARY_DIR"\n    --library "$PROTOCOL_LIB"\n'
        ')\nif [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then\n'
        '    COMPILE_CMD+=( --build-property "build.extra_flags= ${EXTRA_FLAGS[*]}" )\n'
        'fi\nCOMPILE_CMD+=( "$SKETCH_DIR" -e )\n',
        f"{PATH}: compile command",
    )

    with open(PATH, "w") as f:
        f.write(s)
    print(f"OK: {PATH} updated")

print("ALL SCRIPTS UPDATED")
