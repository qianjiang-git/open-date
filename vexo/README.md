# vexo-hack

Everything needed to find, read and drive a **Vexo Open band** — the `Vexo-HACK-XX` wrist
band with a motion sensor, a microphone and an RGB light — from this laptop, over Bluetooth.

One command sets up the tools, finds the band, connects and prints what it is:

```sh
./setup.sh
```

```
==> USB device detected
  Vexo Open band
    Product ID: 0x0004
    Vendor ID: 0x2fe3
    Serial Number: CF0FF5D6A80D4687
==> Starting
Scanning 8s for Vexo bands...
  Vexo-HACK-36  4A919FE6-...  rssi -54
name:      Vexo-HACK-36
band no:   36
firmware:  1.1.0  protocol 1.1  hardware 1
features:  fast-motion, intervals, clock
caps:      accel, gyro, events, steps, mic, led, battery, temperature, storage, tx-power, usb
battery:   0% (3387 mV, charging)
```

## The hardware

| | |
|---|---|
| Product | Vexo Open band (`Vexo-HACK-36`) |
| USB | `0x2FE3:0x0004`, serial `CF0FF5D6A80D4687` (`/dev/cu.usbmodem*` on macOS) |
| Radio | Bluetooth Low Energy, name `Vexo-HACK-<number>` |
| Service | `254f0001-df82-4a9c-a2b5-563a0f6b2021` |
| Board | XIAO nRF52840 Sense, firmware 1.1.0, protocol 1.1 |
| Sensors | accelerometer, gyroscope, microphone, RGB LED, battery, chip temperature, 1000-slot storage |

How it behaves:

- **Double-tap to wake it.** An idle band does not advertise. Double-tapping blinks the
  light blue and opens a 60-second window to connect.
- **One program at a time.** Close the dashboard tab before running a Python program.
- **Everything resets on disconnect**, except the stored values and the band number.
- **The microphone shows a solid blue light** while it is streaming.
- The band number can only be changed over USB, never over Bluetooth.

## Requirements

- macOS, Linux, or Windows (this repo was set up on macOS).
- Python 3.9+ and `git`.
- Bluetooth on. On macOS, allow Terminal/your editor to use Bluetooth when asked.
- Chrome or Edge for the browser dashboard (Safari and Firefox cannot use Web Bluetooth).

## Quick start

```sh
git clone https://github.com/Khagendra01/vexo-hack.git
cd vexo-hack
./setup.sh
```

If the band is not found, double-tap it (blue blink) and run `./setup.sh` again. Only one
band is needed; if several are nearby the script asks which number to use.

### Common commands

| Command | What it does |
|---|---|
| `./setup.sh` | Set up, scan, connect, print band info and battery |
| `./setup.sh 36` | Skip the scan and use band 36 |
| `./setup.sh --only-scan` | List the bands advertising right now |
| `./setup.sh --led` | Connect and flash the LED red → green → blue → blink white |
| `./setup.sh --json` | Same, as JSON (handy for scripts) |
| `./setup.sh --dashboard` | Serve the browser dashboard on `localhost:8000` |
| `./setup.sh --dashboard --port 8001` | Same, on another port |

`./setup.sh --help` lists everything.

## What `setup.sh` does

1. Checks for Python 3.9+ and `git`.
2. Creates a local `.venv` and installs [`bleak`](https://github.com/hbldh/bleak) there, so
   nothing is installed system-wide.
3. Clones [VexoAI-Org/vexo-open-kit](https://github.com/VexoAI-Org/vexo-open-kit) next to
   the script if it is missing (MIT, the official reference kit), and updates it on later
   runs.
4. On macOS, prints the USB details of the band if it is plugged in.
5. Finds the band by its advertised service UUID and name, connects, and reads
   `GET_INFO`, `GET_NAME` and `BATTERY_GET`.
6. With `--dashboard`, starts a local web server and opens the dashboard in your browser.

It is idempotent: running it again only reuses what is already there. The kit folder and
`.venv` are git-ignored, so your repo stays small.

## The browser dashboard

```sh
./setup.sh --dashboard
```

It prints (and opens) something like
`http://localhost:8000/vexo-open-kit/dashboard/?band=36`. Double-tap the band, press
**Connect**, pick `Vexo-HACK-36`. You get live motion, taps, battery, chip temperature and
an LED colour picker. The server binds to `127.0.0.1` only, so nothing is exposed on your
network.

No band on hand? The dashboard has a **Try without a band** mode.

## Write your own program

The kit is a reference; your code lives in this folder, outside `vexo-open-kit/`. The
script installs `bleak` into `.venv`, so use that interpreter:

```python
# try.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vexo-open-kit" / "python"))
from vexo_open.sync import Band

band = Band.connect(36)          # Vexo-HACK-36
print(band.get_name())
band.set_led("#00ff00")
band.configure(motion=50, events=True, battery=True)
band.on("tap", lambda e: print("tap!", e))
band.wait(10)
band.disconnect()
```

```sh
.venv/bin/python try.py
```

Useful pieces of the API (`vexo-open-kit/docs/api.md` has all of it):

| Task | Call |
|---|---|
| Read a value once | `band.get_info()`, `band.get_name()`, `band.get_battery()`, `band.get_led()` |
| Light | `band.set_led("#ff8800", pattern="breathe", brightness=0.6)` |
| Streams | `band.configure(motion=50, events=True, battery=True, temperature=True, mic_level=True)` |
| Events | `band.on("tap", handler)`, `on("double-tap")`, `on("free-fall")`, `on("tilt")` |
| Steps | `band.configure(activity=True)` |
| Microphone level | `band.configure(mic_level=True)` |
| Record sound | `vexo-open-kit/examples/python/audio_to_text.py 36 --text no` |
| Storage | `band.store_put(key, value)`, `band.store_get(key)` |
| Time | `band.set_time()`, `band.get_time()` |

Everything also exists as `async` (`from vexo_open import Band`) and in JavaScript
(`vexo-open-kit/js/src/index.js`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No Vexo band found` | Double-tap the band, then rerun within 60 s. It stops advertising when idle. |
| `Found Vexo-HACK-36 but could not connect` | Another program holds the link (a dashboard tab, an earlier script). Close it and double-tap again. |
| Dashboard cannot see Bluetooth | Use Chrome or Edge on a laptop; Safari, Firefox and phones do not work. Serve over `http://localhost`, not `file://`. |
| `Scanning ...` then nothing on macOS | Allow Bluetooth for Terminal in **System Settings → Privacy & Security → Bluetooth**, then rerun. |
| Battery shows `0%` while charging | The band is on USB with a nearly empty cell; leave it plugged in for a while. Behavior can be restricted at critical battery. |
| `Address already in use` | The dashboard port is taken: `./setup.sh --dashboard --port 8001`. |
| `No module named 'bleak'` | Use the virtual environment: `.venv/bin/python your_program.py`, or rerun `./setup.sh`. |
| `No module named 'vexo_open'` | Run `./setup.sh` once so the kit is cloned, and keep the `sys.path.insert` line at the top of your program. |

## Repo layout

```
vexo-hack/
  setup.sh        one command: environment, kit, scan, connect, read, dashboard
  detect.py       scan for bands, connect, print info/battery (JSON optional)
  README.md
  .gitignore      ignores .venv/, the kit clone, and .env
  vexo-open-kit/  cloned by setup.sh on first run, not committed
  .venv/          created by setup.sh, not committed
```

## Notes and credits

- The band, its Bluetooth contract and the kit are by **Vexo**:
  [VexoAI-Org/vexo-open-kit](https://github.com/VexoAI-Org/vexo-open-kit) (MIT). This repo
  only adds a setup/diagnostic wrapper and notes for one band.
- The full byte-level protocol is in
  `vexo-open-kit/contract/contract.md` and `vexo-open-kit/docs/bluetooth-contract.md`.
- `detect.py` and `setup.sh` in this repo are MIT as well. Do what you like with them.
