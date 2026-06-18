import _input
import os
import builtins
import machine
import powman
import binascii

# Robust model detection. The original `machine[9:-17]` slice assumes the exact
# string "Pimoroni <Model> 2350 with RP2350"; the GitHub Badger's board name breaks
# that slice (yields "dger"). The GitHub Universe badge is Tufty-class colour-LCD
# hardware, so it must resolve to "tufty" for correct display-mode setup.
_machine = os.uname().machine.lower()
if "tufty" in _machine or "github" in _machine:
    MODEL = "tufty"
elif "blinky" in _machine:
    MODEL = "blinky"
elif "badger" in _machine:
    MODEL = "badger"
else:
    MODEL = _machine[9:-17]

# The GitHub Badger's LCD has no tearing-effect (TE) line, unlike the Pimoroni
# Tufty. Enabling VSYNC makes display.update() block forever waiting for a sync
# that never arrives. Gate VSYNC off for the github board.
_HAS_TE = "github" not in _machine

UID = binascii.hexlify(machine.unique_id()).decode("ASCII")

builtins.LORES = 0b00
builtins.HIRES = 0b01
builtins.VSYNC = 0b10

builtins.FAST_UPDATE = 3 << 4
builtins.FULL_UPDATE = 0 << 4
builtins.MEDIUM_UPDATE = 2 << 4
builtins.DITHER = 1 << 8

builtins.BUTTON_A = machine.Pin.board.BUTTON_A
builtins.BUTTON_B = machine.Pin.board.BUTTON_B
builtins.BUTTON_C = machine.Pin.board.BUTTON_C
builtins.BUTTON_UP = machine.Pin.board.BUTTON_UP
builtins.BUTTON_DOWN = machine.Pin.board.BUTTON_DOWN
builtins.BUTTON_HOME = machine.Pin.board.BUTTON_HOME


VBAT_SENSE = machine.ADC(machine.Pin.board.VBAT_SENSE)
VBUS_DETECT = machine.Pin.board.VBUS_DETECT
CHARGE_STAT = machine.Pin.board.CHARGE_STAT
SENSE_1V1 = machine.ADC(machine.Pin.board.SENSE_1V1)

BAT_MAX = 4.10
BAT_MIN = 3.00

conversion_factor = 3.3 / 65536

if MODEL == "tufty":
    LIGHT_SENSOR = machine.ADC(machine.Pin("LIGHT_SENSE"))
else:
    LIGHT_SENSOR = None


def sample_adc_u16(adc, samples=1):
    val = []
    for _ in range(samples):
        val.append(adc.read_u16())
    return sum(val) / len(val)


class Badge():
    def  __init__(self):
        if MODEL == "badger":
            self.default_clear = color.white
            self.default_pen = color.black
        else:
            self.default_clear = color.black
            self.default_pen = color.white

        # current display mode
        self._current_mode = None

        # either badger, tufty, or blinky
        self.model = MODEL

        # the system
        self.uid = UID

        # track first display update, for badger
        self.first_update = True

        self._case_light_values = [
            0, 0, 0, 0
        ]
        self._case_lights = [
            machine.PWM(machine.Pin.board.CL0),
            machine.PWM(machine.Pin.board.CL1),
            machine.PWM(machine.Pin.board.CL2),
            machine.PWM(machine.Pin.board.CL3)
        ]
        for led in self._case_lights:
            led.freq(500)
            led.duty_u16(0)

        # optional QwSTPad I2C gamepad — merges into the button input
        self._init_pad()

    @property
    def ticks(self):
        return _input.ticks

    @property
    def ticks_delta(self):
        return _input.ticks_delta

    def poll(self):
        _input.poll()
        self._poll_pad()

    def _init_pad(self):
        # Optional QwSTPad I2C gamepad on the badge I2C bus (GPIO4/5, shared with
        # the RTC). It maps onto the symbolic BUTTON_* of THIS board, so the same
        # code is correct on both the Tufty and the GitHub Badger — pin mappings
        # never cross. No pad attached => stays disabled (a no-op).
        self._pad = None
        self._pad_held = set()
        self._pad_pressed = set()
        self._pad_released = set()
        self._pad_retry = 0
        self._pad_map = {
            "U": BUTTON_UP, "D": BUTTON_DOWN,
            "L": BUTTON_A, "R": BUTTON_C,
            "A": BUTTON_A, "B": BUTTON_B,
            "X": BUTTON_C, "Y": BUTTON_B,
            "+": BUTTON_HOME, "-": BUTTON_HOME,
        }
        try:
            import qwstpad
            i2c = machine.I2C(0, sda=machine.Pin.board.I2C_SDA, scl=machine.Pin.board.I2C_SCL)
            # Construct at the default 0x21 ONLY. The constructor's config-register
            # writes ACK-fail (raise) if nothing is there, so it doubles as the probe
            # and never touches 0x23/0x25/0x27 — those collide with Qw/ST sensors
            # (the Multi-Sensor Stick's LTR-559 is at 0x23).
            self._pad = qwstpad.QwSTPad(i2c, qwstpad.DEFAULT_ADDRESS)
        except Exception:
            self._pad = None

    def _poll_pad(self):
        pad = self._pad
        if pad is None:
            # hot-plug: cheaply re-probe 0x21 about once a second
            self._pad_retry += 1
            if self._pad_retry >= 60:
                self._pad_retry = 0
                self._init_pad()
            return
        try:
            b = pad.read_buttons()
        except Exception:
            # pad unplugged / bus error: disable gracefully
            self._pad = None
            self._pad_held = set()
            self._pad_pressed = set()
            self._pad_released = set()
            return
        prev = self._pad_held
        held = set()
        for key, btn in self._pad_map.items():
            if b.get(key):
                held.add(btn)
        self._pad_pressed = held - prev
        self._pad_released = prev - held
        self._pad_held = held

    @property
    def resolution(self):
        return screen.width, screen.height

    def clear(self):
        if self.default_clear is not None:
            screen.pen = self.default_clear
            screen.clear()
        screen.pen = self.default_pen
        return True

    def update(self):
        display.update()
        badge.clear()
        badge.poll()
        return True

    def mode(self, mode=None):
        if mode is None:
            return self._current_mode

        if mode == self._current_mode:
            return None

        self._current_mode = mode

        if MODEL == "tufty":
            display.fullres(bool(mode & HIRES))
            display.set_vsync(bool(mode & VSYNC) and _HAS_TE)

        elif MODEL == "badger":
            display.speed((self._current_mode >> 4) & 0xf)

        if MODEL == "tufty" or getattr(builtins, "screen", None) is None:
            font = getattr(getattr(builtins, "screen", None), "font", None)
            brush = getattr(getattr(builtins, "screen", None), "pen", None)
            builtins.screen = image(display.WIDTH, display.HEIGHT, memoryview(display))
            screen.font = font if font is not None else rom_font.sins
            screen.pen = brush if brush is not None else self.default_pen

        return None

    def battery_voltage(self):
        # Get the average reading over 20 samples from our VBAT and VREF
        voltage = sample_adc_u16(VBAT_SENSE, 10) * conversion_factor * 2
        vref = sample_adc_u16(SENSE_1V1, 10) * conversion_factor
        return  voltage / vref * 1.1

    def usb_connected(self):
        return bool(VBUS_DETECT.value())

    def battery_level(self):
        # Use the battery voltage to estimate the remaining percentage
        return min(100, max(0, round(123 - (123 / pow((1 + pow((self.battery_voltage() / 3.2), 80)), 0.165)))))

    def is_charging(self):
        # We only want to return the charge status if the USB cable is connected.
        if VBUS_DETECT.value():
            return not CHARGE_STAT.value()

        return False

    def disk_free(self, mountpoint="/system"):
        # f_bfree and f_bavail should be the same?
        # f_files, f_ffree, f_favail and f_flag are unsupported.
        f_bsize, f_frsize, f_blocks, f_bfree = os.statvfs(mountpoint)[:4]

        f_total_size = f_frsize * f_blocks
        f_total_free = f_bsize * f_bfree

        return f_total_size, f_total_size - f_total_free, f_total_free

    def light_level(self):
        # TODO: Returning the raw u16 is a little meh here, can we do an approx lux conversion?
        if LIGHT_SENSOR is None:
            raise RuntimeError("Light level not supported!")
        return LIGHT_SENSOR.read_u16()

    def pressed(self, button=None):
        if button is None:
            return set(_input.pressed) | self._pad_pressed
        return button in _input.pressed or button in self._pad_pressed

    def held(self, button=None):
        if button is None:
            return set(_input.held) | self._pad_held
        return button in _input.held or button in self._pad_held

    def released(self, button=None):
        if button is None:
            return set(_input.released) | self._pad_released
        return button in _input.released or button in self._pad_released

    def changed(self, button=None):
        if button is None:
            return set(_input.changed) | self._pad_pressed | self._pad_released
        return (button in _input.changed
                or button in self._pad_pressed or button in self._pad_released)

    def caselights(self, *args):
        if args:
            self._case_light_values[:] = (args[0], ) * 4 if len(args) == 1 else args

            for idx, cl in enumerate(self._case_lights):
                cl.duty_u16(int(self._case_light_values[idx] ** 2.2 * 65535))

        return list(self._case_light_values)

    def sleep(self, duration=None):
        powman.goto_dormant_for(duration) if duration else powman.sleep()

    def wake_reason(self):
        return powman.get_wake_reason()

    def woken_by_button(self):
        return powman.get_wake_reason() in (
            powman.WAKE_BUTTON_A,
            powman.WAKE_BUTTON_B,
            powman.WAKE_BUTTON_C,
            powman.WAKE_BUTTON_UP,
            powman.WAKE_BUTTON_DOWN,
        )

    def pressed_to_wake(self, button):
        return button in powman.get_wake_buttons()

    def woken_by_reset(self):
        return powman.get_wake_reason() == 255


builtins.badge = Badge()
