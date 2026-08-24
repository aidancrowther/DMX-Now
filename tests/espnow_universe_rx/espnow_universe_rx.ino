/**
 * Feature 5: Wireless DMX universe receiver test
 *
 * Purpose: Receive and validate individual QuickESPNow broadcast fragments.
 * This sketch does NOT reconstruct or assemble fragments into a complete
 * universe (that is Feature 6). Each fragment is validated independently
 * and diagnostic information is printed to UART0.
 *
 * Receiver behavior:
 *   - Validates each packet: size, magic, version, type, universe ID,
 *     payload length, fragment count/index, offset bounds.
 *   - Performs per-fragment integrity check against the deterministic
 *     transmitter pattern g_universe[i] = (i + seq) & 0xFF.
 *   - Prints fragment diagnostics including sequence, fragment index,
 *     offset, payload length, RSSI, integrity status.
 *   - Maintains only diagnostic counters (no staging/active buffers).
 *   - UART0 used exclusively for debugging (no espDMX).
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* Single canonical protocol definition shared with the transmitter
 * (WirelessDMX in the project's top-level libraries/ folder). */
#include "../../../libraries/WirelessDMX/src/wireless_protocol.h"

/* --------------------------------------------------------------------------
 * RX callback: validate each fragment independently, print diagnostics
 *
 * Validation steps:
 *   1. Check received length is sufficient for header validation
 *   2. Decode the 14-byte packed header
 *   3. Validate magic
 *   4. Validate protocol version
 *   5. Validate packet type
 *   6. Validate declared payload length (1..DMX_PAYLOAD_SIZE)
 *   7. Validate total size == header + declared payload
 *   8. Validate fragment count is non-zero
 *   9. Validate fragment index < fragment count
 *  10. Validate data offset (< 512)
 *  11. Validate offset + payloadLength <= 512
 *  12. Verify payload first/last bytes against the deterministic ramp
 * -------------------------------------------------------------------------- */
void dataReceived(uint8_t* address, uint8_t* data, uint8_t len, signed int rssi, bool broadcast) {
    (void)address;
    (void)broadcast;

    /* Step 1: must be able to read the 14-byte header safely */
    if (len < DMX_HEADER_SIZE) {
        Serial.printf("RX FRAG invalid short packet len=%u\n", len);
        return;
    }

    /* Step 2: decode the packed header (14 bytes) */
    DmxFragmentPacket pkt;
    if (len < sizeof(pkt)) {
        Serial.printf("RX FRAG insufficient for header len=%u\n", len);
        return;
    }
    memcpy(&pkt, data, sizeof(pkt));

    /* Step 3: magic */
    if (pkt.magic != DMX_PACKET_MAGIC) {
        Serial.printf("RX FRAG bad magic=0x%04X expected=0x%04X len=%u\n",
                      pkt.magic, DMX_PACKET_MAGIC, len);
        return;
    }

    /* Step 4: protocol version */
    if (pkt.protocolVersion != DMX_PROTO_VERSION) {
        Serial.printf("RX FRAG bad version=%u expected=%u\n",
                      pkt.protocolVersion, DMX_PROTO_VERSION);
        return;
    }

    /* Step 5: packet type */
    if (pkt.packetType != DMX_PACKET_TYPE) {
        Serial.printf("RX FRAG bad type=%u expected=%u\n",
                      pkt.packetType, DMX_PACKET_TYPE);
        return;
    }

    /* Step 6: declared payload length within range */
    if (pkt.payloadLength < 1 || pkt.payloadLength > DMX_PAYLOAD_SIZE) {
        Serial.printf("RX FRAG bad payloadLength=%u expected 1..%u\n",
                      pkt.payloadLength, DMX_PAYLOAD_SIZE);
        return;
    }

    /* Step 7: total size must equal header + declared payload */
    const uint8_t expectedTotalLen = DMX_HEADER_SIZE + pkt.payloadLength;
    if (len != expectedTotalLen) {
        Serial.printf("RX FRAG size mismatch len=%u declared=%u\n",
                      len, expectedTotalLen);
        return;
    }

    /* Step 8: fragment count non-zero */
    if (pkt.fragmentCount <= 0) {
        Serial.printf("RX FRAG bad fragmentCount=%u expected>0\n", pkt.fragmentCount);
        return;
    }

    /* Step 9: fragment index in range */
    if (pkt.fragmentIndex >= pkt.fragmentCount) {
        Serial.printf("RX FRAG bad fragmentIndex=%u >= fragmentCount=%u\n",
                      pkt.fragmentIndex, pkt.fragmentCount);
        return;
    }

    /* Step 10: data offset within universe */
    if (pkt.dataOffset >= DMX_UNIVERSE_SIZE) {
        Serial.printf("RX FRAG bad dataOffset=%u >= UNIVERSE_SIZE\n", pkt.dataOffset);
        return;
    }

    /* Step 11: fragment end within universe */
    const uint16_t fragmentEnd = static_cast<uint16_t>(pkt.dataOffset) + pkt.payloadLength;
    if (fragmentEnd > DMX_UNIVERSE_SIZE) {
        Serial.printf("RX FRAG offset+payload overflow %u+%u=%u > 512\n",
                      pkt.dataOffset, pkt.payloadLength, fragmentEnd);
        return;
    }

    /* -----------------------------------------------------------------------
     * Step 12: payload integrity against the deterministic transmitter ramp.
     *
     * Transmitter: g_universe[i] = (i + seq) & 0xFF.
     * A fragment covers universe indices [dataOffset, dataOffset+payloadLength),
     * so:
     *   first byte (universe index dataOffset)           -> (dataOffset + seq) & 0xFF
     *   last  byte (universe index dataOffset+len-1)     -> (dataOffset+len-1+seq) & 0xFF
     * ----------------------------------------------------------------------- */
    const uint32_t seq = pkt.frameSequence;
    const uint8_t expectedFirst = static_cast<uint8_t>((static_cast<uint32_t>(pkt.dataOffset) + seq) & 0xFF);
    const uint8_t expectedLast  = static_cast<uint8_t>((static_cast<uint32_t>(pkt.dataOffset) + pkt.payloadLength - 1 + seq) & 0xFF);

    const uint8_t actualFirst = data[DMX_HEADER_SIZE];
    const uint8_t actualLast  = data[DMX_HEADER_SIZE + pkt.payloadLength - 1];

    bool integrityPass = true;

    if (actualFirst != expectedFirst) {
        Serial.printf("RX FRAG seq=%u frag=%d/%d offset=%u len=%u rssi=%d integrity=FAIL\n",
                      seq, pkt.fragmentIndex + 1, pkt.fragmentCount,
                      pkt.dataOffset, pkt.payloadLength, rssi);
        Serial.printf("RX FRAG data[first]=0x%02X expected=0x%02X\n", actualFirst, expectedFirst);
        integrityPass = false;
    }
    if (actualLast != expectedLast) {
        Serial.printf("RX FRAG seq=%u frag=%d/%d offset=%u len=%u rssi=%d integrity=FAIL\n",
                      seq, pkt.fragmentIndex + 1, pkt.fragmentCount,
                      pkt.dataOffset, pkt.payloadLength, rssi);
        Serial.printf("RX FRAG data[last]=0x%02X expected=0x%02X\n", actualLast, expectedLast);
        integrityPass = false;
    }

    /* Print fragment validation result */
    if (integrityPass) {
        Serial.printf("RX FRAG seq=%u frag=%d/%d offset=%u len=%u rssi=%d integrity=PASS\n",
                      seq, pkt.fragmentIndex + 1, pkt.fragmentCount,
                      pkt.dataOffset, pkt.payloadLength, rssi);
        Serial.printf("RX FRAG data[first]=0x%02X data[last]=0x%02X\n", actualFirst, actualLast);
    }

    /* Diagnostic counters */
    static unsigned long packetsReceived = 0;
    static unsigned long validFragments = 0;
    static unsigned long integrityFailures = 0;

    packetsReceived++;
    if (integrityPass) {
        validFragments++;
    } else {
        integrityFailures++;
    }
}

/* --------------------------------------------------------------------------
 * Setup: initialize QuickESPNow, register callback, print diagnostics
 * -------------------------------------------------------------------------- */
void setup(void) {
    Serial.begin(115200);
    Serial.println();
    Serial.print("Feature 5 RX ready");
    Serial.print(", channel=");
    Serial.println(ESPNOW_CHANNEL);

    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);

    if (!quickEspNow.begin(ESPNOW_CHANNEL)) {
        Serial.println("Failed to initialize QuickESPNow");
        while (true) delay(10);
    }

    quickEspNow.onDataRcvd(dataReceived);

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
    Serial.printf("RX ready seq=any\n");
    Serial.printf("Fragment validation: size/magic/version/type/universeId/payloadLength/fragCount/index/offset/bounds\n");
    Serial.printf("Integrity check: per-fragment first/last payload byte vs ramp (i + seq) & 0xFF\n");
    Serial.printf("No universe reconstruction (Feature 6 not implemented)\n");

    Serial.println();
    Serial.printf("header=%d payload=%d total=%d frags=%d\n",
                  static_cast<int>(DMX_HEADER_SIZE),
                  static_cast<int>(DMX_PAYLOAD_SIZE),
                  static_cast<int>(DMX_TOTAL_PACKET_SIZE),
                  static_cast<int>(DMX_FRAGMENTS_PER_UNIVERSE));
}

/* --------------------------------------------------------------------------
 * Main loop: no explicit work; the QuickESPNow receive task invokes
 * dataReceived() when packets arrive.
 * -------------------------------------------------------------------------- */
void loop(void) {
}
