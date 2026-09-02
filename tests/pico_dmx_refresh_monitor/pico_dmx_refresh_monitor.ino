/*
 * Feature 7: Raspberry Pi Pico DMX refresh-rate monitor
 *
 * DMX input: GPIO 1 / UART0 RX (Serial1)
 * Telemetry: native USB Serial
 *
 * The Pico-DMX library uses PIO plus DMA to capture one complete frame and
 * invokes a callback once the 513-byte buffer is filled. This avoids doing
 * frame parsing in the foreground and minimizes measurement interference.
 * The command protocol and RESULT fields match the MEGA monitor so captures
 * from both devices can be compared by the existing analyzer.
 */

#include <Arduino.h>
#include <DmxInput.h>

static constexpr uint8_t DMX_RX_PIN = 1;
static constexpr uint16_t DMX_FRAME_BYTES = 513;
static constexpr uint16_t COMMAND_BUFFER_SIZE = 64;

static volatile uint8_t frame[DMX_FRAME_BYTES];
static DmxInput dmxInput;

static unsigned long updates = 0;
static unsigned long lostUniv = 0;
static unsigned long seqGaps = 0;
static unsigned long patternErr = 0;
static unsigned long maxGapMs = 0;
static unsigned long lastUpdateMs = 0;
static uint8_t prevSeq8 = 0;
static uint8_t lastSeq8 = 0;
static bool havePrev = false;

enum RecordState { RECORD_IDLE, RECORD_SETTLE, RECORD_MEASURE };
static RecordState recordState = RECORD_IDLE;
static unsigned long recordSettleUntil = 0;
static unsigned long recordMeasureUntil = 0;
static unsigned long recordMeasureStart = 0;

static char commandBuffer[COMMAND_BUFFER_SIZE];
static uint8_t commandLength = 0;

static bool validatePattern(const uint8_t* buf) {
    const uint8_t seq8 = buf[1];
    for (uint16_t channel = 1; channel <= 512; ++channel) {
        const uint8_t expected = (uint8_t)(seq8 + channel - 1);
        if (buf[channel] != expected) return false;
    }
    return true;
}

static void resetMetrics() {
    updates = 0;
    lostUniv = 0;
    seqGaps = 0;
    patternErr = 0;
    maxGapMs = 0;
    lastUpdateMs = 0;
    prevSeq8 = 0;
    lastSeq8 = 0;
    havePrev = false;
}

static void startMeasurement(unsigned long now) {
    resetMetrics();
    recordMeasureStart = now;
    recordState = RECORD_MEASURE;
}

static void finishMeasurement(unsigned long now) {
    const unsigned long window = now - recordMeasureStart;
    const float rate = window ? (float)updates * 1000.0f / window : 0.0f;
    const unsigned long total = updates + lostUniv;
    const float lossPct = total ? 100.0f * (float)lostUniv / total : 0.0f;

    Serial.print("RESULT seconds="); Serial.print(window / 1000UL);
    Serial.print(" updates="); Serial.print(updates);
    Serial.print(" rate="); Serial.print(rate, 2);
    Serial.print(" lost="); Serial.print(lostUniv);
    Serial.print(" gaps="); Serial.print(seqGaps);
    Serial.print(" loss="); Serial.print(lossPct, 1);
    Serial.print("% pat_err="); Serial.print(patternErr);
    Serial.print(" max_gap="); Serial.print(maxGapMs);
    Serial.print(" last_seq8="); Serial.print(lastSeq8);
    Serial.print(" no_data="); Serial.print(millis() - dmxInput.latest_packet_timestamp());
    Serial.println("ms");
    recordState = RECORD_IDLE;
}

static void accountFrame(unsigned long now) {
    if (recordState != RECORD_MEASURE || frame[0] != 0) {
        return;
    }

    const uint8_t seq8 = frame[1];
    if (!(havePrev && seq8 == prevSeq8)) {
        updates++;
        if (havePrev) {
            const unsigned long gap = now - lastUpdateMs;
            if (gap > maxGapMs) maxGapMs = gap;
            const uint8_t delta = (uint8_t)(seq8 - prevSeq8);
            if (delta > 1) {
                lostUniv += (unsigned long)(delta - 1);
                seqGaps++;
            }
            if (!validatePattern((const uint8_t*)frame)) patternErr++;
        }
        prevSeq8 = seq8;
        lastSeq8 = seq8;
        havePrev = true;
        lastUpdateMs = now;
    }
}

static void onDmxFrame(DmxInput*) {
    /* DmxInput calls this from the DMA IRQ after the 513-byte transfer
     * completes and before it re-arms DMA. Account for the frame here so the
     * validation cannot race a subsequent DMA write to the same buffer. The
     * callback does no Serial or allocation work. */
    accountFrame(millis());
}

static void processCommand(char* command, unsigned long now) {
    unsigned long settleSeconds = 0;
    unsigned long measureSeconds = 0;
    if (sscanf(command, "START %lu %lu", &settleSeconds, &measureSeconds) == 2 && measureSeconds > 0) {
        resetMetrics();
        recordSettleUntil = now + settleSeconds * 1000UL;
        recordMeasureUntil = recordSettleUntil + measureSeconds * 1000UL;
        recordState = settleSeconds ? RECORD_SETTLE : RECORD_MEASURE;
        if (!settleSeconds) startMeasurement(now);
        Serial.print("ACK START settle="); Serial.print(settleSeconds);
        Serial.print(" measure="); Serial.println(measureSeconds);
    } else if (strcmp(command, "STATUS") == 0) {
        Serial.print("STATUS state="); Serial.println((int)recordState);
    } else if (strcmp(command, "ABORT") == 0) {
        recordState = RECORD_IDLE;
        resetMetrics();
        Serial.println("ACK ABORT");
    }
}

static void pollCommands(unsigned long now) {
    while (Serial.available() > 0) {
        const char ch = (char)Serial.read();
        if (ch == '\n' || ch == '\r') {
            if (commandLength) {
                commandBuffer[commandLength] = '\0';
                processCommand(commandBuffer, now);
                commandLength = 0;
            }
        } else if (commandLength < COMMAND_BUFFER_SIZE - 1) {
            commandBuffer[commandLength++] = ch;
        } else {
            commandLength = 0;
        }
    }
}

void setup() {
    Serial.begin(115200);
    dmxInput.begin(DMX_RX_PIN, 0, 512);
    dmxInput.read_async(frame, onDmxFrame);

    delay(200);
    Serial.println();
    Serial.println("=== DMX refresh monitor (Pico) ===");
    Serial.println("DMX input : PIO/DMA GPIO 1 @ 250000 8N2");
    Serial.println("Telemetry : native USB Serial");
    Serial.println("Pattern   : channel c = (seq8 + c - 1) & 0xFF");
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
}