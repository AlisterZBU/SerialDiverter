```python
#!/usr/bin/env python3

"""
Linux serial port diverter

             1200 Bd                         9600 Bd
 Wine       /dev/ttyVCOM1                    /dev/ttyACM0
 COM1  <----------->  PTY  <------------->  Raspberry Pi Pico
              byte-paced                  real USB serial

The bridge is completely byte-transparent.

Pico disconnection is tolerated.  The virtual serial port remains
available and the program repeatedly attempts to reconnect to the Pico.

For 8N1 serial:

    1200 baud = 120 bytes/second
             = 8.333 ms per byte
"""

import os
import pty
import tty
import termios
import serial
import select
import time
import signal
import sys


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

PICO_PORT = "/dev/ttyACM0"
VIRTUAL_PORT = "/dev/ttyVCOM1"

PICO_BAUD = 9600
VIRTUAL_BAUD = 1200

# Serial framing: 1 start + 8 data + 1 stop = 10 bits/byte.
BITS_PER_BYTE = 10

BYTE_TIME = BITS_PER_BYTE / VIRTUAL_BAUD

READ_SIZE = 256

# Time between attempts to reconnect the Pico.
RECONNECT_INTERVAL = 2.0


# ---------------------------------------------------------------------
# Global objects
# ---------------------------------------------------------------------

master_fd = None
slave_fd = None
pico = None

next_wine_time = time.monotonic()
next_reconnect_time = 0


# ---------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------

def cleanup():

    global master_fd, slave_fd, pico

    print("\nStopping serial bridge...")

    if pico is not None:
        try:
            pico.close()
        except Exception:
            pass

    if master_fd is not None:
        try:
            os.close(master_fd)
        except Exception:
            pass

    if slave_fd is not None:
        try:
            os.close(slave_fd)
        except Exception:
            pass

    try:
        if os.path.islink(VIRTUAL_PORT):
            os.unlink(VIRTUAL_PORT)
    except Exception:
        pass


def signal_handler(signum, frame):

    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ---------------------------------------------------------------------
# Open Pico
# ---------------------------------------------------------------------

def connect_pico():

    global pico

    try:

        print("Opening", PICO_PORT)

        pico = serial.Serial(
            port=PICO_PORT,
            baudrate=PICO_BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0,
            write_timeout=0
        )

        print("Pico connected at", PICO_BAUD, "Bd")

        return True

    except (serial.SerialException, OSError) as e:

        print("Pico not available:", e)

        pico = None

        return False


# ---------------------------------------------------------------------
# Create virtual serial port
# ---------------------------------------------------------------------

master_fd, slave_fd = pty.openpty()

# Put slave side into raw mode.
#
# This is essential for byte transparency.  In particular, it prevents
# Linux from performing CR/LF processing, echoing, canonical buffering,
# signal generation, etc.

tty.setraw(slave_fd)

slave_name = os.ttyname(slave_fd)

print("PTY created:")
print("   ", slave_name)


# Remove an existing virtual-port link.

if os.path.lexists(VIRTUAL_PORT):
    os.unlink(VIRTUAL_PORT)


# Create stable name.

os.symlink(slave_name, VIRTUAL_PORT)

print("Virtual serial port:")
print("   ", VIRTUAL_PORT)


# ---------------------------------------------------------------------
# Connect to Pico
# ---------------------------------------------------------------------

connect_pico()

next_reconnect_time = time.monotonic() + RECONNECT_INTERVAL


# ---------------------------------------------------------------------
# Buffers
# ---------------------------------------------------------------------

# Bytes received from Pico and waiting to be sent to Wine.

to_wine = bytearray()


# Bytes received from Wine and waiting to be sent to Pico.

to_pico = bytearray()


# ---------------------------------------------------------------------
# Main bridge
# ---------------------------------------------------------------------

try:

    while True:

        now = time.monotonic()


        # =============================================================
        # Reconnect Pico if necessary
        # =============================================================

        if pico is None and now >= next_reconnect_time:

            if connect_pico():
                next_reconnect_time = now + RECONNECT_INTERVAL
            else:
                next_reconnect_time = now + RECONNECT_INTERVAL


        # =============================================================
        # Pico -> Wine
        #
        # Read whatever bytes are available from the Pico.
        # =============================================================

        if pico is not None:

            try:

                data = pico.read(READ_SIZE)

                if data:
                    to_wine.extend(data)

            except (serial.SerialException, OSError) as e:

                print("\nPico disconnected:", e)

                try:
                    pico.close()
                except Exception:
                    pass

                pico = None

                next_reconnect_time = time.monotonic()


        # =============================================================
        # Wine -> bridge
        #
        # Read bytes from the PTY without interpreting them.
        # =============================================================

        try:

            readable, _, _ = select.select(
                [master_fd],
                [],
                [],
                0
            )

            if master_fd in readable:

                data = os.read(master_fd, READ_SIZE)

                if data:
                    to_pico.extend(data)

        except OSError:

            print("\nPTY closed.")
            break


        # =============================================================
        # Wine -> Pico
        #
        # The actual USB serial hardware handles the 9600 Bd timing.
        # =============================================================

        if pico is not None and to_pico:

            try:

                written = pico.write(to_pico)

                if written:
                    del to_pico[:written]

            except (serial.SerialException, OSError) as e:

                print("\nPico write error:", e)

                try:
                    pico.close()
                except Exception:
                    pass

                pico = None

                next_reconnect_time = time.monotonic()


        # =============================================================
        # Pico -> Wine
        #
        # A PTY has no physical baud rate, so explicitly pace the
        # characters at the equivalent of 1200 Bd.
        #
        # 8N1:
        #
        #        10 bits / character
        #
        #        1200 / 10 = 120 characters/second
        #
        #        1 / 120 = 8.333 ms/character
        # =============================================================

        now = time.monotonic()

        if to_wine and now >= next_wine_time:

            try:

                # Send exactly one byte.
                os.write(master_fd, bytes((to_wine[0],)))

                del to_wine[0]

                next_wine_time += BYTE_TIME

                # If we have fallen behind, don't send a burst to catch
                # up.  That would defeat the purpose of the baud pacing.

                if next_wine_time < now:
                    next_wine_time = now + BYTE_TIME

            except OSError:

                print("\nUnable to write to PTY.")
                break


        # =============================================================
        # Prevent excessive CPU usage.
        # =============================================================

        time.sleep(0.0005)


finally:

    cleanup()
```
