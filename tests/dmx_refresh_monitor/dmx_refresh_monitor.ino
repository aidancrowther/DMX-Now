/*
 * Feature 7: DMX refresh-rate monitor (Arduino MEGA 2560)
 *
 * Sits on the DMX output of the integrated receiver:
 *
 *   tests/espnow_universe_tx  --(ESP-NOW broadcast)-->  receiver.ino (ESP-01)
 *   (paces off WIRELESS_REFRESH_HZ)                      |
 *                                                        MAX3485 DMX out (250 k, 8N2)
 *                                                        v
 *                                                    this MEGA (DMXSerial RX)
 *                                                        |
 *                                                    USB Serial (115200) --> host PC
 *
 * It receives the DMX universe with the DMXSerial library, validates the
 * deterministic Feature 5/6 test pattern, and reports a set of reliability
 * metrics to the host once per second. The goal is to find roughly what
 * wireless refresh rate the system can sustain reliably (Feature 7).
 *
 * Wiring (MEGA):
 *   DMX data (receiver MAX3485 RO) -> MEGA pin 19 (RX1 / USART1)
 *   MEGA USB (pins 0/1)            -> host PC (telemetry, 115200 8N1)
 *   NOTE: DMXSerial drives its (default) mode pin 2 to LOW in receiver mode.
 *
 * DMXSerial port selection (IMPORTANT):
 *   DMX_USE_PORT1 must be defined so DMXSerial binds USART1 (pins 18/19).
 *   It is set as a GLOBAL build flag (-DDMX_USE_PORT1) in ./flash_dmx_monitor.sh,
 *   NOT here, because the port is chosen inside the library's own translation
 *   unit (DMXSerial.cpp -> DMXSerial_avr.h) and a local #define would not reach it.
 *
 * Metrics (per 1 s window, sent as one line):
 *   updates    : genuinely NEW universes (a complete frame whose sequence /
 *                channel 1 differs from the previous one) = delivered wireless rate
 *   rate       : updates / window  = measured delivered refresh rate (Hz)
 *   lost       : universes inferred lost from frame-sequence gaps (sum of delta-1)
 *   gaps       : number of sequence gaps (>1) observed
 *   loss       : lost / (updates + lost), %
 *   pat_err    : new universes that failed the full pattern check (should be ~0)
 *   max_gap    : longest time between two consecutive NEW universes (ms)
 *   last_seq8  : low byte of the last frame sequence (== DMX channel 1)
 *   no_data    : ms since any DMX data arrived (link liveness)
 *
 * Detection (important): use DMXSerial.packetReady(), NOT dataUpdated().
 *   - packetReady() is a one-shot latch the library sets once per COMPLETE frame
 *     and clears when we read it, so the 512-channel buffer is fully settled
 *     before we read/validate it.
 *   - dataUpdated() is re-set by the receive ISR for *every changed channel byte*
 *     (up to 512x per frame), which made us count one physical frame as many
 *     "updates" and read the buffer half-filled -> bogus rate and pat_err.
 *   - espDMX retransmits the active universe at ~44 Hz, so most complete frames
 *     are identical re-sends; we only count a frame when its sequence (channel 1)
 *     actually changed, filtering those retransmits.
 *
 * Pattern (Feature 5/6 test universe, receiver-promoted):
 *   universe[i] = (i + seq) & 0xFF   (i = 0..511)
 * On the DMX wire (1-based channel c = i + 1), espDMX sends start code 0 first:
 *   channel 1 = universe[0] = seq & 0xFF          (== seq8)
 *   channel c = (seq8 + c - 1) & 0xFF
 * espDMX transmits all 512 channels for this pattern (every channel changes
 * each frame, so no trailing-zero trim), so all 512 are checkable here.
 *
 * Design: non-blocking, no FreeRTOS, no dynamic allocation, no String.
 */

#include <DMXSerial.h>

#define TELE_BAUD        115200UL
#define REPORT_PERIOD_MS 1000UL

/* Per-window metrics (reset each report). */
static unsigned long updates      = 0;   /* new universes this window          */
static unsigned long lostUniv     = 0;   /* inferred lost (from seq gaps)      */
static unsigned long seqGaps      = 0;   /* count of sequence gaps (>1)        */
static unsigned long patternErr   = 0;   /* universes failing the pattern check*/
static unsigned long maxGapMs     = 0;   /* longest inter-universe gap         */
static unsigned long lastUpdateMs = 0;
static uint8_t       prevSeq8     = 0;
static uint8_t       lastSeq8     = 0;
static bool          havePrev     = false;

static bool          firstTX      = true;

/* Validate the full 512-channel pattern. seq8 is read from channel 1.
 * Returns true only if every channel c (1..512) equals (seq8 + c - 1) & 0xFF. */
static bool validatePattern(const uint8_t* buf) {
    const uint8_t seq8 = buf[1];
    for (int c = 1; c <= 512; c++) {
        const uint8_t expected = (uint8_t)(seq8 + (c - 1));
        if (buf[c] != expected) {
            return false;
        }
    }
    return true;
}

void setup() {
    Serial.begin(TELE_BAUD);
    delay(200);
    Serial.println();
    Serial.println("=== DMX refresh monitor (MEGA) ===");
    Serial.println("DMX input : USART1 (pin 19 RX)  [DMX_USE_PORT1]");
    Serial.println("Telemetry : USB Serial (pins 0/1) @ 115200");
    Serial.println("Pattern   : channel c = (seq8 + c - 1) & 0xFF");

    DMXSerial.init(DMXReceiver);
    DMXSerial.maxChannel(512);

    Serial.println("READY");
}

void loop() {
    const unsigned long now = millis();

    /* A COMPLETE DMX frame has just finished arriving: DMXSerial.packetReady()
     * is a one-shot latch the library sets once per completed frame and clears
     * when we read it, so the 512-channel buffer is fully settled before we read
     * or validate it. (This is the fix: dataUpdated() was re-set by the ISR for
     * every changed channel byte -- up to 512x per frame -- which made one
     * physical frame count as many "updates" and let us read the buffer
     * half-filled, producing the bogus rate/pat_err values.)
     *
     * espDMX retransmits the active universe at ~44 Hz, so most of these
     * complete frames are identical re-sends of the last promoted (wireless)
     * universe. We therefore only count a frame as a NEW delivered universe when
     * its sequence (channel 1 = seq low byte) differs from the previous one;
     * identical retransmits are skipped. */
    if (DMXSerial.packetReady()) {
        const uint8_t seq8 = DMXSerial.read(1);   /* channel 1 = seq low byte */

        if (!(havePrev && seq8 == prevSeq8)) {
            /* A genuinely new (or first) universe. */
            updates++;

            if (havePrev) {
                const unsigned long gap = now - lastUpdateMs;
                if (gap > maxGapMs) maxGapMs = gap;

                const uint8_t delta = (uint8_t)(seq8 - prevSeq8);  /* mod 256 forward */
                if (delta > 1) {
                    /* one or more universes were skipped between the two we saw */
                    lostUniv += (unsigned long)(delta - 1);
                    seqGaps++;
                }

                const uint8_t* buf = DMXSerial.getBuffer();
                if (!validatePattern(buf)) {
                    patternErr++;
                }
            }

            prevSeq8 = seq8;
            lastSeq8 = seq8;
            havePrev = true;
            lastUpdateMs = now;
        }
        /* else: identical retransmit of the already-counted universe -> skipped.
         * We deliberately do NOT update lastUpdateMs here, so max_gap keeps
         * measuring the time between consecutive NEW universes. */
    }

    /* Report every REPORT_PERIOD_MS. */
    static unsigned long lastReportMs = 0;
    if (now - lastReportMs >= REPORT_PERIOD_MS) {
        const unsigned long window  = now - lastReportMs;
        lastReportMs = now;

        const float rate    = (window > 0) ? (float)updates * 1000.0f / (float)window : 0.0f;
        const unsigned long total = updates + lostUniv;
        const float lossPct = (total > 0) ? 100.0f * (float)lostUniv / (float)total : 0.0f;

        if(!firstTX){
            Serial.print("t=");          Serial.print(now / 1000UL);
            Serial.print(" updates=");   Serial.print(updates);
            Serial.print(" rate=");      Serial.print(rate, 2);
            Serial.print("Hz lost=");    Serial.print(lostUniv);
            Serial.print(" gaps=");      Serial.print(seqGaps);
            Serial.print(" loss=");      Serial.print(lossPct, 1);
            Serial.print("% pat_err=");  Serial.print(patternErr);
            Serial.print(" max_gap=");   Serial.print(maxGapMs);
            Serial.print("ms last_seq8="); Serial.print(lastSeq8);
            Serial.print(" no_data=");   Serial.print(DMXSerial.noDataSince());
            Serial.println("ms");
        } else firstTX = false;

        updates = 0; lostUniv = 0; seqGaps = 0; patternErr = 0; maxGapMs = 0;
    }
}
