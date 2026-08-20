# Pitwall Roadmap

## Vision

Pitwall should be the best way for data-loving motorsport fans to explore a
session — live or after the fact. Your own pit wall: every car on track, every
lap time, every tyre decision, in one place, for whatever series you follow.

Formula 1 works today. The architecture is deliberately being pulled towards
being series-agnostic so MotoGP and others can slot in behind the same
interface.

## Now

- **Live sessions.** Watch a session as it happens with `python main.py --live`.
  See [docs/LiveMode.md](./docs/LiveMode.md).
- **Race, sprint and qualifying replays** with leaderboard, tyres, weather,
  safety car and driver telemetry.
- **Telemetry stream** so custom dashboards can run alongside the replay.

## Next

### Multi-series support

The largest piece of work, and the reason this project is no longer named after
one championship.

- Extract a series-agnostic session interface: schedule lookup, track geometry,
  driver list, position feed, timing feed.
- **MotoGP** first. Its timing data differs in shape from F1's, so the frame
  builder needs to stop assuming F1 concepts such as DRS zones and pit windows.
- Keep `src/live/sources/` transport-only, as it already is, so a new series
  means a new source plus a new frame builder, not a new application.

### Practice sessions

Combine the telemetry analysis used for qualifying with the track-position
replay used for races: compare runs, stints and lap times across a practice
session.

### Live mode depth

- Sector and mini-sector timing from the feed, which is already received but
  not yet visualised.
- Live gap and interval charts.
- Optional recording of a live session straight into a replayable file.

## Performance and user experience

- **Rendering cost.** Some UI elements are heavy enough to be noticeable on
  lower-end machines. Live mode adds a second producer thread, so this matters
  more than it used to.
- **UI density.** As features accumulate the window gets crowded. Preset view
  modes and better toggles would let people focus on what they care about
  without capping how much can be added.
- **Memory.** A full race holds a lot of frames. Live mode already bounds its
  buffer; the offline path could use the same treatment.

## Contributing

Issues, ideas and pull requests are all welcome — see the contributing notes in
the [README](./README.md#contributing).
