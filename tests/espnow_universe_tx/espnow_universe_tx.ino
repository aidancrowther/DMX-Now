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

/* Static universe buffer (the latest generated snapshot). */
static uint8_t g_universe[DMX_UNIVERSE_SIZE];

/* Sequence number for the current frame (incremented after a full frame). */
static uint32_t g_frameSequence = 0;

/* Fragment-send confirmations received for the in-flight frame (0..fragCount). */
static volatile uint8_t g_sendConfirmations = 0;

/* Generate the deterministic test universe: g_universe[i] = (i + seq) & 0xFF. */
void generateTestUniverse(uint32_t seq) {
    for (uint16_t i = 0; i < DMX_UNIVERSE_SIZE; ++i) {
        g_universe[i] = static_cast<uint8_t>((static_cast<uint32_t>(i) + seq) & 0xFF);
    }
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

    delay(500);

    Serial.println();
    Serial.printf("TX ready seq=%u\n", g_frameSequence);
    Serial.printf("refresh=%uHz\n", WIRELESS_REFRESH_HZ);
    Serial.printf("header=%d payload=%d total=%d frags=%d\n",
                  static_cast<int>(DMX_HEADER_SIZE),
                  static_cast<int>(DMX_PAYLOAD_SIZE),
                  static_cast<int>(DMX_TOTAL_PACKET_SIZE),
                  static_cast<int>(DMX_FRAGMENTS_PER_UNIVERSE));
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
                          g_frameSequence, DMX_FRAGMENTS_PER_UNIVERSE);
            txState = TX_SENDING;
            stateEnteredTime = now;
            break;

        case TX_SENDING:
            if (currentFragment < DMX_FRAGMENTS_PER_UNIVERSE) {
                submitFragment(g_frameSequence, currentFragment);
                currentFragment++;
            } else {
                /* All fragments queued - wait for the queue to drain. */
                txState = TX_DRAIN;
                stateEnteredTime = now;
            }
            break;

        case TX_DRAIN:
            if (g_sendConfirmations >= DMX_FRAGMENTS_PER_UNIVERSE ||
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
