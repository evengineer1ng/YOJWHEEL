# ==========================
# PATCHED HYBRID LED SYSTEM
# CHUNK 1 — CORE SYSTEM & PRIORITY ENGINE
# ==========================
import psutil
import os
import time
import random
import math
import threading
from queue import Queue
from pynput import keyboard, mouse
from rpi_ws281x import PixelStrip, Color
strip_lock = threading.Lock()

def hard_clear(strip):
    """Hard wipe the strip to fully off with thread safety."""
    with strip_lock:
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()

# ==========================
# LED STRIP CONFIG
# ==========================

# ==========================
# LED STRIP CONFIG — PI 5 SPI MODE
# ==========================

LED_COUNT = 10
LED_BRIGHTNESS = 100

# SPI configuration (Raspberry Pi 5 compatible)
LED_SPI_BUS = 0        # SPI bus 0
LED_SPI_DEVICE = 0     # CE0
LED_SPI_SPEED_HZ = 8000000  # 8 MHz (safe for WS2812 via SPI)

strip = PixelStrip(
    LED_COUNT,
    0,                          # GPIO pin not used in SPI mode
    brightness=LED_BRIGHTNESS,
    strip_type=None,            # auto-detect (WS2812 / NeoPixel)
    bus=LED_SPI_BUS,
    device=LED_SPI_DEVICE,
    spi_speed_hz=LED_SPI_SPEED_HZ
)

strip.begin()


# ==========================
# PRIORITY MODEL (Protected Micro Layer)
# ==========================

# Micro layer = key pulses, ripples, mouse follow
# Mid layer = animation 001-100
# High layer = system transitions, idle resets

PRIORITY_MICRO = 0
PRIORITY_MID = 1
PRIORITY_HIGH = 2
CAPS_LED_INDEX = LED_COUNT - 1  # use rightmost LED
caps_lock_active = False
caps_thread = None

# Global control state
current_priority = PRIORITY_MICRO

priority_lock = threading.Lock()
mid_layer_lock = threading.Lock()
high_layer_lock = threading.Lock()

interrupt_flag = False

def interrupt_all():
    global interrupt_flag
    interrupt_flag = True

def clear_interrupt():
    global interrupt_flag
    interrupt_flag = False

# ==========================
# WRAPPERS FOR SAFE EXECUTION
# ==========================

def run_micro(anim_func, *args):
    """Micro animations never interrupt or block anything."""
    def wrapper():
        try:
            anim_func(*args)
        except:
            pass
    threading.Thread(target=wrapper, daemon=True).start()

def run_mid(anim_func, *args):
    """Mid-level animations interrupt each other but not micro or high."""
    def wrapper():
        global current_priority
        with priority_lock:
            if current_priority > PRIORITY_MID:
                return
            current_priority = PRIORITY_MID

        interrupt_all()
        time.sleep(0.01)
        clear_interrupt()

        with mid_layer_lock:
            try:
                anim_func(*args)
            except:
                pass

        with priority_lock:
            current_priority = PRIORITY_MICRO

    threading.Thread(target=wrapper, daemon=True).start()

def run_high(anim_func, *args):
    """High-priority system events override everything."""
    def wrapper():
        global current_priority
        with priority_lock:
            current_priority = PRIORITY_HIGH

        interrupt_all()
        time.sleep(0.02)
        clear_interrupt()

        with high_layer_lock:
            try:
                anim_func(*args)
            except:
                pass

        with priority_lock:
            current_priority = PRIORITY_MICRO

    threading.Thread(target=wrapper, daemon=True).start()

# ==========================
# BASIC LED HELPERS
# ==========================

def clear(strip):
    for i in range(LED_COUNT):
        strip.setPixelColor(i, 0)
    strip.show()

def fade_all(strip, factor=0.8, cutoff=4):
    for i in range(LED_COUNT):
        col = strip.getPixelColor(i)
        r = (col >> 16) & 255
        g = (col >> 8) & 255
        b = col & 255

        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)

        # 🔥 NEW — hard zero small values
        if r < cutoff: r = 0
        if g < cutoff: g = 0
        if b < cutoff: b = 0

        strip.setPixelColor(i, Color(r, g, b))
    strip.show()
# =====================================================
# SAFE SET PIXEL (telemetry-aware)
# =====================================================
from shared_state import telemetry_present

def safe_led_set(i, color):
    """Only draw if telemetry mode is NOT active."""
    if telemetry_present:
        return  # telemetry owns LEDs, block engine writes
    try:
        strip.setPixelColor(i, color)
    except:
        pass


# ==========================
# CHUNK 2 — COLOR ENGINE + KEY/LED MAPPING
# ==========================
JOYSTICK_BUTTON_COLORS = {
    "A":   (255, 60, 60),
    "B":   (255, 120, 0),
    "X":   (60, 160, 255),
    "Y":   (0, 255, 120),

    "L":   (160, 80, 255),
    "R":   (255, 80, 220),
    "ZL":  (120, 40, 255),
    "ZR":  (255, 40, 180),

    "SL":  (0, 200, 255),
    "SR":  (0, 255, 200),

    "PLUS":      (255, 255, 255),
    "MINUS":     (200, 200, 200),
    "HOME":      (0, 180, 255),
    "CAPTURE":   (255, 0, 120),

    "BTN_SOUTH": (255, 0, 0),
    "BTN_EAST":  (0, 255, 0),
    "BTN_WEST":  (0, 0, 255),
    "BTN_NORTH": (255, 255, 0),
    "BTN_TL":    (255, 128, 0),
    "BTN_TR":    (128, 0, 255),
    "BTN_SELECT": (0, 255, 255),
    "BTN_START":  (255, 0, 255),

}
JOYCON_BUTTON_MAP = {
    0: "Y",
    1: "X",
    2: "B",
    3: "A",
    4: "L",
    5: "R",
    6: "ZL",
    7: "ZR",
    8: "MINUS",
    9: "PLUS",
    10: "L_STICK",
    11: "R_STICK",
    12: "HOME",
    13: "CAPTURE",
    14: "SL",
    15: "SR",
}

# Keyboard row color groupings (harmonized version)
ROW_COLORS = {
    "top": Color(200, 50, 50),      # numbers row
    "q_row": Color(50, 200, 50),    # QWERTY row
    "a_row": Color(50, 50, 200),    # ASDF row
    "z_row": Color(200, 200, 50),   # ZXCV row
    "special": Color(180, 80, 180)  # space/enter/shifts/etc.
}

# A unified 10‑LED linear mapping.
# Your original file had many conflicting maps; this is the stable merged one.
COLUMN_MAP = {
    "1": 0, "2": 1, "3": 2, "4": 3, "5": 4,
    "6": 5, "7": 6, "8": 7, "9": 8, "0": 9,

    "q": 0, "w": 1, "e": 2, "r": 3, "t": 4,
    "y": 5, "u": 6, "i": 7, "o": 8, "p": 9,

    "a": 0, "s": 1, "d": 2, "f": 3, "g": 4,
    "h": 5, "j": 6, "k": 7, "l": 8, ";": 9,

    "z": 0, "x": 1, "c": 2, "v": 3, "b": 4,
    "n": 5, "m": 6, ",": 7, ".": 8, "/": 9,

    " ": 4,
    "enter": 9,
    "tab": 0,
    "backspace": 9,
    "delete": 9,
    "shift": 0,
    "ctrl": 0,
    "alt": 1
}

def key_to_led_index(key):
    key = str(key).lower()
    return COLUMN_MAP.get(key, None)
LED_TO_KEY = {}

# build reverse map from your existing key → LED logic
for key in COLUMN_MAP.keys():
    try:
        idx = key_to_led_index(key)
        LED_TO_KEY[idx] = key
    except:
        pass

# ==========================
# COLOR RESOLUTION ENGINE
# ==========================

def key_to_color(key):
    k = str(key).lower()

    top = "1234567890"
    qrow = "qwertyuiop"
    arow = "asdfghjkl;"
    zrow = "zxcvbnm,./"

    if k in top:   return ROW_COLORS["top"]
    if k in qrow:  return ROW_COLORS["q_row"]
    if k in arow:  return ROW_COLORS["a_row"]
    if k in zrow:  return ROW_COLORS["z_row"]

    return ROW_COLORS["special"]

# Wheel function preserved
def wheel(pos):
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)



# ==========================
# CHUNK 3 — MICRO-REACTIVE ANIMATIONS
# (Protected Micro Layer)
# ==========================
def caps_indicator_loop():
    """Soft pulsing indicator on a single LED while Caps Lock is active."""
    global caps_lock_active

    phase = 0.0
    base = 40    # base brightness
    amp = 40     # pulse amplitude

    while caps_lock_active:
        level = base + int(amp * (0.5 + 0.5 * math.sin(phase)))
        phase += 0.25

        with strip_lock:
            strip.setPixelColor(CAPS_LED_INDEX, Color(level, level, level))
            strip.show()

        time.sleep(0.05)

    # turn off when caps is no longer active
    with strip_lock:
        strip.setPixelColor(CAPS_LED_INDEX, Color(0, 0, 0))
        strip.show()
def toggle_caps_indicator():
    global caps_lock_active, caps_thread

    caps_lock_active = not caps_lock_active

    if caps_lock_active:
        # start loop if not already running
        if caps_thread is None or not caps_thread.is_alive():
            caps_thread = threading.Thread(
                target=caps_indicator_loop,
                daemon=True
            )
            caps_thread.start()

import threading
def anim_keypress(strip):
    global last_key_index, last_key_color
    if last_key_index is None:
        return
    strip.setPixelColor(last_key_index, last_key_color)
    strip.show()
    time.sleep(0.02)

# ----------------------------------
# Soft Pulse (single-key micro effect)
# ----------------------------------
def soft_pulse(strip, idx, color):
    r = (color >> 16) & 255
    g = (color >> 8) & 255
    b = color & 255

    for i in range(3):
        strip.setPixelColor(idx, Color(r//4, g//4, b//4))
        strip.show()
        time.sleep(0.03)
        strip.setPixelColor(idx, Color(r, g, b))
        strip.show()
        time.sleep(0.03)
    fade_all(strip, factor=0.6)


# ----------------------------------
# Soft Ripple (centered ripple)
# ----------------------------------
def soft_ripple(strip, center_idx, base_color, spread=3, duration=0.03):
    r = (base_color >> 16) & 255
    g = (base_color >> 8) & 255
    b = base_color & 255

    for radius in range(spread):
        for i in range(LED_COUNT):
            if abs(i - center_idx) == radius:
                strip.setPixelColor(i, Color(r, g, b))
        strip.show()
        time.sleep(duration)
        fade_all(strip, 0.75)

# ----------------------------------
# Soft Spark (random micro sparkles)
# ----------------------------------
def soft_spark(strip, idx, color):
    """Small spark at a specific LED and color."""
    # Fallback if idx somehow out of range
    if idx is None or not (0 <= idx < LED_COUNT):
        idx = random.randint(0, LED_COUNT - 1)

    strip.setPixelColor(idx, color)
    strip.show()
    time.sleep(0.02)
    fade_all(strip)
	

# ----------------------------------
# Scroll Animations (Up / Down flick)
# ----------------------------------
def scroll_up_anim(strip):
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(60, 90, 10))
    strip.show()
    time.sleep(0.05)
    fade_all(strip)

def scroll_down_anim(strip):
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(10, 20, 120))
    strip.show()
    time.sleep(0.05)
    fade_all(strip)

# ----------------------------------
# Mouse Click Pulse (flash effect)
# ----------------------------------
def mouse_click_pulse(strip):
    for i in range(LED_COUNT):
        strip.setPixelColor(i, Color(120, 40, 20))
    strip.show()
    time.sleep(0.05)
    fade_all(strip)

# ----------------------------------
# Mouse Follow Glow (gold trail)
# ----------------------------------
mouse_led_index = 0
last_mouse_x = None

def update_mouse_led():
    global mouse_led_index

    idle = (time.time() - last_mouse_move_time) > 0.12

    # If idle → clear and STOP DRAWING ANYTHING
    if idle:
        hard_clear(strip)
        return

    # If NOT idle → draw the moving glow
    for i in range(LED_COUNT):
        col = strip.getPixelColor(i)
        r = int(((col >> 16) & 255) * 0.35)
        g = int(((col >> 8) & 255) * 0.5)
        b = int((col & 255) * 0.5)
        strip.setPixelColor(i, Color(r, g, b))

    # gold highlight
    strip.setPixelColor(mouse_led_index, Color(200, 150, 60))

    left = (mouse_led_index - 1) % LED_COUNT
    right = (mouse_led_index + 1) % LED_COUNT

    strip.setPixelColor(left, Color(80, 40, 10))
    strip.setPixelColor(right, Color(80, 40, 10))

    strip.show()

# ----------------------------------
# SPECIAL KEY MICRO ANIMATIONS
# ----------------------------------

SPECIAL_ANIMS = {}

def register_special_anim(key, func):
    SPECIAL_ANIMS[key] = func

# Assign later after full animation set is loaded

# --- NEXT CHUNK PLACEHOLDER ---



    


# =====================================================================
# CHUNK 4 — MID‑LAYER ANIMATIONS (001–020)
# Fully Patched with:
#   • interrupt_flag support
#   • early‑exit checks
#   • non‑blocking design
#   • performance‑safe timing
# =====================================================================

# 001 — Ember Pulse
def anim_001_ember_pulse(strip):
    for intensity in range(0, 200, 5):
        if interrupt_flag: return
        col = Color(intensity, intensity//4, 0)
        for i in range(LED_COUNT): strip.setPixelColor(i, col)
        strip.show(); time.sleep(0.02)
    for intensity in range(200, -1, -5):
        if interrupt_flag: return
        col = Color(intensity, intensity//4, 0)
        for i in range(LED_COUNT): strip.setPixelColor(i, col)
        strip.show(); time.sleep(0.02)

# 002 — Ice Sweep
def anim_002_ice_sweep(strip):
    for pos in range(LED_COUNT):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(pos, Color(0,140,255))
        strip.show(); time.sleep(0.03)

# 003 — Sparkle Rain
def anim_003_sparkle_rain(strip):
    for _ in range(30):
        if interrupt_flag: return
        i = random.randint(0,9)
        strip.setPixelColor(i, Color(255,255,255))
        strip.show(); time.sleep(0.03)
        strip.setPixelColor(i,0)

# 004 — Lava Flow
def anim_004_lava_flow(strip):
    colors = [Color(255,0,0), Color(255,80,0), Color(255,200,0)]
    for pos in range(LED_COUNT):
        if interrupt_flag: return
        clear(strip)
        for j,c in enumerate(colors):
            if pos+j < LED_COUNT: strip.setPixelColor(pos+j,c)
        strip.show(); time.sleep(0.04)

# 005 — Neon Bounce
def anim_005_neon_bounce(strip):
    col = Color(0,255,180)
    for i in range(LED_COUNT):
        if interrupt_flag: return
        strip.setPixelColor(i,col); strip.show(); time.sleep(0.04)
        strip.setPixelColor(i,0)
    for i in reversed(range(LED_COUNT)):
        if interrupt_flag: return
        strip.setPixelColor(i,col); strip.show(); time.sleep(0.04)
        strip.setPixelColor(i,0)

# 006 — Sunrise Fade
def anim_006_sunrise(strip):
    for i in range(255):
        if interrupt_flag: return
        col = Color(i, i//4, 0)
        for p in range(LED_COUNT): strip.setPixelColor(p,col)
        strip.show(); time.sleep(0.01)

# 007 — Cylon Scanner
def anim_007_cylon(strip):
    col = Color(255,0,0)
    for i in range(LED_COUNT):
        if interrupt_flag: return
        strip.setPixelColor(i,col); strip.show(); time.sleep(0.02)
        strip.setPixelColor(i,0)
    for i in range(LED_COUNT-1,-1,-1):
        if interrupt_flag: return
        strip.setPixelColor(i,col); strip.show(); time.sleep(0.02)
        strip.setPixelColor(i,0)

# 008 — Flicker Flame
def anim_008_flicker_flame(strip):
    for _ in range(40):
        if interrupt_flag: return
        for i in range(LED_COUNT):
            v=random.randint(100,255)
            strip.setPixelColor(i, Color(v,v//3,0))
        strip.show(); time.sleep(0.03)

# 009 — Ocean Tide
def anim_009_ocean_tide(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col = Color(0,b,255)
        for i in range(LED_COUNT): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-5):
        if interrupt_flag: return
        col = Color(0,b,255)
        for i in range(LED_COUNT): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

# 010 — Rainbow March
def anim_010_rainbow_march(strip):
    for shift in range(255):
        if interrupt_flag: return
        for i in range(LED_COUNT):
            strip.setPixelColor(i, wheel((i*25+shift)%255))
        strip.show(); time.sleep(0.02)

# 011 — Meteor Trail
def anim_011_meteor(strip):
    tail=[255,150,80,30,5]
    for head in range(LED_COUNT):
        if interrupt_flag: return
        clear(strip)
        for t,v in enumerate(tail):
            pos=head-t
            if 0 <= pos < LED_COUNT:
                strip.setPixelColor(pos, Color(v,v,v))
        strip.show(); time.sleep(0.03)

# 012 — Heartbeat
def anim_012_heartbeat(strip):
    for k in [255,0,255,0]:
        if interrupt_flag: return
        for i in range(LED_COUNT):
            strip.setPixelColor(i,Color(k,0,0))
        strip.show(); time.sleep(0.08)

# 013 — Comet Whip
def anim_013_comet(strip):
    for head in range(LED_COUNT):
        if interrupt_flag: return
        for i in range(LED_COUNT):
            brightness=max(0,255-(abs(i-head)*60))
            strip.setPixelColor(i,Color(brightness,brightness,brightness))
        strip.show(); time.sleep(0.03)

# 014 — Prism Flicker
def anim_014_prism(strip):
    for _ in range(40):
        if interrupt_flag: return
        for i in range(LED_COUNT):
            strip.setPixelColor(i, Color(
                random.randint(80,255),
                random.randint(80,255),
                random.randint(80,255),
            ))
        strip.show(); time.sleep(0.04)

# 015 — Fill Left to Right
def anim_015_fill(strip):
    col=Color(0,180,255)
    for i in range(LED_COUNT):
        if interrupt_flag: return
        strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.05)

# 016 — Shockwave
def anim_016_shockwave(strip):
    center=4
    col=Color(255,255,255)
    for dist in range(0,LED_COUNT):
        if interrupt_flag: return
        clear(strip)
        for i in range(LED_COUNT):
            if abs(i-center)==dist:
                strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.03)

# 017 — Diamond Pulse
def anim_017_diamond(strip):
    for d in range(5):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(4-d,Color(255,0,255))
        strip.setPixelColor(5+d,Color(255,0,255))
        strip.show(); time.sleep(0.04)
    for d in reversed(range(5)):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(4-d,Color(255,0,255))
        strip.setPixelColor(5+d,Color(255,0,255))
        strip.show(); time.sleep(0.04)

# 018 — Dual Runners
def anim_018_dual_runners(strip):
    for t in range(LED_COUNT):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(t, Color(255,0,0))
        strip.setPixelColor(9-t, Color(0,0,255))
        strip.show(); time.sleep(0.03)

# 019 — Snake Segments
def anim_019_snake(strip):
    for head in range(LED_COUNT):
        if interrupt_flag: return
        clear(strip)
        for seg in range(4):
            pos=head-seg
            if 0<=pos<LED_COUNT:
                strip.setPixelColor(pos, Color(0,255//(seg+1),0))
        strip.show(); time.sleep(0.04)

# 020 — Neon Flicker
def anim_020_neon_flicker(strip):
    for _ in range(25):
        if interrupt_flag: return
        v=random.randint(120,255)
        col=Color(0,v,255)
        for i in range(LED_COUNT): strip.setPixelColor(i,col)
        strip.show(); time.sleep(random.uniform(0.01,0.05))


# =====================================================================

# (Real patched animations will be inserted in the next step)
# =====================================================================


# =====================================================================
# CHUNK 5 — MID-LAYER ANIMATIONS (021–040) — REAL PATCHED VERSIONS
# Fully interrupt-safe + mid-layer compliant
# =====================================================================

def anim_021_firefly(strip):
    for _ in range(40):
        if interrupt_flag: return
        i=random.randint(0,9)
        strip.setPixelColor(i,Color(255,255,150))
        strip.show(); time.sleep(0.04)
        strip.setPixelColor(i,0)

def anim_022_blue_strobe(strip):
    for _ in range(6):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,Color(0,0,255))
        strip.show(); time.sleep(0.05)
        clear(strip); time.sleep(0.05)

def anim_023_ember_trail(strip):
    for pos in range(10):
        if interrupt_flag: return
        for i in range(10):
            val=max(0,255-(abs(i-pos)*60))
            strip.setPixelColor(i,Color(val,val//4,0))
        strip.show(); time.sleep(0.04)

def anim_024_candy_cane(strip):
    for pos in range(10):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i, Color(255,0,0) if (i+pos)%2==0 else Color(255,255,255))
        strip.show(); time.sleep(0.05)

def anim_025_pastel_drift(strip):
    for shift in range(100):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i,Color(
                150+(i*10)%100,
                150+(shift*3)%100,
                200
            ))
        strip.show(); time.sleep(0.03)

def anim_026_binary(strip):
    for _ in range(10):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,Color(255,255,255))
        strip.show(); time.sleep(0.1)
        clear(strip); time.sleep(0.1)

def anim_027_purple_mist(strip):
    for b in range(0,200,5):
        if interrupt_flag: return
        col=Color(b//2,0,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(200,-1,-5):
        if interrupt_flag: return
        col=Color(b//2,0,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_028_pixel_chase(strip):
    col=Color(255,255,0)
    for i in range(20):
        if interrupt_flag: return
        idx=i%10
        clear(strip)
        strip.setPixelColor(idx,col)
        strip.show(); time.sleep(0.05)

def anim_029_rev_chase(strip):
    col=Color(0,255,200)
    for i in range(20):
        if interrupt_flag: return
        idx=9-(i%10)
        clear(strip)
        strip.setPixelColor(idx,col)
        strip.show(); time.sleep(0.05)

def anim_030_soft_wave(strip):
    for shift in range(30):
        if interrupt_flag: return
        for i in range(10):
            level=int((1+math.sin((i+shift)/2))*120)
            strip.setPixelColor(i,Color(0,level,255))
        strip.show(); time.sleep(0.04)

def anim_031_fire_pulse(strip):
    for b in range(0,255,8):
        if interrupt_flag: return
        col=Color(255,b//2,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-8):
        if interrupt_flag: return
        col=Color(255,b//2,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_032_static(strip):
    for _ in range(40):
        if interrupt_flag: return
        for i in range(10):
            v=random.randint(0,255)
            strip.setPixelColor(i,Color(v,v,v))
        strip.show(); time.sleep(0.03)

def anim_033_triple_sweep(strip):
    for pos in range(10):
        if interrupt_flag: return
        clear(strip)
        for off in (0,2,4):
            if pos+off<10: strip.setPixelColor(pos+off,Color(255,0,200))
        strip.show(); time.sleep(0.04)

def anim_034_red_pulse(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col=Color(b,0,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-5):
        if interrupt_flag: return
        col=Color(b,0,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_035_spark_fountain(strip):
    for pos in range(10):
        if interrupt_flag: return
        clear(strip)
        for i in range(pos+1):
            strip.setPixelColor(i,Color(255,i*20,0))
        strip.show(); time.sleep(0.04)

def anim_036_rain(strip):
    for step in range(20):
        if interrupt_flag: return
        for i in range(10):
            if random.random()>0.8:
                strip.setPixelColor(i,Color(150,150,255))
            else:
                strip.setPixelColor(i,0)
        strip.show(); time.sleep(0.05)

def anim_037_laser(strip):
    for pos in range(10):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(pos,Color(255,0,50))
        strip.setPixelColor(min(9,pos+1),Color(150,0,30))
        strip.setPixelColor(min(9,pos+2),Color(80,0,20))
        strip.show(); time.sleep(0.03)

def anim_038_glow_blue(strip):
    for b in range(0,255,6):
        if interrupt_flag: return
        col=Color(0,b,255)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-6):
        if interrupt_flag: return
        col=Color(0,b,255)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_039_chaos(strip):
    for _ in range(50):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i,Color(
                random.randint(0,255),
                random.randint(0,255),
                random.randint(0,255)
            ))
        strip.show(); time.sleep(0.02)

def anim_040_horizon(strip):
    for pos in range(10):
        if interrupt_flag: return
        for i in range(10):
            d=abs(i-pos)
            strip.setPixelColor(i,Color(max(0,150-d*40),100,255))
        strip.show(); time.sleep(0.03)


# =====================================================================

# (Real patched animations will be inserted when requested)
# =====================================================================


# =====================================================================
# CHUNK 6 — MID-LAYER ANIMATIONS (041–060) — REAL PATCHED VERSIONS
# Fully interrupt-safe + mid-layer compliant
# =====================================================================

def anim_041_gold_wave(strip):
    for shift in range(40):
        if interrupt_flag: return
        for i in range(10):
            level = int((1 + math.sin((i + shift)/2)) * 120)
            strip.setPixelColor(i, Color(255, 200, level//2))
        strip.show(); time.sleep(0.04)

def anim_042_ripple_center(strip):
    center = 4
    for r in range(6):
        if interrupt_flag: return
        clear(strip)
        for i in range(10):
            if abs(i-center) == r:
                strip.setPixelColor(i, Color(0, 180, 255))
        strip.show(); time.sleep(0.05)

def anim_043_scan_blue(strip):
    col = Color(0, 150, 255)
    for i in range(10):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.04)

def anim_044_scan_green(strip):
    col = Color(0, 255, 150)
    for i in range(10):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.04)

def anim_045_magenta_burst(strip):
    for r in range(255, 0, -10):
        if interrupt_flag: return
        col = Color(r, 0, r)
        for i in range(10): strip.setPixelColor(i, col)
        strip.show(); time.sleep(0.02)

def anim_046_dual_snake(strip):
    for pos in range(10):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(pos, Color(255, 50, 0))
        strip.setPixelColor(9-pos, Color(0, 255, 50))
        strip.show(); time.sleep(0.04)

def anim_047_frost(strip):
    for b in range(0,255,6):
        if interrupt_flag: return
        col = Color(150, 200, b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_048_glitter(strip):
    for _ in range(50):
        if interrupt_flag: return
        i = random.randint(0,9)
        strip.setPixelColor(i, Color(255,255,255))
        strip.show(); time.sleep(0.02)
        strip.setPixelColor(i,0)

def anim_049_sandstorm(strip):
    for _ in range(40):
        if interrupt_flag: return
        for i in range(10):
            v=random.randint(100,180)
            strip.setPixelColor(i,Color(v,v//2,0))
        strip.show(); time.sleep(0.03)

def anim_050_dragonfire(strip):
    for step in range(10):
        if interrupt_flag: return
        for i in range(10):
            level=255-(abs(i-step)*40)
            strip.setPixelColor(i,Color(level, level//3, 0))
        strip.show(); time.sleep(0.04)

def anim_051_wave_dual(strip):
    for shift in range(40):
        if interrupt_flag: return
        for i in range(10):
            val = int((1+math.sin((i+shift)/3))*120)
            strip.setPixelColor(i,Color(val,0,val))
        strip.show(); time.sleep(0.04)

def anim_052_static_blue(strip):
    col=Color(0,100,255)
    for _ in range(20):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.03)

def anim_053_spark_blue(strip):
    for _ in range(40):
        if interrupt_flag: return
        i=random.randint(0,9)
        strip.setPixelColor(i,Color(100,200,255))
        strip.show(); time.sleep(0.03)
        strip.setPixelColor(i,0)

def anim_054_pulse_yellow(strip):
    for b in range(0,255,6):
        if interrupt_flag: return
        col=Color(255,b,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-6):
        if interrupt_flag: return
        col=Color(255,b,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_055_centerflare(strip):
    center=4
    for r in range(6):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(center, Color(255,255,255))
        if center-r >= 0: strip.setPixelColor(center-r, Color(100,100,100))
        if center+r < 10: strip.setPixelColor(center+r, Color(100,100,100))
        strip.show(); time.sleep(0.04)

def anim_056_matrix(strip):
    for _ in range(30):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i,Color(0, random.randint(150,255), 0))
        strip.show(); time.sleep(0.03)

def anim_057_rainbow_soft(strip):
    for shift in range(80):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i, wheel((shift*3 + i*20) % 255))
        strip.show(); time.sleep(0.03)

def anim_058_shimmer(strip):
    for _ in range(50):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i, Color(
                random.randint(150,255),
                random.randint(150,255),
                random.randint(150,255)
            ))
        strip.show(); time.sleep(0.02)

def anim_059_breath_cyan(strip):
    for b in range(0,255,4):
        if interrupt_flag: return
        col=Color(0,255,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-4):
        if interrupt_flag: return
        col=Color(0,255,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_060_zigzag(strip):
    for step in range(20):
        if interrupt_flag: return
        for i in range(10):
            col = Color(255,0,100) if (i+step)%2==0 else Color(0,0,0)
            strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.04)


# =====================================================================

# (Real patched animations will be inserted when requested)
# =====================================================================


# =====================================================================
# CHUNK 7 — MID-LAYER ANIMATIONS (061–080) — REAL PATCHED VERSIONS
# Fully interrupt-safe + mid-layer compliant
# =====================================================================

def anim_061_bloom(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col = Color(b, b//2, 255)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_062_hotcore(strip):
    for t in range(20):
        if interrupt_flag: return
        for i in range(10):
            val = max(0,255 - abs(i-4)*50)
            strip.setPixelColor(i,Color(val,val//3,0))
        strip.show(); time.sleep(0.04)

def anim_063_orbit(strip):
    col = Color(255,120,0)
    for t in range(20):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(t%10,col)
        strip.setPixelColor((t+5)%10,Color(100,40,0))
        strip.show(); time.sleep(0.04)

def anim_064_rainbow_fade(strip):
    for shift in range(100):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i, wheel((shift+i*15)%255))
        strip.show(); time.sleep(0.03)

def anim_065_soft_green(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col = Color(0,255,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_066_soft_red(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col = Color(255,b,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_067_meteor_blue(strip):
    for head in range(10):
        if interrupt_flag: return
        for i in range(10):
            v = max(0,255 - abs(i-head)*80)
            strip.setPixelColor(i,Color(0,0,v))
        strip.show(); time.sleep(0.04)

def anim_068_soft_hue(strip):
    for shift in range(60):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i, wheel((shift*4 + i*10) % 255))
        strip.show(); time.sleep(0.03)

def anim_069_flicker_white(strip):
    for _ in range(30):
        if interrupt_flag: return
        for i in range(10):
            v=random.randint(80,255)
            strip.setPixelColor(i,Color(v,v,v))
        strip.show(); time.sleep(0.02)

def anim_070_dual_comet(strip):
    for head in range(10):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(head,Color(255,40,0))
        strip.setPixelColor(9-head,Color(0,40,255))
        strip.show(); time.sleep(0.04)

def anim_071_hyperpulse(strip):
    for step in range(20):
        if interrupt_flag: return
        level=int((1+math.sin(step/2))*255)
        col=Color(level,0,level)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.03)

def anim_072_static_gold(strip):
    col=Color(255,180,40)
    for _ in range(20):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.03)

def anim_073_pulse_teal(strip):
    for b in range(0,255,6):
        if interrupt_flag: return
        col = Color(0,b,180)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-6):
        if interrupt_flag: return
        col = Color(0,b,180)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_074_wave_red(strip):
    for shift in range(40):
        if interrupt_flag: return
        for i in range(10):
            val=int((1+math.sin((i+shift)/2))*120)
            strip.setPixelColor(i,Color(255,val,0))
        strip.show(); time.sleep(0.03)

def anim_075_glow_orange(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col=Color(255,b//2,0)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_076_rain_purple(strip):
    for _ in range(30):
        if interrupt_flag: return
        for i in range(10):
            if random.random()>0.8:
                strip.setPixelColor(i,Color(180,0,255))
            else:
                strip.setPixelColor(i,0)
        strip.show(); time.sleep(0.04)

def anim_077_soft_matrix(strip):
    for _ in range(30):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i,Color(0,random.randint(80,255),0))
        strip.show(); time.sleep(0.03)

def anim_078_lime_flash(strip):
    for _ in range(6):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,Color(100,255,50))
        strip.show(); time.sleep(0.05)
        clear(strip); time.sleep(0.05)

def anim_079_drift(strip):
    for shift in range(50):
        if interrupt_flag: return
        for i in range(10):
            val=(shift+i*8)%255
            strip.setPixelColor(i,Color(val//2,val,255))
        strip.show(); time.sleep(0.03)

def anim_080_energy(strip):
    for step in range(30):
        if interrupt_flag: return
        for i in range(10):
            v=max(0,255-abs(i-step%10)*30)
            strip.setPixelColor(i,Color(v,0,255))
        strip.show(); time.sleep(0.03)


# =====================================================================

# (Real patched animations will be inserted when requested)
# =====================================================================


# =====================================================================
# CHUNK 8 — MID-LAYER ANIMATIONS (081–100) — REAL PATCHED VERSIONS
# Fully interrupt-safe + mid-layer compliant
# =====================================================================

def anim_081_plasma(strip):
    for t in range(60):
        if interrupt_flag: return
        for i in range(10):
            v = int((1 + math.sin((i+t)/2)) * 120)
            strip.setPixelColor(i, Color(v, 0, 255 - v))
        strip.show(); time.sleep(0.03)

def anim_082_hearth_glow(strip):
    for b in range(0,255,4):
        if interrupt_flag: return
        col = Color(255, b//3, b//6)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_083_confetti(strip):
    for _ in range(60):
        if interrupt_flag: return
        i = random.randint(0,9)
        strip.setPixelColor(i, wheel(random.randint(0,255)))
        strip.show(); time.sleep(0.02)
        strip.setPixelColor(i,0)

def anim_084_soft_aqua(strip):
    for shift in range(80):
        if interrupt_flag: return
        for i in range(10):
            v = (shift*4 + i*10) % 255
            strip.setPixelColor(i, Color(0, v, 255))
        strip.show(); time.sleep(0.03)

def anim_085_pulse_white(strip):
    for b in range(0,255,5):
        if interrupt_flag: return
        col=Color(b,b,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)
    for b in range(255,-1,-5):
        if interrupt_flag: return
        col=Color(b,b,b)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.02)

def anim_086_flash_magenta(strip):
    for _ in range(6):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,Color(200,0,200))
        strip.show(); time.sleep(0.05)
        clear(strip); time.sleep(0.05)

def anim_087_spectrum(strip):
    for shift in range(120):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i, wheel((i*20+shift) % 255))
        strip.show(); time.sleep(0.02)

def anim_088_meteor_red(strip):
    for head in range(10):
        if interrupt_flag: return
        for i in range(10):
            v=max(0,255-abs(i-head)*70)
            strip.setPixelColor(i,Color(v,0,0))
        strip.show(); time.sleep(0.04)

def anim_089_drift_green(strip):
    for shift in range(60):
        if interrupt_flag: return
        for i in range(10):
            val=(shift+i*8)%255
            strip.setPixelColor(i,Color(0,val,80))
        strip.show(); time.sleep(0.03)

def anim_090_energy_pulse(strip):
    for t in range(40):
        if interrupt_flag: return
        level=int((1+math.sin(t/2))*255)
        col=Color(level,50,200)
        for i in range(10): strip.setPixelColor(i,col)
        strip.show(); time.sleep(0.03)

def anim_091_crystal(strip):
    for _ in range(60):
        if interrupt_flag: return
        for i in range(10):
            v=random.randint(150,255)
            strip.setPixelColor(i,Color(v,v,255))
        strip.show(); time.sleep(0.02)

def anim_092_rolling_gold(strip):
    col = Color(255,200,80)
    for t in range(20):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor(t%10,col)
        strip.show(); time.sleep(0.04)

def anim_093_rolling_teal(strip):
    col = Color(0,255,200)
    for t in range(20):
        if interrupt_flag: return
        clear(strip)
        strip.setPixelColor((9-t)%10,col)
        strip.show(); time.sleep(0.04)
def micro_space_flash(strip):
    idx = 4  # center LED
    for _ in range(3):
        strip.setPixelColor(idx, Color(255,220,80))
        strip.show()
        time.sleep(0.03)
        strip.setPixelColor(idx, 0)
        strip.show()
        time.sleep(0.02)

def anim_094_soft_lava(strip):
    for shift in range(40):
        if interrupt_flag: return
        for i in range(10):
            val=int((1+math.sin((i+shift)/2))*120)
            strip.setPixelColor(i,Color(255,val//2,0))
        strip.show(); time.sleep(0.03)

def anim_095_spark_bluegold(strip):
    for _ in range(60):
        if interrupt_flag: return
        i=random.randint(0,9)
        strip.setPixelColor(i,Color(80,180,255))
        strip.show(); time.sleep(0.02)
        strip.setPixelColor(i,Color(255,200,80))
        strip.show(); time.sleep(0.02)
        strip.setPixelColor(i,0)

def anim_096_matrix_purple(strip):
    for _ in range(40):
        if interrupt_flag: return
        for i in range(10):
            strip.setPixelColor(i,Color(random.randint(80,255),0,random.randint(180,255)))
        strip.show(); time.sleep(0.03)

def anim_097_rainbow_fire(strip):
    for shift in range(80):
        if interrupt_flag: return
        for i in range(10):
            c = wheel((i*25 + shift) % 255)
            strip.setPixelColor(i,c)
        strip.show(); time.sleep(0.02)

def anim_098_neon_tide(strip):
    for t in range(60):
        if interrupt_flag: return
        for i in range(10):
            val=int((1+math.sin((t+i)/3))*120)
            strip.setPixelColor(i,Color(0,val,255))
        strip.show(); time.sleep(0.03)

def anim_099_white_strobe(strip):
    for _ in range(6):
        if interrupt_flag: return
        for i in range(10): strip.setPixelColor(i,Color(255,255,255))
        strip.show(); time.sleep(0.05)
        clear(strip); time.sleep(0.05)

def anim_100_finale(strip):
    # Hybrid rainbow + spark finale
    for shift in range(100):
        if interrupt_flag: return
        for i in range(10):
            col = wheel((shift*4 + i*15) % 255)
            strip.setPixelColor(i,col)
        if random.random() < 0.2:
            idx=random.randint(0,9)
            strip.setPixelColor(idx,Color(255,255,255))
        strip.show(); time.sleep(0.02)

# 101 — ShiftGlow
def anim_101_shiftglow(strip):
    # LEDs representing "left shift"
    idx = [0, 1, 2]

    # Starting dim RGB for first 3 LEDs
    start_colors = [
        (20, 0, 0),   # LED 0 -> dim red
        (0, 20, 0),   # LED 1 -> dim green
        (0, 0, 20),   # LED 2 -> dim blue
    ]

    # Apply initial dim RGB
    for (led, (r, g, b)) in zip(idx, start_colors):
        if interrupt_flag: return
        strip.setPixelColor(led, Color(r, g, b))
    strip.show()
    time.sleep(0.05)

    # Brightening + color-gradient phase
    # Go from dim -> bright with gradient sweeps
    for level in range(20, 256, 5):  # smooth ramp up
        if interrupt_flag: return
        for n, led in enumerate(idx):

            # Each bulb sweeps differently for visual emphasis
            # Red LED: red → yellow → white
            if n == 0:
                r = level
                g = int(level * 0.6)
                b = int(level * 0.3)

            # Green LED: green → cyan → white
            elif n == 1:
                r = int(level * 0.3)
                g = level
                b = int(level * 0.6)

            # Blue LED: blue → magenta → white
            else:
                r = int(level * 0.6)
                g = int(level * 0.3)
                b = level

            strip.setPixelColor(led, Color(r, g, b))

        strip.show()
        time.sleep(0.015)

    # Fade out completely
    for level in range(255, -1, -10):
        if interrupt_flag: return
        for led in idx:
            strip.setPixelColor(led, Color(level, level, level))
        strip.show()
        time.sleep(0.01)

# 102 — ShiftGlowReversed

def anim_102_shiftglowreversed(strip):
    # LEDs representing "left shift"
    idx = [9, 8, 7]

    # Starting dim RGB for first 3 LEDs
    start_colors = [
        (20, 0, 0),   # LED 0 -> dim red
        (0, 20, 0),   # LED 1 -> dim green
        (0, 0, 20),   # LED 2 -> dim blue
    ]

    # Apply initial dim RGB
    for (led, (r, g, b)) in zip(idx, start_colors):
        if interrupt_flag: return
        strip.setPixelColor(led, Color(r, g, b))
    strip.show()
    time.sleep(0.05)

    # Brightening + color-gradient phase
    # Go from dim -> bright with gradient sweeps
    for level in range(20, 256, 5):  # smooth ramp up
        if interrupt_flag: return
        for n, led in enumerate(idx):

            # Each bulb sweeps differently for visual emphasis
            # Red LED: red → yellow → white
            if n == 0:
                r = level
                g = int(level * 0.6)
                b = int(level * 0.3)

            # Green LED: green → cyan → white
            elif n == 1:
                r = int(level * 0.3)
                g = level
                b = int(level * 0.6)

            # Blue LED: blue → magenta → white
            else:
                r = int(level * 0.6)
                g = int(level * 0.3)
                b = level

            strip.setPixelColor(led, Color(r, g, b))

        strip.show()
        time.sleep(0.015)

    # Fade out completely
    for level in range(255, -1, -10):
        if interrupt_flag: return
        for led in idx:
            strip.setPixelColor(led, Color(level, level, level))
        strip.show()
        time.sleep(0.01)

def anim_103_pixel_chasereversed(strip):
    col = Color(255, 255, 0)  # Yellow
    for idx in range(9, 0 - 1, -1):  # Count from 9 down to 0
        if interrupt_flag:
            return
        clear(strip)
        strip.setPixelColor(idx, col)
        strip.show()
        time.sleep(0.05)

def anim_104_rolling_tealreversed(strip):
    col = Color(0,255,200)
    for t in range(20):
        if interrupt_flag:
            return
        clear(strip)
        strip.setPixelColor(t % 10, col)  # moves 0 → 9 repeatedly
        strip.show()
        time.sleep(0.04)

class SystemLoadMonitor(threading.Thread):
    def __init__(self, cpu_threshold=75, ram_threshold=85,
                 bg_load_multiplier=2, io_wait_threshold=20,
                 cpu_spike_cooldown=1.5, ram_overload_cooldown=5,
                 bg_load_cooldown=3):
        super().__init__(daemon=True)
        self.cpu_threshold = cpu_threshold
        self.ram_threshold = ram_threshold
        self.bg_load_multiplier = bg_load_multiplier
        self.io_wait_threshold = io_wait_threshold
        self.cpu_cooldown = cpu_spike_cooldown
        self.ram_cooldown = ram_overload_cooldown
        self.bg_cooldown = bg_load_cooldown

        self.last_cpu_event = 0
        self.last_ram_event = 0
        self.last_bg_event = 0

        self.num_cores = os.cpu_count() or 4

    def run(self):
        while True:
            now = time.time()

            # --- CPU ---
            cpu = psutil.cpu_percent(interval=0.25)
            if cpu > self.cpu_threshold:
                if now - self.last_cpu_event > self.cpu_cooldown:
                    dispatch_system("system_cpu_spike")
                    self.last_cpu_event = now

            # --- RAM ---
            ram = psutil.virtual_memory().percent
            if ram > self.ram_threshold:
                if now - self.last_ram_event > self.ram_cooldown:
                    dispatch_system("system_ram_overload")
                    self.last_ram_event = now

            # --- Background task indicators ---
            load1, _, _ = os.getloadavg()
            iowait = psutil.cpu_times_percent().iowait

            if (
                load1 > self.num_cores * self.bg_load_multiplier
                or iowait > self.io_wait_threshold
            ):
                if now - self.last_bg_event > self.bg_cooldown:
                    dispatch_system("system_background_load")
                    self.last_bg_event = now

# =====================================================================
# CHUNK 9 — ACTION REGISTRY & HIGH‑LEVEL EVENT MAP (FINAL)
# =====================================================================

# All 100 animations are now registered via ACTION_TO_ANIM.
# This registry builds a reverse‑lookup table and exposes a clean API
# for triggering animations from any subsystem.

ACTION_REGISTRY = {
    "keyboard": {
        "press":  ["keypress_generic"],
        "release": ["keypress_flash"],
    },
    "mouse": {
        "move":   ["cursor_moved"],
        "click":  ["mouse_click"],
        "scroll": ["scroll_webpage"],
    },
    "system": {
        "boot":        ["system_boot"],
        "shutdown":    ["logout"],
        "warning":     ["system_warning"],
        "cooling":     ["system_cooling"],
        "network":     ["wifi_connected", "network_online"],
        "update":      ["update_progress", "auto_update_done"],
    },
    "ui": {
        "open_window": ["open_tab", "maximize_window"],
        "close_window": ["close_window", "minimize_window"],
        "switch":       ["switch_tab", "switch_window", "switch_desktops"],
        "theme":        ["switch_theme", "theme_toggle", "install_theme"],
    },
    "file": {
        "open":   ["open_folder", "open_explorer"],
        "copy":   ["file_copy"],
        "delete": ["move_to_trash", "delete_text"],
        "save":   ["save_file", "save_complete"],
        "search": ["file_search"],
    },
}
def pre_anim_reset():
    hard_clear(strip)   # full blackout, thread-safe
    clear_interrupt()   # ensure stale interrupts do not kill new anim

def trigger_action(action_name):
    if action_name not in ACTION_TO_ANIM:
        print(f"[WARN] Action '{action_name}' not found.")
        return

    anim = ACTION_TO_ANIM[action_name]

    def wrapper(strip):
        if not callable(anim):
            return
        anim(strip)
            # smooth fade-out so letters/swipes don’t linger
        fade_all(strip, factor=0.5)
        strip.show()
        time.sleep(0.03)
        clear(strip)
    threading.Thread(target=wrapper, args=(strip,),daemon=True).start()

# =====================================================================
# ACTION → ANIMATION FUNCTION MAP (GENERATED LOOKUP TABLE)
# =====================================================================

# Map events to specific animation functions by name:
ACTION_TO_ANIM = {
    "keypress_generic": anim_keypress,
  
    "keypress_flash":   None,     

    # -------------------
    # Mouse actions
    # -------------------
    "mouse_click":      anim_079_drift,
    "cursor_moved":     anim_067_meteor_blue,
    "scroll_webpage":   anim_070_dual_comet,

    # -------------------
    # System-level
    # -------------------
    "system_warning":   anim_099_white_strobe,
    "system_cooling":   anim_065_soft_green,
    "wifi_connected":   anim_087_spectrum,
    "network_online":   anim_064_rainbow_fade,
    "update_progress":  anim_085_pulse_white,
    "auto_update_done": anim_078_lime_flash,

    # -------------------
    # UI actions
    # -------------------
    "open_tab":         anim_019_snake,
    # No crossfade exists → pick the closest “smooth transition”
    "switch_tab":       anim_068_soft_hue,
    # No dual_wave exists → correct: anim_051_wave_dual
    "switch_window":    anim_051_wave_dual,
    "switch_desktops":  anim_068_soft_hue,

    # No sunrise named “052” → correct: anim_006_sunrise
    "maximize_window":  anim_006_sunrise,

    # No sunset function → best thematic match is anim_054_pulse_yellow
    "minimize_window":  anim_054_pulse_yellow,

    "close_window":     anim_073_pulse_teal,
    "theme_toggle":     anim_066_soft_red,
    "install_theme":    anim_071_hyperpulse,

    # -------------------
    # File actions
    # -------------------
    "open_explorer":    anim_061_bloom,
    "open_folder":      anim_062_hotcore,
    "file_copy":        anim_077_soft_matrix,
    "file_search":      anim_097_rainbow_fire,
    "move_to_trash":    anim_099_white_strobe,
    "delete_text":      anim_001_ember_pulse,
    "save_file":        anim_090_energy_pulse,
    "save_complete":    anim_098_neon_tide,
    "mouse_left":  anim_067_meteor_blue,
    "mouse_right": anim_088_meteor_red,
    "special_enter": anim_017_diamond,
    "special_space": micro_space_flash,
    "special_tab": anim_033_triple_sweep,
    "special_shift": anim_101_shiftglow,
    "special_ctrl": anim_104_rolling_tealreversed,
    "special_alt": anim_028_pixel_chase,
    "special_backspace": anim_007_cylon,
    "special_delete": anim_092_rolling_gold,
    "special_`":   anim_021_firefly,
    "special_~":   anim_022_blue_strobe,
    "special_-":   anim_023_ember_trail,
    "special__":   anim_024_candy_cane,
    "special_\\":  anim_025_pastel_drift,
    "special_|":   anim_026_binary,
    "special_esc": anim_083_confetti,


    # right-side modifiers
    "special_shift_r":  anim_102_shiftglowreversed,
    "special_ctrl_r":   anim_093_rolling_teal,
    "special_alt_r":    anim_103_pixel_chasereversed,

    # combo: alt+tab
    "alt_tab":          anim_030_soft_wave,
    "system_cpu_spike": anim_097_rainbow_fire,
    "system_ram_overload": anim_081_plasma,
    "system_background_load": anim_080_energy

}


# =====================================================================
# CHUNK 10 — FINAL LED WORKER THREAD (HYBRID EVENT ENGINE)
# =====================================================================

# This engine handles:
#  ✓ Priority ordering
#  ✓ Interrupt-safe animation spawning
#  ✓ Mouse + keyboard + system action routing
#  ✓ Non-blocking threading for all animation types

import queue

event_queue = queue.Queue()

##############################################################
# LED WORKER — MASTER EVENT EXECUTION LOOP
##############################################################
def led_worker():
    global current_priority

    while True:
        raw_event = event_queue.get()  # (name, payload)
        if raw_event is None:
            continue

        # ==========================================================================
        # EVENT NORMALIZATION
        # ==========================================================================
        if isinstance(raw_event, tuple) and len(raw_event) == 2:
            event_name, payload = raw_event
        else:
            event_name = raw_event
            payload = None

        # ==========================================================================
        # TELEMETRY OVERRIDE MODEL
        #
        # If telemetry_present:
        #   - ONLY events beginning with "telemetry_" are allowed to run
        #   - ALL other events (keypress, scroll, idle, system) are suppressed
        # ==========================================================================
        from shared_state import telemetry_present
        if telemetry_present:
            if not (isinstance(event_name, str) and event_name.startswith("telemetry_")):
                continue  # Drop non-telemetry events silently

        # ==========================================================================
        # TELEMETRY EVENTS (ALLOWED REGARDLESS OF PRIORITY)
        # ==========================================================================
        if isinstance(event_name, str) and event_name.startswith("telemetry_"):
            # TELEMETRY: RPM BAR
            if event_name == "telemetry_rpm":
                telemetry_draw_rpm(payload)  # <= your telemetry mapping function
                continue

            # TELEMETRY: SHIFT FLASH / WARN (OPTIONAL)
            if event_name == "telemetry_shift":
                telemetry_flash_shift(payload)
                continue

            # (you can add telemetry_flag, telemetry_warning, telemetry_pit, etc)
            continue

        # ==========================================================================
        # NON-TELEMETRY CASES BELOW
        #
        # Only allowed when telemetry_present == False
        #
        # NORMAL LED SYSTEM BEHAVIOR
        # ==========================================================================
        # MICRO EVENTS: never interrupt higher events
        if event_name == "caps_toggle":
            run_micro(toggle_caps_indicator)
            continue

        if event_name == "keypress":
            run_micro(anim_keypress, *payload)
            continue

        if event_name == "mouse":
            run_micro(mouse_reaction, *payload)
            continue

        if event_name == "scroll_up":
            run_mid(scroll_up_anim, strip)
            continue

        if event_name == "scroll_down":
            run_mid(scroll_down_anim, strip)
            continue

        # ==========================================================================
        # HIGH-LEVEL EVENTS (system resets, hard transitions)
        # ==========================================================================
        if event_name == "system_reset":
            run_high(system_reset_sequence)
            continue

        if event_name == "system_splash":
            run_high(system_splash_animation)
            continue

        # You can add other cases here...
        # NOTE: they only run if telemetry is NOT active
        # ==========================================================================
        # FALLBACK: ACTION_TO_ANIM MAP
        # ==========================================================================
        if isinstance(event_name, str) and event_name in ACTION_TO_ANIM:
            anim = ACTION_TO_ANIM[event_name]
            if callable(anim):
                # most of these are "mid" animations
                run_mid(anim, strip)
            continue

        # If we reach here, the event was unknown
        print(f"[LED WORKER] Unhandled event: {event_name} | payload={payload}")


# Start worker thread
worker_thread = threading.Thread(target=led_worker, daemon=True)
worker_thread.start()

LETTER_KEYS = set("1234567890qwertyuiopasdfghjkl;zxcvbnm")

def is_letter_key(k):
    return k in LETTER_KEYS

# =====================================================================
# JOYSTICK SUPPORT (multi-device, unique per-device colors)
# =====================================================================

try:
    from evdev import InputDevice, categorize, ecodes
    Joystick = InputDevice 
except ImportError:
    print("[WARN] 'joystick' library not installed — skipping joystick integration.")
    Joystick = None

import glob

JOYSTICKS = {}    # id → Joystick instance
JOY_COLORS = {}   # id → (r,g,b)

# Predefined color themes for up to many joysticks
JOY_COLOR_POOL = [
    (255, 30, 30),   # red
    (30, 255, 30),   # green
    (30, 120, 255),  # blue
    (255, 140, 0),   # orange
    (180, 0, 255),   # purple
    (255, 0, 180),   # magenta
    (0, 255, 200),   # aqua
]

def get_joystick_color(js_id):
    if js_id not in JOY_COLORS:
        JOY_COLORS[js_id] = JOY_COLOR_POOL[len(JOY_COLORS) % len(JOY_COLOR_POOL)]
    return JOY_COLORS[js_id]

def anim_joystick_button(strip, js_id, btn_name):
    r, g, b = JOYSTICK_BUTTON_COLORS.get(btn_name, (255, 0, 255))

    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(r, g, b))
    strip.show()

    time.sleep(0.07)

    for i in range(strip.numPixels()):
        strip.setPixelColor(i, 0)
    strip.show()
import math

def anim_joystick_axis(strip, js_id, axis, value):
    # Normalize value -32768..32767 → -1..1
    norm = value / 32768.0

    # Store state per joystick:
    if js_id not in JOY_AXIS_STATE:
        JOY_AXIS_STATE[js_id] = {"x": 0, "y": 0, "rx": 0, "ry": 0}

    JOY_AXIS_STATE[js_id][axis] = norm

    # Use left stick (X/Y)
    x = JOY_AXIS_STATE[js_id]["x"]
    y = -JOY_AXIS_STATE[js_id]["y"]  # invert Y so up = positive

    mag = math.sqrt(x*x + y*y)  # 0 to 1
    if mag < 0.02:
        # stick centered → fade LEDs out
        for i in range(strip.numPixels()):
            strip.setPixelColor(i, 0)
        strip.show()
        return

    angle = math.atan2(y, x)  # -π..+π
    hue = (angle + math.pi) / (2*math.pi)  # 0..1

    # Convert hue → RGB
    r, g, b = hsv_to_rgb(hue, 1, mag)

    # Set LEDs
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(int(r), int(g), int(b)))
    strip.show()
JOY_AXIS_STATE = {}
def hsv_to_rgb(h, s, v):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return r*255, g*255, b*255


def anim_joystick_axis(strip, js_id, axis, value):
    r, g, b = get_joystick_color(js_id)

    # axis value is usually -32767..32767
    intensity = int(abs(value) / 32767 * 255)
    col = Color(
        int(intensity * (r / 255)),
        int(intensity * (g / 255)),
        int(intensity * (b / 255))
    )


    mid = LED_COUNT // 2
    span = int((value / 32767) * mid)

    for i in range(LED_COUNT):
        strip.setPixelColor(i, 0)

    if value < 0:
        for i in range(mid + span, mid):
            strip.setPixelColor(i, col)
    else:
        for i in range(mid, mid + span):
            strip.setPixelColor(i, col)

    strip.show()
    time.sleep(0.01)


# Register joystick events in the action system
ACTION_REGISTRY["joystick"] = {
    "button": ["joystick_button"],
    "axis":   ["joystick_axis"]
}

#ACTION_TO_ANIM["joystick_button"] = anim_joystick_flash
ACTION_TO_ANIM["joystick_axis"]   = None    # handled manually per axis
def joystick_listener(js_id, dev):
    for event in dev.read_loop():
        if event.type == ecodes.EV_KEY:
            btn = event.code
            if event.value == 1:  # press
                event_queue.put(("joystick_button", {
                    "js_id": js_id,
                    "button": btn
                }))

        elif event.type == ecodes.EV_ABS:
            axis = event.code
            value = event.value
            event_queue.put(("joystick_axis", {
                "js_id": js_id,
                "axis": axis,
                "value": value
            }))


def discover_joysticks():
    paths = sorted(glob.glob("/dev/input/event*"))

    for path in paths:
        try:
            dev = InputDevice(path)
            caps = dev.capabilities()

            # Filter: Device must have analog axes (EV_ABS) AND buttons (EV_KEY)
            if ecodes.EV_ABS in caps and ecodes.EV_KEY in caps:
                js_id = f"js{len(JOYSTICKS)}"
                JOYSTICKS[js_id] = dev

                print(f"[JOYSTICK] Connected: {dev.name} via {path} as {js_id}")

                t = threading.Thread(
                    target=joystick_listener,
                    args=(js_id, dev),
                    daemon=True
                )
                t.start()

        except Exception as e:
            print(f"[JOYSTICK] Could not open {path}: {e}")

# Call on startup
if Joystick:
    discover_joysticks()

# =====================================================================
# CHUNK 11 — FINAL MOUSE LISTENER INTEGRATION (NO PLACEHOLDERS)
# =====================================================================

from pynput import mouse

# State for mouse LED tracking
mouse_led_index = 0
last_mouse_x = None
last_mouse_move_time = time.time()
def mouse_led_refresher():
    """Continuously updates mouse LEDs so the inactivity timeout can work."""
    while True:
        try:
            update_mouse_led()
        except Exception as e:
            print("Refresher error:", e)
        time.sleep(1/60)   # ~60 FPS
threading.Thread(target=mouse_led_refresher, daemon=True).start()
system_monitor = SystemLoadMonitor()
system_monitor.start()

def on_move(x, y):
    global mouse_led_index, last_mouse_x, last_mouse_move_time
    last_mouse_move_time = time.time()

    if last_mouse_x is not None:
        if x > last_mouse_x:
            mouse_led_index = (mouse_led_index + 1) % LED_COUNT
        elif x < last_mouse_x:
            mouse_led_index = (mouse_led_index - 1) % LED_COUNT

    last_mouse_x = x
    event_queue.put("mouse_move")

def scroll_animation(strip, direction):
    # pynput: dy < 0 = scroll UP, dy > 0 = scroll DOWN
    color_up   = Color(255, 200, 40)
    color_down = Color(80, 160, 255)

    color = color_up if direction < 0 else color_down

    for _ in range(2):
        for i in range(LED_COUNT):
            strip.setPixelColor(i, color)
        strip.show()
        time.sleep(0.03)

        for i in range(LED_COUNT):
            strip.setPixelColor(i, 0)
        strip.show()
        time.sleep(0.03)

    # extra fade to prevent lingering light
    fade_all(strip, factor=0.6)


def on_click(x, y, button, pressed):
    if not pressed:
        return

    if button == mouse.Button.left:
        event_queue.put("mouse_left")

    elif button == mouse.Button.right:
        event_queue.put("mouse_right")


def on_scroll(x, y, dx, dy):
    threading.Thread(
        target=scroll_animation,
        args=(strip, dy),
        daemon=True
    ).start()

    event_queue.put("mouse_scroll")

mouse_listener = mouse.Listener(
    on_move=on_move,
    on_click=on_click,
    on_scroll=on_scroll
)
mouse_listener.start()


# =====================================================================
# CHUNK 12 — FINAL KEYBOARD LISTENER INTEGRATION (NO PLACEHOLDERS)
# =====================================================================
# ============================================================
# CHORD DETECTION ENGINE — NEW
# ============================================================

import collections
import time

# Guitar chord → required letters
CHORD_MAP = {
    "C":  set("ceg"),
    "Cm": set("cegb"),       # c Eb g, but using letters available on keyboard
    "G":  set("gbd"),
    "Am": set("ace"),
    "A":  set("ac#e"),       # simplified → ace
    "Em": set("egb"),
    "E":  set("eg#b"),       # simplified → egb
    "F":  set("fac"),
    "Dm": set("dfa"),
    "D":  set("dfa#"),       # simplified → dfa
}

# rolling buffer of (letter, timestamp)
KEY_HISTORY = collections.deque(maxlen=12)

CHORD_WINDOW = 0.35   # seconds allowed between letters
last_chord_time = 0
CHORD_COOLDOWN = 0.6  # prevent repeating the chord instantly


def detect_chord():
    """Returns chord name if detected, else None."""
    now = time.time()
    global last_chord_time

    # Prevent immediate repeat
    if now - last_chord_time < CHORD_COOLDOWN:
        return None

    # Collect letters in the window
    letters = [k for k, t in KEY_HISTORY if now - t <= CHORD_WINDOW]
    letters_set = set(letters)

    for chord, notes in CHORD_MAP.items():
        if notes.issubset(letters_set):
            last_chord_time = now
            return chord

    return None


# ============================================================
# CHORD RESONANCE ANIMATION — NEW
# ============================================================

import math
import random

def chord_gradient(strip, notes):
    """
    Natural dissipating chord animation:
    - Generates a chord-color gradient across columns
    - Adds bloom, shimmer, and organic falloff
    """

    chord_notes = list(notes)
    num_notes = len(chord_notes)

    # Create anchor gradient positions across 0–9 columns
    anchors = []
    for idx, note in enumerate(chord_notes):
        anchors.append({
            "column": int((idx / max(1, num_notes - 1)) * 9),
            "color": key_to_color(note)
        })

    # First frame: full gradient (base colors)
    base_colors = []
    for i in range(LED_COUNT):

        key = LED_TO_KEY.get(i, None)
        col = COLUMN_MAP.get(key, 5) if key else 5

        # Neighbor anchors
        left = None
        right = None
        for a in anchors:
            if a["column"] <= col:
                left = a
            if a["column"] >= col and right is None:
                right = a

        if left is None:
            left = anchors[0]
        if right is None:
            right = anchors[-1]

        # Position blend ratio
        if left["column"] == right["column"]:
            t = 0
        else:
            t = (col - left["column"]) / (right["column"] - left["column"])

        lr, lg, lb = (left["color"]>>16)&255, (left["color"]>>8)&255, left["color"]&255
        rr, rg, rb = (right["color"]>>16)&255, (right["color"]>>8)&255, right["color"]&255

        r = int(lr + (rr - lr) * t)
        g = int(lg + (rg - lg) * t)
        b = int(lb + (rb - lb) * t)

        base_colors.append((r, g, b))
        strip.setPixelColor(i, Color(r, g, b))

    strip.show()

    # Organic dissipation
    # - exponential falloff
    # - shimmer
    # - slight wave motion
    frame_count = 50
    for frame in range(frame_count):
        decay = math.exp(-frame * 0.08)  # natural falloff

        for i in range(LED_COUNT):
            r, g, b = base_colors[i]

            # shimmer: tiny flicker in 0.97–1.03 range
            shimmer = 1 + (random.random()*0.06 - 0.03)

            # wave propagation from center of strip
            wave = 0.95 + 0.1 * math.sin((i*0.25) + frame*0.18)

            scale = decay * shimmer * wave
            scale = max(0, min(scale, 1))

            rr = int(r * scale)
            gg = int(g * scale)
            bb = int(b * scale)

            strip.setPixelColor(i, Color(rr, gg, bb))

        strip.show()
        time.sleep(0.03)


from pynput import keyboard
from pynput.keyboard import Key

def normalize_key(key):
    try:
        if hasattr(key, "char") and key.char:
            return key.char.lower()
    except:
        pass

    special_map = {
        Key.space:      " ",
        Key.enter:      "enter",
        Key.tab:        "tab",
        Key.shift:      "shift",
        Key.shift_r:    "shift_r",
        Key.ctrl:       "ctrl",
        Key.ctrl_r:     "ctrl_r",
        Key.alt:        "alt",
        Key.alt_r:      "alt_r",
        Key.caps_lock:  "caps",
        Key.backspace:  "backspace",
        Key.delete:     "delete",
        Key.esc:        "esc",
        Key.up:         "up",
        Key.down:       "down",
        Key.left:       "left",
        Key.right:      "right",
    }

    return special_map.get(key, None)
keys_down = set()

def on_press(key):
    global last_key_index, last_key_color, last_keypress_time, keys_down

    last_keypress_time = time.time()

    k = normalize_key(key)
    if k is None:
        return

    # Track keys held (needed for alt+tab later)
    keys_down.add(k)

    # CAPS LOCK TOGGLE
    if k == "caps":
        toggle_caps_indicator()
        return

    # 🔥 ALT + TAB combo
    if k == "tab" and ("alt" in keys_down or "alt_r" in keys_down):
        event_queue.put("alt_tab")
        return

    # 🔤 LETTER / NUMBER KEYS → column animation
    if is_letter_key(k):
        # record time + letter
        KEY_HISTORY.append((k, time.time()))

        # normal per-key LED
        last_key_index = key_to_led_index(k)
        last_key_color = key_to_color(k)
        event_queue.put(("keypress", last_key_index, last_key_color))

        # chord check
        chord = detect_chord()
        if chord:
            required_notes = CHORD_MAP[chord]
            # spawn resonance safely (micro layer)
            threading.Thread(
                target=chord_gradient,
                args=(strip, required_notes),
                daemon=True
            ).start()

        return


    # 🎯 EVERYTHING ELSE (INCLUDING SPACE) IS A SPECIAL KEY
    special_action = f"special_{k}"          # ← builds e.g. "special_space"
    if special_action in ACTION_TO_ANIM:
        event_queue.put(special_action)
    else:
        print("No anim for:", special_action)


def on_release(key):
    global keys_down

    k = normalize_key(key)
    if k in keys_down:
        keys_down.discard(k)
    # if you ever want release effects, you can still trigger here
    # e.g. event_queue.put("keyboard_release")

keyboard_listener = keyboard.Listener(
    on_press=on_press,
    on_release=on_release
)
keyboard_listener.start()


# =====================================================================
# CHUNK 13 — UNIFIED DISPATCHER FINALIZATION (NO PLACEHOLDERS)
# =====================================================================

# This layer provides:
#   ✓ A single consistent API for all event sources
#   ✓ Automatic routing to ACTION_REGISTRY
#   ✓ Translation of UI/system/file events into animation calls
#   ✓ Full compatibility with the hybrid LED engine

def dispatch(event_type, event_name=None, payload=None):
    """High-level dispatcher entrypoint used by all subsystems."""

    # -------------------------------
    # 1 — Direct animation event
    # -------------------------------
    if event_name in ACTION_TO_ANIM:
        event_queue.put(event_name)
        return

    # -------------------------------
    # 2 — Registry-based dispatch
    # -------------------------------
    if event_type in ACTION_REGISTRY:
        category = ACTION_REGISTRY[event_type]

        if event_name in category:
            actions = category[event_name]
            for action in actions:
                event_queue.put(action)
            return

    print(f"[DISPATCH WARNING] Unknown event: type={event_type}, name={event_name}")

# Helper convenience wrappers
def dispatch_system(event): dispatch("system", event)
def dispatch_file(event):   dispatch("file", event)
def dispatch_ui(event):     dispatch("ui", event)
def dispatch_mouse(event):  dispatch("mouse", event)
def dispatch_key(event):    dispatch("keyboard", event)


# =====================================================================
# CHUNK 14 — IDLE ENGINE / BACKGROUND ACTIVITY LAYER (NO PLACEHOLDERS)
# =====================================================================

# Purpose:
#   ✓ Detect user inactivity
#   ✓ Trigger low‑priority idle animations
#   ✓ Stop immediately on any input (interrupt_flag)
#   ✓ Never block high‑priority events
#   ✓ Fully integrated with hybrid LED engine

IDLE_TIMEOUT = 60     # seconds of no mouse/keyboard input
idle_running = False
idle_thread = None
# Build a global list of idle-capable animations
ALL_IDLE_ANIMS = []

for name, fn in list(globals().items()):
    if not callable(fn):
        continue
    if not name.startswith("anim_"):
        continue

    # Filter out things that shouldn't ever be part of idle
    if name in (
        "anim_keypress",
        "anim_joystick_axis",
    ):
        continue

    ALL_IDLE_ANIMS.append(fn)

print(f"[IDLE ENGINE] Registered {len(ALL_IDLE_ANIMS)} idle-capable animations.")

def idle_animation(strip):
    """Soft, slow ambient idle mode using all registered animations."""
    hard_clear(strip)

    global idle_running

    while idle_running:
        if interrupt_flag:
            hard_clear(strip)
            break

        if not ALL_IDLE_ANIMS:
            time.sleep(0.5)
            continue

        # pick a random animation
        anim = random.choice(ALL_IDLE_ANIMS)

        # run that animation for a bit, but allow exit
        start = time.time()
        while time.time() - start < 8:  # ~8 seconds per pattern
            if interrupt_flag or not idle_running:
                hard_clear(strip)
                return

            try:
                anim(strip)
            except Exception as e:
                print("[IDLE ANIM ERROR]", anim.__name__, e)
                break

            # slow overall rate so we don't smash the CPU
            time.sleep(0.05)

        # cross-fade between animations
        for _ in range(30):
            if interrupt_flag or not idle_running:
                hard_clear(strip)
                return
            fade_all(strip, factor=0.9)
            strip.show()
            time.sleep(0.05)

def idle_engine_loop():
    global idle_running, idle_thread

    while True:
        # Compute last activity time from keyboard & mouse
        last_input = max(last_mouse_move_time, last_keypress_time)

        # Enter idle mode
        if not idle_running:
            if time.time() - last_input > IDLE_TIMEOUT:
                idle_running = True
                idle_thread = threading.Thread(
                    target=idle_animation,
                    args=(strip,),
                    daemon=True
                )
                idle_thread.start()

        # Exit idle mode immediately on activity
        else:
            if time.time() - last_input < 0.2:
                idle_running = False

        time.sleep(0.2)

# Initialize last keypress time tracker
last_keypress_time = time.time()



# Start idle engine monitor thread
idle_monitor_thread = threading.Thread(target=idle_engine_loop, daemon=True)
idle_monitor_thread.start()


# =====================================================================
# CHUNK 15 — SYSTEM BOOT & SHUTDOWN ANIMATIONS (NO PLACEHOLDERS)
# =====================================================================

# These animations run automatically when the program starts and exits.
# They integrate cleanly with the hybrid engine and respect interrupts.

def boot_sequence(strip):
    colors = [
        Color(255,0,0),
        Color(255,80,0),
        Color(255,200,0),
        Color(0,180,255),
        Color(120,0,255),
    ]
    for c in colors:
        if interrupt_flag: return
        for i in range(LED_COUNT):
            strip.setPixelColor(i, c)
        strip.show()
        time.sleep(0.15)

    # soft fade to neutral
    for b in range(255, -1, -10):
        if interrupt_flag: return
        col = Color(b//6, b//6, b//6)
        for i in range(LED_COUNT):
            strip.setPixelColor(i, col)
        strip.show()
        time.sleep(0.03)

def shutdown_sequence(strip):
    for step in range(50):
        if interrupt_flag: return
        level = int((1+math.sin(step/5))*255)
        col = Color(level,0,60)
        for i in range(LED_COUNT):
            strip.setPixelColor(i,col)
        strip.show()
        time.sleep(0.02)

    # Final blackout
    clear(strip)
    strip.show()

# Automatically run boot animation at startup
threading.Thread(target=boot_sequence, args=(strip,), daemon=True).start()


# =====================================================================
# CHUNK 16 — MAIN LOOP / SYSTEM ENTRYPOINT (FINAL, NO PLACEHOLDERS)
# =====================================================================

# The main loop does NOT block — the entire architecture runs on:
#   ✓ Mouse listener thread
#   ✓ Keyboard listener thread
#   ✓ LED worker thread
#   ✓ Idle engine monitor thread
#   ✓ Boot sequence thread
#
# This loop simply keeps the process alive cleanly and supports a graceful
# shutdown animation.

def main():
    print("[LED SYSTEM] Starting hybrid engine...")
    print("[LED SYSTEM] Listeners active. Boot sequence running.")
    print("[LED SYSTEM] Press CTRL+C to exit.")

    try:
        while True:
            # main loop stays alive, all work is done in threads
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[LED SYSTEM] Shutdown requested. Running shutdown sequence...")
        shutdown_sequence(strip)
        print("[LED SYSTEM] Shutdown complete.")


if __name__ == "__main__":
    main()
