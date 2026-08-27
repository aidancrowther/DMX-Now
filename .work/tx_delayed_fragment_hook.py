#!/usr/bin/env python3
"""Applies the TEST_DELAYED_FRAGMENT hook edits to tests/espnow_universe_tx/espnow_universe_tx.ino.

Each replacement asserts exactly one occurrence, so a mismatch aborts cleanly
instead of corrupting the file.
"""
import sys

PATH = "tests/espnow_universe_tx/espnow_universe_tx.ino"

def apply(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        print(f"ABORT: pattern for '{label}' occurred {n} times (expected 1)")
        sys.exit(1)
    print(f"OK: {label}")
    return src.replace(old, new)

with open(PATH, "r") as f:
    s = f.read()

# ---------------------------------------------------------------- Edit A
# Block-1 config comment: tighten wording (already present from earlier edit).
s = apply(
    s,
    " *   #define TEST_DELAYED_FRAGMENT                    // hold fragment 3 for >2.5 s (late fragment)\n",
    " *   #define TEST_DELAYED_FRAGMENT                    // transmit one fragment ~2.5 s late (stale test)\n",
    "A: block-1 comment wording",
)

# ---------------------------------------------------------------- Edit B
# Block-2 hook list: document the new hook.
s = apply(
    s,
    " *   TEST_FORCE_SEQUENCE_START      start the frame sequence at this value\n"
    " *   TEST_SEQUENCE_WRAP             start at 0xFFFFFFFE to exercise rollover\n"
    " * -------------------------------------------------------------------------- */\n",
    " *   TEST_FORCE_SEQUENCE_START      start the frame sequence at this value\n"
    " *   TEST_SEQUENCE_WRAP             start at 0xFFFFFFFE to exercise rollover\n"
    " *   TEST_DELAYED_FRAGMENT          transmit one fragment of each frame ~2.5 s late (stale fragment)\n"
    " * -------------------------------------------------------------------------- */\n",
    "B: block-2 hook list",
)

# ---------------------------------------------------------------- Edit C
# State enum + guarded late-fragment globals/constant.
s = apply(
    s,
    "enum TxState { TX_IDLE, TX_GENERATING, TX_SENDING, TX_DRAIN };\n"
    "static TxState txState = TX_IDLE;\n"
    "static unsigned long lastFrameGenerationTime = 0;\n"
    "static unsigned long stateEnteredTime = 0;\n"
    "static uint8_t currentFragment = 0;\n"
    "\n"
    "/* Safety bound so a stuck queue cannot wedge the state machine. */\n"
    "const unsigned long TX_DRAIN_TIMEOUT_MS = 200UL;\n",
    "enum TxState {\n"
    "    TX_IDLE,\n"
    "    TX_GENERATING,\n"
    "    TX_SENDING,\n"
    "    TX_DRAIN\n"
    "#if defined(TEST_DELAYED_FRAGMENT)\n"
    "    , TX_LATE\n"
    "#endif\n"
    "};\n"
    "static TxState txState = TX_IDLE;\n"
    "static unsigned long lastFrameGenerationTime = 0;\n"
    "static unsigned long stateEnteredTime = 0;\n"
    "static uint8_t currentFragment = 0;\n"
    "\n"
    "/* Safety bound so a stuck queue cannot wedge the state machine. */\n"
    "const unsigned long TX_DRAIN_TIMEOUT_MS = 200UL;\n"
    "\n"
    "/* TEST HOOK (Feature 6, Test 6): late-fragment state. */\n"
    "#if defined(TEST_DELAYED_FRAGMENT)\n"
    "static bool     lateSent = false;\n"
    "static uint32_t lateSeq  = 0;\n"
    "/* Hold the late fragment until this long after the frame completed.\n"
    " * Chosen > the receiver's STAGING_TIMEOUT_MS (2000 ms) yet < its\n"
    " * TRANSMITTER_RESET_RECOVERY_MS (3000 ms), so the receiver classifies\n"
    " * the late fragment as STALE (live link) rather than as a re-baseline. */\n"
    "static const unsigned long TEST_DELAYED_FRAGMENT_DELAY_MS = 2500UL;\n"
    "#endif\n",
    "C: enum + guarded globals",
)

# ---------------------------------------------------------------- Edit D
# DRAIN case: branch into TX_LATE when the hook is enabled.
s = apply(
    s,
    "        case TX_DRAIN:\n"
    "            if (g_sendConfirmations >= txSlotCount ||\n"
    "                (now - stateEnteredTime >= TX_DRAIN_TIMEOUT_MS)) {\n"
    "                /* Frame fully transmitted; advance to the next one. */\n"
    "                g_frameSequence++;\n"
    "                txState = TX_IDLE;\n"
    "                lastFrameGenerationTime = now;\n"
    "                Serial.printf(\"TX FRAME complete seq=%u, next seq=%u\\n\",\n"
    "                              g_frameSequence, g_frameSequence + 1);\n"
    "            }\n"
    "            break;\n",
    "        case TX_DRAIN:\n"
    "            if (g_sendConfirmations >= txSlotCount ||\n"
    "                (now - stateEnteredTime >= TX_DRAIN_TIMEOUT_MS)) {\n"
    "                /* Frame fully transmitted; advance to the next one. */\n"
    "                g_frameSequence++;\n"
    "                lastFrameGenerationTime = now;\n"
    "#if defined(TEST_DELAYED_FRAGMENT)\n"
    "                /* TEST HOOK (Test 6): schedule one late fragment of the\n"
    "                 * frame we just completed. The receiver must flag it\n"
    "                 * STALE (older-or-equal than active, link still live). */\n"
    "                lateSeq = g_frameSequence - 1;\n"
    "                lateSent = false;\n"
    "                txState = TX_LATE;\n"
    "                stateEnteredTime = now;\n"
    "                Serial.println(\"TX LATE: scheduling delayed fragment\");\n"
    "#else\n"
    "                txState = TX_IDLE;\n"
    "                Serial.printf(\"TX FRAME complete seq=%u, next seq=%u\\n\",\n"
    "                              g_frameSequence, g_frameSequence + 1);\n"
    "#endif\n"
    "            }\n"
    "            break;\n",
    "D: DRAIN case branch",
)

# ---------------------------------------------------------------- Edit E
# Add the TX_LATE case at the end of the switch.
s = apply(
    s,
    "                Serial.println(\"TX LATE: scheduling delayed fragment\");\n"
    "#else\n"
    "                txState = TX_IDLE;\n"
    "                Serial.printf(\"TX FRAME complete seq=%u, next seq=%u\\n\",\n"
    "                              g_frameSequence, g_frameSequence + 1);\n"
    "#endif\n"
    "            }\n"
    "            break;\n"
    "    }\n"
    "}\n",
    "                Serial.println(\"TX LATE: scheduling delayed fragment\");\n"
    "#else\n"
    "                txState = TX_IDLE;\n"
    "                Serial.printf(\"TX FRAME complete seq=%u, next seq=%u\\n\",\n"
    "                              g_frameSequence, g_frameSequence + 1);\n"
    "#endif\n"
    "            }\n"
    "            break;\n"
    "#if defined(TEST_DELAYED_FRAGMENT)\n"
    "        case TX_LATE:\n"
    "            if (!lateSent) {\n"
    "                /* Hold, then transmit one fragment of the previous frame. */\n"
    "                if ((now - stateEnteredTime) >= TEST_DELAYED_FRAGMENT_DELAY_MS) {\n"
    "                    g_sendConfirmations = 0; /* count only the late send */\n"
    "                    submitFragment(lateSeq, 0);\n"
    "                    lateSent = true;\n"
    "                    stateEnteredTime = now;\n"
    "                    Serial.println(\"TX LATE: transmitted delayed fragment of previous frame\");\n"
    "                }\n"
    "            } else if (g_sendConfirmations >= 1 ||\n"
    "                       (now - stateEnteredTime) >= TX_DRAIN_TIMEOUT_MS) {\n"
    "                txState = TX_IDLE;\n"
    "                Serial.println(\"TX LATE: complete, resuming normal frames\");\n"
    "            }\n"
    "            break;\n"
    "#endif\n"
    "    }\n"
    "}\n",
    "E: TX_LATE case",
)

with open(PATH, "w") as f:
    f.write(s)

print("ALL EDITS APPLIED")
