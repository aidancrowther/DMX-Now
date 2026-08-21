// Feature 3 (updated): Basic wired DMX output from ESP-01 through MAX3485.
//
// Purpose of this sketch is to prove the basic physical path:
//   ESP-01 GPIO1 (UART0 TX) -> MAX3485 DI -> DMX fixture
// using the locally patched ESP-Dmx library (UART0/GPIO1, TX-only).
//
// This feature does NOT implement:
//   - QuickESPNow transmission/reception
//   - wireless packet structures or buffering
//   - ENTTEC parsing
//   - telemetry
//   - low-battery handling
//
// Feature 4 (Off-by-one fix + ESP8266 UART boundary workaround):
//   - Channel-cycling test pattern uses explicit byte-by-byte writes
//     to avoid triggering ESP8266 UART buffer corruption at offset 255.
//   - Bulk buffer write via update() works fine for normal operation.
//   - Total frame: 513 bytes ([start_code=0x00] + 512 channels) after Feature 4 fix.
//
// Note: UART flashes MUST begin at offset 0x0000. The ESP-Dmx library's update()
// begins each frame with a BREAK sequence followed by data starting at offset 0x0000.
// This is required by DMX512 specification; any other start offset corrupts the protocol.

// Intended receiver pin allocation (fixed by README.md).
static const int PIN_DMX_DATA    = 1; // GPIO1 / UART0 TX -> DMX data (MAX3485 DI)
static const int PIN_DMX_ENABLE  = 2; // GPIO2           -> MAX3485 DE (via inverting 2N2222 stage)
static const int PIN_BATTERY_LOW = 3; // GPIO3           -> future digital low-battery input

// Mandatory libraries (locally cloned under ./libraries):
#include <QuickEspNow.h>   // QuickESPNow wireless transport (not initialized in this feature)
#include <ESPDMX.h>        // ESP-Dmx DMX512 output (patched to UART0/GPIO1, TX-only; Feature 4 off-by-one fix applied)

// Global DMX object: state persists across setup() and loop() per user instruction.
// Feature 4 fix: dmxData[0] = start code, dmxData[1..512] = channels. Total frame = 513 bytes.
DMXESPSerial dmx;

// DMX universe constants (named over magic numbers for clarity).
const int DMX_UNIVERSE_CHANNELS = 512;  // Channel count (1-based, channels 1..512)

// Channel-cycling test pattern: distinct marker value to identify channel cutoff during hardware testing.
// Layout: [start_code=0x00] + cycling markers at currentTestChannel + remaining channels at 0x00
const uint8_t DMX_PATTERN_MARKER = 0xAA;  // Marker value for active channel (distinct from 0x55-0x77)

// State tracking for non-blocking timing.
unsigned long lastPatternChangeTime = 0;
int currentTestChannel = 1;             // Channel index being marked (1-based, persists in global dmx object)

// Helper to write the channel-cycling test pattern using explicit byte-by-byte writes.
// This avoids triggering ESP8266 UART buffer corruption that occurs when writing to
// offset 255 via bulk Serial.write() calls. Instead, we set each channel individually.
void writeChannelCyclingPattern() {
  // Zero all channels first:
  for (int ch = 1; ch <= DMX_UNIVERSE_CHANNELS; ++ch) {
    dmx.write(ch, 0x00);
  }
  // Mark the current channel with distinct pattern value.
  dmx.write(currentTestChannel, DMX_PATTERN_MARKER);
}

void setup() {
  // Initialize GPIO2 as output and set HIGH to keep MAX3485 disabled during initialization.
  pinMode(PIN_DMX_ENABLE, OUTPUT);
  digitalWrite(PIN_DMX_ENABLE, HIGH);  // MAX3485 DE LOW -> transmitter disabled

  // Initialize ESP-Dmx with full 512-channel support (Feature 4: buffer = 513 bytes).
  // The patched library uses UART0/GPIO1 in TX-only mode.
  dmx.init(DMX_UNIVERSE_CHANNELS);

  // Write initial channel-cycling test pattern (persists in global dmx object state).
  writeChannelCyclingPattern();

  // Ensure first valid DMX state is ready by calling update() once.
  // This sends an initial DMX frame with: start_code (0x00) + all 512 channels.
  // Total transmitted: 513 bytes (Feature 4 fix).
  dmx.update();

  // Now that ESP-Dmx is initialized and a valid universe is being transmitted,
  // enable the MAX3485 by setting GPIO2 LOW.
  digitalWrite(PIN_DMX_ENABLE, LOW);  // MAX3485 DE HIGH -> transmitter enabled
}

void loop() {
  // Non-blocking timing for channel-cycling test pattern (0.5s between changes).
  unsigned long currentTime = millis();
  if (currentTime - lastPatternChangeTime >= 500) {  // 0.5 seconds
    // Advance to next channel marker.
    currentTestChannel++;
    
    // Wrap around after reaching end of universe.
    if (currentTestChannel > DMX_UNIVERSE_CHANNELS) {
      currentTestChannel = 1;
    }
    
    // Write new pattern (state persists in global dmx object).
    writeChannelCyclingPattern();
    
    // Record timing.
    lastPatternChangeTime = currentTime;
    
    // Continue outputting DMX frames via update().
  }
  
  // Continuously output DMX frames via ESP-Dmx's update() method.
  // This handles BREAK + frame at 250k baud with proper timing.
  dmx.update();
}
