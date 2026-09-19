/**
 * Feature 4: Basic QuickESPNow broadcast receiver test
 *
 * Purpose: Prove that an ESP8266 can reliably receive and decode small,
 * validated broadcast packets from the transmitter test sketch. This sketch
 * does NOT use espDMX or any DMX hardware.
 *
 * Validates each packet by checking:
 *   1) received length matches sizeof(TestPacket) = 12 bytes
 *   2) magic value equals TEST_PACKET_MAGIC (0x454E504EUL)
 *
 * Prints sender MAC, sequence, value, RSSI, broadcast flag, and payload length.
 *
 * UART0 is used exclusively for debugging since espDMX is NOT active.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* --------------------------------------------------------------------------
 * Constants shared with transmitter sketch (must match exactly)
 * -------------------------------------------------------------------------- */
#define ESPNOW_CHANNEL 1            /* Fixed test channel (0-14, or 255=follow WiFi) */
#define TEST_PACKET_MAGIC        0x454E504EUL   /* "ENPN" in ASCII, for validation */

/* --------------------------------------------------------------------------
 * Receiver packet structure (must match transmitter exactly)
 * Fixed-size, trivially copyable, no dynamic allocation.
 * -------------------------------------------------------------------------- */
struct TestPacket {
    uint32_t magic;     /* Protocol/magic value */
    uint32_t sequence;  /* Incrementing sequence number */
    uint32_t value;     /* Echoes sequence (for this test) */
};

/* --------------------------------------------------------------------------
 * RX callback registered on the global quickEspNow instance.
 * The library arms a receive task in begin() that invokes this periodically.
 * We MUST validate length and magic before decoding. Use memcpy() into a
 * local struct to avoid retaining pointers after the callback returns.
 * -------------------------------------------------------------------------- */
void dataReceived(uint8_t* address, uint8_t* data, uint8_t len, signed int rssi, bool broadcast) {
    /* Check payload length matches our fixed-size packet */
    if (len != sizeof(TestPacket)) {
        Serial.printf("RX invalid len=%u\n", len);
        return;
    }

    /* Decode into a local struct (safe copy, no pointer retention) */
    TestPacket pkt;
    memcpy(&pkt, data, sizeof(pkt));

    /* Validate magic to reject unrelated/malformed packets */
    if (pkt.magic != TEST_PACKET_MAGIC) {
        Serial.printf("RX bad magic=0x%08X len=%u\n", pkt.magic, len);
        return;
    }

    /* Packet validated — print diagnostic info */
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
             address[0], address[1], address[2],
             address[3], address[4], address[5]);

    Serial.printf("RX from=%s seq=%u value=%u len=%u rssi=%d broadcast=%s\n",
                  macStr, pkt.sequence, pkt.value, (unsigned)len,
                  rssi, broadcast ? "yes" : "no");
}

/* --------------------------------------------------------------------------
 * Serial output for UART0 debugging (no espDMX, normal TX behavior)
 * -------------------------------------------------------------------------- */
void setup(void) {
    Serial.begin(115200);
    Serial.println();
    Serial.print("QuickESPNow RX ready");
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

    // Register receive callback on the global instance
    quickEspNow.onDataRcvd(dataReceived);

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
    /* Receiver runs indefinitely, waiting for broadcasts.
     * No explicit work needed in loop() — QuickESPNow's receive task
     * invokes the callback when packets arrive.
     */
}
