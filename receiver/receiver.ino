// Library replacement: ESP-Dmx → espDMX (basic usage).
//
// Purpose of this sketch is to prove:
//   ESP-01 GPIO1 (UART0 TX) -> MAX3485 DI -> DMX fixture
// and verify the external MAX3485 DE transistor control.
//
// GPIO2 drives MAX3485 DE through an inverting 2N2222:
//
//   GPIO2 HIGH -> transistor ON  -> DE LOW  -> DMX output DISABLED
//   GPIO2 LOW  -> transistor OFF -> DE HIGH -> DMX output ENABLED
//
// Test behavior:
//   - Moving 0xAA marker advances every 500 ms.
//   - DMX output is enabled for 4 seconds.
//   - DMX output is disabled for 1 second.
//   - espDMX continues running during the disabled interval.
//   - A DMX sniffer should therefore see the stream disappear for
//     approximately one second, then resume with the marker having advanced.

static const int PIN_DMX_DATA    = 1; // GPIO1 / UART0 TX -> DMX data
static const int PIN_DMX_ENABLE  = 2; // GPIO2 -> MAX3485 DE via inverting 2N2222
static const int PIN_BATTERY_LOW = 3; // GPIO3 -> future low-battery input

#include <QuickEspNow.h>
#include <espDMX.h>

static const uint16_t DMX_UNIVERSE_CHANNELS = 512;

static const unsigned long PATTERN_INTERVAL_MS = 500;

// MAX3485 enable/disable test timing.
static const unsigned long DMX_ENABLED_TIME_MS  = 4000;
static const unsigned long DMX_DISABLED_TIME_MS = 1000;

// One moving 0xAA marker.
// Channel 512 is permanently held at 0x01 to force a full 512-slot universe.
static uint8_t testPattern[DMX_UNIVERSE_CHANNELS];

static unsigned long lastPatternChangeTime = 0;
static unsigned long lastEnableStateChangeTime = 0;

// Start at zero so the first increment selects DMX channel 1.
static uint16_t currentTestChannel = 0;

// Track the physical MAX3485 output state.
static bool dmxOutputEnabled = false;

static void setDmxOutputEnabled(bool enabled) {
  dmxOutputEnabled = enabled;

  // External transistor inverts the logic:
  //
  // GPIO LOW  -> transistor OFF -> DE HIGH -> enabled
  // GPIO HIGH -> transistor ON  -> DE LOW  -> disabled
  digitalWrite(PIN_DMX_ENABLE, enabled ? LOW : HIGH);
}

void setup() {
  // IMPORTANT:
  // GPIO2 must be HIGH during ESP8266 boot.
  // The external base resistor is 100K so the transistor circuit
  // does not prevent normal ESP-01 startup.

  pinMode(PIN_DMX_ENABLE, OUTPUT);

  // Keep MAX3485 disabled while everything initializes.
  setDmxOutputEnabled(false);

  dmxA.begin();

  // Clear the whole universe.
  for (uint16_t ch = 0; ch < DMX_UNIVERSE_CHANNELS; ++ch) {
    testPattern[ch] = 0x00;
  }

  // Keep channel 512 non-zero to force a full 512-slot universe.
  testPattern[511] = 0x01;

  // Load initial universe into espDMX.
  dmxA.setChans(testPattern, DMX_UNIVERSE_CHANNELS, 1);

  // Enable the physical MAX3485 output.
  setDmxOutputEnabled(true);

  lastPatternChangeTime = millis();
  lastEnableStateChangeTime = millis();
}

void loop() {
  const unsigned long currentTime = millis();

  //
  // DMX DATA TEST PATTERN
  //
  if (currentTime - lastPatternChangeTime >= PATTERN_INTERVAL_MS) {
    lastPatternChangeTime = currentTime;

    // Advance moving marker.
    currentTestChannel++;

    // Channels 1-511 are available for the moving marker.
    // Channel 512 is reserved as the permanent 0x01 marker.
    if (currentTestChannel >= DMX_UNIVERSE_CHANNELS) {
      currentTestChannel = 1;
    }

    // Clear channels 1-511.
    for (uint16_t ch = 0; ch < 511; ++ch) {
      testPattern[ch] = 0x00;
    }

    // Moving marker.
    testPattern[currentTestChannel - 1] = 0xAA;

    // Keep channel 512 permanently non-zero.
    testPattern[511] = 0x01;

    // Update espDMX.
    //
    // This happens even while the MAX3485 is disabled, allowing us
    // to verify that the ESP/espDMX continues operating normally
    // while the physical RS-485 output is disconnected.
    dmxA.setChans(testPattern, DMX_UNIVERSE_CHANNELS, 1);
  }

  //
  // MAX3485 DRIVER-ENABLE TEST
  //
  if (dmxOutputEnabled) {
    if (currentTime - lastEnableStateChangeTime >= DMX_ENABLED_TIME_MS) {
      setDmxOutputEnabled(false);
      lastEnableStateChangeTime = currentTime;
    }
  } else {
    if (currentTime - lastEnableStateChangeTime >= DMX_DISABLED_TIME_MS) {
      setDmxOutputEnabled(true);
      lastEnableStateChangeTime = currentTime;
    }
  }
}