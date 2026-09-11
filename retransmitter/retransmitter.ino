/**
 * Dumb physical DMX512 -> ESP-NOW retransmitter.
 * UART0/GPIO3 is owned by LXESP8266DMX. Do not call Serial.begin() or log.
 */
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>
#include <LXESP8266UARTDMX.h>
#include <wireless_protocol.h>

#ifndef RETRANSMITTER_ESPNOW_CHANNEL
#define RETRANSMITTER_ESPNOW_CHANNEL ESPNOW_CHANNEL
#endif
#ifndef RETRANSMITTER_UNIVERSE_ID
#define RETRANSMITTER_UNIVERSE_ID DMX_UNIVERSE_ID
#endif
#ifndef RETRANSMITTER_WIRELESS_REFRESH_HZ
#define RETRANSMITTER_WIRELESS_REFRESH_HZ WIRELESS_REFRESH_HZ
#endif
#ifndef RETRANSMITTER_TX_DRAIN_TIMEOUT_MS
#define RETRANSMITTER_TX_DRAIN_TIMEOUT_MS 100UL
#endif
#ifndef RETRANSMITTER_TX_OVERHEAD_MS
#define RETRANSMITTER_TX_OVERHEAD_MS 27UL
#endif
/* Strict 512-slot input is the production default. Define this flag to accept
 * shorter valid DMX frames and zero-fill the remaining channels. */
#ifndef RETRANSMITTER_ACCEPT_PARTIAL_UNIVERSE
#define RETRANSMITTER_ACCEPT_PARTIAL_UNIVERSE 0
#endif

#if RETRANSMITTER_WIRELESS_REFRESH_HZ == 0
#error RETRANSMITTER_WIRELESS_REFRESH_HZ must be positive
#endif

static LX8266DMX& dmxInput = ESP8266DMX;
static volatile bool inputFramePending = false;
static volatile uint32_t inputFramesReceived = 0;
static uint8_t g_universe[DMX_UNIVERSE_SIZE];
static uint8_t g_txUniverse[DMX_UNIVERSE_SIZE];
static uint32_t g_frameSequence = 0;
static volatile uint8_t sendConfirmations = 0;
static bool haveUniverse = false;
static unsigned long lastFrameAt = 0;
static unsigned long stateAt = 0;
static uint8_t currentFragment = 0;

enum TxState { TX_WAIT_INPUT, TX_IDLE, TX_SENDING, TX_DRAIN };
static TxState txState = TX_WAIT_INPUT;
static constexpr unsigned long TX_INTERVAL_MS =
    (1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ > RETRANSMITTER_TX_OVERHEAD_MS)
        ? (1000UL / RETRANSMITTER_WIRELESS_REFRESH_HZ - RETRANSMITTER_TX_OVERHEAD_MS) : 0UL;

static void inputFrameReceived(int slots) {
    if (slots > 0 &&
#if RETRANSMITTER_ACCEPT_PARTIAL_UNIVERSE
        slots <= DMX_UNIVERSE_SIZE
#else
        slots >= DMX_UNIVERSE_SIZE
#endif
    ) {
        inputFramePending = true;
        if (inputFramesReceived < 0xFFFFFFFFUL) inputFramesReceived++;
    }
}

static void copyCompletedInput(void) {
    if (!inputFramePending) return;
    noInterrupts();
    inputFramePending = false;
    interrupts();
    /* LXESP8266DMX exposes one receive buffer rather than a double buffer.
     * Quiesce its UART interrupt while copying the completed frame so the next
     * physical frame cannot overwrite the snapshot halfway through. A frame
     * arriving during this short handoff is intentionally dropped; latest-state
     * wireless pacing makes that safer than forwarding mixed channel data. */
    dmxInput.stop();
    uint8_t* received = dmxInput.receivedData();
    const uint16_t slots = dmxInput.numberOfSlots();
    if (received != nullptr && received[0] == 0 && slots > 0 && slots <= DMX_UNIVERSE_SIZE) {
        memset(g_universe, 0, sizeof(g_universe));
        memcpy(g_universe, received + 1, slots);
        haveUniverse = true;
    }
    dmxInput.startInput();
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
    quickEspNow.sendBcast(packetBuffer, DMX_HEADER_SIZE + payloadLength);
}

void setup(void) {
    dmxInput.setMaxSlots(DMX_UNIVERSE_SIZE);
    dmxInput.setDataReceivedCallback(inputFrameReceived);
    dmxInput.startInput();
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);
    if (!quickEspNow.begin(RETRANSMITTER_ESPNOW_CHANNEL, WIFI_IF_STA, false)) {
        while (true) delay(10);
    }
    quickEspNow.onDataSent([](uint8_t*, uint8_t) {
        if (sendConfirmations < 255) sendConfirmations++;
    });
}

void loop(void) {
    const unsigned long now = millis();
    copyCompletedInput();
    if (!haveUniverse) {
        txState = TX_WAIT_INPUT;
        return;
    }
    if (txState == TX_WAIT_INPUT) {
        lastFrameAt = now;
        txState = TX_IDLE;
    }
    switch (txState) {
        case TX_IDLE:
            if (now - lastFrameAt >= TX_INTERVAL_MS) {
                memcpy(g_txUniverse, g_universe, sizeof(g_txUniverse));
                currentFragment = 0;
                sendConfirmations = 0;
                txState = TX_SENDING;
                stateAt = now;
            }
            break;
        case TX_SENDING:
            if (currentFragment < DMX_FRAGMENTS_PER_UNIVERSE) {
                submitFragment(currentFragment++);
            } else {
                txState = TX_DRAIN;
                stateAt = now;
            }
            break;
        case TX_DRAIN:
            if (sendConfirmations >= DMX_FRAGMENTS_PER_UNIVERSE ||
                now - stateAt >= RETRANSMITTER_TX_DRAIN_TIMEOUT_MS) {
                g_frameSequence++;
                lastFrameAt = now;
                txState = TX_IDLE;
            }
            break;
        case TX_WAIT_INPUT:
            break;
    }
}