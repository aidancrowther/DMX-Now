/*
 * Simple USB-controlled DMX controller for an Arduino Mega 2560.
 *
 * Wiring:
 *   Mega USART1 TX / pin 18 -> RS-485 driver DI
 *   Mega USB                -> host control serial at 115200 8N1
 *
 * Build with -DDMX_USE_PORT1 so DMXSerial uses USART1 for DMX output while
 * the USB Serial connection remains available for commands.
 *
 * Enter one command per line:
 *   <channel> <value>
 *
 * Examples:
 *   1 255       Set channel 1 to 255
 *   24 128      Set channel 24 to 128
 *   1 0         Turn channel 1 off
 *
 * Channels are 1-based and range from 1 through 512. Values range from 0
 * through 255. The complete universe is continuously transmitted and values
 * remain set until changed or the board is reset.
 */

#include <DMXSerial.h>
#include <stdio.h>
#include <string.h>

static const unsigned long USB_BAUD = 115200UL;
static const uint16_t MAX_CHANNEL = 512;
static const uint8_t COMMAND_BUFFER_SIZE = 32;

static char commandBuffer[COMMAND_BUFFER_SIZE];
static uint8_t commandLength = 0;

static void printHelp() {
  Serial.println(F("Commands: <channel 1-512> <value 0-255>"));
  Serial.println(F("Example: 1 255"));
  Serial.println(F("Other commands: help, clear, status"));
}

static void processCommand(char *command) {
  unsigned long channel;
  unsigned long value;

  if (!strcmp(command, "help")) {
    printHelp();
    return;
  }

  if (!strcmp(command, "clear")) {
    for (uint16_t index = 1; index <= MAX_CHANNEL; ++index) {
      DMXSerial.write(index, 0);
    }
    Serial.println(F("OK cleared"));
    return;
  }

  if (!strcmp(command, "status")) {
    Serial.println(F("OK transmitting 512 channels"));
    return;
  }

  if (sscanf(command, "%lu %lu", &channel, &value) == 2 &&
      channel >= 1 && channel <= MAX_CHANNEL && value <= 255) {
    DMXSerial.write((uint16_t)channel, (uint8_t)value);
    Serial.print(F("OK channel="));
    Serial.print(channel);
    Serial.print(F(" value="));
    Serial.println(value);
    return;
  }

  Serial.println(F("ERR use: <channel 1-512> <value 0-255>"));
}

static void pollCommands() {
  while (Serial.available() > 0) {
    const char character = (char)Serial.read();

    if (character == '\n' || character == '\r') {
      if (commandLength > 0) {
        commandBuffer[commandLength] = '\0';
        processCommand(commandBuffer);
        commandLength = 0;
      }
    } else if (commandLength < COMMAND_BUFFER_SIZE - 1) {
      commandBuffer[commandLength++] = character;
    } else {
      commandLength = 0;
      Serial.println(F("ERR command too long"));
    }
  }
}

void setup() {
  Serial.begin(USB_BAUD);
  DMXSerial.init(DMXController);
  DMXSerial.maxChannel(MAX_CHANNEL);

  Serial.println(F("READY MEGA_DMX_CONTROLLER"));
  Serial.println(F("DMX: USART1 TX pin 18, USB: 115200 8N1"));
  printHelp();
}

void loop() {
  pollCommands();
}