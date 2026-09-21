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
#if RETRANSMITTER_WIRELESS_REFRESH_HZ == 0
#error RETRANSMITTER_WIRELESS_REFRESH_HZ must be positive
#endif
#if RETRANSMITTER_FRAGMENT_SPACING_MS == 0
#error RETRANSMITTER_FRAGMENT_SPACING_MS must be positive
#endif
#if RETRANSMITTER_FRAGMENT_SPACING_MS * DMX_FRAGMENTS_PER_UNIVERSE >= (1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ)
#error RETRANSMITTER_FRAGMENT_SPACING_MS leaves no inter-universe guard time
#endif

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
static volatile uint8_t sendConfirmations = 0;
static volatile uint32_t txCallbackSuccess = 0;
static volatile uint32_t txCallbackFailure = 0;
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
static unsigned long nextFrameAt = 0;
static bool frameDeadlineValid = false;
static unsigned long stateAt = 0;
static uint8_t currentFragment = 0;

enum TxState { TX_IDLE, TX_SENDING, TX_DRAIN };
static TxState txState = TX_IDLE;
/* Absolute wireless deadlines overlap continuous DMX capture with RF drain. */
static constexpr unsigned long FRAME_PERIOD_MS =
    1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ;

static void pollDmxInput(void) {
    if (dmxInput == nullptr) return;

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

    /* DMXUART owns the ISR-side frame assembly. read() copies the completed,
     * stable frame into dmxReadBuffer in foreground context. */
    memcpy(g_universe, dmxReadBuffer, (size_t)slots);
    memset(g_universe + slots, 0, DMX_UNIVERSE_SIZE - (size_t)slots);
    inputFramesReceived++;
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
    static DMXUART input(
        RETRANSMITTER_DMX_UART, dmxReadBuffer, -1, -1,
        RETRANSMITTER_DMX_RX_PIN, RETRANSMITTER_DMX_INVERT, false);
    dmxInput = &input;
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);
    /* Use asynchronous QuickESPNow. Fragment serialization is enforced by
     * the library's packet-aware queue/in-flight state, not by the sketch's
     * global and untagged send callback. */
    if (!quickEspNow.begin(RETRANSMITTER_ESPNOW_CHANNEL, WIFI_IF_STA, false)) {
        while (true) delay(10);
    }
    quickEspNow.onDataSent([](uint8_t*, uint8_t status) {
        if (sendConfirmations < 255) sendConfirmations++;
        if (status == ESP_NOW_SEND_SUCCESS) txCallbackSuccess++;
        else txCallbackFailure++;
    });
}

void loop(void) {
    const unsigned long now = millis();
    pollDmxInput();
#if RETRANSMITTER_DIAGNOSTICS && RETRANSMITTER_DIAGNOSTIC_BROADCAST
    if (txState == TX_IDLE &&
        (!frameDeadlineValid || (long)(nextFrameAt - now) > 0) &&
        quickEspNow.readyForSerializedSend() &&
        now - lastDiagnosticsAt >= DIAGNOSTICS_INTERVAL_MS) {
        lastDiagnosticsAt = now;
        submitDiagnostics();
        return;
    }
#endif
    if (!frameDeadlineValid && freshUniverseAvailable) {
        nextFrameAt = now;
        frameDeadlineValid = true;
    }
    switch (txState) {
        case TX_IDLE:
            if (freshUniverseAvailable && (long)(now - nextFrameAt) >= 0 &&
                quickEspNow.readyForSerializedSend()) {
                memcpy(g_txUniverse, g_universe, sizeof(g_txUniverse));
                // Input reception continues while the immutable g_txUniverse
                // supplies all three fragments. A new burst requires a new
                // complete physical frame, even after a wireless deadline.
                freshUniverseAvailable = false;
                currentFragment = 0;
                sendConfirmations = 0;
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
                 * queued sends while DMXUART receives the next physical frame. */
                submitFragment(txFragmentOrder[currentFragment++]);
            } else {
                stateAt = now;
                txState = TX_DRAIN;
            }
            break;
        case TX_DRAIN:
            if (sendConfirmations >= DMX_FRAGMENTS_PER_UNIVERSE ||
                now - stateAt >= RETRANSMITTER_TX_DRAIN_TIMEOUT_MS) {
                g_frameSequence++;
                txState = TX_IDLE;
            }
            break;
    }
}
