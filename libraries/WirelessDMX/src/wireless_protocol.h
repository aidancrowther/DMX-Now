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
#define TELEMETRY_PACKET_TYPE  2U        /* Packet type: 2 = receiver telemetry */
#define DMX_PRIORITY_PACKET_TYPE 3U      /* Packet type: 3 = priority DMX fragment */
#define PRIORITY_COMPLETION_PACKET_TYPE 4U /* Packet type: 4 = priority completion */
#define PRIORITY_LIVENESS_REQUEST_PACKET_TYPE 5U
#define PRIORITY_LIVENESS_RESPONSE_PACKET_TYPE 6U
#define PRIORITY_GATE_METADATA_PACKET_TYPE 7U
#define PRIORITY_COMPLETE_ACCEPTED 1U
#define PRIORITY_COMPLETE_DUPLICATE 2U
#define PRIORITY_COMPLETE_INVALID 3U
#define PRIORITY_COMPLETE_NOT_PROMOTED 4U
#define DMX_UNIVERSE_ID        1U        /* Single universe for now; extendable later */
#define DMX_UNIVERSE_SIZE      512U      /* 512 DMX channels */

/* Host-facing management protocol. These frames share the transmitter UART
 * with ENTTEC, but use a distinct sync pair and a CRC so a bridge daemon can
 * safely separate management traffic from lighting traffic. */
#define MANAGEMENT_SYNC_1      0xA5U
#define MANAGEMENT_SYNC_2      0x5AU
#define MANAGEMENT_PROTO_VERSION 1U
#define MANAGEMENT_GET_RECEIVER_TELEMETRY 0x01U
#define MANAGEMENT_MARK_NEXT_PRIORITY    0x02U
#define MANAGEMENT_GET_PRIORITY_ACKS     0x03U
#define MANAGEMENT_CLEAR_RECEIVER_CACHE  0x04U
#define MANAGEMENT_RECEIVER_TELEMETRY      0x81U
#define MANAGEMENT_PRIORITY_ACKS           0x83U
#define MANAGEMENT_CACHE_CLEARED           0x84U
#define MANAGEMENT_ERROR                   0xE0U

/* --------------------------------------------------------------------------
 * Channel and refresh rate (test defaults; configurable)
 * -------------------------------------------------------------------------- */
#define ESPNOW_CHANNEL         1UL

/* Wireless universe refresh rate. Configurable per build (Feature 7):
 * pass -DWIRELESS_REFRESH_HZ=N to the compiler (e.g. via the flash scripts'
 * --define option) to override the validated 20 Hz production default. Only the
 * transmitter paces off this value; receivers do not depend on it. */
#ifndef WIRELESS_REFRESH_HZ
#define WIRELESS_REFRESH_HZ    20U
#endif
static constexpr unsigned long WIRELESS_REFRESH_INTERVAL_MS = 1000UL / WIRELESS_REFRESH_HZ;
#ifndef WIRELESS_PRIORITY_REFRESH_HZ
#define WIRELESS_PRIORITY_REFRESH_HZ 1U
#endif
static constexpr unsigned long WIRELESS_PRIORITY_REFRESH_INTERVAL_MS =
    1000UL / WIRELESS_PRIORITY_REFRESH_HZ;

/* --------------------------------------------------------------------------
 * Packet sizes (derived from the QuickESPNow ESP8266 transmit limit)
 * -------------------------------------------------------------------------- */
static constexpr uint8_t DMX_HEADER_SIZE       = 14U;
static constexpr uint8_t DMX_PAYLOAD_SIZE      = ESP_NOW_MAX_DATA_LEN - DMX_HEADER_SIZE; // 236
static constexpr uint8_t DMX_TOTAL_PACKET_SIZE = DMX_HEADER_SIZE + DMX_PAYLOAD_SIZE;     // 250
static constexpr uint8_t PRIORITY_HEADER_SIZE  = 24U;
static constexpr uint8_t PRIORITY_PAYLOAD_SIZE =
    ESP_NOW_MAX_DATA_LEN - PRIORITY_HEADER_SIZE; // 226 with the targeted header
static constexpr uint16_t DMX_GATE_MASK_SIZE = DMX_UNIVERSE_SIZE / 8U;

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

struct __attribute__((packed)) DmxPriorityFragmentPacket {
    uint16_t magic;
    uint8_t  protocolVersion;
    uint8_t  packetType;
    uint8_t  universeId;
    uint32_t targetReceiverId;
    uint32_t frameSequence;
    uint32_t priorityId;
    uint8_t  attempt;
    uint8_t  repeatCount;
    uint8_t  fragmentIndex;
    uint8_t  fragmentCount;
    uint16_t dataOffset;
    uint8_t  payloadLength;
};

struct __attribute__((packed)) PriorityGateMetadataPacket {
    uint16_t magic;
    uint8_t  protocolVersion;
    uint8_t  packetType;
    uint8_t  universeId;
    uint32_t targetReceiverId;
    uint32_t priorityId;
    uint8_t  attempt;
    uint8_t  hardGateMask[DMX_GATE_MASK_SIZE];
};

struct __attribute__((packed)) PriorityCompletionPacket {
    uint16_t magic;
    uint8_t  protocolVersion;
    uint8_t  packetType;
    uint8_t  universeId;
    uint32_t receiverId;
    uint32_t priorityId;
    uint32_t frameSequence;
    uint8_t  attempt;
    uint8_t  completionStatus;
    uint8_t  attemptsObserved;
    int8_t   lastRssi;
};

struct __attribute__((packed)) PriorityLivenessPacket {
    uint16_t magic;
    uint8_t  protocolVersion;
    uint8_t  packetType;
    uint32_t receiverId;
    uint32_t priorityId;
    uint8_t  attempt;
};

/* Receiver telemetry is deliberately separate from the DMX fragment format.
 * It is broadcast at a low rate so a future transmitter can collect status
 * from multiple receivers without requiring per-receiver pairing first. */
struct __attribute__((packed)) ReceiverTelemetryPacket {
    uint16_t magic;
    uint8_t  protocolVersion;
    uint8_t  packetType;
    uint8_t  universeId;
    uint32_t receiverId;             /* ESP8266 chip ID */
    uint8_t  macAddress[6];
    uint32_t uptimeSeconds;
    uint8_t  batteryLow;
    uint32_t lastActiveSequence;
    uint32_t completeUniverses;
    uint32_t incompleteUniverses;
    uint32_t malformedPackets;
    uint32_t timeSinceLastUniverseMs;
    int8_t   lastRssi;
    uint16_t firmwareVersion;
    uint32_t telemetrySequence;
};

struct __attribute__((packed)) PriorityTransmitRequest {
    uint32_t priorityId;
    uint32_t targetReceiverId; /* zero means legacy broadcast */
    uint8_t  repeatCount;
    uint8_t  attempt;
    uint8_t  gateMetadataPresent;
    uint8_t  hardGateMask[DMX_GATE_MASK_SIZE];
};

struct __attribute__((packed)) PriorityAckReportHeader {
    uint8_t  reportVersion;
    uint8_t  recordCount;
    uint32_t reportSequence;
    uint32_t acceptedCount;
    uint32_t duplicateCount;
    uint32_t invalidCount;
    uint32_t droppedCount;
};

struct __attribute__((packed)) PriorityAckReportRecord {
    uint32_t priorityId;
    uint32_t receiverId;
    uint32_t frameSequence;
    uint8_t  attempt;
    uint8_t  completionStatus;
    uint8_t  attemptsObserved;
    int8_t   lastRssi;
    uint32_t receivedAtMs;
    uint16_t ackDelayMs;
};

/* One multipart host response part. The payload consists of zero or more
 * TelemetryReportRecord values. */
struct __attribute__((packed)) TelemetryReportPartHeader {
    uint8_t  reportVersion;
    uint8_t  partIndex;
    uint8_t  partCount;
    uint8_t  recordCount;
    uint32_t reportSequence;
};

/* Fixed-size record deliberately duplicates the wireless telemetry fields and
 * adds transmitter-side link age/RSSI and a derived link state. */
struct __attribute__((packed)) TelemetryReportRecord {
    uint32_t receiverId;
    uint8_t  macAddress[6];
    uint8_t  linkState;                 /* 1 online, 2 stale, 3 offline */
    uint8_t  batteryLow;
    int8_t   transmitterRssi;
    int8_t   receiverLastRssi;
    uint32_t uptimeSeconds;
    uint32_t lastActiveSequence;
    uint32_t completeUniverses;
    uint32_t incompleteUniverses;
    uint32_t malformedPackets;
    uint32_t timeSinceLastUniverseMs;
    uint32_t transmitterLastSeenMs;
    uint16_t firmwareVersion;
    uint8_t  protocolVersion;
    uint8_t  reserved;
    uint32_t telemetrySequence;
};

/* --------------------------------------------------------------------------
 * Compile-time guards against the Feature 5 bug class: the header must be
 * exactly 14 bytes (packed, no padding) and fit inside one ESP-NOW packet.
 * -------------------------------------------------------------------------- */
static_assert(sizeof(DmxFragmentPacket) == DMX_HEADER_SIZE,
              "DmxFragmentPacket must be exactly 14 bytes (packed, no padding)");
static_assert(sizeof(DmxFragmentPacket) <= ESP_NOW_MAX_DATA_LEN,
              "DmxFragmentPacket header must fit within ESP_NOW_MAX_DATA_LEN");
static_assert(sizeof(DmxPriorityFragmentPacket) == PRIORITY_HEADER_SIZE,
              "DmxPriorityFragmentPacket layout changed unexpectedly");
static_assert(sizeof(DmxPriorityFragmentPacket) + PRIORITY_PAYLOAD_SIZE <= ESP_NOW_MAX_DATA_LEN,
              "DmxPriorityFragmentPacket must fit within ESP_NOW_MAX_DATA_LEN");
static_assert(sizeof(PriorityGateMetadataPacket) <= ESP_NOW_MAX_DATA_LEN,
              "PriorityGateMetadataPacket must fit within ESP_NOW_MAX_DATA_LEN");
static_assert(sizeof(PriorityCompletionPacket) <= ESP_NOW_MAX_DATA_LEN,
              "PriorityCompletionPacket must fit within ESP_NOW_MAX_DATA_LEN");
static_assert(sizeof(PriorityLivenessPacket) <= ESP_NOW_MAX_DATA_LEN,
              "PriorityLivenessPacket must fit within ESP_NOW_MAX_DATA_LEN");
static_assert(sizeof(ReceiverTelemetryPacket) <= ESP_NOW_MAX_DATA_LEN,
              "ReceiverTelemetryPacket must fit within ESP_NOW_MAX_DATA_LEN");
static_assert(sizeof(TelemetryReportPartHeader) == 8,
              "TelemetryReportPartHeader layout changed unexpectedly");
static_assert(sizeof(TelemetryReportRecord) == 50,
              "TelemetryReportRecord layout changed unexpectedly");
static_assert(sizeof(PriorityAckReportHeader) == 22,
              "PriorityAckReportHeader layout changed unexpectedly");
static_assert(sizeof(PriorityAckReportRecord) == 22,
              "PriorityAckReportRecord layout changed unexpectedly");

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
