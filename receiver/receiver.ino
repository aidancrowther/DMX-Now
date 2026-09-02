/**
 * Integrated Wireless DMX Receiver (QuickESPNow RX -> DMX output)
 *
 * Combines the two previously-verified halves into one sketch:
 *   - QuickESPNow broadcast reception + Feature 6 reconstruction/double
 *     buffering (from tests/espnow_universe_rx), with all Serial logging
 *     removed (UART0 is owned by espDMX once dmxA.begin() runs).
 *   - espDMX physical output on UART0/GPIO1 + MAX3485 driver-enable control
 *     (from the original receiver.ino).
 *
 * Data path:
 *   QuickESPNow fragment (ROM timer callback)
 *     -> bounded SPSC handoff ring
 *     -> loop(): validate, assemble into staging, wrap-safe sequence check
 *     -> on COMPLETE + integrity pass: pointer-swap promote to active
 *     -> dmxA.setChans(active)   (espDMX copies into its own buffer)
 *     -> espDMX self-refreshes the last active universe continuously.
 *   - Low-rate ReceiverTelemetryPacket broadcast with deterministic phase and
 *     bounded retry backoff so multiple receivers do not transmit together.
 *
 * MAX3485 driver enable (GPIO2 via inverting 2N2222):
 *   GPIO2 HIGH -> transistor ON  -> DE LOW  -> DMX output DISABLED
 *   GPIO2 LOW  -> transistor OFF -> DE HIGH -> DMX output ENABLED
 *   Kept disabled during boot/init; enabled once after safe init and left on.
 *
 * NOTE: espDMX dmx_init() calls system_set_os_print(0) +
 * ets_install_putc1(&uart_ignore_char), so the Serial console is dead after
 * dmxA.begin(). No Serial logging is performed in this sketch.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* Single canonical protocol definition shared with the transmitter. */
#include <wireless_protocol.h>

#include <espDMX.h>

/* --------------------------------------------------------------------------
 * Receiver pins (fixed hardware allocation)
 * -------------------------------------------------------------------------- */
static const int PIN_DMX_DATA    = 1; // GPIO1 / UART0 TX -> DMX data / MAX3485 DI
static const int PIN_DMX_ENABLE  = 2; // GPIO2 -> MAX3485 DE via inverting 2N2222
static const int PIN_BATTERY_LOW = 3; // GPIO3 -> HIGH when battery is low

/* --------------------------------------------------------------------------
 * Reconstruction configuration
 * -------------------------------------------------------------------------- */
/* Abandon a partially assembled staging frame after this much silence. */
static const unsigned long STAGING_TIMEOUT_MS = 2000UL;

/* Permit an "older" sequence to establish a new baseline only after the
 * wireless link has had no accepted fragment for this long (transmitter
 * restarted). Chosen as 3x the 1 Hz refresh period so a live link never
 * falsely re-baselines. Wrap-safe via millis(). */
static const unsigned long TRANSMITTER_RESET_RECOVERY_MS = 3000UL;

/* Telemetry is intentionally low priority and approximately 4-5 seconds apart.
 * The per-receiver phase and per-cycle jitter spread simultaneous receivers. */
#ifndef TELEMETRY_PERIOD_MS
#define TELEMETRY_PERIOD_MS 4000UL
#endif
#ifndef TELEMETRY_JITTER_MS
#define TELEMETRY_JITTER_MS 1000UL
#endif
#ifndef TELEMETRY_RETRY_BACKOFF_MS
#define TELEMETRY_RETRY_BACKOFF_MS 250UL
#endif
#define TELEMETRY_FIRMWARE_VERSION 1U

/* Battery comparator filtering.  Override either value with a compiler
 * definition when a different hardware debounce period is required. */
#ifndef BATTERY_LOW_ASSERT_MS
#define BATTERY_LOW_ASSERT_MS 2000UL
#endif
#ifndef BATTERY_LOW_CLEAR_MS
#define BATTERY_LOW_CLEAR_MS 5000UL
#endif

/* Bounded callback->loop handoff ring. One more than QuickESPNow's own RX
 * queue depth (ESPNOW_QUEUE_SIZE = 3), so a tight 3-fragment burst is never
 * dropped by our own architecture. Static, bounded, no dynamic allocation. */
static const uint8_t RX_RING_SIZE = 4;
static const uint8_t RX_SLOT_MAX  = ESPNOW_MAX_MESSAGE_LENGTH; /* 255 */

/* --------------------------------------------------------------------------
 * Universe storage: exactly two 512-byte buffers, promoted by pointer swap.
 * -------------------------------------------------------------------------- */
static uint8_t universeBufferA[DMX_UNIVERSE_SIZE];
static uint8_t universeBufferB[DMX_UNIVERSE_SIZE];

static uint8_t* stagingUniverse = universeBufferA; /* frame being assembled  */
static uint8_t* activeUniverse  = universeBufferB; /* last complete universe */

/* --------------------------------------------------------------------------
 * Callback -> loop handoff ring (single producer / single consumer).
 *   Producer : dataReceived() callback (ROM timer context)
 *   Consumer : loop()
 * Guarded by noInterrupts()/interrupts() (the core xt_rsil critical section).
 * -------------------------------------------------------------------------- */
struct RxFragSlot {
    uint8_t payload[RX_SLOT_MAX];
    uint8_t len;
    int8_t  rssi;
};
static RxFragSlot rxRing[RX_RING_SIZE];
static volatile uint8_t ringHead = 0; /* written only by the callback */
static volatile uint8_t ringTail = 0; /* written only by loop()       */

/* --------------------------------------------------------------------------
 * Staging (reconstruction) state — owned exclusively by loop().
 * -------------------------------------------------------------------------- */
static bool     stagingActive         = false;
static uint32_t stagingSequence       = 0;
static uint8_t  stagingFragmentCount  = 0;
static uint32_t stagingReceivedMask   = 0; /* bit per fragment index       */
static uint8_t  stagingUniqueCount    = 0;
static uint8_t  stagingCoverage[DMX_UNIVERSE_SIZE / 8]; /* 512 coverage bits */
static unsigned long stagingLastActivityMs = 0;

/* Active-universe state — owned exclusively by loop(). */
static bool     hasActiveWirelessFrame     = false; /* a complete frame accepted */
static uint32_t lastActiveSequence         = 0;
static unsigned long lastCompletionTimeMs  = 0;
static unsigned long lastAcceptedFragmentTimeMs = 0; /* drives reset recovery */
static int8_t   lastRssi = 0;

/* Battery monitor state — owned exclusively by loop(). */
static bool batteryLow = false;
static bool batteryInputHigh = false;
static unsigned long batteryInputChangedMs = 0;

static void updateBatteryLow(void) {
    const bool inputHigh = (digitalRead(PIN_BATTERY_LOW) == HIGH);
    const unsigned long now = millis();

    if (inputHigh != batteryInputHigh) {
        batteryInputHigh = inputHigh;
        batteryInputChangedMs = now;
    }

    const unsigned long requiredMs = inputHigh ? BATTERY_LOW_ASSERT_MS
                                               : BATTERY_LOW_CLEAR_MS;
    if ((now - batteryInputChangedMs) < requiredMs) return;

    if (batteryLow != inputHigh) {
        batteryLow = inputHigh;
    }
}

/* --------------------------------------------------------------------------
 * Diagnostic counters — local only, no telemetry (usable for future telemetry).
 * -------------------------------------------------------------------------- */
static unsigned long packetsReceived        = 0;
static unsigned long malformedFragments     = 0;
static unsigned long validFragmentsAccepted = 0;
static unsigned long duplicateFragments     = 0;
static unsigned long staleFragments         = 0;
static unsigned long abandonedIncomplete    = 0;
static unsigned long abandonedTimeout       = 0;
static unsigned long completeUniverses      = 0;
static unsigned long integrityFailures      = 0;
static unsigned long rxRingOverflow         = 0;
static unsigned long resetRebaselined       = 0;

/* Telemetry scheduling and identity.  These values are collected in loop()
 * context; no telemetry work is performed by the receive callback. */
static uint32_t receiverId = 0;
static uint8_t receiverMac[6];
static uint32_t telemetrySequence = 0;
static unsigned long nextTelemetryMs = 0;
static uint16_t telemetryRetryCount = 0;

static uint32_t saturatingU32(unsigned long value) {
    return (value > 0xFFFFFFFFUL) ? 0xFFFFFFFFUL : (uint32_t)value;
}

static unsigned long telemetryDelayMs(void) {
    return TELEMETRY_PERIOD_MS + (TELEMETRY_JITTER_MS ?
           (unsigned long)random(TELEMETRY_JITTER_MS + 1UL) : 0UL);
}

static void scheduleTelemetry(unsigned long now, bool initial) {
    /* Startup uses a deterministic slot within the jitter window. Later cycles
     * use a fresh random jitter, keeping each interval within 4-5 seconds by
     * default rather than adding phase and jitter together. */
    const unsigned long offset = initial
        ? (TELEMETRY_JITTER_MS ? receiverId % (TELEMETRY_JITTER_MS + 1UL) : 0UL)
        : (telemetryDelayMs() - TELEMETRY_PERIOD_MS);
    nextTelemetryMs = now + TELEMETRY_PERIOD_MS + offset;
}

static void transmitTelemetry(void) {
    ReceiverTelemetryPacket packet;
    packet.magic = DMX_PACKET_MAGIC;
    packet.protocolVersion = DMX_PROTO_VERSION;
    packet.packetType = TELEMETRY_PACKET_TYPE;
    packet.universeId = DMX_UNIVERSE_ID;
    packet.receiverId = receiverId;
    memcpy(packet.macAddress, receiverMac, sizeof(receiverMac));
    packet.uptimeSeconds = (uint32_t)(millis() / 1000UL);
    packet.batteryLow = batteryLow ? 1U : 0U;
    packet.lastActiveSequence = lastActiveSequence;
    packet.completeUniverses = saturatingU32(completeUniverses);
    packet.incompleteUniverses = saturatingU32(
        abandonedIncomplete > (0xFFFFFFFFUL - abandonedTimeout)
            ? 0xFFFFFFFFUL
            : abandonedIncomplete + abandonedTimeout);
    packet.malformedPackets = saturatingU32(malformedFragments);
    packet.timeSinceLastUniverseMs = hasActiveWirelessFrame
        ? saturatingU32(millis() - lastCompletionTimeMs) : 0xFFFFFFFFUL;
    packet.lastRssi = lastRssi;
    packet.firmwareVersion = TELEMETRY_FIRMWARE_VERSION;
    packet.telemetrySequence = telemetrySequence++;

    if (!quickEspNow.readyToSendData()) {
        telemetryRetryCount++;
        nextTelemetryMs = millis() + TELEMETRY_RETRY_BACKOFF_MS;
        return;
    }

    const comms_send_error_t result = quickEspNow.sendBcast(
        reinterpret_cast<const uint8_t*>(&packet), sizeof(packet));
    if (result == COMMS_SEND_OK) {
        telemetryRetryCount = 0;
        scheduleTelemetry(millis(), false);
    } else {
        telemetryRetryCount++;
        /* Bounded deterministic retry spacing avoids a busy-loop when the
         * ESP-NOW queue is full or another sender is occupying the radio. */
        const unsigned long backoff = TELEMETRY_RETRY_BACKOFF_MS *
            (telemetryRetryCount > 8 ? 8 : telemetryRetryCount);
        nextTelemetryMs = millis() + backoff;
    }
}

/* --------------------------------------------------------------------------
 * Helpers
 * -------------------------------------------------------------------------- */
/* Wrap-safe "is a newer than b" (treats 0xFFFFFFFF -> 0 as forward). */
static inline bool seqIsNewer(uint32_t a, uint32_t b) {
    return (int32_t)(a - b) > 0;
}

/* Canonical tile for a fragment index (offset + payload length). Enforcing this
 * prevents overlapping or gapped tiles from falsely completing a frame. */
static inline bool canonicalTile(uint8_t fragIdx,
                                 uint16_t offset, uint8_t len,
                                 uint16_t* outOffset, uint8_t* outLen) {
    const uint16_t expOffset = (uint16_t)fragIdx * DMX_PAYLOAD_SIZE;
    if (offset != expOffset) return false;
    const uint8_t expLen = dmx_fragment_payload_length(expOffset, DMX_UNIVERSE_SIZE);
    if (len != expLen) return false;
    *outOffset = expOffset;
    *outLen    = expLen;
    return true;
}

static void coverageClear(void) {
    memset(stagingCoverage, 0, sizeof(stagingCoverage));
}

static bool coverageFull(void) {
    for (uint16_t i = 0; i < (uint16_t)(DMX_UNIVERSE_SIZE / 8); i++) {
        if (stagingCoverage[i] != 0xFF) return false;
    }
    return true;
}

/* True if any bit in [offset, offset+len) is already set (an overlap). */
static bool coverageOverlaps(uint16_t offset, uint8_t len) {
    for (uint16_t i = 0; i < len; i++) {
        const uint16_t idx = (uint16_t)(offset + i);
        if (stagingCoverage[idx / 8] & (1u << (idx % 8))) return true;
    }
    return false;
}

static void coverageSet(uint16_t offset, uint8_t len) {
    for (uint16_t i = 0; i < len; i++) {
        const uint16_t idx = (uint16_t)(offset + i);
        stagingCoverage[idx / 8] |= (1u << (idx % 8));
    }
}

/* --------------------------------------------------------------------------
 * QuickESPNow receive callback (ROM timer context) — MINIMAL.
 * Only copies the packet into the bounded handoff ring; no staging/active
 * state is touched here. loop() is the sole reconstruction owner.
 * -------------------------------------------------------------------------- */
void dataReceived(uint8_t* address, uint8_t* data, uint8_t len, signed int rssi, bool broadcast) {
    (void)address;
    (void)broadcast;

    /* Drop anything that cannot be a valid fragment (header + >=1 payload byte). */
    if (len < (DMX_HEADER_SIZE + 1) || len > RX_SLOT_MAX) {
        return;
    }

    const uint8_t slotIdx = ringHead;
    const uint8_t next    = (uint8_t)((ringHead + 1) % RX_RING_SIZE);

    /* If the ring is full we cannot accept without dropping an unconsumed
     * fragment. This is a fail-safe (latest-state) drop, never a grow. */
    if (next == ringTail) {
        if (rxRingOverflow < 0xFFFFFFFFUL) rxRingOverflow++;
        return;
    }

    /* Core critical section, SAVE/RESTORE form (xt_rsil(15)/xt_wsr_ps) — the
     * pattern the ESP8266 core documents and uses in its own InterruptLock /
     * ets_post_rom (the ROM context does not preserve the PS level). */
    const uint32_t savedPS = xt_rsil(15);
    if ((uint8_t)((ringHead + 1) % RX_RING_SIZE) != ringTail) {
        memcpy(rxRing[slotIdx].payload, data, len);
        rxRing[slotIdx].len  = len;
        rxRing[slotIdx].rssi = (int8_t)rssi;
        ringHead = next; /* publish: slot now valid, head advanced */
    }
    xt_wsr_ps(savedPS);
}

/* --------------------------------------------------------------------------
 * Ring consumer (loop context): copy one pending fragment out, if any.
 * Returns false if the ring is empty.
 * -------------------------------------------------------------------------- */
static bool popPendingFrag(uint8_t* outBuf, uint8_t& outLen, int8_t& outRssi) {
    if (ringHead == ringTail) {
        return false;
    }
    const uint8_t slotIdx = ringTail;
    const uint32_t savedPS = xt_rsil(15); /* core save/restore critical section */
    if (ringHead != ringTail) {
        memcpy(outBuf, rxRing[slotIdx].payload, rxRing[slotIdx].len);
        outLen  = rxRing[slotIdx].len;
        outRssi = rxRing[slotIdx].rssi;
        ringTail = (uint8_t)((ringTail + 1) % RX_RING_SIZE);
        xt_wsr_ps(savedPS);
        return true;
    }
    xt_wsr_ps(savedPS);
    return false;
}

/* --------------------------------------------------------------------------
 * Staging state transitions (loop context only).
 * -------------------------------------------------------------------------- */
static void stagingBegin(uint32_t seq, uint8_t fragCount) {
    stagingActive         = true;
    stagingSequence       = seq;
    stagingFragmentCount  = fragCount;
    stagingReceivedMask   = 0;
    stagingUniqueCount    = 0;
    coverageClear();
    stagingLastActivityMs = millis();
}

static void stagingAbandonIncomplete(void) {
    if (stagingActive) {
        abandonedIncomplete++;
    }
    stagingActive = false;
    stagingReceivedMask = 0;
    stagingUniqueCount  = 0;
    coverageClear();
}

/* TEST-ONLY: validate the ENTIRE reconstructed universe against the
 * deterministic Feature 5 pattern. Returns the first failing index, or
 * DMX_UNIVERSE_SIZE if all 512 bytes match. Kept so the integrated receiver
 * stays verifiable against the existing test transmitter; swap out when the
 * production transmitter ships real DMX content. */
static uint16_t fullIntegrityCheck(uint32_t seq) {
    for (uint16_t i = 0; i < DMX_UNIVERSE_SIZE; i++) {
        const uint8_t expected = (uint8_t)(i + seq);
        if (stagingUniverse[i] != expected) {
            return i;
        }
    }
    return DMX_UNIVERSE_SIZE;
}

/* Promote staging -> active by swapping the pointers (no 512-byte copy).
 * After the swap, the buffer that WAS active becomes the (reusable) staging
 * buffer; a new frame overwrites it fully before it can ever be promoted.
 *
 * INTEGRATION POINT: hand the new active universe to espDMX. dmxA.setChans()
 * COPIES the 512 bytes into espDMX's own internal buffer before returning,
 * so this is safe with pointer-swap promotion (no aliasing). espDMX then
 * self-refreshes this universe continuously at ~44 Hz+. */
static void promoteActive(uint32_t seq) {
    uint8_t* oldActive = activeUniverse;
    activeUniverse  = stagingUniverse;
    stagingUniverse = oldActive;

    hasActiveWirelessFrame = true;
    lastActiveSequence     = seq;
    lastCompletionTimeMs   = millis();
    completeUniverses++;

    /* Load the newly active universe into the physical DMX output. */
    dmxA.setChans(activeUniverse, DMX_UNIVERSE_SIZE, 1);

    /* Reset staging metadata for the next frame (do NOT clear the 512 bytes). */
    stagingActive       = false;
    stagingReceivedMask = 0;
    stagingUniqueCount  = 0;
    coverageClear();
}

/* --------------------------------------------------------------------------
 * Malformed-packet rejection (loop context). Counts only; never touches
 * staging/active. (No Serial available — UART0 is owned by espDMX.)
 * -------------------------------------------------------------------------- */
static void rejectMalformed(void) {
    malformedFragments++;
}

/* --------------------------------------------------------------------------
 * Accept one structurally-valid fragment into the STAGING buffer and update
 * reconstruction state. loop() context only. Promotes when the frame is
 * complete and passes the full 512-byte integrity check.
 * -------------------------------------------------------------------------- */
static void acceptFragment(const uint8_t* pkt, uint32_t seq,
                           const DmxFragmentPacket& hdr,
                           uint16_t tileOffset, uint8_t tileLen, int8_t rssi) {
    /* Metadata consistency with the staging frame (same fragment count). */
    if (hdr.fragmentCount != stagingFragmentCount) {
        rejectMalformed();
        return;
    }
    /* Defensive: a valid distinct tile must not overlap already-covered bytes. */
    if (coverageOverlaps(tileOffset, tileLen)) {
        rejectMalformed();
        return;
    }

    /* Copy the payload into STAGING only (never into active here). */
    const uint8_t* payload = pkt + DMX_HEADER_SIZE;
    memcpy(stagingUniverse + tileOffset, payload, tileLen);

    /* Count a fragment only once (duplicate-safe via the received mask). */
    const uint32_t bit = (1UL << hdr.fragmentIndex);
    if (!(stagingReceivedMask & bit)) {
        stagingReceivedMask |= bit;
        if (stagingUniqueCount < 255) stagingUniqueCount++;
    }
    coverageSet(tileOffset, tileLen);

    stagingLastActivityMs       = millis();
    lastAcceptedFragmentTimeMs  = millis();
    lastRssi                    = rssi;
    validFragmentsAccepted++;

    /* Completion: every one of the 512 bytes is covered by received tiles. */
    if (coverageFull() && (stagingUniqueCount == stagingFragmentCount)) {
        const uint16_t badIndex = fullIntegrityCheck(seq);
        if (badIndex >= DMX_UNIVERSE_SIZE) {
            promoteActive(seq);
        } else {
            /* Corrupt-but-complete frame: do NOT promote; active unchanged. */
            integrityFailures++;
            stagingActive       = false;
            stagingReceivedMask = 0;
            stagingUniqueCount  = 0;
            coverageClear();
        }
    }
}

/* --------------------------------------------------------------------------
 * Feature 6 reconstruction state machine (loop context only).
 * Validates structure, resolves sequence ordering (wrap-safe), and either
 * assembles into staging, flags stale/duplicate, supersedes, or re-baselines.
 * -------------------------------------------------------------------------- */
static void processPacket(const uint8_t* pkt, uint8_t len, int8_t rssi) {
    /* Telemetry is intended for the transmitter; do not classify it as a
     * malformed DMX fragment when receivers hear one another. */
    if (len >= 4 && pkt[3] == TELEMETRY_PACKET_TYPE) return;

    DmxFragmentPacket hdr;
    memcpy(&hdr, pkt, sizeof(hdr));

    /* ---- Structural validation (Feature 5 checks, plus universe ID) ---- */
    if (len < DMX_HEADER_SIZE)                       { rejectMalformed(); return; }
    if (hdr.magic != DMX_PACKET_MAGIC)               { rejectMalformed(); return; }
    if (hdr.protocolVersion != DMX_PROTO_VERSION)    { rejectMalformed(); return; }
    if (hdr.packetType != DMX_PACKET_TYPE)           { rejectMalformed(); return; }
    if (hdr.universeId != DMX_UNIVERSE_ID)           { rejectMalformed(); return; }
    if (hdr.payloadLength < 1 || hdr.payloadLength > DMX_PAYLOAD_SIZE) { rejectMalformed(); return; }
    if (len != (uint8_t)(DMX_HEADER_SIZE + hdr.payloadLength))         { rejectMalformed(); return; }
    if (hdr.fragmentCount <= 0)                      { rejectMalformed(); return; }
    if (hdr.fragmentIndex >= hdr.fragmentCount)      { rejectMalformed(); return; }
    if (hdr.dataOffset >= DMX_UNIVERSE_SIZE)         { rejectMalformed(); return; }
    if ((uint16_t)hdr.dataOffset + hdr.payloadLength > DMX_UNIVERSE_SIZE) { rejectMalformed(); return; }

    /* ---- Canonical tile: offset/length must match the fragment index ---- */
    uint16_t tileOffset; uint8_t tileLen;
    if (!canonicalTile(hdr.fragmentIndex, hdr.dataOffset, hdr.payloadLength, &tileOffset, &tileLen)) {
        rejectMalformed();
        return;
    }

    const uint32_t seq = hdr.frameSequence;

    /* ---- No frame in progress: may this fragment start one? ---- */
    if (!stagingActive) {
        if (!hasActiveWirelessFrame) {
            /* First frame ever: accept ANY sequence (no seq-0 assumption). */
            stagingBegin(seq, hdr.fragmentCount);
            acceptFragment(pkt, seq, hdr, tileOffset, tileLen, rssi);
            return;
        }
        if (seqIsNewer(seq, lastActiveSequence)) {
            stagingBegin(seq, hdr.fragmentCount);
            acceptFragment(pkt, seq, hdr, tileOffset, tileLen, rssi);
            return;
        }
        /* Older-or-equal to the last active frame. */
        if ((millis() - lastAcceptedFragmentTimeMs) >= TRANSMITTER_RESET_RECOVERY_MS) {
            /* Link quiet for the recovery window: transmitter likely restarted.
             * Permit establishing a new baseline (commits only if this frame
             * completes + passes integrity). */
            resetRebaselined++;
            stagingBegin(seq, hdr.fragmentCount);
            acceptFragment(pkt, seq, hdr, tileOffset, tileLen, rssi);
            return;
        }
        /* A late/old packet during a live link: stale, do not regress. */
        staleFragments++;
        return;
    }

    /* ---- Frame in progress ---- */
    if (seq == stagingSequence) {
        if (stagingReceivedMask & (1UL << hdr.fragmentIndex)) {
            /* Duplicate fragment for the current frame: do not double-count. */
            duplicateFragments++;
            stagingLastActivityMs      = millis();
            lastAcceptedFragmentTimeMs = millis();
            lastRssi                   = rssi;
            return;
        }
        /* New fragment for the current frame. */
        acceptFragment(pkt, seq, hdr, tileOffset, tileLen, rssi);
        return;
    }

    if (seqIsNewer(seq, stagingSequence)) {
        /* A newer frame supersedes the incomplete one (fresh state wins). */
        stagingAbandonIncomplete();
        stagingBegin(seq, hdr.fragmentCount);
        acceptFragment(pkt, seq, hdr, tileOffset, tileLen, rssi);
        return;
    }

    /* Older than the frame being staged: stale. */
    staleFragments++;
}

/* --------------------------------------------------------------------------
 * MAX3485 driver-enable control (from the original receiver.ino).
 *
 * External transistor inverts the logic:
 *
 *   GPIO LOW  -> transistor OFF -> DE HIGH -> enabled
 *   GPIO HIGH -> transistor ON  -> DE LOW  -> disabled
 * -------------------------------------------------------------------------- */
static bool dmxOutputEnabled = false;

static void setDmxOutputEnabled(bool enabled) {
    dmxOutputEnabled = enabled;
    digitalWrite(PIN_DMX_ENABLE, enabled ? LOW : HIGH);
}

/* --------------------------------------------------------------------------
 * Setup (per README "Receiver Startup Safety")
 *   1. Keep MAX3485 DE disabled.
 *   2. Initialize GPIO.
 *   3. Initialize universe buffers.
 *   4. Initialize QuickESPNow.
 *   5. Initialize espDMX (dmxA.begin()).
 *   6. Establish a valid initial universe (dmxA.setChans()).
 *   7. Start controlled DMX operation.
 *   8. Enable MAX3485 only when safe.
 *
 * NOTE: no Serial here — UART0 is taken over by espDMX for DMX output.
 * -------------------------------------------------------------------------- */
void setup(void) {
    /* GPIO2 must be HIGH during ESP8266 boot; the external base resistor is
     * 100K so the transistor circuit does not prevent normal ESP-01 startup. */
    pinMode(PIN_DMX_ENABLE, OUTPUT);
    pinMode(PIN_BATTERY_LOW, INPUT);

    receiverId = ESP.getChipId();
    WiFi.macAddress(receiverMac);
    randomSeed(receiverId ^ micros());

    batteryInputHigh = (digitalRead(PIN_BATTERY_LOW) == HIGH);
    batteryInputChangedMs = millis();

    /* Keep MAX3485 disabled while everything initializes. */
    setDmxOutputEnabled(false);

    /* Initialize QuickESPNow (STA mode, no WiFi connection). */
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);

    if (!quickEspNow.begin(ESPNOW_CHANNEL)) {
        /* Wireless init failed: stay with MAX3485 disabled; spin forever. */
        while (true) delay(10);
    }
    quickEspNow.onDataRcvd(dataReceived);

    /* Explicit initial state (buffers are zero-initialized as statics). */
    memset(universeBufferA, 0, DMX_UNIVERSE_SIZE);
    memset(universeBufferB, 0, DMX_UNIVERSE_SIZE);
    stagingUniverse = universeBufferA;
    activeUniverse  = universeBufferB;
    hasActiveWirelessFrame = false;
    stagingActive = false;

    /* Initialize espDMX on UART0/GPIO1 (this takes over the console). */
    dmxA.begin();

    /* Establish a valid initial (zero) universe before enabling the line. */
    dmxA.setChans(universeBufferA, DMX_UNIVERSE_SIZE, 1);

    /* Enable the physical MAX3485 output now that init is complete and a
     * valid (zero) universe is loaded. Left enabled: DMX output is
     * continuous, independent of wireless updates. */
    setDmxOutputEnabled(true);

    delay(200);

    scheduleTelemetry(millis(), true);
}

/* --------------------------------------------------------------------------
 * Main loop — SOLE owner of the reconstruction state machine.
 *   1. Drain the bounded handoff ring (each pending fragment -> processPacket).
 *   2. Enforce the staging timeout (abandon a partially assembled frame).
 *   3. Send low-priority telemetry when its collision-avoiding slot is due.
 *   (No periodic stats printing — no Serial on this target.)
 * -------------------------------------------------------------------------- */
static uint8_t rxWorkBuf[RX_SLOT_MAX];

void loop(void) {
    uint8_t len;
    int8_t  rssi;

    /* 1. Debounce the active-HIGH battery comparator input. */
    updateBatteryLow();

    /* 2. Drain every pending fragment (bounded by RX_RING_SIZE). */
    while (popPendingFrag(rxWorkBuf, len, rssi)) {
        packetsReceived++;
        processPacket(rxWorkBuf, len, rssi);
    }

    /* 3. Staging timeout: abandon a frame that stopped receiving fragments. */
    if (stagingActive &&
        (millis() - stagingLastActivityMs) >= STAGING_TIMEOUT_MS) {
        abandonedTimeout++;
        stagingActive       = false;
        stagingReceivedMask = 0;
        stagingUniqueCount  = 0;
        coverageClear();
    }

    if ((long)(millis() - nextTelemetryMs) >= 0) {
        transmitTelemetry();
    }
}
