/**
 * Integrated Wireless DMX transmitter: ENTTEC DMX USB Pro serial input,
 * wireless universe broadcast, and receiver telemetry reporting.
 *
 * Each universe is split into DMX_FRAGMENTS_PER_UNIVERSE (3) fragments.
 * A frame is fully "sent" once all 3 fragments have been transmitted and the
 * QuickESPNow TX queue has drained (confirmed via the onDataSent callback).
 * The frame sequence increments after each complete frame so the receiver can
 * observe monotonically sequenced completed input snapshots.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <QuickEspNow.h>

/* Single canonical protocol definition shared with the receiver
 * (WirelessDMX library, pinned by the build via --library). */
#include <wireless_protocol.h>

/* The UART is the PC-facing ENTTEC protocol port. Do not enable text logging
 * on this port: it would corrupt the binary protocol stream. */
#ifdef TRANSMITTER_VERBOSE_LOGGING
#define TX_LOG(...) Serial.printf(__VA_ARGS__)
#else
#define TX_LOG(...) do { } while (0)
#endif

/* The ENTTEC input and telemetry output share UART0. Keep telemetry logging
 * disabled by default because text would corrupt the binary input stream.
 * Packet reception/validation continues regardless. */
#ifndef TRANSMITTER_TELEMETRY_LOGGING
#define TRANSMITTER_TELEMETRY_LOGGING 0
#endif

/* --------------------------------------------------------------------------
 * TEST HOOK CONFIG (Feature 6) — ALL DEFAULT OFF.
 * To run a fault-injection test, uncomment (or add) exactly ONE mode below,
 * then build/flash with the existing script (./flash_espnow_tx.sh, add -f to
 * flash). With this block EMPTY the transmitter sends real ENTTEC input (slots
 * {0,1,2}, no corruption, sequence starts at 0).
 *
 *   #define TEST_DROP_FRAGMENT_INDEX      1   // omit fragment 1 (middle) each frame
 *   #define TEST_DUPLICATE_FRAGMENT_INDEX 1   // send fragment 1 twice each frame
 *   #define TEST_REORDER_FRAGMENTS                 // transmit order 2,0,1
 *   #define TEST_CORRUPT_FRAGMENT_INDEX   1   // corrupt one payload byte of fragment 1
 *   #define TEST_CORRUPT_BYTE             0   // (optional) which payload byte (0-based)
 *   #define TEST_FORCE_SEQUENCE_START     42  // start the frame sequence at 42
 *   #define TEST_SEQUENCE_WRAP                     // start at 0xFFFFFFFE (rollover)
 *   #define TEST_DELAYED_FRAGMENT                    // transmit one fragment ~2.5 s late (stale test)
 *
 * After testing, remove the #define (restore this block to empty) and
 * re-run ./flash_espnow_tx.sh. Do NOT leave a fault mode enabled.
 * -------------------------------------------------------------------------- */

/* Latest complete universe received from the PC. */
static uint8_t g_universe[DMX_UNIVERSE_SIZE];

/* Snapshot used by one wireless frame. The parser may commit a newer PC frame
 * while this frame's fragments are still being queued; keeping a snapshot
 * prevents a wireless frame from containing bytes from two universes. */
static uint8_t g_txUniverse[DMX_UNIVERSE_SIZE];
/* Immutable payload for all physical repeats of one logical priority event. */
static uint8_t g_priorityUniverse[DMX_UNIVERSE_SIZE];

/* Sequence number for the current frame (incremented after a full frame). */
static uint32_t g_frameSequence = 0;

/* Fragment-send confirmations received for the in-flight frame (0..fragCount). */
static volatile uint8_t g_sendConfirmations = 0;

static const uint8_t TELEMETRY_RING_SIZE = 4;
struct TelemetrySlot {
    uint8_t payload[ESPNOW_MAX_MESSAGE_LENGTH];
    uint8_t len;
    int8_t rssi;
};
static TelemetrySlot telemetryRing[TELEMETRY_RING_SIZE];
static volatile uint8_t telemetryHead = 0;
static volatile uint8_t telemetryTail = 0;
static unsigned long telemetryPacketsDropped = 0;
static unsigned long priorityCompletionsReceived = 0;
static unsigned long priorityCompletionDuplicates = 0;
static unsigned long priorityCompletionInvalid = 0;
static unsigned long priorityCompletionDropped = 0;

#define PRIORITY_ACK_RING_SIZE 32U
struct PriorityAckSlot {
    PriorityCompletionPacket packet;
    uint32_t receivedAtMs;
    uint16_t ackDelayMs;
};
static PriorityAckSlot priorityAckRing[PRIORITY_ACK_RING_SIZE];
static uint8_t priorityAckHead = 0;
static uint8_t priorityAckTail = 0;
static uint32_t priorityAckReportSequence = 0;
static bool priorityAckReportPending = false;
static uint32_t lastPriorityTransmitId = 0;
static uint8_t lastPriorityTransmitAttempt = 0;
static unsigned long lastPriorityTransmitFinishedMs = 0;

/* Feature 11: bounded cache retained for the host management interface. */
#ifndef MAX_TELEMETRY_RECEIVERS
#define MAX_TELEMETRY_RECEIVERS 32U
#endif
#ifndef RECEIVER_STALE_TIMEOUT_MS
#define RECEIVER_STALE_TIMEOUT_MS 15000UL
#endif
#ifndef RECEIVER_OFFLINE_TIMEOUT_MS
#define RECEIVER_OFFLINE_TIMEOUT_MS 30000UL
#endif
#ifndef MANAGEMENT_MIN_REPORT_INTERVAL_MS
#define MANAGEMENT_MIN_REPORT_INTERVAL_MS 1000UL
#endif
#define TELEMETRY_REPORT_RECORDS_PER_PART 4U

struct ReceiverTelemetryEntry {
    bool valid;
    uint8_t macAddress[6];
    ReceiverTelemetryPacket telemetry;
    int8_t transmitterRssi;
    unsigned long lastSeenMs;
};
static ReceiverTelemetryEntry receiverTable[MAX_TELEMETRY_RECEIVERS];
static uint32_t telemetryReportSequence = 0;

enum ManagementParserState {
    MGMT_WAIT_SYNC_1,
    MGMT_WAIT_SYNC_2,
    MGMT_READ_VERSION,
    MGMT_READ_OPCODE,
    MGMT_READ_LENGTH_LOW,
    MGMT_READ_LENGTH_HIGH,
    MGMT_READ_PAYLOAD,
    MGMT_READ_CRC_LOW,
    MGMT_READ_CRC_HIGH
};
static ManagementParserState managementState = MGMT_WAIT_SYNC_1;
static uint8_t managementVersion = 0;
static uint8_t managementOpcode = 0;
static uint16_t managementLength = 0;
static uint16_t managementIndex = 0;
static uint16_t managementReceivedCrc = 0;
static uint8_t managementPayload[sizeof(PriorityTransmitRequest)];
static bool priorityNextUniverse = false;
static uint32_t priorityIdForNextUniverse = 0;
static uint32_t priorityTargetReceiverIdForNextUniverse = 0;
static uint8_t priorityRepeatCountForNextUniverse = 1;
static uint8_t priorityAttemptForNextUniverse = 1;
static bool priorityGateMetadataForNextUniverse = false;
static uint8_t priorityHardGateMaskForNextUniverse[DMX_GATE_MASK_SIZE];
static bool priorityMetadataPending = false;
static uint32_t prioritySequenceForCurrentFrame = 0;
static uint8_t priorityRepeatsRemaining = 0;
static bool currentFrameIsPriority = false;
static uint8_t priorityAttempt = 1;

static bool telemetryReportPending = false;
static uint8_t telemetryReportPart = 0;
static uint8_t telemetryReportPartCount = 0;
static uint8_t telemetryReportRecordIndex = 0;
static uint8_t telemetryReportRecordCount = 0;
static uint32_t telemetryReportActiveSequence = 0;
static unsigned long telemetryReportLastStartMs = 0;

static void clearReceiverCache(void) {
    memset(receiverTable, 0, sizeof(receiverTable));
    telemetryHead = 0;
    telemetryTail = 0;
    /* A daemon restart must not receive ACK records belonging to a previous
     * priority-ID namespace. Clear the exported ACK ring together with the
     * receiver telemetry cache so a fresh seeded run cannot see stale IDs. */
    priorityAckHead = 0;
    priorityAckTail = 0;
    priorityAckReportPending = false;
    priorityNextUniverse = false;
    priorityIdForNextUniverse = 0;
    priorityTargetReceiverIdForNextUniverse = 0;
    priorityRepeatCountForNextUniverse = 1;
    priorityAttemptForNextUniverse = 1;
    priorityGateMetadataForNextUniverse = false;
    memset(priorityHardGateMaskForNextUniverse, 0, sizeof(priorityHardGateMaskForNextUniverse));
    priorityMetadataPending = false;
    prioritySequenceForCurrentFrame = 0;
    priorityRepeatsRemaining = 0;
    memset(g_priorityUniverse, 0, sizeof(g_priorityUniverse));
    currentFrameIsPriority = false;
    priorityAttempt = 1;
    g_sendConfirmations = 0;
    telemetryReportPending = false;
    telemetryReportRecordIndex = 0;
    telemetryReportRecordCount = 0;
}

static uint16_t managementCrc16(const uint8_t* data, uint16_t length) {
    uint16_t crc = 0xFFFFU;
    for (uint16_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t bit = 0; bit < 8; bit++)
            crc = (crc & 0x8000U) ? (uint16_t)((crc << 1) ^ 0x1021U)
                                   : (uint16_t)(crc << 1);
    }
    return crc;
}

static bool sequenceIsNewer(uint32_t a, uint32_t b) {
    return (int32_t)(a - b) > 0;
}

static int findReceiverEntry(const ReceiverTelemetryPacket& packet) {
    for (uint8_t i = 0; i < MAX_TELEMETRY_RECEIVERS; i++) {
        if (receiverTable[i].valid &&
            receiverTable[i].telemetry.receiverId == packet.receiverId)
            return i;
    }
    return -1;
}

static uint8_t receiverLinkState(const ReceiverTelemetryEntry& entry,
                                 unsigned long now) {
    const unsigned long age = now - entry.lastSeenMs;
    if (age <= RECEIVER_STALE_TIMEOUT_MS) return 1U;
    if (age <= RECEIVER_OFFLINE_TIMEOUT_MS) return 2U;
    return 3U;
}

static void cacheTelemetry(const ReceiverTelemetryPacket& packet, int8_t rssi) {
    int index = findReceiverEntry(packet);
    if (index < 0) {
        unsigned long oldestAge = 0;
        uint8_t oldest = 0;
        for (uint8_t i = 0; i < MAX_TELEMETRY_RECEIVERS; i++) {
            if (!receiverTable[i].valid) { index = i; break; }
            const unsigned long age = millis() - receiverTable[i].lastSeenMs;
            if (age >= oldestAge) { oldestAge = age; oldest = i; }
        }
        if (index < 0) index = oldest;
    } else if (receiverTable[index].valid &&
               !sequenceIsNewer(packet.telemetrySequence,
                                receiverTable[index].telemetry.telemetrySequence) &&
               packet.uptimeSeconds >= receiverTable[index].telemetry.uptimeSeconds) {
        return;
    }

    receiverTable[index].valid = true;
    memcpy(receiverTable[index].macAddress, packet.macAddress, 6);
    receiverTable[index].telemetry = packet;
    receiverTable[index].transmitterRssi = rssi;
    receiverTable[index].lastSeenMs = millis();
}

/* --------------------------------------------------------------------------
 * ENTTEC DMX USB Pro input (Feature 8)
 *
 * Packet format: 0x7E, label, length LSB, length MSB, payload, 0xE7.
 * SEND_DMX_PACKET (0x06) payload is start code followed by 1..512 channels.
 * The parser is deliberately byte-wise and non-blocking; Serial input can
 * arrive in arbitrarily sized chunks and never delays the RF state machine.
 * -------------------------------------------------------------------------- */
static const uint8_t ENTTEC_START = 0x7E;
static const uint8_t ENTTEC_END = 0xE7;
static const uint8_t ENTTEC_SEND_DMX_PACKET = 0x06;
static const uint16_t ENTTEC_MAX_PAYLOAD = DMX_UNIVERSE_SIZE + 1U;
static uint8_t enttecPayload[ENTTEC_MAX_PAYLOAD];
static uint16_t enttecLength = 0;
static uint16_t enttecPayloadIndex = 0;
static uint32_t enttecDiscardRemaining = 0;
static uint8_t enttecLabel = 0;
static unsigned long enttecValidFrames = 0;
static unsigned long enttecMalformedFrames = 0;

enum EnttecParserState {
    ENTTEC_WAIT_START,
    ENTTEC_READ_LABEL,
    ENTTEC_READ_LENGTH_LOW,
    ENTTEC_READ_LENGTH_HIGH,
    ENTTEC_READ_PAYLOAD,
    ENTTEC_READ_TERMINATOR,
    ENTTEC_DISCARD_PAYLOAD,
    ENTTEC_DISCARD_TERMINATOR
};
static EnttecParserState enttecState = ENTTEC_WAIT_START;

static void resetEnttecParser(void) {
    enttecState = ENTTEC_WAIT_START;
    enttecLength = 0;
    enttecPayloadIndex = 0;
    enttecDiscardRemaining = 0;
}

static void startEnttecPacket(void) {
    enttecState = ENTTEC_READ_LABEL;
    enttecLength = 0;
    enttecPayloadIndex = 0;
    enttecDiscardRemaining = 0;
}

static void commitEnttecUniverse(void) {
    /* ENTTEC includes the DMX start code in the payload; this project carries
     * channel slots only, so reject non-zero start codes and strip byte 0. */
    if (enttecLabel != ENTTEC_SEND_DMX_PACKET ||
        enttecLength < 2 || enttecLength > ENTTEC_MAX_PAYLOAD ||
        enttecPayload[0] != 0x00) {
        if (enttecMalformedFrames < 0xFFFFFFFFUL) enttecMalformedFrames++;
        return;
    }

    memset(g_universe, 0, sizeof(g_universe));
    memcpy(g_universe, enttecPayload + 1, enttecLength - 1);
    if (priorityNextUniverse) {
        memcpy(g_priorityUniverse, g_universe, sizeof(g_priorityUniverse));
        prioritySequenceForCurrentFrame = priorityIdForNextUniverse;
        priorityRepeatsRemaining = priorityRepeatCountForNextUniverse;
        priorityNextUniverse = false;
    }
    if (enttecValidFrames < 0xFFFFFFFFUL) enttecValidFrames++;
}

static void processEnttecByte(uint8_t value) {
    switch (enttecState) {
        case ENTTEC_WAIT_START:
            if (value == ENTTEC_START) startEnttecPacket();
            break;
        case ENTTEC_READ_LABEL:
            /* Treat a repeated start delimiter as a fresh packet boundary.
             * This allows recovery from noise or a truncated packet that ends
             * immediately before the next valid frame, without interpreting
             * the real frame delimiter as its label.  Do not apply this rule
             * inside the payload: 0x7E is valid DMX data there. */
            if (value == ENTTEC_START) {
                startEnttecPacket();
                break;
            }
            enttecLabel = value;
            enttecState = ENTTEC_READ_LENGTH_LOW;
            break;
        case ENTTEC_READ_LENGTH_LOW:
            enttecLength = value;
            enttecState = ENTTEC_READ_LENGTH_HIGH;
            break;
        case ENTTEC_READ_LENGTH_HIGH:
            enttecLength |= (uint16_t)value << 8;
            enttecPayloadIndex = 0;
            if (enttecLength >= 2 && enttecLength <= ENTTEC_MAX_PAYLOAD) {
                enttecState = ENTTEC_READ_PAYLOAD;
            } else {
                enttecDiscardRemaining = enttecLength;
                /* Zero/one-byte payloads have no bytes to discard.  Advance
                 * directly to the terminator instead of entering the discard
                 * state with a zero counter, which would consume the next
                 * packet's first byte as discarded payload forever. */
                enttecState = enttecDiscardRemaining == 0
                    ? ENTTEC_DISCARD_TERMINATOR
                    : ENTTEC_DISCARD_PAYLOAD;
            }
            break;
        case ENTTEC_READ_PAYLOAD:
            enttecPayload[enttecPayloadIndex++] = value;
            if (enttecPayloadIndex >= enttecLength)
                enttecState = ENTTEC_READ_TERMINATOR;
            break;
        case ENTTEC_READ_TERMINATOR:
            if (value == ENTTEC_END) commitEnttecUniverse();
            else if (enttecMalformedFrames < 0xFFFFFFFFUL) enttecMalformedFrames++;
            resetEnttecParser();
            if (value == ENTTEC_START) startEnttecPacket();
            break;
        case ENTTEC_DISCARD_PAYLOAD:
            if (enttecDiscardRemaining > 0) enttecDiscardRemaining--;
            if (enttecDiscardRemaining == 0)
                enttecState = ENTTEC_DISCARD_TERMINATOR;
            break;
        case ENTTEC_DISCARD_TERMINATOR:
            if (enttecMalformedFrames < 0xFFFFFFFFUL) enttecMalformedFrames++;
            resetEnttecParser();
            if (value == ENTTEC_START) startEnttecPacket();
            break;
        default:
            resetEnttecParser();
            break;
    }
}

static void serviceEnttecInput(void) {
    /* Bound work per loop so a hostile/overrunning serial source cannot starve
     * QuickESPNow callbacks or the wireless scheduler. */
    uint16_t budget = 128;
    while (Serial.available() > 0 && budget-- > 0) {
        const uint8_t value = (uint8_t)Serial.read();
        processEnttecByte(value);
        /* Management parsing observes the same input stream. It only accepts
         * a complete, CRC-checked A5 5A frame, so arbitrary ENTTEC payload
         * bytes cannot become a command. */
        switch (managementState) {
            case MGMT_WAIT_SYNC_1:
                if (value == MANAGEMENT_SYNC_1) managementState = MGMT_WAIT_SYNC_2;
                break;
            case MGMT_WAIT_SYNC_2:
                if (value == MANAGEMENT_SYNC_2) managementState = MGMT_READ_VERSION;
                else managementState = (value == MANAGEMENT_SYNC_1)
                    ? MGMT_WAIT_SYNC_2 : MGMT_WAIT_SYNC_1;
                break;
            case MGMT_READ_VERSION: managementVersion = value; managementState = MGMT_READ_OPCODE; break;
            case MGMT_READ_OPCODE: managementOpcode = value; managementState = MGMT_READ_LENGTH_LOW; break;
            case MGMT_READ_LENGTH_LOW: managementLength = value; managementState = MGMT_READ_LENGTH_HIGH; break;
            case MGMT_READ_LENGTH_HIGH:
                managementLength |= (uint16_t)value << 8;
                managementIndex = 0;
                managementState = managementLength <= sizeof(managementPayload)
                    ? (managementLength ? MGMT_READ_PAYLOAD : MGMT_READ_CRC_LOW)
                    : MGMT_WAIT_SYNC_1;
                break;
            case MGMT_READ_PAYLOAD:
                managementPayload[managementIndex++] = value;
                if (managementIndex >= managementLength) managementState = MGMT_READ_CRC_LOW;
                break;
            case MGMT_READ_CRC_LOW: managementReceivedCrc = value; managementState = MGMT_READ_CRC_HIGH; break;
            case MGMT_READ_CRC_HIGH: {
                managementReceivedCrc |= (uint16_t)value << 8;
                uint8_t crcInput[4 + sizeof(managementPayload)];
                crcInput[0] = managementVersion;
                crcInput[1] = managementOpcode;
                crcInput[2] = (uint8_t)managementLength;
                crcInput[3] = (uint8_t)(managementLength >> 8);
                memcpy(crcInput + 4, managementPayload, managementLength);
                if (managementVersion == MANAGEMENT_PROTO_VERSION &&
                    managementCrc16(crcInput, (uint16_t)(4 + managementLength)) == managementReceivedCrc &&
                    managementOpcode == MANAGEMENT_GET_RECEIVER_TELEMETRY && managementLength == 0) {
                    const unsigned long now = millis();
                    if (!telemetryReportPending &&
                        now - telemetryReportLastStartMs >= MANAGEMENT_MIN_REPORT_INTERVAL_MS) {
                        uint8_t count = 0;
                        for (uint8_t i = 0; i < MAX_TELEMETRY_RECEIVERS; i++)
                            if (receiverTable[i].valid) count++;
                        telemetryReportPartCount = (uint8_t)((count + TELEMETRY_REPORT_RECORDS_PER_PART - 1) /
                                                             TELEMETRY_REPORT_RECORDS_PER_PART);
                        if (telemetryReportPartCount == 0) telemetryReportPartCount = 1;
                        telemetryReportRecordCount = count;
                        telemetryReportPart = 0;
                        telemetryReportRecordIndex = 0;
                        telemetryReportActiveSequence = telemetryReportSequence++;
                        telemetryReportPending = true;
                        telemetryReportLastStartMs = now;
                    }
                }
                if (managementVersion == MANAGEMENT_PROTO_VERSION &&
                    managementCrc16(crcInput, (uint16_t)(4 + managementLength)) == managementReceivedCrc &&
                    managementOpcode == MANAGEMENT_GET_PRIORITY_ACKS && managementLength == 0) {
                    priorityAckReportPending = true;
                }
                if (managementVersion == MANAGEMENT_PROTO_VERSION &&
                    managementCrc16(crcInput, (uint16_t)(4 + managementLength)) == managementReceivedCrc &&
                    managementOpcode == MANAGEMENT_CLEAR_RECEIVER_CACHE && managementLength == 0) {
                    clearReceiverCache();
                    uint8_t response[8] = {MANAGEMENT_SYNC_1, MANAGEMENT_SYNC_2,
                                           MANAGEMENT_PROTO_VERSION, MANAGEMENT_CACHE_CLEARED,
                                           0, 0, 0, 0};
                    const uint16_t responseCrc = managementCrc16(response + 2, 4);
                    response[6] = (uint8_t)responseCrc;
                    response[7] = (uint8_t)(responseCrc >> 8);
                    Serial.write(response, sizeof(response));
                }
                if (managementVersion == MANAGEMENT_PROTO_VERSION &&
                    managementCrc16(crcInput, (uint16_t)(4 + managementLength)) == managementReceivedCrc &&
                    managementOpcode == MANAGEMENT_MARK_NEXT_PRIORITY &&
                    (managementLength == sizeof(PriorityTransmitRequest) || managementLength == 10U)) {
                    PriorityTransmitRequest request;
                    memset(&request, 0, sizeof(request));
                    memcpy(&request, managementPayload, managementLength);
                    if (request.repeatCount >= 1) {
                        priorityNextUniverse = true;
                        priorityIdForNextUniverse = request.priorityId;
                        priorityTargetReceiverIdForNextUniverse = request.targetReceiverId;
                        priorityRepeatCountForNextUniverse = request.repeatCount;
                        priorityAttemptForNextUniverse = request.attempt;
                        priorityGateMetadataForNextUniverse = request.gateMetadataPresent != 0;
                        memcpy(priorityHardGateMaskForNextUniverse, request.hardGateMask,
                               sizeof(priorityHardGateMaskForNextUniverse));
                        TX_LOG("TX PRIORITY MARK id=%lu target=%08lX attempt=%u repeats=%u\n",
                               (unsigned long)request.priorityId,
                               (unsigned long)request.targetReceiverId,
                               request.attempt, request.repeatCount);
                    }
                }
                managementState = MGMT_WAIT_SYNC_1;
                break;
            }
        }
    }
}

static void onTelemetryReceived(uint8_t* address, uint8_t* data, uint8_t len,
                                signed int rssi, bool broadcast) {
    (void)address;
    (void)broadcast;
    if (len == sizeof(PriorityCompletionPacket)) {
        PriorityCompletionPacket completion;
        memcpy(&completion, data, sizeof(completion));
        if (completion.magic != DMX_PACKET_MAGIC ||
            completion.protocolVersion != DMX_PROTO_VERSION ||
            completion.packetType != PRIORITY_COMPLETION_PACKET_TYPE ||
            completion.universeId != DMX_UNIVERSE_ID) {
            if (priorityCompletionInvalid < 0xFFFFFFFFUL) priorityCompletionInvalid++;
            return;
        }
        if (completion.completionStatus == PRIORITY_COMPLETE_ACCEPTED ||
            completion.completionStatus == PRIORITY_COMPLETE_GATE_APPLIED) {
            if (priorityCompletionsReceived < 0xFFFFFFFFUL) priorityCompletionsReceived++;
        } else if (completion.completionStatus == PRIORITY_COMPLETE_DUPLICATE) {
            if (priorityCompletionDuplicates < 0xFFFFFFFFUL) priorityCompletionDuplicates++;
        } else if (priorityCompletionInvalid < 0xFFFFFFFFUL) {
            priorityCompletionInvalid++;
        }
        const uint8_t next = (uint8_t)((priorityAckHead + 1U) % PRIORITY_ACK_RING_SIZE);
        if (next == priorityAckTail) {
            if (priorityCompletionDropped < 0xFFFFFFFFUL) priorityCompletionDropped++;
        } else {
            memcpy(&priorityAckRing[priorityAckHead].packet, &completion, sizeof(completion));
            priorityAckRing[priorityAckHead].receivedAtMs = millis();
            priorityAckRing[priorityAckHead].ackDelayMs =
                (completion.priorityId == lastPriorityTransmitId &&
                 completion.attempt == lastPriorityTransmitAttempt)
                ? (uint16_t)min(65535UL, millis() - lastPriorityTransmitFinishedMs) : 65535U;
            priorityAckRing[priorityAckHead].ackDelayMs =
                (completion.priorityId == lastPriorityTransmitId &&
                 completion.attempt == lastPriorityTransmitAttempt)
                ? (uint16_t)min(65535UL, millis() - lastPriorityTransmitFinishedMs) : 65535U;
            priorityAckHead = next;
        }
        (void)rssi;
        return;
    }
    if (len != sizeof(ReceiverTelemetryPacket)) return;
    ReceiverTelemetryPacket packet;
    memcpy(&packet, data, sizeof(packet));
    if (packet.magic != DMX_PACKET_MAGIC ||
        packet.protocolVersion != DMX_PROTO_VERSION ||
        packet.packetType != TELEMETRY_PACKET_TYPE) return;

    const uint8_t next = (uint8_t)((telemetryHead + 1) % TELEMETRY_RING_SIZE);
    const uint32_t savedPS = xt_rsil(15);
    if (next != telemetryTail) {
        memcpy(telemetryRing[telemetryHead].payload, data, len);
        telemetryRing[telemetryHead].len = len;
        telemetryRing[telemetryHead].rssi = (int8_t)rssi;
        telemetryHead = next;
    } else if (telemetryPacketsDropped < 0xFFFFFFFFUL) {
        telemetryPacketsDropped++;
    }
    xt_wsr_ps(savedPS);
}

static bool popTelemetry(ReceiverTelemetryPacket& packet, int8_t& rssi) {
    if (telemetryHead == telemetryTail) return false;
    const uint32_t savedPS = xt_rsil(15);
    if (telemetryHead == telemetryTail) {
        xt_wsr_ps(savedPS);
        return false;
    }
    const uint8_t slot = telemetryTail;
    memcpy(&packet, telemetryRing[slot].payload, sizeof(packet));
    rssi = telemetryRing[slot].rssi;
    telemetryTail = (uint8_t)((telemetryTail + 1) % TELEMETRY_RING_SIZE);
    xt_wsr_ps(savedPS);
    return true;
}

static void reportTelemetry(void) {
#if TRANSMITTER_TELEMETRY_LOGGING
    ReceiverTelemetryPacket packet;
    int8_t rssi;
    while (popTelemetry(packet, rssi)) {
        cacheTelemetry(packet, rssi);
        Serial.printf("RX TELEMETRY id=%08lX mac=%02X:%02X:%02X:%02X:%02X:%02X uptime=%lus battery=%s last_seq=%lu complete=%lu incomplete=%lu malformed=%lu since=%lums rssi=%d fw=%u proto=%u t_seq=%lu\n",
                      (unsigned long)packet.receiverId,
                      packet.macAddress[0], packet.macAddress[1], packet.macAddress[2],
                      packet.macAddress[3], packet.macAddress[4], packet.macAddress[5],
                      (unsigned long)packet.uptimeSeconds,
                      packet.batteryLow ? "LOW" : "OK",
                      (unsigned long)packet.lastActiveSequence,
                      (unsigned long)packet.completeUniverses,
                      (unsigned long)packet.incompleteUniverses,
                      (unsigned long)packet.malformedPackets,
                      (unsigned long)packet.timeSinceLastUniverseMs,
                      rssi, packet.firmwareVersion, packet.protocolVersion,
                      (unsigned long)packet.telemetrySequence);
    }
#else
    /* Drain the queue even when reporting is disabled, while retaining the
     * latest packet for the binary management interface. */
    ReceiverTelemetryPacket packet;
    int8_t rssi;
    while (popTelemetry(packet, rssi)) cacheTelemetry(packet, rssi);
#endif
}

static int validReceiverByOrdinal(uint8_t ordinal) {
    uint8_t seen = 0;
    for (uint8_t i = 0; i < MAX_TELEMETRY_RECEIVERS; i++) {
        if (receiverTable[i].valid) {
            if (seen++ == ordinal) return i;
        }
    }
    return -1;
}

/* Emit one bounded response part per loop. Multipart responses are supported
 * from the initial implementation so receiver counts can exceed 16. */
static void serviceTelemetryReport(void) {
    if (!telemetryReportPending) return;

    uint8_t packet[6 + sizeof(TelemetryReportPartHeader) +
                   TELEMETRY_REPORT_RECORDS_PER_PART * sizeof(TelemetryReportRecord) + 2];
    uint16_t offset = 0;
    packet[offset++] = MANAGEMENT_SYNC_1;
    packet[offset++] = MANAGEMENT_SYNC_2;
    packet[offset++] = MANAGEMENT_PROTO_VERSION;
    packet[offset++] = MANAGEMENT_RECEIVER_TELEMETRY;

    TelemetryReportPartHeader header;
    header.reportVersion = 1U;
    header.partIndex = telemetryReportPart;
    header.partCount = telemetryReportPartCount;
    header.recordCount = telemetryReportRecordCount - telemetryReportRecordIndex;
    if (header.recordCount > TELEMETRY_REPORT_RECORDS_PER_PART)
        header.recordCount = TELEMETRY_REPORT_RECORDS_PER_PART;
    header.reportSequence = telemetryReportActiveSequence;

    const uint16_t payloadLength = sizeof(header) +
                                   header.recordCount * sizeof(TelemetryReportRecord);
    packet[offset++] = (uint8_t)payloadLength;
    packet[offset++] = (uint8_t)(payloadLength >> 8);
    memcpy(packet + offset, &header, sizeof(header));
    offset += sizeof(header);

    for (uint8_t n = 0; n < header.recordCount; n++) {
        const int index = validReceiverByOrdinal((uint8_t)(telemetryReportRecordIndex + n));
        if (index < 0) break;
        const ReceiverTelemetryEntry& source = receiverTable[index];
        TelemetryReportRecord record;
        record.receiverId = source.telemetry.receiverId;
        memcpy(record.macAddress, source.macAddress, sizeof(record.macAddress));
        record.linkState = receiverLinkState(source, millis());
        record.batteryLow = source.telemetry.batteryLow;
        record.transmitterRssi = source.transmitterRssi;
        record.receiverLastRssi = source.telemetry.lastRssi;
        record.uptimeSeconds = source.telemetry.uptimeSeconds;
        record.lastActiveSequence = source.telemetry.lastActiveSequence;
        record.completeUniverses = source.telemetry.completeUniverses;
        record.incompleteUniverses = source.telemetry.incompleteUniverses;
        record.malformedPackets = source.telemetry.malformedPackets;
        record.timeSinceLastUniverseMs = source.telemetry.timeSinceLastUniverseMs;
        record.transmitterLastSeenMs = millis() - source.lastSeenMs;
        record.firmwareVersion = source.telemetry.firmwareVersion;
        record.protocolVersion = source.telemetry.protocolVersion;
        record.reserved = 0;
        record.telemetrySequence = source.telemetry.telemetrySequence;
        memcpy(packet + offset, &record, sizeof(record));
        offset += sizeof(record);
    }

    /* CRC covers version, opcode, length, and payload (not sync bytes). */
    const uint16_t crc = managementCrc16(packet + 2,
                                         (uint16_t)(4 + payloadLength));
    packet[offset++] = (uint8_t)crc;
    packet[offset++] = (uint8_t)(crc >> 8);
    Serial.write(packet, offset);

    telemetryReportRecordIndex = (uint8_t)(telemetryReportRecordIndex + header.recordCount);
    telemetryReportPart++;
    if (telemetryReportPart >= telemetryReportPartCount || header.recordCount == 0)
        telemetryReportPending = false;
}

static void servicePriorityAckReport(void) {
    if (!priorityAckReportPending) return;
    uint8_t packet[6 + sizeof(PriorityAckReportHeader) + 9 * sizeof(PriorityAckReportRecord) + 2];
    uint16_t offset = 0;
    packet[offset++] = MANAGEMENT_SYNC_1;
    packet[offset++] = MANAGEMENT_SYNC_2;
    packet[offset++] = MANAGEMENT_PROTO_VERSION;
    packet[offset++] = MANAGEMENT_PRIORITY_ACKS;
    const uint8_t count = (uint8_t)((priorityAckHead >= priorityAckTail)
        ? (priorityAckHead - priorityAckTail)
        : (PRIORITY_ACK_RING_SIZE - priorityAckTail + priorityAckHead));
    const uint8_t records = count > 9U ? 9U : count;
    const uint16_t payloadLength = sizeof(PriorityAckReportHeader) +
                                   records * sizeof(PriorityAckReportRecord);
    packet[offset++] = (uint8_t)payloadLength;
    packet[offset++] = (uint8_t)(payloadLength >> 8);
    PriorityAckReportHeader header = {1U, records, priorityAckReportSequence++,
        (uint32_t)priorityCompletionsReceived, (uint32_t)priorityCompletionDuplicates,
        (uint32_t)priorityCompletionInvalid, (uint32_t)priorityCompletionDropped};
    memcpy(packet + offset, &header, sizeof(header));
    offset += sizeof(header);
    for (uint8_t i = 0; i < records; i++) {
        PriorityAckSlot& source = priorityAckRing[priorityAckTail];
        PriorityAckReportRecord record = {source.packet.priorityId, source.packet.receiverId,
            source.packet.frameSequence, source.packet.attempt, source.packet.completionStatus,
            source.packet.attemptsObserved, source.packet.lastRssi, source.receivedAtMs,
            source.ackDelayMs};
        memcpy(packet + offset, &record, sizeof(record));
        offset += sizeof(record);
        priorityAckTail = (uint8_t)((priorityAckTail + 1U) % PRIORITY_ACK_RING_SIZE);
    }
    const uint16_t crc = managementCrc16(packet + 2, (uint16_t)(4 + payloadLength));
    packet[offset++] = (uint8_t)crc;
    packet[offset++] = (uint8_t)(crc >> 8);
    Serial.write(packet, offset);
    priorityAckReportPending = false;
}

/* --------------------------------------------------------------------------
 * Feature 6 TEST HOOKS (all compile-time, DEFAULT OFF).
 * Enabling any of these changes only the TX test behavior so the receiver's
 * reconstruction / double buffering can be exercised robustly. With NONE
 * defined the transmitter uses normal ENTTEC input: slots {0,1,2}, count 3,
 * no corruption, sequence starts at 0.
 *
 *   TEST_DROP_FRAGMENT_INDEX       omit this fragment (0/1/2) each frame
 *   TEST_DUPLICATE_FRAGMENT_INDEX  send this fragment twice each frame
 *   TEST_REORDER_FRAGMENTS         transmit in order 2,0,1
 *   TEST_CORRUPT_FRAGMENT_INDEX    corrupt one payload byte of this fragment
 *   TEST_CORRUPT_BYTE              (optional) which payload byte (0-based)
 *   TEST_FORCE_SEQUENCE_START      start the frame sequence at this value
 *   TEST_SEQUENCE_WRAP             start at 0xFFFFFFFE to exercise rollover
 *   TEST_DELAYED_FRAGMENT          transmit one fragment of each frame ~2.5 s late (stale fragment)
 * -------------------------------------------------------------------------- */

/* Per-frame send slot list: ordered fragment indices to transmit.
 * Default (no hooks) = {0,1,2}, count 3. A duplicate appends a 4th slot. */
static uint8_t txSlotList[DMX_FRAGMENTS_PER_UNIVERSE + 1];
static uint8_t txSlotCount = DMX_FRAGMENTS_PER_UNIVERSE;

/* Build the per-frame send slot list from the (compile-time) test hooks.
 * Default (no hooks) = fragments 0,1,2 in order. A drop removes a slot; a
 * duplicate appends a 4th slot; reorder changes the order. */
static void buildTxSlotList(void) {
    uint8_t order[DMX_FRAGMENTS_PER_UNIVERSE];
    uint8_t n = 0;
#if defined(TEST_REORDER_FRAGMENTS)
    order[n++] = 2; order[n++] = 0; order[n++] = 1;
#else
    for (uint8_t i = 0; i < DMX_FRAGMENTS_PER_UNIVERSE; i++) order[n++] = i;
#endif

    uint8_t m = 0;
    for (uint8_t k = 0; k < n; k++) {
        const uint8_t idx = order[k];
#if defined(TEST_DROP_FRAGMENT_INDEX)
        if (idx == TEST_DROP_FRAGMENT_INDEX) continue;
#endif
        txSlotList[m++] = idx;
    }
#if defined(TEST_DUPLICATE_FRAGMENT_INDEX)
    txSlotList[m++] = TEST_DUPLICATE_FRAGMENT_INDEX;
#endif
    txSlotCount = m;
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
        pPayload[i] = (universeIndex < DMX_UNIVERSE_SIZE) ? g_txUniverse[universeIndex] : 0;
    }

#if defined(TEST_CORRUPT_FRAGMENT_INDEX)
    /* TEST-ONLY: corrupt one payload byte of the targeted fragment. Metadata
     * stays valid; the receiver's full 512-byte integrity check must fail. */
    if (fragIdx == TEST_CORRUPT_FRAGMENT_INDEX) {
        uint8_t corruptAt = 0;
#ifdef TEST_CORRUPT_BYTE
        corruptAt = TEST_CORRUPT_BYTE;
#endif
        if (corruptAt >= payloadLength) corruptAt = 0;
        const uint16_t uIdx = static_cast<uint16_t>(offset + corruptAt);
        pPayload[corruptAt] = static_cast<uint8_t>(g_txUniverse[uIdx] ^ 0xFF);
    }
#endif

    /* Broadcast at the fragment's true size (not always the max). */
    const uint16_t totalSize = static_cast<uint16_t>(DMX_HEADER_SIZE + payloadLength);
    quickEspNow.sendBcast(packetBuffer, totalSize);

}

static void submitPriorityFragment(uint32_t seq, uint8_t fragIdx) {
    const uint16_t offset = (uint16_t)fragIdx * PRIORITY_PAYLOAD_SIZE;
    const uint8_t payloadLength = (offset + PRIORITY_PAYLOAD_SIZE <= DMX_UNIVERSE_SIZE)
        ? PRIORITY_PAYLOAD_SIZE : (uint8_t)(DMX_UNIVERSE_SIZE - offset);
    uint8_t packetBuffer[ESP_NOW_MAX_DATA_LEN];
    DmxPriorityFragmentPacket pkt;
    pkt.magic = DMX_PACKET_MAGIC;
    pkt.protocolVersion = DMX_PROTO_VERSION;
    pkt.packetType = DMX_PRIORITY_PACKET_TYPE;
    pkt.universeId = DMX_UNIVERSE_ID;
    pkt.targetReceiverId = 0U; /* zero retains legacy broadcast behavior */
    pkt.targetReceiverId = priorityTargetReceiverIdForNextUniverse;
    pkt.frameSequence = seq;
    pkt.priorityId = prioritySequenceForCurrentFrame;
    pkt.attempt = priorityAttempt;
    pkt.repeatCount = priorityRepeatCountForNextUniverse;
    pkt.fragmentIndex = fragIdx;
    pkt.fragmentCount = 3U;
    pkt.dataOffset = offset;
    pkt.payloadLength = payloadLength;
    memcpy(packetBuffer, &pkt, sizeof(pkt));
    memcpy(packetBuffer + PRIORITY_HEADER_SIZE, g_priorityUniverse + offset, payloadLength);
    if (priorityTargetReceiverIdForNextUniverse == 0U
#if defined(PRIORITY_FORCE_BROADCAST_DIAGNOSTIC)
        || true
#endif
    ) {
        const comms_send_error_t result = quickEspNow.sendBcast(
            packetBuffer, (uint16_t)(PRIORITY_HEADER_SIZE + payloadLength));
#if defined(TRANSMITTER_VERBOSE_LOGGING)
        TX_LOG("TX PRIORITY broadcast frag=%u len=%u result=%d\n", fragIdx,
               (unsigned)(PRIORITY_HEADER_SIZE + payloadLength), result);
#endif
    } else {
        uint8_t destination[6];
        bool found = false;
        for (uint8_t i = 0; i < MAX_TELEMETRY_RECEIVERS; i++) {
            if (receiverTable[i].valid &&
                receiverTable[i].telemetry.receiverId == priorityTargetReceiverIdForNextUniverse) {
                memcpy(destination, receiverTable[i].macAddress, sizeof(destination));
                found = true;
                break;
            }
        }
        if (found) {
            const comms_send_error_t result = quickEspNow.send(
                destination, packetBuffer,
                (uint16_t)(PRIORITY_HEADER_SIZE + payloadLength));
#if defined(TRANSMITTER_VERBOSE_LOGGING)
            TX_LOG("TX PRIORITY unicast target=%08lX frag=%u len=%u result=%d\n",
                   (unsigned long)priorityTargetReceiverIdForNextUniverse,
                   fragIdx, (unsigned)(PRIORITY_HEADER_SIZE + payloadLength), result);
#endif
        }
    }
}

static bool submitPriorityGateMetadata(void) {
    if (!priorityGateMetadataForNextUniverse) return true;
    PriorityGateMetadataPacket packet;
    packet.magic = DMX_PACKET_MAGIC;
    packet.protocolVersion = DMX_PROTO_VERSION;
    packet.packetType = PRIORITY_GATE_METADATA_PACKET_TYPE;
    packet.universeId = DMX_UNIVERSE_ID;
    packet.targetReceiverId = priorityTargetReceiverIdForNextUniverse;
    packet.priorityId = prioritySequenceForCurrentFrame;
    packet.attempt = priorityAttemptForNextUniverse;
    memcpy(packet.hardGateMask, priorityHardGateMaskForNextUniverse,
           sizeof(packet.hardGateMask));
    const uint16_t packetSize = sizeof(packet);
    if (packet.targetReceiverId == 0U) {
        return quickEspNow.sendBcast(reinterpret_cast<const uint8_t*>(&packet), packetSize) == COMMS_SEND_OK;
    }
    uint8_t destination[6];
    for (uint8_t i = 0; i < MAX_TELEMETRY_RECEIVERS; i++) {
        if (receiverTable[i].valid &&
            receiverTable[i].telemetry.receiverId == packet.targetReceiverId) {
            memcpy(destination, receiverTable[i].macAddress, sizeof(destination));
            return quickEspNow.send(destination, reinterpret_cast<const uint8_t*>(&packet), packetSize) == COMMS_SEND_OK;
        }
    }
    return false;
}

void setup(void) {
    /* ENTTEC-compatible host input at 115200 baud, 8 data bits, no parity,
     * 2 stops. This supports the full-universe input bandwidth needed when the
     * validated 20 Hz wireless refresh default is used. */
    Serial.begin(115200, SERIAL_8N2);

    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false);

    if (!quickEspNow.begin(ESPNOW_CHANNEL, WIFI_IF_STA, false)) {
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
    quickEspNow.onDataRcvd(onTelemetryReceived);

    {
        uint8_t macBuffer[6];
        WiFi.macAddress(macBuffer);
        char macStr[18];
        snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
                 macBuffer[0], macBuffer[1], macBuffer[2],
                 macBuffer[3], macBuffer[4], macBuffer[5]);
        (void)macStr; /* UART is reserved for ENTTEC binary input. */
    }

    /* TEST HOOKS: initialize the frame sequence (default 0). */
#if defined(TEST_SEQUENCE_WRAP)
    g_frameSequence = 0xFFFFFFFEUL;
#elif defined(TEST_FORCE_SEQUENCE_START)
    g_frameSequence = TEST_FORCE_SEQUENCE_START;
#endif

    /* TEST HOOKS: build the per-frame send slot list (default {0,1,2}). */
    buildTxSlotList();

    delay(500);

}

/* --------------------------------------------------------------------------
 * Non-blocking frame state machine:
 *   IDLE -> GENERATE -> SEND(all fragments) -> DRAIN(queue empty) -> IDLE
 * -------------------------------------------------------------------------- */
enum TxState {
    TX_IDLE,
    TX_GENERATING,
    TX_SENDING,
    TX_PRIORITY_METADATA,
    TX_DRAIN
#if defined(TEST_DELAYED_FRAGMENT)
    , TX_LATE
#endif
};
static TxState txState = TX_IDLE;
static unsigned long lastFrameGenerationTime = 0;
static unsigned long stateEnteredTime = 0;
static uint8_t currentFragment = 0;

/* TX per-frame overhead (measured ~27 ms for a 512-channel frame: radio airtime + drain).
 * When defined, we use it as a budget subtraction so period ≈ 1000/Hz rather than
 * interval + overhead. Omit -DWIRELESS_TX_OVERHEAD_MS=N to restore the original behavior. */
#ifndef WIRELESS_TX_OVERHEAD_MS
#define WIRELESS_TX_OVERHEAD_MS 27UL      /* measured median from the sweep */
#endif

/* Safety bound so a stuck queue cannot wedge the state machine. Tightened to ~100 ms,
 * and configurable via -DWIRELESS_TX_DRAIN_TIMEOUT_MS if needed. */
#ifndef WIRELESS_TX_DRAIN_TIMEOUT_MS
#define WIRELESS_TX_DRAIN_TIMEOUT_MS 100UL /* down from 200 ms; still covers the drain case */
#endif

/* Effective interval = requested interval minus overhead (budget pacing).
 * Clamp at zero: unsigned subtraction must not wrap at/above the estimated
 * overhead ceiling. At that point the state machine runs as fast as the
 * completed-fragment drain permits, rather than waiting for a huge interval. */
static constexpr unsigned long TX_INTERVAL_MS =
    (WIRELESS_REFRESH_INTERVAL_MS > WIRELESS_TX_OVERHEAD_MS)
        ? (WIRELESS_REFRESH_INTERVAL_MS - WIRELESS_TX_OVERHEAD_MS)
        : 0UL;
static constexpr unsigned long PRIORITY_TX_INTERVAL_MS =
    (WIRELESS_PRIORITY_REFRESH_INTERVAL_MS > WIRELESS_TX_OVERHEAD_MS)
        ? (WIRELESS_PRIORITY_REFRESH_INTERVAL_MS - WIRELESS_TX_OVERHEAD_MS)
        : 0UL;

/* TEST HOOK (Feature 6, Test 6): late-fragment state. */
#if defined(TEST_DELAYED_FRAGMENT)
static bool     lateSent = false;
static uint32_t lateSeq  = 0;
/* Hold the late fragment until this long after the frame completed.
 * Chosen > the receiver's STAGING_TIMEOUT_MS (2000 ms) yet < its
 * TRANSMITTER_RESET_RECOVERY_MS (3000 ms), so the receiver classifies
 * the late fragment as STALE (live link) rather than as a re-baseline. */
static const unsigned long TEST_DELAYED_FRAGMENT_DELAY_MS = 2500UL;
#endif

void loop(void) {
    const unsigned long now = millis();
    const unsigned long activeInterval = priorityRepeatsRemaining > 0
        ? PRIORITY_TX_INTERVAL_MS : TX_INTERVAL_MS;

    serviceEnttecInput();
    reportTelemetry();
    serviceTelemetryReport();
    servicePriorityAckReport();

    switch (txState) {
        case TX_IDLE:
            if (now - lastFrameGenerationTime >= activeInterval) {
                txState = TX_GENERATING;
                stateEnteredTime = now;
            TX_LOG("TX GENERATE: starting new frame\n");
            }
            break;

        case TX_GENERATING:
            memcpy(g_txUniverse, g_universe, sizeof(g_txUniverse));
            currentFragment = 0;
            g_sendConfirmations = 0;   /* reset before the sends so all are counted */
            currentFrameIsPriority = priorityRepeatsRemaining > 0;
            if (currentFrameIsPriority) {
                priorityMetadataPending = priorityGateMetadataForNextUniverse;
                if (priorityMetadataPending) {
                    g_sendConfirmations = 0;
                    if (submitPriorityGateMetadata()) {
                        txState = TX_PRIORITY_METADATA;
                    } else {
                        txState = TX_IDLE;
                        lastFrameGenerationTime = now + 50UL;
                    }
                }
                priorityAttempt = priorityAttemptForNextUniverse;
                lastPriorityTransmitId = prioritySequenceForCurrentFrame;
                lastPriorityTransmitAttempt = priorityAttempt;
                lastPriorityTransmitFinishedMs = now;
            }
            TX_LOG("TX FRAME seq=%u fragments=%u priority=%u\n",
                          g_frameSequence, txSlotCount, currentFrameIsPriority ? 1U : 0U);
            if (!priorityMetadataPending) txState = TX_SENDING;
            stateEnteredTime = now;
            break;

        case TX_PRIORITY_METADATA:
            if (g_sendConfirmations >= 1) {
                g_sendConfirmations = 0;
                priorityMetadataPending = false;
                txState = TX_SENDING;
            }
            break;

        case TX_SENDING:
            if (currentFragment < txSlotCount) {
                if (currentFrameIsPriority && !quickEspNow.readyToSendData()) {
                    break;
                }
                if (currentFrameIsPriority && priorityTargetReceiverIdForNextUniverse != 0U &&
                    g_sendConfirmations < currentFragment) {
                    /* Targeted delivery is serialized fragment-by-fragment.
                     * This gives the receiver a confirmed radio boundary before
                     * the next fragment arrives instead of creating a burst in
                     * the shared ESP-NOW queue. */
                    break;
                }
                if (currentFrameIsPriority) {
                    submitPriorityFragment(g_frameSequence, currentFragment);
                } else {
                    submitFragment(g_frameSequence, txSlotList[currentFragment]);
                }
                currentFragment++;
            } else {
                /* All fragments queued - wait for the queue to drain. */
                txState = TX_DRAIN;
                stateEnteredTime = now;
            }
            break;

        case TX_DRAIN:
            if (g_sendConfirmations >= txSlotCount ||
                (now - stateEnteredTime >= WIRELESS_TX_DRAIN_TIMEOUT_MS)) {
                if (currentFrameIsPriority && priorityRepeatsRemaining > 1) {
                    priorityRepeatsRemaining--;
                    currentFragment = 0;
                    g_sendConfirmations = 0;
                    /* Return through TX_IDLE so the priority-specific 1 Hz
                     * interval is honored between physical repeats. */
                    lastFrameGenerationTime = now;
                    txState = TX_IDLE;
                    stateEnteredTime = now;
                    break;
                }
                /* Frame fully transmitted; advance to the next one. */
                const bool completedPriority = currentFrameIsPriority;
                currentFrameIsPriority = false;
                /* A MARK_NEXT_PRIORITY command may arrive while a normal frame
                 * is draining. Do not erase the pending priority transaction;
                 * only clear the repeat budget after a priority frame itself
                 * has completed. */
                if (completedPriority) priorityRepeatsRemaining = 0;
                g_frameSequence++;
                lastFrameGenerationTime = now;
#if defined(TEST_DELAYED_FRAGMENT)
                /* TEST HOOK (Test 6): schedule one late fragment of the
                 * frame we just completed. The receiver must flag it
                 * STALE (older-or-equal than active, link still live). */
                lateSeq = g_frameSequence - 1;
                lateSent = false;
                txState = TX_LATE;
                stateEnteredTime = now;
                TX_LOG("TX LATE: scheduling delayed fragment\n");
#else
                txState = TX_IDLE;
                TX_LOG("TX FRAME complete seq=%u, next seq=%u\n",
                              g_frameSequence, g_frameSequence + 1);
#endif
            }
            break;
#if defined(TEST_DELAYED_FRAGMENT)
        case TX_LATE:
            if (!lateSent) {
                /* Hold, then transmit one fragment of the previous frame. */
                if ((now - stateEnteredTime) >= TEST_DELAYED_FRAGMENT_DELAY_MS) {
                    g_sendConfirmations = 0; /* count only the late send */
                    submitFragment(lateSeq, 0);
                    lateSent = true;
                    stateEnteredTime = now;
                    TX_LOG("TX LATE: transmitted delayed fragment of previous frame\n");
                }
            } else if (g_sendConfirmations >= 1 ||
                       (now - stateEnteredTime) >= WIRELESS_TX_DRAIN_TIMEOUT_MS) {
                txState = TX_IDLE;
                TX_LOG("TX LATE: complete, resuming normal frames\n");
            }
            break;
#endif
    }
}
