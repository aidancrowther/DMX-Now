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
 * metrics to the host after a silent recording window. The goal is to find roughly what
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
 * Metrics (one line after a recording window):
 *   updates    : genuinely NEW complete DMX payloads = delivered wireless rate
 *   rate       : updates / window  = measured delivered refresh rate (Hz)
 *   lost       : universes inferred lost from frame-sequence gaps (sum of delta-1)
 *   gaps       : number of sequence gaps (>1) observed
 *   loss       : lost / (updates + lost), %
 *   pat_err    : new universes that failed the full pattern check (should be ~0)
 *   max_gap    : longest time between two consecutive NEW universes (ms)
 *   last_seq8  : low byte of the last frame sequence (channel 1, test diagnostic)
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
 *     are identical re-sends; the test transmitter's sequence byte filters those
 *     retransmits with minimal foreground work.
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
#define COMMAND_BUFFER_SIZE 64

/* Metrics accumulated during the measurement window. */
static unsigned long updates      = 0;   /* new universes this window          */
static unsigned long lostUniv     = 0;   /* inferred lost (from seq gaps)      */
static unsigned long seqGaps      = 0;   /* count of sequence gaps (>1)        */
static unsigned long patternErr   = 0;   /* universes failing the pattern check*/
static unsigned long maxGapMs     = 0;   /* longest inter-universe gap         */
static unsigned long lastUpdateMs = 0;
static uint8_t       prevSeq8     = 0;
static uint8_t       lastSeq8     = 0;
static bool          havePrev     = false;
static uint8_t       frameSnapshot[DMXSERIAL_MAX + 1];

enum RecordState { RECORD_IDLE, RECORD_SETTLE, RECORD_MEASURE };
static RecordState recordState = RECORD_IDLE;
static unsigned long recordSettleUntil = 0;
static unsigned long recordMeasureUntil = 0;
static unsigned long recordMeasureStart = 0;
static char commandBuffer[COMMAND_BUFFER_SIZE];
static uint8_t commandLength = 0;

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

static void resetMetrics(void) {
    updates = 0; lostUniv = 0; seqGaps = 0; patternErr = 0; maxGapMs = 0;
    lastUpdateMs = 0; prevSeq8 = 0; lastSeq8 = 0; havePrev = false;
}

static void startMeasurement(unsigned long now) {
    resetMetrics();
    recordMeasureStart = now;
    recordState = RECORD_MEASURE;
}

static void finishMeasurement(unsigned long now) {
    const unsigned long window = now - recordMeasureStart;
    const float rate = (window > 0) ? (float)updates * 1000.0f / (float)window : 0.0f;
    const unsigned long total = updates + lostUniv;
    const float lossPct = (total > 0) ? 100.0f * (float)lostUniv / (float)total : 0.0f;

    /* This is the only normal output during/after a run. */
    Serial.print("RESULT seconds="); Serial.print(window / 1000UL);
    Serial.print(" updates="); Serial.print(updates);
    Serial.print(" rate="); Serial.print(rate, 2);
    Serial.print(" lost="); Serial.print(lostUniv);
    Serial.print(" gaps="); Serial.print(seqGaps);
    Serial.print(" loss="); Serial.print(lossPct, 1);
    Serial.print("% pat_err="); Serial.print(patternErr);
    Serial.print(" max_gap="); Serial.print(maxGapMs);
    Serial.print(" last_seq8="); Serial.print(lastSeq8);
    Serial.print(" no_data="); Serial.print(DMXSerial.noDataSince());
    Serial.println("ms");
    recordState = RECORD_IDLE;
}

static void processCommand(char* command, unsigned long now) {
    unsigned long settleSeconds = 0;
    unsigned long measureSeconds = 0;
    if (sscanf(command, "START %lu %lu", &settleSeconds, &measureSeconds) == 2 && measureSeconds > 0) {
        resetMetrics();
        recordSettleUntil = now + settleSeconds * 1000UL;
        recordMeasureUntil = recordSettleUntil + measureSeconds * 1000UL;
        recordState = (settleSeconds == 0) ? RECORD_MEASURE : RECORD_SETTLE;
        if (recordState == RECORD_MEASURE) startMeasurement(now);
        Serial.print("ACK START settle="); Serial.print(settleSeconds);
        Serial.print(" measure="); Serial.println(measureSeconds);
        return;
    }
    if (strcmp(command, "STATUS") == 0) {
        Serial.print("STATUS state="); Serial.println((int)recordState);
        return;
    }
    if (strcmp(command, "ABORT") == 0) {
        recordState = RECORD_IDLE;
        resetMetrics();
        Serial.println("ACK ABORT");
    }
}

static void pollCommands(unsigned long now) {
    while (Serial.available() > 0) {
        const char ch = (char)Serial.read();
        if (ch == '\n' || ch == '\r') {
            if (commandLength > 0) {
                commandBuffer[commandLength] = '\0';
                processCommand(commandBuffer, now);
                commandLength = 0;
            }
        } else if (commandLength < COMMAND_BUFFER_SIZE - 1) {
            commandBuffer[commandLength++] = ch;
        } else {
            commandLength = 0; // reject an overlong command
        }
    }
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

    pollCommands(now);

    if (recordState == RECORD_SETTLE && now >= recordSettleUntil) {
        startMeasurement(now);
    }
    if (recordState == RECORD_MEASURE && now >= recordMeasureUntil) {
        finishMeasurement(now);
    }

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
    if (DMXSerial.packetReady() && recordState == RECORD_MEASURE) {
        /* Take a short, contiguous snapshot immediately after the complete
         * frame latch. This avoids validating the library's mutable receive
         * buffer while the next frame is being received. Interrupts remain
         * enabled; the copy is far shorter than one physical DMX frame period.
         */
        memcpy(frameSnapshot, DMXSerial.getBuffer(), sizeof(frameSnapshot));
        const uint8_t seq8 = frameSnapshot[1];

        /* A genuinely new complete payload. The sequence byte is used only
         * for duplicate filtering; packetReady() remains the complete-frame
         * boundary. */
        if (!(havePrev && seq8 == prevSeq8)) {
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

                if (!validatePattern(frameSnapshot)) {
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

}
