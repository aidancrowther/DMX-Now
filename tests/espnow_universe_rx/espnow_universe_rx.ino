/**
 * Feature 6: Wireless DMX universe receiver — reconstruction + double buffering
 *
 * Reconstructs the complete 512-byte universe from QuickESPNow broadcast
 * fragments and maintains two 512-byte buffers with POINTER-SWAP promotion:
 *
 *   stagingUniverse : the frame currently being assembled (may be incomplete)
 *   activeUniverse  : the most recent COMPLETE, integrity-validated universe
 *
 * Architecture (no FreeRTOS — plain Arduino setup()/loop() + QuickESPNow callback):
 *   - The QuickESPNow receive callback runs in a ROM timer (ETSTimer/ets_post)
 *     context that interleaves with loop(). It is kept MINIMAL: it only copies
 *     the received packet into a bounded static handoff ring (SPSC) and returns.
 *   - loop() is the SOLE owner of the reconstruction state machine: it drains the
 *     ring, validates fragments, updates staging, runs the full 512-byte integrity
 *     check, and promotes by swapping the active/staging pointers (no 512-byte copy).
 *   - The only state shared between the callback and loop() is the ring head/tail
 *     and slot contents, guarded by the core's own critical section
 *     (noInterrupts()/interrupts() == xt_rsil(15)/xt_rsil(0)) — the same primitive
 *     the ESP8266 core uses to guard cross-context shared state. NOT FreeRTOS.
 *
 * Sequence handling (wrap-safe):
 *   - seqIsNewer(a,b) = (int32_t)(a-b) > 0  (treats 0xFFFFFFFF -> 0 as forward)
 *   - A newer fragment supersedes an incomplete staging frame.
 *   - An older fragment is STALE, except when the link has been quiet for
 *     >= TRANSMITTER_RESET_RECOVERY_MS (transmitter restarted), in which case it
 *     may establish a new baseline. Re-baselining only commits when a COMPLETE,
 *     integrity-passing frame arrives, so a single delayed stale packet cannot
 *     regress the active universe.
 *
 * Timeouts (named constants, wrap-safe millis() arithmetic):
 *   - STAGING_TIMEOUT_MS             : abandon a partially assembled frame
 *   - TRANSMITTER_RESET_RECOVERY_MS  : permit re-baselining after link silence
 *
 * TEST-ONLY: the full 512-byte integrity check validates the deterministic
 * Feature 5 pattern  universe[i] = (i + seq) & 0xFF. Isolated and clearly
 * marked; production will use real DMX content instead.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* Single canonical protocol definition shared with the transmitter. */
#include <wireless_protocol.h>

/* --------------------------------------------------------------------------
 * Configuration
 * -------------------------------------------------------------------------- */
#ifndef RX_VERBOSE_DEBUG
#define RX_VERBOSE_DEBUG 1
#endif

/* Abandon a partially assembled staging frame after this much silence.
 * Kept separate from (and shorter than) the transmitter-reset window. */
static const unsigned long STAGING_TIMEOUT_MS = 2000UL;

/* Permit an "older" sequence to establish a new baseline only after the
 * wireless link has had no accepted fragment for this long (transmitter
 * restarted). Chosen as 3x the 1 Hz refresh period so a live link (a frame
 * every ~1000 ms) never falsely re-baselines. Wrap-safe via millis(). */
static const unsigned long TRANSMITTER_RESET_RECOVERY_MS = 3000UL;

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

/* --------------------------------------------------------------------------
 * Diagnostic counters — local only, no telemetry.
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
     * pattern the ESP8266 core documents (core_esp8266_features.h) and uses in
     * its own InterruptLock / ets_post_rom (the ROM context does not preserve
     * the PS level). Save/restore (not bare noInterrupts()/interrupts()) is
     * context-safe: it restores the exact base level of the ROM timer context. */
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
        if (RX_VERBOSE_DEBUG) {
            Serial.printf("RX ABANDON seq=%u received=%d/%d (superseded)\n",
                          stagingSequence, stagingUniqueCount, stagingFragmentCount);
        }
    }
    stagingActive = false;
    stagingReceivedMask = 0;
    stagingUniqueCount  = 0;
    coverageClear();
}

/* TEST-ONLY: validate the ENTIRE reconstructed universe against the
 * deterministic Feature 5 pattern. Returns the first failing index, or
 * DMX_UNIVERSE_SIZE if all 512 bytes match. */
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
 * buffer; a new frame overwrites it fully before it can ever be promoted. */
static void promoteActive(uint32_t seq) {
    uint8_t* oldActive = activeUniverse;
    activeUniverse  = stagingUniverse;
    stagingUniverse = oldActive;

    hasActiveWirelessFrame = true;
    lastActiveSequence     = seq;
    lastCompletionTimeMs   = millis();
    completeUniverses++;

    /* Reset staging metadata for the next frame (do NOT clear the 512 bytes). */
    stagingActive       = false;
    stagingReceivedMask = 0;
    stagingUniqueCount  = 0;
    coverageClear();

    if (RX_VERBOSE_DEBUG) {
        Serial.printf("RX COMPLETE seq=%u fragments=%d integrity=PASS complete=%lu dup=%lu stale=%lu abandon=%lu rssi=%d\n",
                      seq, stagingFragmentCount, completeUniverses,
                      duplicateFragments, staleFragments, abandonedIncomplete, lastRssi);
        Serial.printf("active[0]=0x%02X [235]=0x%02X [236]=0x%02X [471]=0x%02X [472]=0x%02X [511]=0x%02X\n",
                      activeUniverse[0],   activeUniverse[235],
                      activeUniverse[236], activeUniverse[471],
                      activeUniverse[472], activeUniverse[511]);
    }
}

/* --------------------------------------------------------------------------
 * Malformed-packet rejection (loop context). Counts + logs; never touches
 * staging/active.
 * -------------------------------------------------------------------------- */
static void rejectMalformed(const char* reason) {
    malformedFragments++;
    if (RX_VERBOSE_DEBUG) {
        Serial.print("RX MALFORMED: ");
        Serial.println(reason);
    }
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
        rejectMalformed("fragmentCount mismatch for staging frame");
        return;
    }
    /* Defensive: a valid distinct tile must not overlap already-covered bytes. */
    if (coverageOverlaps(tileOffset, tileLen)) {
        rejectMalformed("tile overlap in staging coverage");
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
            if (RX_VERBOSE_DEBUG) {
                Serial.printf("RX INTEGRITY FAIL seq=%u index=%u expected=0x%02X actual=0x%02X\n",
                              seq, badIndex,
                              (uint8_t)(badIndex + seq), stagingUniverse[badIndex]);
            }
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
    DmxFragmentPacket hdr;
    memcpy(&hdr, pkt, sizeof(hdr));

    /* ---- Structural validation (Feature 5 checks, plus universe ID) ---- */
    if (len < DMX_HEADER_SIZE)                       { rejectMalformed("short packet"); return; }
    if (hdr.magic != DMX_PACKET_MAGIC)               { rejectMalformed("bad magic"); return; }
    if (hdr.protocolVersion != DMX_PROTO_VERSION)    { rejectMalformed("bad version"); return; }
    if (hdr.packetType != DMX_PACKET_TYPE)           { rejectMalformed("bad packet type"); return; }
    if (hdr.universeId != DMX_UNIVERSE_ID)           { rejectMalformed("bad universe id"); return; }
    if (hdr.payloadLength < 1 || hdr.payloadLength > DMX_PAYLOAD_SIZE) { rejectMalformed("payloadLength out of range"); return; }
    if (len != (uint8_t)(DMX_HEADER_SIZE + hdr.payloadLength))         { rejectMalformed("total size mismatch"); return; }
    if (hdr.fragmentCount <= 0)                      { rejectMalformed("fragmentCount zero"); return; }
    if (hdr.fragmentIndex >= hdr.fragmentCount)      { rejectMalformed("fragmentIndex >= fragmentCount"); return; }
    if (hdr.dataOffset >= DMX_UNIVERSE_SIZE)         { rejectMalformed("dataOffset out of range"); return; }
    if ((uint16_t)hdr.dataOffset + hdr.payloadLength > DMX_UNIVERSE_SIZE) { rejectMalformed("offset+payload overflow"); return; }

    /* ---- Canonical tile: offset/length must match the fragment index ---- */
    uint16_t tileOffset; uint8_t tileLen;
    if (!canonicalTile(hdr.fragmentIndex, hdr.dataOffset, hdr.payloadLength, &tileOffset, &tileLen)) {
        rejectMalformed("non-canonical tile for fragment index");
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
            if (RX_VERBOSE_DEBUG) {
                Serial.printf("RX REBASELINE permit seq=%u (link quiet >= %lu ms)\n",
                              seq, TRANSMITTER_RESET_RECOVERY_MS);
            }
            stagingBegin(seq, hdr.fragmentCount);
            acceptFragment(pkt, seq, hdr, tileOffset, tileLen, rssi);
            return;
        }
        /* A late/old packet during a live link: stale, do not regress. */
        staleFragments++;
        if (RX_VERBOSE_DEBUG) {
            Serial.printf("RX STALE seq=%u current=%u\n", seq, lastActiveSequence);
        }
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
            if (RX_VERBOSE_DEBUG) {
                Serial.printf("RX DUP seq=%u frag=%u\n", seq, hdr.fragmentIndex);
            }
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
    if (RX_VERBOSE_DEBUG) {
        Serial.printf("RX STALE seq=%u current=%u\n", seq, stagingSequence);
    }
}

/* --------------------------------------------------------------------------
 * TEST-ONLY local fault-injection path (default OFF).
 * Exercises the malformed-metadata rejection branch (Test 8) without RF:
 * builds a packet that is structurally malformed and feeds it through
 * processPacket() directly. Only compiled when TEST_INJECT_MALFORMED is
 * defined at build time. No dynamic allocation.
 * -------------------------------------------------------------------------- */
#ifdef TEST_INJECT_MALFORMED
static void injectMalformedTestPacket(void) {
    /* Fragment 0 header, but dataOffset pushed so offset+payload > 512. */
    uint8_t pkt[DMX_HEADER_SIZE + 4];
    DmxFragmentPacket* h = (DmxFragmentPacket*)pkt;
    h->magic           = DMX_PACKET_MAGIC;
    h->protocolVersion = DMX_PROTO_VERSION;
    h->packetType      = DMX_PACKET_TYPE;
    h->universeId      = DMX_UNIVERSE_ID;
    h->frameSequence   = 0;
    h->fragmentIndex   = 0;
    h->fragmentCount   = DMX_FRAGMENTS_PER_UNIVERSE;
    h->dataOffset      = 511;              /* near the end */
    h->payloadLength   = 4;                /* 511 + 4 = 515 > 512 -> overflow */
    memset(pkt + DMX_HEADER_SIZE, 0xAA, 4);
    packetsReceived++;
    Serial.println("RX INJECT: feeding a malformed (overflow) packet to processPacket()");
    processPacket(pkt, (uint8_t)(DMX_HEADER_SIZE + 4), -50);
    Serial.printf("RX INJECT: malformed counter now = %lu\n", malformedFragments);
}
#endif /* TEST_INJECT_MALFORMED */

/* --------------------------------------------------------------------------
 * Setup
 * -------------------------------------------------------------------------- */
void setup(void) {
    Serial.begin(115200);
    Serial.println();
    Serial.print("Feature 6 RX starting");
    Serial.print(", channel=");
    Serial.println(ESPNOW_CHANNEL);

    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);

    if (!quickEspNow.begin(ESPNOW_CHANNEL)) {
        Serial.println("Failed to initialize QuickESPNow");
        while (true) delay(10);
    }

    quickEspNow.onDataRcvd(dataReceived);

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

    /* Explicit initial state (buffers are zero-initialized as statics). */
    memset(universeBufferA, 0, DMX_UNIVERSE_SIZE);
    memset(universeBufferB, 0, DMX_UNIVERSE_SIZE);
    stagingUniverse = universeBufferA;
    activeUniverse  = universeBufferB;
    hasActiveWirelessFrame = false;
    stagingActive = false;

    delay(200);

    Serial.println();
    Serial.println("Feature 6 RX ready (reconstruction + double buffering)");
    Serial.printf("  header=%d payload=%d total=%d frags=%d\n",
                  (int)DMX_HEADER_SIZE, (int)DMX_PAYLOAD_SIZE,
                  (int)DMX_TOTAL_PACKET_SIZE, (int)DMX_FRAGMENTS_PER_UNIVERSE);
    Serial.printf("  staging_timeout=%lu ms  reset_recovery=%lu ms  ring=%d slots\n",
                  STAGING_TIMEOUT_MS, TRANSMITTER_RESET_RECOVERY_MS, RX_RING_SIZE);
    Serial.println("  integrity: full 512-byte check vs (i + seq) & 0xFF (test-only)");
    Serial.println("  promotion: pointer swap (no 512-byte copy)");

#ifdef TEST_INJECT_MALFORMED
    Serial.println("  TEST_INJECT_MALFORMED enabled: injecting one malformed packet now");
    injectMalformedTestPacket();
#endif
}

/* --------------------------------------------------------------------------
 * Main loop — SOLE owner of the reconstruction state machine.
 *   1. Drain the bounded handoff ring (each pending fragment -> processPacket).
 *   2. Enforce the staging timeout (abandon a partially assembled frame).
 *   3. Periodically print diagnostic counters.
 * -------------------------------------------------------------------------- */
static unsigned long lastStatsPrintMs = 0;
static const unsigned long STATS_PERIOD_MS = 5000UL;
static uint8_t rxWorkBuf[RX_SLOT_MAX];

void loop(void) {
    uint8_t len;
    int8_t  rssi;

    /* 1. Drain every pending fragment (bounded by RX_RING_SIZE). */
    while (popPendingFrag(rxWorkBuf, len, rssi)) {
        packetsReceived++;
        processPacket(rxWorkBuf, len, rssi);
    }

    /* 2. Staging timeout: abandon a frame that stopped receiving fragments. */
    if (stagingActive &&
        (millis() - stagingLastActivityMs) >= STAGING_TIMEOUT_MS) {
        abandonedTimeout++;
        if (RX_VERBOSE_DEBUG) {
            Serial.printf("RX ABANDON seq=%u received=%d/%d (timeout %lu ms)\n",
                          stagingSequence, stagingUniqueCount,
                          stagingFragmentCount, STAGING_TIMEOUT_MS);
        }
        stagingActive       = false;
        stagingReceivedMask = 0;
        stagingUniqueCount  = 0;
        coverageClear();
    }

    /* 3. Periodic diagnostic counters. */
    if ((millis() - lastStatsPrintMs) >= STATS_PERIOD_MS) {
        lastStatsPrintMs = millis();
        Serial.printf("RX STATS pkts=%lu valid=%lu malformed=%lu dup=%lu stale=%lu "
                      "abandon=%lu(+timeout %lu) complete=%lu integrityFail=%lu ringOvfl=%lu rebase=%lu\n",
                      packetsReceived, validFragmentsAccepted, malformedFragments,
                      duplicateFragments, staleFragments, abandonedIncomplete,
                      abandonedTimeout, completeUniverses, integrityFailures,
                      rxRingOverflow, resetRebaselined);
        if (hasActiveWirelessFrame) {
            Serial.printf("  active seq=%u  lastComplete=%lu ms ago\n",
                          lastActiveSequence, (unsigned long)(millis() - lastCompletionTimeMs));
        } else {
            Serial.println("  active = none yet (no complete frame accepted)");
        }
    }
}



