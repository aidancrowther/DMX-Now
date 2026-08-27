#!/usr/bin/env python3
"""Updates the Feature 6 section of README.md to document the --define test
hooks (incl. the new TEST_DELAYED_FRAGMENT TX hook) and the corrected test plan.
Each replacement asserts exactly one occurrence.
"""
import sys

PATH = "README.md"

def apply(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        print(f"ABORT [{label}]: pattern occurred {n} times (expected 1)")
        sys.exit(1)
    return src.replace(old, new)

with open(PATH, "r") as f:
    s = f.read()

# 1. Compile Verification: document the --define hook workflow.
s = apply(
    s,
    "### Compile Verification\n"
    "Both sketches compile successfully via the existing scripts (compile-only, no flash):\n"
    "  ```bash\n"
    "  ./flash_espnow_tx.sh   # compile only\n"
    "  ./flash_espnow_rx.sh   # compile only\n"
    "  ```\n"
    "Use `./flash_espnow_tx.sh -f` and `./flash_espnow_rx.sh -f` to compile and flash.\n",
    "### Compile Verification\n"
    "Both sketches compile successfully via the existing scripts (compile-only, no flash):\n"
    "  ```bash\n"
    "  ./flash_espnow_tx.sh   # compile only\n"
    "  ./flash_espnow_rx.sh   # compile only\n"
    "  ```\n"
    "Use `./flash_espnow_tx.sh -f` and `./flash_espnow_rx.sh -f` to compile and flash.\n"
    "\n"
    "### Test Hooks (Feature 6 fault injection, all DEFAULT OFF)\n"
    "Test hooks are compile-time defines passed to the flash scripts with `--define` (added\n"
    "to `build.extra_flags`); hook code is compiled out when the define is absent:\n"
    "  ```bash\n"
    "  ./flash_espnow_tx.sh --define -DTEST_DROP_FRAGMENT_INDEX=1\n"
    "  ./flash_espnow_tx.sh --define -DTEST_DUPLICATE_FRAGMENT_INDEX=1\n"
    "  ./flash_espnow_tx.sh --define -DTEST_REORDER_FRAGMENTS\n"
    "  ./flash_espnow_tx.sh --define -DTEST_CORRUPT_FRAGMENT_INDEX=1\n"
    "  ./flash_espnow_tx.sh --define -DTEST_DELAYED_FRAGMENT\n"
    "  ./flash_espnow_tx.sh --define -DTEST_SEQUENCE_WRAP\n"
    "  ./flash_espnow_rx.sh --define -DTEST_INJECT_MALFORMED\n"
    "  ```\n"
    "  - `TEST_DELAYED_FRAGMENT` (TX, Test 6): after each frame, holds ~2.5 s then re-sends one\n"
    "    fragment of the already-active frame, so the receiver must classify it STALE.\n"
    "  - `TEST_INJECT_MALFORMED` (RX, Test 8): at startup feeds one structurally-malformed\n"
    "    packet through the receiver's own validation path (no RF required).\n",
    "README: test hooks subsection",
)

# 2. Testing Plan: reference the executable --define workflow + 12 tests.
s = apply(
    s,
    "### Feature 6 Testing Plan\n"
    "A comprehensive testing plan exists at `tests/FEATURE6_TEST_PLAN.md`. It documents 12 tests covering: normal frame reception, dropped fragments, duplicate/reorder handling, late/stale fragments, corrupted payloads, malformed metadata, mid-stream startup, transmitter reset recovery, sequence rollover, and multiple receivers.\n",
    "### Feature 6 Testing Plan\n"
    "A comprehensive testing plan exists at `tests/FEATURE6_TEST_PLAN.md`. It documents 12 tests — normal frame reception, dropped fragments (middle/final), duplicate, reorder, late/stale fragment, corrupted payload, malformed metadata, mid-stream startup, transmitter reset re-baseline, uint32 sequence rollover, and multiple receivers. Each test lists the exact `--define` build setting(s) and the expected RX serial output/counter deltas (see the Test Hooks section above for the hook list).\n",
    "README: testing plan subsection",
)

with open(PATH, "w") as f:
    f.write(s)
print("README Feature 6 section updated")
