/*
 * Re-transmitter end-to-end Mega generator/monitor.
 *
 * USB Serial / USART0: commands and finite results at 115200 8N1.
 * USART1 / pins 18 TX, 19 RX: DMXSerial-generated physical DMX output.
 * USART2 / pin 17 RX: returned DMX monitor from the wireless receiver.
 *
 * Build with -DDMX_USE_PORT1. DMXSerial then owns USART1 for generation while
 * this sketch owns USART2 for a second, receive-only DMX input. The returned
 * DMX input must use a separate RS-485 receiver whose RO is connected to Mega
 * pin 17 and whose driver is permanently disabled.
 */
#include <Arduino.h>
#include <avr/interrupt.h>
#include <avr/io.h>
#include <string.h>

#define TELE_BAUD 115200UL
#define DMX_SLOTS 512U
#define COMMAND_BUFFER_SIZE 80U
#define MONITOR_UART_BAUD 250000UL
#define SOURCE_UBRR_250K 3U
#define SOURCE_UBRR_100K 9U
#define SOURCE_FRAME_PERIOD_US 22700UL /* approximately 44.05 Hz */

enum SourceTxState { SOURCE_TX_IDLE, SOURCE_TX_BREAK, SOURCE_TX_DATA, SOURCE_TX_DONE };

enum GeneratorPattern { GENERATOR_CONST, GENERATOR_RAMP, GENERATOR_SHORT,
                        GENERATOR_DYNAMIC, GENERATOR_DYNAMIC_SHORT };
enum RecordState { RECORD_IDLE, RECORD_SETTLE, RECORD_MEASURE };

static GeneratorPattern generatorPattern = GENERATOR_CONST;
static uint16_t generatorSlots = DMX_SLOTS;
static uint8_t generatorBase = 0;
static uint8_t dynamicEpoch = 0;
static volatile SourceTxState sourceTxState = SOURCE_TX_IDLE;
static volatile uint16_t sourceTxChannel = 0;
static uint32_t nextSourceFrameAtUs = 0;
static unsigned long sourceFramesSent = 0;
static unsigned long firstSourceFrameAtUs = 0;
static unsigned long lastSourceFrameAtUs = 0;
static bool sourceEnabled = true;
static RecordState recordState = RECORD_IDLE;
static unsigned long settleUntil = 0;
static unsigned long measureUntil = 0;
static unsigned long measureStart = 0;
static char commandBuffer[COMMAND_BUFFER_SIZE];
static uint8_t commandLength = 0;

static uint8_t expected[DMX_SLOTS + 1];
static uint8_t sourceFrame[DMX_SLOTS + 1];
static uint8_t monitorSnapshot[DMX_SLOTS + 1];
static volatile uint8_t monitorFrame[DMX_SLOTS + 1];
static volatile uint16_t monitorSlots = 0;
static volatile bool monitorReady = false;
static volatile uint16_t monitorIndex = 0;
static volatile bool monitorReceiving = false;

static unsigned long checkedFrames = 0;
static unsigned long passedFrames = 0;
static unsigned long failedFrames = 0;
static unsigned long partialFrames = 0;
static unsigned long maxGapMs = 0;
static unsigned long lastCheckedAt = 0;
static unsigned long lastMonitorDataAt = 0;
static bool haveCheckedFrame = false;

static void configureMonitorUart(void) {
    /* USART2: 250000 baud, 8N2, receive interrupt. */
    uint16_t divisor = (uint16_t)((F_CPU / (16UL * MONITOR_UART_BAUD)) - 1UL);
    UBRR2H = (uint8_t)(divisor >> 8);
    UBRR2L = (uint8_t)divisor;
    UCSR2A = 0;
    UCSR2B = (1 << RXEN2) | (1 << RXCIE2);
    UCSR2C = (1 << UCSZ21) | (1 << UCSZ20) | (1 << USBS2);
    while (UCSR2A & (1 << RXC2)) (void)UDR2;
}

ISR(USART2_RX_vect) {
    const uint8_t status = UCSR2A;
    const uint8_t value = UDR2;
    const bool framingError = (status & (1 << FE2)) != 0;

    /* DMX BREAK is received as a framing error. A BREAK closes the previous
     * frame and starts the next one. The foreground loop copies monitorFrame
     * only after monitorReady is published. */
    if (framingError) {
        if (monitorReceiving && monitorIndex > 1 && !monitorReady) {
            monitorSlots = monitorIndex > 0 ? monitorIndex - 1 : 0;
            monitorReady = true;
        }
        monitorReceiving = true;
        monitorIndex = 0;
        return;
    }
    if (!monitorReceiving || monitorIndex >= sizeof(monitorFrame)) return;
    monitorFrame[monitorIndex++] = value;
    if (monitorIndex >= sizeof(monitorFrame) && !monitorReady) {
        monitorSlots = DMX_SLOTS;
        monitorReady = true;
        monitorReceiving = false;
    }
}

static void setExpected(void) {
    expected[0] = 0;
    for (uint16_t channel = 1; channel <= DMX_SLOTS; channel++) {
        if (generatorPattern == GENERATOR_CONST) expected[channel] = generatorBase;
        /* Change one slot per epoch. Updating an entire DMXSerial buffer in
         * place can race the UART ISR and create a torn physical source frame;
         * the fixed body keeps this harness from manufacturing invalid input
         * while still exercising dynamic retransmission data. */
        else if (generatorPattern == GENERATOR_DYNAMIC ||
                 generatorPattern == GENERATOR_DYNAMIC_SHORT) {
            expected[channel] = channel == 1
                ? dynamicEpoch
                : (uint8_t)(generatorBase + dynamicEpoch * 29U +
                            channel * 37U + (channel >> 3) * 11U);
            if (generatorPattern == GENERATOR_DYNAMIC_SHORT && channel > generatorSlots)
                expected[channel] = 0;
        } else if (generatorPattern == GENERATOR_SHORT && channel > generatorSlots) expected[channel] = 0;
        else expected[channel] = (uint8_t)(generatorBase + channel - 1);
    }
}

static void applyGenerator(void) {
    setExpected();
    memcpy(sourceFrame, expected, sizeof(sourceFrame));
}

static void advanceDynamicSourceFrame(void) {
    if (generatorPattern != GENERATOR_DYNAMIC &&
        generatorPattern != GENERATOR_DYNAMIC_SHORT) return;
    dynamicEpoch++;
    setExpected();
    memcpy(sourceFrame, expected, sizeof(sourceFrame));
}

static void stopSourceDmx(void) {
    UCSR1B = 0;
    sourceTxState = SOURCE_TX_IDLE;
}

static void startSourceDmx(void) {
    /* Raw USART1 ownership avoids the Arduino Serial1 ISR. A 100-kbaud 8N1
     * zero byte provides the BREAK, then the TX-complete ISR switches to
     * 250-kbaud 8N2 for the start code and channel data. */
    advanceDynamicSourceFrame();
    UBRR1H = (uint8_t)(SOURCE_UBRR_100K >> 8);
    UBRR1L = (uint8_t)SOURCE_UBRR_100K;
    UCSR1A = 0;
    UCSR1C = (1 << UCSZ11) | (1 << UCSZ10); /* 8N1 */
    UCSR1B = (1 << TXEN1) | (1 << TXCIE1);
    UCSR1A |= (1 << TXC1);
    UDR1 = 0;
    sourceTxState = SOURCE_TX_BREAK;
}

ISR(USART1_TX_vect) {
    if (sourceTxState == SOURCE_TX_BREAK) {
        /* DMX requires at least 12 us of mark-after-break before the start
         * code. The delay is bounded to this UART interrupt only. */
        delayMicroseconds(12UL);
        UBRR1H = (uint8_t)(SOURCE_UBRR_250K >> 8);
        UBRR1L = (uint8_t)SOURCE_UBRR_250K;
        UCSR1C = (1 << UCSZ11) | (1 << UCSZ10) | (1 << USBS1); /* 8N2 */
        UCSR1B = (1 << TXEN1) | (1 << UDRIE1);
        UDR1 = 0;
        sourceTxChannel = 0;
        sourceTxState = SOURCE_TX_DATA;
    } else if (sourceTxState == SOURCE_TX_DONE) {
        sourceTxState = SOURCE_TX_IDLE;
        sourceFramesSent++;
        lastSourceFrameAtUs = micros();
        if (!firstSourceFrameAtUs) firstSourceFrameAtUs = lastSourceFrameAtUs;
    }
}

ISR(USART1_UDRE_vect) {
    if (sourceTxState != SOURCE_TX_DATA) {
        UCSR1B &= ~(1 << UDRIE1);
        return;
    }
    if (sourceTxChannel < generatorSlots) {
        UDR1 = sourceFrame[++sourceTxChannel];
        if (sourceTxChannel >= generatorSlots) {
            UCSR1B &= ~(1 << UDRIE1);
            UCSR1B |= (1 << TXCIE1);
            sourceTxState = SOURCE_TX_DONE;
        }
    }
}

static void resetMetrics(void) {
    checkedFrames = passedFrames = failedFrames = partialFrames = 0;
    maxGapMs = 0;
    lastCheckedAt = 0;
    haveCheckedFrame = false;
    sourceFramesSent = 0;
    firstSourceFrameAtUs = 0;
    lastSourceFrameAtUs = 0;
}

static bool matchesExpected(uint16_t slots) {
    const uint16_t checkedSlots = slots > DMX_SLOTS ? DMX_SLOTS : slots;
    for (uint16_t channel = 1; channel <= DMX_SLOTS; channel++) {
        const uint8_t wanted = channel <= checkedSlots ? expected[channel] : 0;
        if (monitorSnapshot[channel] != wanted) return false;
    }
    return true;
}

static void consumeMonitorFrame(unsigned long now) {
    if (!monitorReady || recordState != RECORD_MEASURE) return;
    noInterrupts();
    const uint16_t slots = monitorSlots;
    memcpy(monitorSnapshot, (const void*)monitorFrame, sizeof(monitorSnapshot));
    monitorReady = false;
    interrupts();
    lastMonitorDataAt = now;
    if (slots < DMX_SLOTS) partialFrames++;
    checkedFrames++;
    if (haveCheckedFrame && now - lastCheckedAt > maxGapMs) maxGapMs = now - lastCheckedAt;
    lastCheckedAt = now;
    haveCheckedFrame = true;
    if (matchesExpected(slots)) passedFrames++;
    else failedFrames++;
}

static void emitResult(unsigned long now) {
    Serial.print("RESULT seconds="); Serial.print((now - measureStart) / 1000UL);
    Serial.print(" generator_slots="); Serial.print(generatorSlots);
    Serial.print(" checked="); Serial.print(checkedFrames);
    Serial.print(" pass="); Serial.print(passedFrames);
    Serial.print(" fail="); Serial.print(failedFrames);
    Serial.print(" partial="); Serial.print(partialFrames);
    Serial.print(" max_gap="); Serial.print(maxGapMs);
    Serial.print(" no_data="); Serial.print(now - lastMonitorDataAt);
    Serial.print("ms source_frames="); Serial.print(sourceFramesSent);
    Serial.print(" source_rate_hz=");
    if (sourceFramesSent > 1 && lastSourceFrameAtUs > firstSourceFrameAtUs) {
        Serial.print((sourceFramesSent - 1) * 1000000.0 /
                     (lastSourceFrameAtUs - firstSourceFrameAtUs), 2);
    } else {
        Serial.print(0.0, 2);
    }
    Serial.println();
    recordState = RECORD_IDLE;
}

static void processCommand(char* command, unsigned long now) {
    unsigned long a = 0, b = 0, c = 0;
    if (sscanf(command, "GENERATE CONST %lu", &a) == 1 && a <= 255) {
        generatorPattern = GENERATOR_CONST; generatorSlots = DMX_SLOTS; generatorBase = (uint8_t)a;
        applyGenerator(); Serial.println("ACK GENERATE");
    } else if (sscanf(command, "GENERATE RAMP %lu", &a) == 1 && a <= 255) {
        generatorPattern = GENERATOR_RAMP; generatorSlots = DMX_SLOTS; generatorBase = (uint8_t)a;
        applyGenerator(); Serial.println("ACK GENERATE");
    } else if (sscanf(command, "GENERATE DYNAMIC %lu %lu", &a, &b) == 2 &&
               a <= 255 && b >= 100 && b <= 60000) {
        generatorPattern = GENERATOR_DYNAMIC; generatorSlots = DMX_SLOTS; generatorBase = (uint8_t)a;
        dynamicEpoch = 0; applyGenerator(); Serial.println("ACK GENERATE");
    } else if (sscanf(command, "GENERATE DYNAMIC_SHORT %lu %lu %lu", &a, &b, &c) == 3 &&
               a >= 1 && a <= DMX_SLOTS && b <= 255 && c >= 100 && c <= 60000) {
        generatorPattern = GENERATOR_DYNAMIC_SHORT; generatorSlots = (uint16_t)a;
        generatorBase = (uint8_t)b;
        dynamicEpoch = 0; applyGenerator(); Serial.println("ACK GENERATE");
    } else if (sscanf(command, "GENERATE SHORT %lu %lu", &a, &b) == 2 &&
               a >= 1 && a <= DMX_SLOTS && b <= 255) {
        generatorPattern = GENERATOR_SHORT; generatorSlots = (uint16_t)a; generatorBase = (uint8_t)b;
        applyGenerator(); Serial.println("ACK GENERATE");
    } else if (!strcmp(command, "STOP")) {
        recordState = RECORD_IDLE; sourceEnabled = false; stopSourceDmx(); Serial.println("ACK STOP");
    } else if (sscanf(command, "START %lu %lu", &a, &b) == 2 && b > 0) {
        resetMetrics(); sourceEnabled = true; stopSourceDmx();
        nextSourceFrameAtUs = micros();
        settleUntil = now + a * 1000UL; measureUntil = settleUntil + b * 1000UL;
        recordState = a ? RECORD_SETTLE : RECORD_MEASURE;
        if (!a) measureStart = now;
        Serial.println("ACK START");
    } else if (!strcmp(command, "STATUS")) {
        Serial.print("STATUS state="); Serial.print((int)recordState);
        Serial.print(" slots="); Serial.print(generatorSlots);
        Serial.print(" pattern="); Serial.println((int)generatorPattern);
    } else if (!strcmp(command, "ABORT")) {
        recordState = RECORD_IDLE; sourceEnabled = false; stopSourceDmx(); Serial.println("ACK STOP");
    } else {
        Serial.println("ERR COMMAND");
    }
}

static void pollCommands(unsigned long now) {
    while (Serial.available()) {
        const char value = (char)Serial.read();
        if (value == '\n' || value == '\r') {
            if (commandLength) {
                commandBuffer[commandLength] = 0;
                processCommand(commandBuffer, now);
                commandLength = 0;
            }
        } else if (commandLength < COMMAND_BUFFER_SIZE - 1) {
            commandBuffer[commandLength++] = value;
        } else commandLength = 0;
    }
}

void setup(void) {
    Serial.begin(TELE_BAUD);
    configureMonitorUart();
    applyGenerator();
    Serial.println("READY RETRANSMITTER_E2E_MEGA");
}

void loop(void) {
    const unsigned long now = millis();
    pollCommands(now);
    const uint32_t nowUs = micros();
    if (sourceEnabled && sourceTxState == SOURCE_TX_IDLE &&
        (int32_t)(nowUs - nextSourceFrameAtUs) >= 0) {
        startSourceDmx();
        nextSourceFrameAtUs += SOURCE_FRAME_PERIOD_US;
    }
    if (recordState == RECORD_SETTLE && now >= settleUntil) {
        recordState = RECORD_MEASURE; measureStart = now; resetMetrics();
    }
    if (recordState == RECORD_MEASURE && now >= measureUntil) emitResult(now);
    consumeMonitorFrame(now);
}