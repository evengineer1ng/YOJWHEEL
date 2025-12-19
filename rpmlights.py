import socket
import time
import math
import board
import neopixel

# ==================================================
# CONFIG
# ==================================================
LED_COUNT = 16
GPIO_PIN = board.D18

BRIGHTNESS = 0.35
UDP_PORT = 5009

# Temporary shift point until we wire OptimalShiftRPM
SHIFT_POINT_PCT = 85

FPS_IDLE = 0.02     # ~50 FPS
FPS_FLASH = 0.05
FPS_REDLINE = 0.03

# ==================================================
# NEOPIXELS
# ==================================================
pixels = neopixel.NeoPixel(
    GPIO_PIN,
    LED_COUNT,
    brightness=BRIGHTNESS,
    auto_write=False,
    pixel_order=neopixel.GRB
)

pixels.fill((0, 0, 0))
pixels.show()

# ==================================================
# UDP SOCKET
# ==================================================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", UDP_PORT))
sock.setblocking(False)

print("=== RPM NeoPixel Listener (Pi 5 / PIO backend) ===")

# ==================================================
# STATE
# ==================================================
rpm_norm = 0.0
rpm_pct = 0
redline = False
last_packet = time.time()

# ==================================================
# HELPERS
# ==================================================
def all_off():
    pixels.fill((0, 0, 0))
    pixels.show()

def set_all(color):
    pixels.fill(color)
    pixels.show()

def redline_pulse(t, i, total):
    """
    Pulsating red gradient for redline
    """
    phase = math.sin(t * 6.0) * 0.5 + 0.5
    intensity = int(255 * phase * (i + 1) / total)
    return (intensity, 0, 0)

# ==================================================
# MAIN LOOP
# ==================================================
while True:
    # ----------------------------------------------
    # RECEIVE UDP
    # ----------------------------------------------
    try:
        data, _ = sock.recvfrom(16)
        if len(data) >= 3:
            rpm_norm = data[0] / 255.0
            redline = data[1] == 1
            rpm_pct = data[2]
            last_packet = time.time()
    except BlockingIOError:
        pass

    # ----------------------------------------------
    # FAILSAFE (no data)
    # ----------------------------------------------
    if time.time() - last_packet > 1.0:
        all_off()
        time.sleep(FPS_IDLE)
        continue

    # ----------------------------------------------
    # REDLINE MODE (pulsating gradient)
    # ----------------------------------------------
    if redline:
        t = time.time()
        for i in range(LED_COUNT):
            pixels[i] = redline_pulse(t, i, LED_COUNT)
        pixels.show()
        time.sleep(FPS_REDLINE)
        continue

    # ----------------------------------------------
    # SHIFT MODE (flash blue)
    # ----------------------------------------------
    if rpm_pct >= SHIFT_POINT_PCT:
        flash = (0, 0, 255) if math.sin(time.time() * 10.0) > 0 else (0, 0, 0)
        set_all(flash)
        time.sleep(FPS_FLASH)
        continue

    # ----------------------------------------------
    # NORMAL RPM BAR (solid red fill)
    # ----------------------------------------------
    lit = int(rpm_norm * LED_COUNT)
    lit = max(0, min(LED_COUNT, lit))

    for i in range(LED_COUNT):
        if i < lit:
            pixels[i] = (255, 0, 0)
        else:
            pixels[i] = (0, 0, 0)

    pixels.show()
    time.sleep(FPS_IDLE)
