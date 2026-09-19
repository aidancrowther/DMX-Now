/* Feature 8 DMX output verifier for an Arduino Mega 2560.
 *
 * Wiring:
 *   receiver MAX3485 RO / DMX data -> Mega pin 19 (RX1 / USART1)
 *   receiver and Mega signal ground -> common ground
 *   Mega USB -> host control/results serial at 115200 8N1
 *
 * Build with -DDMX_USE_PORT1 so DMXSerial binds USART1 and USB Serial remains
 * available to the Python runner. Commands are newline terminated:
 *   EXPECT RAMP <base> | EXPECT SHORT <slots> <base> | EXPECT CONST <value>
 *   START <settle_seconds> <measure_seconds> | STATUS | ABORT
 */
#include <DMXSerial.h>
#include <string.h>

#define COMMAND_BUFFER_SIZE 64
static uint8_t snapshot[DMXSERIAL_MAX + 1];
static char commandBuffer[COMMAND_BUFFER_SIZE];
static uint8_t commandLength = 0;
enum Expectation { EXPECT_RAMP, EXPECT_SHORT, EXPECT_CONST };
static Expectation expectation = EXPECT_RAMP;
static uint16_t expectedSlots = 512;
static uint8_t expectedBase = 0;
enum RecordState { RECORD_IDLE, RECORD_SETTLE, RECORD_MEASURE };
static RecordState recordState = RECORD_IDLE;
static unsigned long settleUntil = 0, measureUntil = 0, measureStart = 0;
static unsigned long checks = 0, passCount = 0, failCount = 0;

static bool matchesExpected(const uint8_t *frame) {
  for (uint16_t channel = 1; channel <= 512; ++channel) {
    uint8_t wanted;
    if (expectation == EXPECT_CONST) wanted = expectedBase;
    else if (expectation == EXPECT_SHORT && channel > expectedSlots) wanted = 0;
    else wanted = (uint8_t)(expectedBase + channel - 1);
    if (frame[channel] != wanted) return false;
  }
  return true;
}
static void resetMetrics(void) { checks = passCount = failCount = 0; }
static void emitResult(unsigned long now) {
  Serial.print("RESULT seconds="); Serial.print((now - measureStart) / 1000UL);
  Serial.print(" checks="); Serial.print(checks);
  Serial.print(" pass="); Serial.print(passCount);
  Serial.print(" fail="); Serial.print(failCount);
  Serial.print(" no_data="); Serial.print(DMXSerial.noDataSince()); Serial.println("ms");
  recordState = RECORD_IDLE;
}
static void processCommand(char *command, unsigned long now) {
  unsigned long a, b;
  if (sscanf(command, "EXPECT RAMP %lu", &a) == 1 && a <= 255) {
    expectation = EXPECT_RAMP; expectedBase = (uint8_t)a; expectedSlots = 512; Serial.println("ACK EXPECT");
  } else if (sscanf(command, "EXPECT SHORT %lu %lu", &a, &b) == 2 && a >= 1 && a <= 512 && b <= 255) {
    expectation = EXPECT_SHORT; expectedSlots = (uint16_t)a; expectedBase = (uint8_t)b; Serial.println("ACK EXPECT");
  } else if (sscanf(command, "EXPECT CONST %lu", &a) == 1 && a <= 255) {
    expectation = EXPECT_CONST; expectedBase = (uint8_t)a; Serial.println("ACK EXPECT");
  } else if (sscanf(command, "START %lu %lu", &a, &b) == 2 && b > 0) {
    resetMetrics(); settleUntil = now + a * 1000UL; measureUntil = settleUntil + b * 1000UL;
    recordState = a ? RECORD_SETTLE : RECORD_MEASURE; if (!a) measureStart = now; Serial.println("ACK START");
  } else if (!strcmp(command, "STATUS")) {
    Serial.print("STATUS state="); Serial.println((int)recordState);
  } else if (!strcmp(command, "ABORT")) {
    recordState = RECORD_IDLE; resetMetrics(); Serial.println("ACK ABORT");
  } else Serial.println("ERR COMMAND");
}
static void pollCommands(unsigned long now) {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') { if (commandLength) { commandBuffer[commandLength] = 0; processCommand(commandBuffer, now); commandLength = 0; } }
    else if (commandLength < COMMAND_BUFFER_SIZE - 1) commandBuffer[commandLength++] = ch;
    else commandLength = 0;
  }
}
void setup() {
  Serial.begin(115200); DMXSerial.init(DMXReceiver); DMXSerial.maxChannel(512);
  Serial.println("READY ENTTEC_DMX_MONITOR");
}
void loop() {
  const unsigned long now = millis(); pollCommands(now);
  if (recordState == RECORD_SETTLE && now >= settleUntil) { recordState = RECORD_MEASURE; measureStart = now; }
  if (recordState == RECORD_MEASURE && now >= measureUntil) emitResult(now);
  if (DMXSerial.packetReady() && recordState == RECORD_MEASURE) {
    memcpy(snapshot, DMXSerial.getBuffer(), sizeof(snapshot)); checks++;
    if (matchesExpected(snapshot)) passCount++; else failCount++;
  }
}
