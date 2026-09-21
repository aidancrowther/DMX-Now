/**
 * Dumb physical DMX512 -> ESP-NOW retransmitter.
 * UART0/GPIO3 is owned by DMXUART. Do not call Serial.begin() or log.
 */
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>
#include <DMXUART.h>
#include <wireless_protocol.h>

#ifndef RETRANSMITTER_ESPNOW_CHANNEL
#define RETRANSMITTER_ESPNOW_CHANNEL ESPNOW_CHANNEL
#endif
#ifndef RETRANSMITTER_UNIVERSE_ID
#define RETRANSMITTER_UNIVERSE_ID DMX_UNIVERSE_ID
#endif
#ifndef RETRANSMITTER_WIRELESS_REFRESH_HZ
#define RETRANSMITTER_WIRELESS_REFRESH_HZ 10U
#endif
#ifndef RETRANSMITTER_TX_DRAIN_TIMEOUT_MS
#define RETRANSMITTER_TX_DRAIN_TIMEOUT_MS 100UL
#endif
#ifndef RETRANSMITTER_TX_OVERHEAD_MS
#define RETRANSMITTER_TX_OVERHEAD_MS 27UL
#endif
#ifndef RETRANSMITTER_FRAGMENT_SPACING_MS
#define RETRANSMITTER_FRAGMENT_SPACING_MS 15UL
#endif
#ifndef RETRANSMITTER_DIAGNOSTICS
#define RETRANSMITTER_DIAGNOSTICS 0
#endif
#ifndef RETRANSMITTER_DIAGNOSTIC_BROADCAST
#define RETRANSMITTER_DIAGNOSTIC_BROADCAST 0
#endif
#ifndef RETRANSMITTER_DMX_UART
#define RETRANSMITTER_DMX_UART 0
#endif
#ifndef RETRANSMITTER_DMX_RX_PIN
#define RETRANSMITTER_DMX_RX_PIN 3
#endif
#ifndef RETRANSMITTER_DMX_INVERT
#define RETRANSMITTER_DMX_INVERT 0
#endif
#ifndef RETRANSMITTER_DMX_SLOT_STABILITY_FRAMES
#define RETRANSMITTER_DMX_SLOT_STABILITY_FRAMES 3
#endif
#ifndef RETRANSMITTER_DMX_INPUT_ENABLE_PIN
/* GPIO2 drives the 2N2222 that pulls the receive transceiver /RE low. */
#define RETRANSMITTER_DMX_INPUT_ENABLE_PIN -1
#endif
#ifndef RETRANSMITTER_DMX_INPUT_ENABLE_ACTIVE_HIGH
/* GPIO2 LOW keeps the 2N2222 off, so the MAX3485 /RE pull-up enables RX. */
#define RETRANSMITTER_DMX_INPUT_ENABLE_ACTIVE_HIGH 0
#endif
#ifndef RETRANSMITTER_LOCATE_PIN
/* GPIO2 is reserved for the external receiver /RE control transistor. */
#define RETRANSMITTER_LOCATE_PIN -1
#endif
#ifndef RETRANSMITTER_LOCATE_ACTIVE_LOW
#define RETRANSMITTER_LOCATE_ACTIVE_LOW 1
#endif
#ifndef RETRANSMITTER_TELEMETRY_PERIOD_MS
#define RETRANSMITTER_TELEMETRY_PERIOD_MS 10000UL
#endif
#ifndef RETRANSMITTER_TELEMETRY_JITTER_MS
#define RETRANSMITTER_TELEMETRY_JITTER_MS 1000UL
#endif
#ifndef RETRANSMITTER_TELEMETRY_ONLY
#define RETRANSMITTER_TELEMETRY_ONLY 0
#endif
#ifndef RETRANSMITTER_BATTERY_MONITOR
#define RETRANSMITTER_BATTERY_MONITOR 0
#endif
#ifndef RETRANSMITTER_BATTERY_PIN
#define RETRANSMITTER_BATTERY_PIN 1
#endif
#ifndef RETRANSMITTER_BATTERY_LOW_ACTIVE_LOW
#define RETRANSMITTER_BATTERY_LOW_ACTIVE_LOW 1
#endif
#if RETRANSMITTER_WIRELESS_REFRESH_HZ == 0
#error RETRANSMITTER_WIRELESS_REFRESH_HZ must be positive
#endif
#if RETRANSMITTER_FRAGMENT_SPACING_MS == 0
#error RETRANSMITTER_FRAGMENT_SPACING_MS must be positive
#endif
#if RETRANSMITTER_FRAGMENT_SPACING_MS * DMX_FRAGMENTS_PER_UNIVERSE >= (1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ)
#error RETRANSMITTER_FRAGMENT_SPACING_MS leaves no inter-universe guard time
#endif

static volatile bool captureRequested = true;
static uint8_t dmxReadBuffer[DMX_UNIVERSE_SIZE];
static DMXUART* dmxInput = nullptr;
static uint32_t inputFramesReceived = 0;
static uint32_t inputFramesSkipped = 0;
static uint32_t inputSlotMismatches = 0;
static uint16_t learnedInputSlots = 0;
static uint16_t candidateInputSlots = 0;
static uint8_t candidateInputSlotFrames = 0;
static uint32_t inputInvalidStartCodes = 0;
static uint32_t inputInvalidLengths = 0;
static uint8_t g_universe[DMX_UNIVERSE_SIZE];
static uint8_t g_txUniverse[DMX_UNIVERSE_SIZE];
static uint32_t g_frameSequence = 0;
/* A valid universe may remain available after it has been transmitted, but a
 * new wireless cycle must not reuse it until a fresh physical-DMX frame has
 * completed. This matters when a 236-slot source changes to 512 slots: the
 * old universe is intentionally zero-filled after slot 236. */
static bool freshUniverseAvailable = false;
static bool inputRequestedEnabled = true;
static uint32_t inputControlGeneration = 0;
static unsigned long lastInputFrameMs = 0;
static uint32_t wirelessFramesSent = 0;
static uint32_t wirelessSendFailures = 0;
static unsigned long nextTelemetryAt = 0;
static uint32_t telemetrySequence = 0;
static volatile bool telemetryPending = false;
static volatile bool telemetryInFlight = false;
static bool locateActive = false;
static bool locateRestoreInputEnabled = true;
static unsigned long locateEndMs = 0;
static unsigned long locateNextPulseMs = 0;
static bool locatePulse = false;
static volatile uint8_t sendConfirmations = 0;
static volatile uint32_t txCallbackSuccess = 0;
static volatile uint32_t txCallbackFailure = 0;
static uint32_t frameCallbackSuccessStart = 0;
static uint32_t frameCallbackFailureStart = 0;
static uint32_t txEnqueueAttempts[DMX_FRAGMENTS_PER_UNIVERSE] = {0};
static uint32_t txEnqueueSuccess[DMX_FRAGMENTS_PER_UNIVERSE] = {0};
static uint32_t txEnqueueFailures[DMX_FRAGMENTS_PER_UNIVERSE] = {0};
static uint32_t txSerializedBusySkips = 0;
static uint32_t txMissedDeadlines = 0;
static uint32_t txCycleOverruns = 0;
#if RETRANSMITTER_DIAGNOSTICS
static unsigned long lastDiagnosticsAt = 0;
static const unsigned long DIAGNOSTICS_INTERVAL_MS = 1000UL;
#endif

/* Diagnostic A/B option: reverse the three-fragment burst without changing
 * packet contents, pacing, or frame sequencing. If the missing fragment
 * follows burst position rather than fragment identity, the loss is temporal
 * (UART/SDK/RF burst interaction) rather than packet-specific. */
#if defined(RETRANSMITTER_REVERSE_FRAGMENT_ORDER)
static const uint8_t txFragmentOrder[DMX_FRAGMENTS_PER_UNIVERSE] = {2, 1, 0};
#else
static const uint8_t txFragmentOrder[DMX_FRAGMENTS_PER_UNIVERSE] = {0, 1, 2};
#endif

/* Diagnostic A/B option: wait for the ESP-NOW send callback before enqueueing
 * the next fragment. This removes the three-packet burst while preserving the
 * same packet format and frame sequence semantics. */
#if defined(RETRANSMITTER_REVERSE_FRAGMENT_ORDER)
#error Do not combine retransmitter fragment-order and serialization diagnostics
#endif
static bool haveUniverse = false;
static unsigned long lastFrameGenerationTime = 0;
static unsigned long nextFrameAt = 0;
static bool frameDeadlineValid = false;
static unsigned long stateAt = 0;
static uint8_t currentFragment = 0;

enum TxState { TX_WAIT_INPUT, TX_IDLE, TX_SENDING, TX_DRAIN };
static TxState txState = TX_WAIT_INPUT;
/* Match the normal transmitter's queue/drain state machine. The requested
 * 20 Hz period includes the measured wireless overhead; DMX RX is paused for
 * the complete queued send and resumed after callbacks or the drain timeout. */
static constexpr unsigned long TX_INTERVAL_MS =
    (1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ > RETRANSMITTER_TX_OVERHEAD_MS)
        ? (1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ - RETRANSMITTER_TX_OVERHEAD_MS) : 0UL;
static constexpr unsigned long FRAME_PERIOD_MS =
    1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ;
static bool dmxRxPaused = false;
static bool administrativeInputPause = false;

struct PendingRetransmitterControl {
    uint8_t data[sizeof(RetransmitterLocatePacket)];
    uint8_t len;
};
static PendingRetransmitterControl pendingControl;
static volatile bool controlPending = false;

static void setInputEnablePin(bool enabled) {
#if RETRANSMITTER_DMX_INPUT_ENABLE_PIN >= 0
    digitalWrite(RETRANSMITTER_DMX_INPUT_ENABLE_PIN,
                 enabled == (RETRANSMITTER_DMX_INPUT_ENABLE_ACTIVE_HIGH != 0) ? HIGH : LOW);
#else
    (void)enabled;
#endif
}

static uint8_t readBatteryState(void) {
#if RETRANSMITTER_BATTERY_MONITOR
    const bool comparatorActive = digitalRead(RETRANSMITTER_BATTERY_PIN) ==
        (RETRANSMITTER_BATTERY_LOW_ACTIVE_LOW ? LOW : HIGH);
    return comparatorActive ? 1U : 0U;
#else
    return RETRANSMITTER_BATTERY_UNKNOWN;
#endif
}

static void scheduleRetransmitterTelemetry(unsigned long now, bool initial) {
    const unsigned long jitter = RETRANSMITTER_TELEMETRY_JITTER_MS
        ? (initial ? (ESP.getChipId() % (RETRANSMITTER_TELEMETRY_JITTER_MS + 1UL))
                   : random(RETRANSMITTER_TELEMETRY_JITTER_MS + 1UL)) : 0UL;
    nextTelemetryAt = now + RETRANSMITTER_TELEMETRY_PERIOD_MS + jitter;
}

static void serviceLocate(void) {
    if (!locateActive) return;
#if RETRANSMITTER_LOCATE_PIN < 0
    locateActive = false;
    return;
#else
    const unsigned long now = millis();
    if ((long)(now - locateEndMs) >= 0) {
        locateActive = false;
        digitalWrite(RETRANSMITTER_LOCATE_PIN,
                     RETRANSMITTER_LOCATE_ACTIVE_LOW ? HIGH : LOW);
        setInputEnablePin(inputRequestedEnabled);
        administrativeInputPause = !locateRestoreInputEnabled;
        if (locateRestoreInputEnabled && dmxInput) {
            dmxInput->resumeRx();
            captureRequested = true;
            freshUniverseAvailable = false;
        }
        return;
    }
    if ((long)(now - locateNextPulseMs) >= 0) {
        locatePulse = !locatePulse;
        const bool on = locatePulse;
        digitalWrite(RETRANSMITTER_LOCATE_PIN,
                     on == (RETRANSMITTER_LOCATE_ACTIVE_LOW != 0) ? LOW : HIGH);
        locateNextPulseMs = now + 500UL;
    }
#endif
}

static void processRetransmitterControl(void) {
    if (!controlPending) return;
    uint8_t data[sizeof(pendingControl.data)];
    uint8_t len;
    noInterrupts();
    memcpy(data, pendingControl.data, sizeof(data));
    len = pendingControl.len;
    controlPending = false;
    interrupts();
    if (len == sizeof(RetransmitterInputControlPacket)) {
        RetransmitterInputControlPacket packet;
        memcpy(&packet, data, sizeof(packet));
        if (packet.magic == DMX_PACKET_MAGIC && packet.protocolVersion == DMX_PROTO_VERSION &&
            packet.packetType == RETRANSMITTER_INPUT_CONTROL_PACKET_TYPE &&
            packet.universeId == RETRANSMITTER_UNIVERSE_ID &&
            (packet.targetRetransmitterId == 0U || packet.targetRetransmitterId == ESP.getChipId()) &&
            packet.generation >= inputControlGeneration) {
            inputControlGeneration = packet.generation;
            inputRequestedEnabled = packet.enabled != 0U;
            setInputEnablePin(inputRequestedEnabled);
            if (!inputRequestedEnabled) {
                captureRequested = false;
                freshUniverseAvailable = false;
                administrativeInputPause = true;
                if (dmxInput && !dmxRxPaused) dmxInput->pauseRx();
            } else if (dmxInput && administrativeInputPause) {
                dmxInput->resumeRx();
                administrativeInputPause = false;
                captureRequested = true;
                freshUniverseAvailable = false;
            }
        }
    } else if (len == sizeof(RetransmitterLocatePacket)) {
        RetransmitterLocatePacket packet;
        memcpy(&packet, data, sizeof(packet));
        if (packet.magic == DMX_PACKET_MAGIC && packet.protocolVersion == DMX_PROTO_VERSION &&
            packet.packetType == RETRANSMITTER_LOCATE_PACKET_TYPE &&
            packet.universeId == RETRANSMITTER_UNIVERSE_ID &&
            (packet.targetRetransmitterId == 0U || packet.targetRetransmitterId == ESP.getChipId()) &&
            packet.durationSeconds >= 1U && packet.durationSeconds <= 15U &&
            packet.generation >= inputControlGeneration) {
#if RETRANSMITTER_LOCATE_PIN < 0
            /* GPIO2 is reserved for receiver /RE control on this hardware.
             * Do not pause DMX or alter input state when no locate output exists. */
            return;
#else
            inputControlGeneration = packet.generation;
            locateActive = true;
            locateRestoreInputEnabled = inputRequestedEnabled;
            locateEndMs = millis() + (unsigned long)packet.durationSeconds * 1000UL;
            locateNextPulseMs = millis();
            locatePulse = false;
            captureRequested = false;
            freshUniverseAvailable = false;
            administrativeInputPause = true;
            if (dmxInput && !dmxRxPaused) dmxInput->pauseRx();
            setInputEnablePin(false);
#endif
        }
    }
}

static void transmitRetransmitterTelemetry(void) {
    if (locateActive) return;
    if (telemetryInFlight || !quickEspNow.readyToSendData()) return;
    RetransmitterTelemetryPacket packet;
    memset(&packet, 0, sizeof(packet));
    packet.magic = DMX_PACKET_MAGIC;
    packet.protocolVersion = DMX_PROTO_VERSION;
    packet.packetType = RETRANSMITTER_TELEMETRY_PACKET_TYPE;
    packet.universeId = RETRANSMITTER_UNIVERSE_ID;
    packet.retransmitterId = ESP.getChipId();
    WiFi.macAddress(packet.macAddress);
    packet.uptimeSeconds = millis() / 1000UL;
    packet.telemetrySequence = telemetrySequence++;
    packet.inputEnabled = inputRequestedEnabled ? 1U : 0U;
    packet.inputSignalActive = lastInputFrameMs && millis() - lastInputFrameMs <= 1500UL;
    packet.batteryState = readBatteryState();
    packet.locateActive = locateActive ? 1U : 0U;
    packet.inputHardwareControlAvailable = RETRANSMITTER_DMX_INPUT_ENABLE_PIN >= 0 ? 1U : 0U;
    packet.learnedInputSlots = learnedInputSlots;
    packet.timeSinceLastInputMs = lastInputFrameMs ? millis() - lastInputFrameMs : 0xFFFFFFFFUL;
    packet.inputFramesReceived = inputFramesReceived;
    packet.inputFramesSkipped = inputFramesSkipped;
    packet.invalidStartCodes = inputInvalidStartCodes;
    packet.invalidLengths = inputInvalidLengths;
    packet.wirelessFrameSequence = g_frameSequence;
    packet.wirelessFramesSent = wirelessFramesSent;
    packet.wirelessSendFailures = wirelessSendFailures;
    packet.missedDeadlines = txMissedDeadlines;
    packet.controlGeneration = inputControlGeneration;
    if (quickEspNow.sendBcast(reinterpret_cast<const uint8_t*>(&packet), sizeof(packet)) == COMMS_SEND_OK) {
        telemetryInFlight = true;
        scheduleRetransmitterTelemetry(millis(), false);
    } else {
        nextTelemetryAt = millis() + 100UL;
    }
}

static void pollDmxInput(void) {
    if (dmxInput == nullptr || dmxRxPaused) return;

    int startCode = -1;
    const int slots = dmxInput->read(&startCode);
    if (slots <= 0) return;
    if (startCode != 0) {
        inputInvalidStartCodes++;
        return;
    }
    if (slots < UART_MINCHANS_DMX || slots > DMX_UNIVERSE_SIZE) {
        inputInvalidLengths++;
        return;
    }

    if (learnedInputSlots == 0) {
        learnedInputSlots = (uint16_t)slots;
    } else if ((uint16_t)slots != learnedInputSlots) {
        inputSlotMismatches++;
        if (candidateInputSlots == (uint16_t)slots) {
            if (candidateInputSlotFrames < 255) candidateInputSlotFrames++;
        } else {
            candidateInputSlots = (uint16_t)slots;
            candidateInputSlotFrames = 1;
        }
        if (candidateInputSlotFrames >= RETRANSMITTER_DMX_SLOT_STABILITY_FRAMES) {
            learnedInputSlots = candidateInputSlots;
            candidateInputSlots = 0;
            candidateInputSlotFrames = 0;
        } else {
            return;
        }
    } else {
        candidateInputSlots = 0;
        candidateInputSlotFrames = 0;
    }

    if (!captureRequested) {
        inputFramesSkipped++;
        return;
    }

    /* DMXUART owns the ISR-side frame assembly. read() copies the completed,
     * stable frame into dmxReadBuffer in foreground context. */
    memcpy(g_universe, dmxReadBuffer, (size_t)slots);
    memset(g_universe + slots, 0, DMX_UNIVERSE_SIZE - (size_t)slots);
    captureRequested = false;
    inputFramesReceived++;
    lastInputFrameMs = millis();
    haveUniverse = true;
    freshUniverseAvailable = true;
}

static void submitFragment(uint8_t fragmentIndex) {
    const uint16_t offset = static_cast<uint16_t>(fragmentIndex) * DMX_PAYLOAD_SIZE;
    const uint8_t payloadLength = dmx_fragment_payload_length(offset, DMX_UNIVERSE_SIZE);
    uint8_t packetBuffer[DMX_TOTAL_PACKET_SIZE];
    DmxFragmentPacket packet;
    packet.magic = DMX_PACKET_MAGIC;
    packet.protocolVersion = DMX_PROTO_VERSION;
    packet.packetType = DMX_PACKET_TYPE;
    packet.universeId = RETRANSMITTER_UNIVERSE_ID;
    packet.frameSequence = g_frameSequence;
    packet.fragmentIndex = fragmentIndex;
    packet.fragmentCount = DMX_FRAGMENTS_PER_UNIVERSE;
    packet.dataOffset = offset;
    packet.payloadLength = payloadLength;
    memcpy(packetBuffer, &packet, sizeof(packet));
    memcpy(packetBuffer + DMX_HEADER_SIZE, g_txUniverse + offset, payloadLength);
    if (fragmentIndex < DMX_FRAGMENTS_PER_UNIVERSE) txEnqueueAttempts[fragmentIndex]++;
    const comms_send_error_t result = quickEspNow.sendBcast(
        packetBuffer, DMX_HEADER_SIZE + payloadLength);
    if (fragmentIndex < DMX_FRAGMENTS_PER_UNIVERSE) {
        if (result == COMMS_SEND_OK) txEnqueueSuccess[fragmentIndex]++;
        else txEnqueueFailures[fragmentIndex]++;
    }
}

#if RETRANSMITTER_DIAGNOSTICS
static void submitDiagnostics(void) {
    RetransmitterDiagnosticsPacket packet;
    packet.magic = DMX_PACKET_MAGIC;
    packet.protocolVersion = DMX_PROTO_VERSION;
    packet.packetType = RETRANSMITTER_DIAGNOSTICS_PACKET_TYPE;
    packet.universeId = RETRANSMITTER_UNIVERSE_ID;
    packet.frameSequence = g_frameSequence;
    packet.inputFramesReceived = inputFramesReceived;
    for (uint8_t i = 0; i < DMX_FRAGMENTS_PER_UNIVERSE; i++) {
        packet.enqueueAttempts[i] = txEnqueueAttempts[i];
        packet.enqueueSuccess[i] = txEnqueueSuccess[i];
        packet.enqueueFailures[i] = txEnqueueFailures[i];
    }
    packet.callbackSuccess = txCallbackSuccess;
    packet.callbackFailure = txCallbackFailure;
    packet.inputFramesSkipped = inputFramesSkipped;
    packet.inputSlotMismatches = inputSlotMismatches;
    packet.learnedInputSlots = learnedInputSlots;
    packet.serializedBusySkips = txSerializedBusySkips;
    packet.missedDeadlines = txMissedDeadlines;
    packet.cycleOverruns = txCycleOverruns;
#if RETRANSMITTER_DIAGNOSTIC_BROADCAST
    quickEspNow.sendBcast(reinterpret_cast<const uint8_t*>(&packet), sizeof(packet));
#endif
}
#endif

void setup(void) {
    /* tx_pin=-1 is intentional. On ESP8266 DMXUART selects
     * SerialMode::SERIAL_RX_ONLY, so UART0 RX/GPIO3 remains DMX input while
     * UART0 TX/GPIO1 is available for the optional battery comparator. */
    static DMXUART input(
        RETRANSMITTER_DMX_UART, dmxReadBuffer, -1, -1,
        RETRANSMITTER_DMX_RX_PIN, RETRANSMITTER_DMX_INVERT, false);
    dmxInput = &input;
#if RETRANSMITTER_DMX_INPUT_ENABLE_PIN >= 0
    pinMode(RETRANSMITTER_DMX_INPUT_ENABLE_PIN, OUTPUT);
#endif
#if RETRANSMITTER_BATTERY_MONITOR
    pinMode(RETRANSMITTER_BATTERY_PIN, INPUT);
#endif
#if RETRANSMITTER_LOCATE_PIN >= 0
    pinMode(RETRANSMITTER_LOCATE_PIN, OUTPUT);
    digitalWrite(RETRANSMITTER_LOCATE_PIN, RETRANSMITTER_LOCATE_ACTIVE_LOW ? HIGH : LOW);
#endif
    setInputEnablePin(true);
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);
    /* Use asynchronous QuickESPNow. Fragment serialization is enforced by
     * the library's packet-aware queue/in-flight state, not by the sketch's
     * global and untagged send callback. */
    if (!quickEspNow.begin(RETRANSMITTER_ESPNOW_CHANNEL, WIFI_IF_STA, false)) {
        while (true) delay(10);
    }
    quickEspNow.onDataSent([](uint8_t*, uint8_t status) {
        if (telemetryInFlight) {
            telemetryInFlight = false;
        } else {
            if (sendConfirmations < 255) sendConfirmations++;
            if (status == ESP_NOW_SEND_SUCCESS) txCallbackSuccess++;
            else txCallbackFailure++;
        }
    });
    quickEspNow.onDataRcvd([](uint8_t*, uint8_t* data, uint8_t len, signed int, bool) {
        if (len == sizeof(RetransmitterInputControlPacket) || len == sizeof(RetransmitterLocatePacket)) {
            noInterrupts();
            memcpy(pendingControl.data, data, len);
            pendingControl.len = len;
            controlPending = true;
            interrupts();
        }
    });
    scheduleRetransmitterTelemetry(millis(), true);
}

void loop(void) {
    const unsigned long now = millis();
    processRetransmitterControl();
    serviceLocate();
    if ((long)(now - nextTelemetryAt) >= 0) telemetryPending = true;
    if (telemetryPending && !telemetryInFlight && txState != TX_SENDING && txState != TX_DRAIN &&
        quickEspNow.readyToSendData()) {
        transmitRetransmitterTelemetry();
        telemetryPending = false;
    }
    if (telemetryInFlight) return;
#if RETRANSMITTER_TELEMETRY_ONLY
    return;
#else
    if (!inputRequestedEnabled || locateActive || administrativeInputPause) return;
    pollDmxInput();
#if RETRANSMITTER_DIAGNOSTICS && RETRANSMITTER_DIAGNOSTIC_BROADCAST
    if (txState == TX_IDLE &&
        now - lastFrameGenerationTime < TX_INTERVAL_MS &&
        quickEspNow.readyForSerializedSend() &&
        now - lastDiagnosticsAt >= DIAGNOSTICS_INTERVAL_MS) {
        lastDiagnosticsAt = now;
        submitDiagnostics();
        return;
    }
#endif
    if (!haveUniverse) {
        txState = TX_WAIT_INPUT;
        return;
    }
    if (txState == TX_WAIT_INPUT) {
        if (!freshUniverseAvailable) return;
        freshUniverseAvailable = false;
        if (!frameDeadlineValid) {
            nextFrameAt = now;
            frameDeadlineValid = true;
        }
        lastFrameGenerationTime = now;
        txState = TX_IDLE;
    }
    switch (txState) {
        case TX_IDLE:
            if ((long)(now - nextFrameAt) >= 0) {
                memcpy(g_txUniverse, g_universe, sizeof(g_txUniverse));
                /* The current universe is latched above. Capture exactly one
                 * subsequent physical-DMX frame for the next wireless cycle. */
                captureRequested = false;
                dmxRxPaused = dmxInput->pauseRx();
                if (!dmxRxPaused) {
                    captureRequested = true;
                    txState = TX_IDLE;
                    break;
                }
                currentFragment = 0;
                sendConfirmations = 0;
                frameCallbackSuccessStart = txCallbackSuccess;
                frameCallbackFailureStart = txCallbackFailure;
                stateAt = now;
                nextFrameAt += FRAME_PERIOD_MS;
                /* A long send/capture stall must not cause an immediate burst
                 * of catch-up universes. Rebase to one period from now. */
                if ((long)(now - nextFrameAt) >= 0) nextFrameAt = now + FRAME_PERIOD_MS;
                txState = TX_SENDING;
            }
            break;
        case TX_SENDING:
            if (currentFragment < DMX_FRAGMENTS_PER_UNIVERSE) {
                /* Queue each fragment once. QuickESPNow serializes these
                 * queued sends while DMXUART RX remains paused. */
                submitFragment(txFragmentOrder[currentFragment++]);
            } else {
                stateAt = now;
                txState = TX_DRAIN;
            }
            break;
        case TX_DRAIN:
            if (sendConfirmations >= DMX_FRAGMENTS_PER_UNIVERSE ||
                now - stateAt >= RETRANSMITTER_TX_DRAIN_TIMEOUT_MS) {
                if (dmxRxPaused) {
                    dmxInput->resumeRx();
                    dmxRxPaused = false;
                }
                captureRequested = true;
                const uint32_t frameSuccesses = txCallbackSuccess - frameCallbackSuccessStart;
                const uint32_t frameFailures = txCallbackFailure - frameCallbackFailureStart;
                if (frameSuccesses >= DMX_FRAGMENTS_PER_UNIVERSE && frameFailures == 0U) {
                    if (wirelessFramesSent < 0xFFFFFFFFUL) wirelessFramesSent++;
                } else if (frameFailures > 0U || frameSuccesses < DMX_FRAGMENTS_PER_UNIVERSE) {
                    if (wirelessSendFailures < 0xFFFFFFFFUL) wirelessSendFailures++;
                }
                g_frameSequence++;
                /* Wait for a complete fresh physical-DMX frame before the
                 * next burst. Elapsed time alone is not a valid boundary for
                 * a full 512-slot frame. */
                txState = TX_WAIT_INPUT;
            }
            break;
        case TX_WAIT_INPUT:
            break;
    }
#endif
}
