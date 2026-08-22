/**
 * Feature 4: Basic QuickESPNow broadcast transmitter test
 *
 * Purpose: Prove that an ESP8266 can repeatedly broadcast a small, validated
 * test packet using the local QuickESPNow library on the same channel as the
 * receiver test sketch. This sketch does NOT use espDMX or any DMX hardware.
 *
 * Test packet (12 bytes):
 *   struct { uint32_t magic; uint32_t sequence; uint32_t value; };
 *
 * Transmits approximately once per second (TEST_BROADCAST_INTERVAL_MS = 1000).
 *
 * UART0 is used exclusively for debugging since espDMX is NOT active.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* --------------------------------------------------------------------------
 * Constants shared with receiver sketch (must match exactly)
 * -------------------------------------------------------------------------- */
#define ESPNOW_CHANNEL 1            /* Fixed test channel (0-14, or 255=follow WiFi) */
#define TEST_BROADCAST_INTERVAL_MS 1000UL
#define TEST_PACKET_MAGIC        0x454E504EUL   /* "ENPN" in ASCII, for validation */

/* --------------------------------------------------------------------------
 * Transmitter packet structure (fixed-size, trivially copyable, no dynamic alloc)
 * -------------------------------------------------------------------------- */
struct TestPacket {
    uint32_t magic;     /* Protocol/magic value */
    uint32_t sequence;  /* Incrementing sequence number */
    uint32_t value;     /* Echoes sequence (for this test) */
};

/* --------------------------------------------------------------------------
 * Serial output for UART0 debugging (no espDMX, normal TX behavior)
 * -------------------------------------------------------------------------- */
void setup(void) {
    Serial.begin(115200);
    Serial.println();
    Serial.print("QuickESPNow TX starting");
    Serial.print(", channel=");
    Serial.println(ESPNOW_CHANNEL);

    // Configure Wi-Fi as STA only (no AP, no station association needed for this test)
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);  /* Stay on current channel rather than scanning */

    /* ----------------------------------------------------------------------
     * Initialize QuickESPNow:
     *   begin(channel) sets the fixed channel via wifi_set_channel() and
     *   arms the internal TX/RX timer tasks (10 ms period).
     *   No local instance needed; global "quickEspNow" is used.
     * ---------------------------------------------------------------------- */
    if (!quickEspNow.begin(ESPNOW_CHANNEL)) {
        Serial.println("Failed to initialize QuickESPNow");
        while (true) delay(10);
    }

    // Register send-status callback (minimal, just status; seq printed in loop)
    quickEspNow.onDataSent([](uint8_t* dstMac, uint8_t status) {
        if (status == 0) {
            Serial.println("SEND status=OK");
        } else {
            Serial.println("SEND status=FAIL");
        }
    });

    // Print own MAC for debugging (WiFi.macAddress expects uint8_t*)
    uint8_t macBuffer[6];
    WiFi.macAddress(macBuffer);
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
             macBuffer[0], macBuffer[1], macBuffer[2],
             macBuffer[3], macBuffer[4], macBuffer[5]);
    Serial.print("Own MAC: ");
    Serial.println(macStr);
    Serial.println();

    // Wait briefly for QuickESPNow tasks to arm (good practice)
    delay(500);
}

void loop(void) {
    static unsigned long lastSendTime = 0;
    static uint32_t sequence = 1;

    const unsigned long now = millis();

    // Non-blocking interval-based transmission (~1 packet/sec)
    if (now - lastSendTime >= TEST_BROADCAST_INTERVAL_MS) {
        lastSendTime = now;

        /* ------------------------------------------------------------------
         * Build the test packet (fixed 12 bytes, no String/pointers)
         * ------------------------------------------------------------------ */
        TestPacket pkt;
        pkt.magic = TEST_PACKET_MAGIC;
        pkt.sequence = sequence++;
        pkt.value = pkt.sequence;  /* For this test: value == sequence */

        uint8_t payload[12];
        memcpy(payload, &pkt, sizeof(pkt));

        // Print TX event to UART0
        uint8_t macBufferTx[6];
        WiFi.macAddress(macBufferTx);
        char macStrTx[18];
        snprintf(macStrTx, sizeof(macStrTx), "%02X:%02X:%02X:%02X:%02X:%02X",
                 macBufferTx[0], macBufferTx[1], macBufferTx[2],
                 macBufferTx[3], macBufferTx[4], macBufferTx[5]);
        Serial.printf("TX sequence=%u value=%u\n", pkt.sequence, pkt.value);

        /* ------------------------------------------------------------------
         * Broadcast using QuickESPNow's sendBcast API.
         * Returns COMMS_SEND_OK (0) on success, non-zero on error.
         * For asynchronous sends (synchronousSend=false), it returns immediately.
         * The callback onDataSent will report the result.
         * ------------------------------------------------------------------ */
        quickEspNow.sendBcast(payload, sizeof(pkt));

    }
}
