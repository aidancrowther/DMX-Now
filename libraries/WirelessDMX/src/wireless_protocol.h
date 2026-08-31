/**
 * @file wireless_protocol.h
 * @brief Shared DMX fragment packet format for QuickESPNow broadcast
 *
 * This is the SINGLE canonical definition of the wire protocol. It lives at
 * the project level (shared/) so the transmitter, the receivers, and the
 * Feature 5 test sketches all use the exact same layout instead of each
 * carrying its own (drift-prone) copy.
 *
 * Packet layout (packed, fixed-width types, no alignment padding):
 *   magic            uint16_t  2 bytes
 *   protocolVersion  uint8_t   1 byte
 *   packetType       uint8_t   1 byte
 *   universeId       uint8_t   1 byte
 *   frameSequence    uint32_t  4 bytes
 *   fragmentIndex    uint8_t   1 byte
 *   fragmentCount    uint8_t   1 byte
 *   dataOffset       uint16_t  2 bytes
 *   payloadLength    uint8_t   1 byte
 *   ---------------------------------------------------
 *   header total: 14 bytes  (== DMX_HEADER_SIZE)
 *   payload:      up to 236 bytes (ESP_NOW_MAX_DATA_LEN - 14)
 *   total:        up to 250 bytes (== ESP_NOW_MAX_DATA_LEN)
 *
 * IMPORTANT: The struct MUST stay `packed`. The `uint32_t frameSequence`
 * otherwise forces 4-byte alignment and inserts 3 padding bytes, which shifts
 * `payloadLength` out from under the fixed 14-byte header assumption that both
 * the TX and RX rely on. That misalignment is exactly what caused the Feature 5
 * "size mismatch" failure. The static_assert below guards against it.
 *
 * Serialization is a straight memcpy of the packed header (host endianness),
 * which is safe because the transmitter and the receivers are the same
 * architecture (ESP8266). The channel payload is intentionally NOT a member of
 * this struct: the sender/receiver copy it immediately after the 14-byte
 * header, which keeps the header size unambiguous.
 */

#ifndef WIRELESS_PROTOCOL_H
#define WIRELESS_PROTOCOL_H

#include <Arduino.h>
#include <QuickEspNow.h>

/* --------------------------------------------------------------------------
 * Protocol constants
 * -------------------------------------------------------------------------- */
#define DMX_PACKET_MAGIC       0x444DU   /* "DM" in ASCII, for validation */
#define DMX_PROTO_VERSION      1U        /* Current protocol version */
#define DMX_PACKET_TYPE        1U        /* Packet type: 1 = DMX fragment */
#define DMX_UNIVERSE_ID        1U        /* Single universe for now; extendable later */
#define DMX_UNIVERSE_SIZE      512U      /* 512 DMX channels */

/* --------------------------------------------------------------------------
 * Channel and refresh rate (test defaults; configurable)
 * -------------------------------------------------------------------------- */
#define ESPNOW_CHANNEL         1UL

/* Wireless universe refresh rate. Configurable per build (Feature 7):
 * pass -DWIRELESS_REFRESH_HZ=N to the compiler (e.g. via the flash scripts'
 * --define option) to override the conservative 1 Hz default. Only the
 * transmitter paces off this value; receivers do not depend on it. */
#ifndef WIRELESS_REFRESH_HZ
#define WIRELESS_REFRESH_HZ    1U
#endif
static constexpr unsigned long WIRELESS_REFRESH_INTERVAL_MS = 1000UL / WIRELESS_REFRESH_HZ;

/* --------------------------------------------------------------------------
 * Packet sizes (derived from the QuickESPNow ESP8266 transmit limit)
 * -------------------------------------------------------------------------- */
static constexpr uint8_t DMX_HEADER_SIZE       = 14U;
static constexpr uint8_t DMX_PAYLOAD_SIZE      = ESP_NOW_MAX_DATA_LEN - DMX_HEADER_SIZE; // 236
static constexpr uint8_t DMX_TOTAL_PACKET_SIZE = DMX_HEADER_SIZE + DMX_PAYLOAD_SIZE;     // 250

/* --------------------------------------------------------------------------
 * Fragment counts for a 512-byte universe in 236-byte payloads:
 *   frag 0: offset=0,   len=236 (bytes   0..235)
 *   frag 1: offset=236, len=236 (bytes 236..471)
 *   frag 2: offset=472, len=40  (bytes 472..511)
 * -------------------------------------------------------------------------- */
static constexpr uint8_t DMX_FRAGMENTS_PER_UNIVERSE = 3U;

/* --------------------------------------------------------------------------
 * Fragment header (exactly 14 bytes, packed).
 * -------------------------------------------------------------------------- */
struct __attribute__((packed)) DmxFragmentPacket {
    uint16_t magic;           /* protocol magic */
    uint8_t  protocolVersion; /* protocol version */
    uint8_t  packetType;      /* packet type (1 = DMX fragment) */
    uint8_t  universeId;      /* universe identifier */
    uint32_t frameSequence;   /* one value per complete universe transmission */
    uint8_t  fragmentIndex;   /* 0 .. fragmentCount-1 */
    uint8_t  fragmentCount;   /* total fragments for this universe */
    uint16_t dataOffset;      /* offset into the 512-byte universe */
    uint8_t  payloadLength;   /* bytes of channel payload that follow the header */
};

/* --------------------------------------------------------------------------
 * Compile-time guards against the Feature 5 bug class: the header must be
 * exactly 14 bytes (packed, no padding) and fit inside one ESP-NOW packet.
 * -------------------------------------------------------------------------- */
static_assert(sizeof(DmxFragmentPacket) == DMX_HEADER_SIZE,
              "DmxFragmentPacket must be exactly 14 bytes (packed, no padding)");
static_assert(sizeof(DmxFragmentPacket) <= ESP_NOW_MAX_DATA_LEN,
              "DmxFragmentPacket header must fit within ESP_NOW_MAX_DATA_LEN");

/* --------------------------------------------------------------------------
 * Helper: payload length a fragment at `offset` should carry (last gets remainder)
 * -------------------------------------------------------------------------- */
inline uint8_t dmx_fragment_payload_length(uint16_t offset, uint16_t universeSize) {
    if (offset + DMX_PAYLOAD_SIZE <= universeSize) {
        return DMX_PAYLOAD_SIZE;                       /* full payload fits */
    }
    return static_cast<uint8_t>(universeSize - offset); /* last fragment: remainder */
}

#endif /* WIRELESS_PROTOCOL_H */
