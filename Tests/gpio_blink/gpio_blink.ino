/**
 * Standalone ESP8266 GPIO blink test.
 *
 * This intentionally does not initialize Wi-Fi, QuickESPNow, Serial, espDMX,
 * or any DMX hardware. It only drives GPIO1 and GPIO2 so onboard LED wiring
 * and basic pin access can be checked independently of the receiver firmware.
 *
 * Both pins change state together every 500 ms. The resulting full blink cycle
 * is one second. Since ESP-01 and ESP-01S LED circuits can use different
 * polarity/configuration, observe whether either onboard LED changes state;
 * the test does not assume active-high or active-low LED wiring.
 */

#include <Arduino.h>

static const uint8_t PIN_GPIO1 = 1;
static const uint8_t PIN_GPIO2 = 2;
static const unsigned long BLINK_HALF_PERIOD_MS = 500UL;

void setup() {
    pinMode(PIN_GPIO1, OUTPUT);
    pinMode(PIN_GPIO2, OUTPUT);
    digitalWrite(PIN_GPIO1, LOW);
    digitalWrite(PIN_GPIO2, LOW);
}

void loop() {
    static bool level = false;
    static unsigned long nextChange = 0;
    const unsigned long now = millis();

    if ((long)(now - nextChange) >= 0) {
        level = !level;
        digitalWrite(PIN_GPIO1, level ? HIGH : LOW);
        digitalWrite(PIN_GPIO2, level ? HIGH : LOW);
        nextChange = now + BLINK_HALF_PERIOD_MS;
    }
    yield();
}