# Pitwall 🏁

**Your own pit wall for motorsport telemetry.** Watch a session live as it
happens, or replay a past one — cars moving on the circuit, a running
leaderboard, tyre strategy, weather and full driver telemetry, all in one
window.

Formula 1 is supported today. MotoGP and other series are next.

![Pitwall preview](./resources/preview.png)

```bash
python main.py --live     # follow the session running right now
python main.py            # pick any past session from the GUI
```

> **🔴 Live Mode** puts cars on track within a couple of seconds of the real
> thing — usually *ahead* of the TV broadcast. See [docs/LiveMode.md](./docs/LiveMode.md).

> **📡 Telemetry stream** broadcasts every frame over a local socket so you can
> build your own dashboards alongside the replay. See [telemetry.md](./telemetry.md).

## Features

- **Live Sessions:** Follow a race, sprint, qualifying or practice session in real time, rewind into what you missed, and jump back to live with **G**.
- **Circuit View:** The track drawn as a racing surface with kerbs on the corners, numbered corners, a runoff apron and the pit lane traced from telemetry. Cars carry their team colour, a tyre-compound ring, a DRS glow and a leader marker.
- **Timing Tower:** Running order with gaps, places gained or lost against the grid, tyre compound and age, pit stop count and the real stationary time in the box, and last lap time coloured purple for the session best and green for a personal best.
- **Race Position Chart:** Every driver's position plotted against lap number, so a whole race reads at a glance. Available from the insights menu.
- **Session Countdown:** Live sessions show the time remaining, continued from race control's clock rather than read off a value that only updates when the clock starts or stops.
- **Race Replay Visualization:** Watch the race unfold with real-time driver positions on a rendered track.
- **Safety Car Visualization:** See the Safety Car deploy from pit lane, lead the field, and return to pits — with animated transitions and pulsing glow effects.
- **Insights Menu:** Floating menu for quick access to telemetry analysis tools (launches automatically with replay).
- **Leaderboard:** See live driver positions and current tyre compounds.
- **Lap & Time Display:** Track the current lap and total race time.
- **Driver Status:** Drivers who retire or go out are marked as "OUT" on the leaderboard.
- **Interactive Controls:** Pause, rewind, fast forward, and adjust playback speed using on-screen buttons or keyboard shortcuts.
- **Legend:** On-screen legend explains all controls.
- **Driver Telemetry Insights:** View speed, gear, DRS status, and current lap for selected drivers when selected on the leaderboard.

## Live Mode

```bash
python main.py --live
```

Attaches to whatever session is running right now and plays it in the replay
window with all the usual features: leaderboard, tyres, weather, safety car,
telemetry stream and insight windows. Press **G** at any time to jump back to
the live edge after rewinding.

When nothing is on, the command tells you what is next:

```
No session is running right now. Next up: Dutch Grand Prix - Practice 1
in 25h 48m (2026-08-21 10:30 UTC).
```

Want to try it outside a race weekend? The simulated source replays a past
session through the same pipeline at real speed:

```bash
python main.py --live --live-source simulated \
  --live-path "2026/2026-07-26_Hungarian_Grand_Prix/2026-07-26_Race/" \
  --live-offset 4200
```

Full details, latency tuning, data sources and troubleshooting are in
[docs/LiveMode.md](./docs/LiveMode.md).

## Controls

- **Go Live (live mode only):** **G** to jump back to the newest data
- **Pause/Resume:** SPACE or Pause button
- **Rewind/Fast Forward:** ← / → or Rewind/Fast Forward buttons
- **Playback Speed:** ↑ / ↓ or Speed button (cycles through 0.5x, 1x, 2x, 4x)
- **Set Speed Directly:** Keys 1–4
- **Restart**: **R** to restart replay
- **Toggle DRS Zone**: **D** to hide/show DRS Zone
- **Toggle Progress Bar**: **B** to hide/show progress bar
- **Toggle Driver Names**: **L** to hide/show driver names on track
- **Select driver/drivers**: Click to select driver or shift click to select multiple drivers


## Safety Car

The replay includes a **simulated Safety Car** that appears on track whenever the F1 data indicates a Safety Car deployment (track status code `4`). Since the F1 API does not provide GPS telemetry for the actual Safety Car, its position is simulated based on the race leader's position.

### How it works

- **Data source:** The Safety Car deployment timing comes from the real F1 track status data via FastF1 (`session.track_status`).
- **Position simulation:** The SC is placed ~500 meters ahead of the race leader on the track reference polyline. This approximates where the real SC would be relative to the field.
- **Three animation phases:**
  - **Deploying** — The SC animates from the pit lane onto the track over ~3 seconds, with a pulsing glow and "SC DEPLOYING" label.
  - **On Track** — The SC drives ahead of the leader with a steady amber glow and "SC" label.
  - **Returning** — The SC animates back to the pit lane over ~3 seconds, with a fading pulsing glow and "SC IN" label.
- **Visual appearance:** The SC is drawn as a larger orange/amber circle (8px radius vs 6px for regular cars) with an orange outline ring and always-visible "SC" label.

### Technical details

The SC position computation happens in `_compute_safety_car_positions()` in `src/f1_data.py`. Each frame gets a `safety_car` field:

```json
{
  "safety_car": {
    "x": 1234.56,
    "y": 7890.12,
    "phase": "on_track",
    "alpha": 1.0
  }
}
```

| Field | Description |
|-------|-------------|
| `x`, `y` | World coordinates of the SC |
| `phase` | `"deploying"`, `"on_track"`, or `"returning"` |
| `alpha` | Opacity value from `0.0` (invisible) to `1.0` (fully visible), used for fade in/out animation |

> **Note:** If you have existing cached `.pkl` files from previous runs, you must re-run with `--refresh-data` to generate SC position data. Older cached files will simply show no Safety Car.

## Qualifying Session Support (in development)

Recently added support for Qualifying session replays with telemetry visualization including speed, gear, throttle, and brake over the lap distance. This feature is still being refined.

## Requirements

- Python 3.11+ (CI covers 3.10–3.12)
- [FastF1](https://github.com/theOehrly/Fast-F1)
- [Arcade](https://api.arcade.academy/en/latest/)
- numpy

Install dependencies:
```bash
pip install -r requirements.txt
```

FastF1 cache folder will be created automatically on first run. If it is not created, you can manually create a folder named `.fastf1-cache` in the project root
> **First Run Notice:** Loading a session for the first time may take noticeably longer because telemetry data must be downloaded, processed, and cached locally. Subsequent launches of the same session are significantly faster..

## Environment Setup

To get started with this project locally, you can follow these steps:

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/Rm1n90/pitwall
    cd pitwall
    ```
2. **Create a Virtual Environment:**
    This process differs based on your operating system.
    - On macOS/Linux:
      ```bash
      python3 -m venv venv
      source venv/bin/activate
      ```
    - On Windows:
      ```bash
      python -m venv venv
      .\venv\Scripts\activate
      ```
3. **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4. **Run the Application:**
    You can now run the application using the instructions in the Usage section below.
## Troubleshooting
If the pull data proccess fails, run:
```bash
pip install --upgrade fastf1
```

## Usage

**DEFAULT GUI MENU:** To use the new GUI menu system, you can simply run:
```bash
python main.py
```

![GUI Menu Preview](./resources/gui-menu.png)

This will open a graphical interface where you can select the year and round of the race weekend you want to replay. This is still a new feature, so please report any issues you encounter.

**OPTIONAL CLI MENU:** To use the CLI menu system, you can simply run:
```bash
python main.py --cli
```

![CLI Menu Preview](./resources/cli-menu.gif)

This will prompt you with series of questions and a list of options to make your choice from using the arrow keys and enter key.

If you would already know the year and round number of the session you would like to watch, you run the commands directly as follows:

Run the main script and specify the year and round:
```bash
python main.py --viewer --year 2025 --round 12
```

To run without HUD:
```bash
python main.py --viewer --year 2025 --round 12 --no-hud
```

To run a Sprint session (if the event has one), add `--sprint`:
```bash
python main.py --viewer --year 2025 --round 12 --sprint
```

The application will load a pre-computed telemetry dataset if you have run it before for the same event. To force re-computation of telemetry data, use the `--refresh-data` flag:
```bash
python main.py --viewer --year 2025 --round 12 --refresh-data
```

### Qualifying Session Replay

To run a Qualifying session replay, use the `--qualifying` flag:
```bash
python main.py --viewer --year 2025 --round 12 --qualifying
```

To run a Sprint Qualifying session (if the event has one), add `--sprint`:
```bash
python main.py --viewer --year 2025 --round 12 --qualifying --sprint
```

## Accuracy and data quality

F1's timing feeds are not always clean, and two problems were worth fixing
properly rather than living with.

**Leaderboard order.** The running order used to be wrong through the first few
corners, disturbed by pit stops, and scrambled at the flag. All three came from
ranking cars by projecting their coordinates onto the track, and the position
feed is not good enough for that. Ranking now uses the speed-integrated
distance channel, with the starting grid seeding lap one and the official
result taking over at the chequered flag. Measured against official timing for
the 2026 Hungarian Grand Prix:

| | Before | After |
|---|---|---|
| Exact at a line crossing | 57.6% | **98.4%** (100% within one place) |
| Worst error | 21 places | **1 place** |
| Order at lights out | 10.4 places out | **exact** |
| Final classification | 1.8 places out | **exact** |

See [src/lib/classification.py](./src/lib/classification.py).

**Lap times and gaps.** The tower's numbers come from the same lap data the
official timing uses. Checked against the 2026 Hungarian Grand Prix at four
points in the race, last lap times matched official timing exactly in all 88
comparisons, personal bests agreed in all 88, and the session best matched
both value and holder.

**Cars freezing on track.** Occasionally a session's position feed degrades and
only locates a car every two or three seconds, so cars appear to freeze and
then jump. Where that happens they are now walked along the circuit at the
speed the telemetry says they were doing; live mode additionally carries a car
forward when the feed has lost it entirely. In the worst part of that same race
this took live mode from 79% frozen frames to 5.7%, and the replay from 55% to
44%. It cannot be solved completely — the coordinates were never transmitted —
but it is rare: the 2026 Belgian, 2025 Hungarian and 2024 Italian races all
show 0.0% frozen frames, and none of this engages on them. See
[docs/LiveMode.md](./docs/LiveMode.md#when-the-position-feed-falls-behind).

> **Rebuild old replays.** Anything cached before these changes still holds the
> old ordering and unrepaired positions. Re-run it once with `--refresh-data`.

## Documentation

| Guide | What it covers |
|-------|----------------|
| [docs/LiveMode.md](./docs/LiveMode.md) | Live sessions: data sources, latency tuning, troubleshooting |
| [telemetry.md](./telemetry.md) | The telemetry stream and its frame format |
| [docs/PitWallWindow.md](./docs/PitWallWindow.md) | Building your own insight window on the telemetry stream |
| [docs/InsightsMenu.md](./docs/InsightsMenu.md) | Adding an entry to the insights menu |
| [docs/DataSources.md](./docs/DataSources.md) | Every feed F1 publishes, what we read, and what each unused one offers |
| [docs/Testing.md](./docs/Testing.md) | Running the test suite |
| [roadmap.md](./roadmap.md) | Where the project is heading |

## Known Issues

- **conda environments** may need an extra package if you hit
  `arcade.application.NoOpenGLException: Unable to create an OpenGL 3.3+ context`:

  ```bash
  conda install -c conda-forge libstdcxx-ng
  ```

  Thanks to @el-mandaloriano for the fix (#12).
- **Cached replays are large** — roughly 450 MB for a race, in `computed_data/`.

## Contributing

Contributions are welcome — issues, ideas and pull requests alike.

- Keep a pull request focused on one feature or fix.
- Run `python -m pytest` before opening it; CI runs the same suite.
- Include a screenshot or short recording for anything visual.

See [roadmap.md](./roadmap.md) for where the project is heading, and
[contributors.md](./contributors.md) for the people whose work is already in
here.

## 📝 License

MIT — see [LICENSE](./LICENSE).

Pitwall builds on an MIT-licensed open-source codebase; the original copyright
notice is preserved in the licence file, as MIT requires. Everyone whose work is
in here is listed in [contributors.md](./contributors.md).

## ⚠️ Disclaimer

No copyright infringement intended. Formula 1 and related trademarks are the property of their respective owners. All data used is sourced from publicly available APIs and is used for educational and non-commercial purposes only.

---

Built and maintained by [Armin](https://github.com/Rm1n90)
