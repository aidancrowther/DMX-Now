/**
 * Feature 5: Wireless DMX universe transmitter test
 * Broadcasts deterministic 512-byte universes via QuickESPNow broadcast.
 *
 * Each universe is split into DMX_FRAGMENTS_PER_UNIVERSE (3) fragments.
 * A frame is fully "sent" once all 3 fragments have been transmitted and the
 * QuickESPNow TX queue has drained (confirmed via the onDataSent callback).
 * The frame sequence increments after each complete frame so the receiver can
 * observe a varying (but still deterministic) payload pattern.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* Single canonical protocol definition shared with the receiver
 * (WirelessDMX library, pinned by the build via --library). */
#include <wireless_protocol.h>

/* --------------------------------------------------------------------------
 * TEST HOOK CONFIG (Feature 6) — ALL DEFAULT OFF.
 * To run a fault-injection test, uncomment (or add) exactly ONE mode below,
 * then build/flash with the existing script (./flash_espnow_tx.sh, add -f to
 * flash). With this block EMPTY the transmitter is the known-good Feature 5
 * behavior (slots {0,1,2}, no corruption, sequence starts at 0).
 *
 *   #define TEST_DROP_FRAGMENT_INDEX      1   // omit fragment 1 (middle) each frame
 *   #define TEST_DUPLICATE_FRAGMENT_INDEX 1   // send fragment 1 twice each frame
 *   #define TEST_REORDER_FRAGMENTS                 // transmit order 2,0,1
 *   #define TEST_CORRUPT_FRAGMENT_INDEX   1   // corrupt one payload byte of fragment 1
 *   #define TEST_CORRUPT_BYTE             0   // (optional) which payload byte (0-based)
 *   #define TEST_FORCE_SEQUENCE_START     42  // start the frame sequence at 42
 *   #define TEST_SEQUENCE_WRAP                     // start at 0xFFFFFFFE (rollover)
 *
 * After testing, remove the #define (restore this block to empty) and
 * re-run ./flash_espnow_tx.sh. Do NOT leave a fault mode enabled.
 * -------------------------------------------------------------------------- */

/* Static universe buffer (the latest generated snapshot). */
static uint8_t g_universe[DMX_UNIVERSE_SIZE];

/* Sequence number for the current frame (incremented after a full frame). */
static uint32_t g_frameSequence = 0;

/* Fragment-send confirmations received for the in-flight frame (0..fragCount). */
static volatile uint8_t g_sendConfirmations = 0;

/* --------------------------------------------------------------------------
 * Feature 6 TEST HOOKS (all compile-time, DEFAULT OFF).
 * Enabling any of these changes only the TX test behavior so the receiver's
 * reconstruction / double buffering can be exercised robustly. With NONE
 * defined the transmitter is the known-good Feature 5 behavior: slots {0,1,2},
 * count 3, no corruption, sequence starts at 0.
 *
 *   TEST_DROP_FRAGMENT_INDEX       omit this fragment (0/1/2) each frame
 *   TEST_DUPLICATE_FRAGMENT_INDEX  send this fragment twice each frame
 *   TEST_REORDER_FRAGMENTS         transmit in order 2,0,1
 *   TEST_CORRUPT_FRAGMENT_INDEX    corrupt one payload byte of this fragment
 *   TEST_CORRUPT_BYTE              (optional) which payload byte (0-based)
 *   TEST_FORCE_SEQUENCE_START      start the frame sequence at this value
 *   TEST_SEQUENCE_WRAP             start at 0xFFFFFFFE to exercise rollover
 * -------------------------------------------------------------------------- */

/* Per-frame send slot list: ordered fragment indices to transmit.
 * Default (no hooks) = {0,1,2}, count 3. A duplicate appends a 4th slot. */
static uint8_t txSlotList[DMX_FRAGMENTS_PER_UNIVERSE + 1];
static uint8_t txSlotCount = DMX_FRAGMENTS_PER_UNIVERSE;

/* Generate the deterministic test universe: g_universe[i] = (i + seq) & 0xFF. */
void generateTestUniverse(uint32_t seq) {
    for (uint16_t i = 0; i < DMX_UNIVERSE_SIZE; ++i) {
        g_universe[i] = static_cast<uint8_t>((static_cast<uint32_t>(i) + seq) & 0xFF);
    }
}

/* Build the per-frame send slot list from the (compile-time) test hooks.
 * Default (no hooks) = fragments 0,1,2 in order. A drop removes a slot; a
 * duplicate appends a 4th slot; reorder changes the order. */
static void buildTxSlotList(void) {
    uint8_t order[DMX_FRAGMENTS_PER_UNIVERSE];
    uint8_t n = 0;
#if defined(TEST_REORDER_FRAGMENTS)
    order[n++] = 2; order[n++] = 0; order[n++] = 1;
#else
    for (uint8_t i = 0; i < DMX_FRAGMENTS_PER_UNIVERSE; i++) order[n++] = i;
#endif

    uint8_t m = 0;
    for (uint8_t k = 0; k < n; k++) {
        const uint8_t idx = order[k];
#if defined(TEST_DROP_FRAGMENT_INDEX)
        if (idx == TEST_DROP_FRAGMENT_INDEX) continue;
#endif
        txSlotList[m++] = idx;
    }
#if defined(TEST_DUPLICATE_FRAGMENT_INDEX)
    txSlotList[m++] = TEST_DUPLICATE_FRAGMENT_INDEX;
#endif
    txSlotCount = m;
}

/*
 * Build one fragment (14-byte packed header + channel payload) and broadcast
 * it at its true size (14 + payloadLength). The library copies the buffer
 * into the TX queue, so reusing a single stack buffer for all fragments is safe.
 */
static void submitFragment(uint32_t seq, uint8_t fragIdx) {
    const uint16_t offset = static_cast<uint16_t>(fragIdx) * DMX_PAYLOAD_SIZE;
    const uint8_t payloadLength = dmx_fragment_payload_length(offset, DMX_UNIVERSE_SIZE);

    /* Fixed-size buffer for the full (header + max payload) packet. */
    uint8_t packetBuffer[DMX_TOTAL_PACKET_SIZE];

    DmxFragmentPacket pkt;
    pkt.magic           = DMX_PACKET_MAGIC;
    pkt.protocolVersion = DMX_PROTO_VERSION;
    pkt.packetType      = DMX_PACKET_TYPE;
    pkt.universeId      = DMX_UNIVERSE_ID;
    pkt.frameSequence   = seq;
    pkt.fragmentIndex   = fragIdx;
    pkt.fragmentCount   = DMX_FRAGMENTS_PER_UNIVERSE;
    pkt.dataOffset      = offset;
    pkt.payloadLength   = payloadLength;

    /* Serialize the packed 14-byte header. */
    memcpy(packetBuffer, &pkt, sizeof(pkt));

    /* Copy this fragment's channel payload immediately after the header. */
    uint8_t* pPayload = packetBuffer + DMX_HEADER_SIZE;
    for (uint16_t i = 0; i < payloadLength; ++i) {
        const uint16_t universeIndex = static_cast<uint16_t>(offset) + i;
        pPayload[i] = (universeIndex < DMX_UNIVERSE_SIZE) ? g_universe[universeIndex] : 0;
    }

#if defined(TEST_CORRUPT_FRAGMENT_INDEX)
    /* TEST-ONLY: corrupt one payload byte of the targeted fragment. Metadata
     * stays valid; the receiver's full 512-byte integrity check must fail. */
    if (fragIdx == TEST_CORRUPT_FRAGMENT_INDEX) {
        uint8_t corruptAt = 0;
#ifdef TEST_CORRUPT_BYTE
        corruptAt = TEST_CORRUPT_BYTE;
#endif
        if (corruptAt >= payloadLength) corruptAt = 0;
        const uint16_t uIdx = static_cast<uint16_t>(offset + corruptAt);
        pPayload[corruptAt] = static_cast<uint8_t>(g_universe[uIdx] ^ 0xFF);
        Serial.printf("TX CORRUPT seq=%u frag=%d byte=%u -> 0x%02X\n",
                      seq, fragIdx, corruptAt, pPayload[corruptAt]);
    }
#endif

    Serial.printf("TX FRAG seq=%u frag=%d/%d offset=%u len=%u\n",
                  seq, fragIdx + 1, DMX_FRAGMENTS_PER_UNIVERSE, offset, payloadLength);

    /* Broadcast at the fragment's true size (not always the max). */
    const uint16_t totalSize = static_cast<uint16_t>(DMX_HEADER_SIZE + payloadLength);
    quickEspNow.sendBcast(packetBuffer, totalSize);

    Serial.printf("TX FRAG queued seq=%u frag=%d total=%u\n", seq, fragIdx + 1, totalSize);
}

void setup(void) {
    Serial.begin(115200);
    Serial.println();
    Serial.print("Feature 5 TX starting");
    Serial.print(", channel=");
    Serial.println(ESPNOW_CHANNEL);

    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);

    if (!quickEspNow.begin(ESPNOW_CHANNEL, WIFI_IF_STA, false)) {
        Serial.println("Failed to initialize QuickESPNow");
        while (true) delay(10);
    }

    /* Count per-fragment send confirmations. Kept free of Serial: it may run
     * from the QuickESPNow ETSTimer task. */
    quickEspNow.onDataSent([](uint8_t* dstMac, uint8_t status) {
        (void)dstMac;
        (void)status;
        if (g_sendConfirmations < 255) {
            g_sendConfirmations++;
        }
    });

    {
        uint8_t macBuffer[6];
        WiFi.macAddress(macBuffer);
        char macStr[18];
        snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
                 macBuffer[0], macBuffer[1], macBuffer[2],
                 macBuffer[3], macBuffer[4], macBuffer[5]);
        Serial.print("Own MAC: ");
        Serial.println(macStr);
    }

    /* TEST HOOKS: initialize the frame sequence (default 0). */
#if defined(TEST_SEQUENCE_WRAP)
    g_frameSequence = 0xFFFFFFFEUL;
#elif defined(TEST_FORCE_SEQUENCE_START)
    g_frameSequence = TEST_FORCE_SEQUENCE_START;
#endif

    /* TEST HOOKS: build the per-frame send slot list (default {0,1,2}). */
    buildTxSlotList();

    delay(500);

    Serial.println();
    Serial.printf("TX ready seq=%u\n", g_frameSequence);
    Serial.printf("refresh=%uHz\n", WIRELESS_REFRESH_HZ);
    Serial.printf("header=%d payload=%d total=%d frags=%d\n",
                  static_cast<int>(DMX_HEADER_SIZE),
                  static_cast<int>(DMX_PAYLOAD_SIZE),
                  static_cast<int>(DMX_TOTAL_PACKET_SIZE),
                  static_cast<int>(DMX_FRAGMENTS_PER_UNIVERSE));
    Serial.printf("slots=%d", txSlotCount);
    for (uint8_t i = 0; i < txSlotCount; i++) {
        Serial.printf(" %u", txSlotList[i]);
    }
    Serial.println();
    if (txSlotCount != DMX_FRAGMENTS_PER_UNIVERSE) {
        Serial.println("NOTE: TEST hook active (slot list differs from default {0,1,2})");
    }
}

/* --------------------------------------------------------------------------
 * Non-blocking frame state machine:
 *   IDLE -> GENERATE -> SEND(all fragments) -> DRAIN(queue empty) -> IDLE
 * -------------------------------------------------------------------------- */
enum TxState { TX_IDLE, TX_GENERATING, TX_SENDING, TX_DRAIN };
static TxState txState = TX_IDLE;
static unsigned long lastFrameGenerationTime = 0;
static unsigned long stateEnteredTime = 0;
static uint8_t currentFragment = 0;

/* Safety bound so a stuck queue cannot wedge the state machine. */
const unsigned long TX_DRAIN_TIMEOUT_MS = 200UL;

void loop(void) {
    const unsigned long now = millis();

    switch (txState) {
        case TX_IDLE:
            if (now - lastFrameGenerationTime >= WIRELESS_REFRESH_INTERVAL_MS) {
                txState = TX_GENERATING;
                stateEnteredTime = now;
                Serial.println("TX GENERATE: starting new frame");
            }
            break;

        case TX_GENERATING:
            generateTestUniverse(g_frameSequence);
            currentFragment = 0;
            g_sendConfirmations = 0;   /* reset before the sends so all are counted */
            Serial.printf("TX FRAME seq=%u fragments=%u\n",
                          g_frameSequence, txSlotCount);
            txState = TX_SENDING;
            stateEnteredTime = now;
            break;

        case TX_SENDING:
            if (currentFragment < txSlotCount) {
                submitFragment(g_frameSequence, txSlotList[currentFragment]);
                currentFragment++;
            } else {
                /* All fragments queued - wait for the queue to drain. */
                txState = TX_DRAIN;
                stateEnteredTime = now;
            }
            break;

        case TX_DRAIN:
            if (g_sendConfirmations >= txSlotCount ||
                (now - stateEnteredTime >= TX_DRAIN_TIMEOUT_MS)) {
                /* Frame fully transmitted; advance to the next one. */
                g_frameSequence++;
                txState = TX_IDLE;
                lastFrameGenerationTime = now;
                Serial.printf("TX FRAME complete seq=%u, next seq=%u\n",
                              g_frameSequence, g_frameSequence + 1);
            }
            break;
    }
}
