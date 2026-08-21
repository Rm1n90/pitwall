# MotoGP Data Sources

What is available for a MotoGP replay, what is not, and what each gap costs us.
Everything here was checked by calling the endpoints and downloading the files
on 20 August 2026, not taken from documentation.

## Summary

MotoGP has a complete, unauthenticated public API for **schedule, entries,
classifications, standings and a live timing feed**, plus official **per-lap
and per-sector timing sheets** as PDFs going back years, plus official
**circuit outlines as SVG**.

It has **no public positional feed**. There is no MotoGP equivalent of F1's
`Position.z`: no x/y, no GPS, no speed trace. Bikes carry telemetry boxes and
Dorna renders 3D tracking in its paid TimingPass product, but nothing of that
reaches an open endpoint.

That single gap defines the whole design. Where the F1 pipeline is *given*
positions and repairs them, the MotoGP pipeline has to *construct* them, from
four intermediate times a lap and a track centreline. The machinery for that
already exists in `src/lib/track_geometry.py` — `TrackLine.point_at()` turns a
distance along the lap into a coordinate, which is exactly the primitive a
sector-driven replay needs.

## Where data comes from

| Source | Auth | What it gives |
|--------|------|---------------|
| **`api.motogp.pulselive.com/motogp/v1`** | None | Seasons, events, sessions, classifications, entries, grids, standings, riders, teams, circuits, live timing |
| **`resources.motogp.com/files/results/...`** | None | Official timing sheets per session as PDF: every lap, every sector, every speed trap |
| **`photos.motogp.com/events-admin/...`** | None | Circuit outline SVG, rider portraits, team pictures |
| **OpenStreetMap / Overpass** | None | Circuit centrelines in real-world coordinates, as a cross-check |
| **TimingPass** (`timingpass.motogp.com`) | Paid subscription | Sector-by-sector live timing and 3D tracking. Behind Imperva; not used |

The same host answers on `api.pulselive.motogp.com`, byte for byte. Either
works; the `api.motogp.pulselive.com` form is the one the site itself uses.

## The API, endpoint by endpoint

Base: `https://api.motogp.pulselive.com/motogp/v1`

### Results

| Endpoint | Returns |
|----------|---------|
| `/results/seasons` | Every season back to 1949 with a UUID and a `current` flag |
| `/results/events?seasonUuid=&isFinished=` | 33 events for 2025, each with circuit, country and links to the event PDFs |
| `/results/categories?eventUuid=` | MotoGP / Moto2 / Moto3 (and MotoE where it ran) UUIDs for that event |
| `/results/sessions?eventUuid=&categoryUuid=` | FP1, PR, FP2, Q1, Q2, SPR, WUP, RAC with start time, track condition, air/ground temperature, humidity, and the session's PDF links |
| `/results/session/{id}/classification` | Final order: position, rider, team, constructor, average speed, gap to first, laps, total time, points, status. Plus a `records` block with pole lap, fastest lap, lap record and whether the record fell |
| `/results/event/{id}/category/{id}/grid` | Grid slots with qualifying times |
| `/results/standings?seasonUuid=&categoryUuid=` | Championship table |
| `/event/{id}/entry?categoryUuid=` | Entry list with team and constructor |

### Broadcast

| Endpoint | Returns |
|----------|---------|
| `/events?seasonYear=` | 46 entries for 2026 — 22 Grands Prix plus tests and presentations. Each carries the full session timetable with ISO start and end times, `num_laps`, `has_timing`, `is_live` and `status` |
| `/riders?seasonYear=` | 95 riders with portrait, helmet and bike images, team colour and text colour, career step |
| `/riders/{legacyId}/stats` | Career wins, podiums, poles, fastest laps |
| `/teams?categoryUuid=&seasonYear=` | Rosters and team colours |

`/events` is the schedule source for live mode. It is what `src/live/schedule.py`
does with FastF1's event schedule, only richer: F1 needs the session start
inferred, MotoGP publishes `date_start`, `date_end`, `status` and `is_live` per
session per class.

### Live timing

`GET /timing-gateway/livetiming-lite` — one JSON document, no auth, no key.

```
head:  championship_id, category, circuit_id, circuit_name, event_id,
       event_tv_name, event_shortname, date, num_laps, session_id,
       session_type, session_name, session_shortname, duration, remaining,
       session_status_id, session_status_name
rider: order, rider_id, rider_number, rider_name, rider_surname,
       rider_shortname, rider_nation, color, text_color, pos,
       status_name, status_id, lap_time, num_lap, last_lap_time, last_lap,
       trac_status, team_name, bike_name, bike_id, gap_first, gap_prev, on_pit
```

`color` and `text_color` are per-rider hex, so the timing tower gets its
palette straight from the feed rather than from a hand-kept table the way F1
driver colours do.

What it does **not** carry: coordinates, sector times, speed, tyre, weather.
`lap_time` is elapsed session time at the rider's last crossing and `gap_first`
is the gap at that crossing, so **the feed advances once per rider per lap** —
about every 90 seconds each in MotoGP, not 4 Hz.

Values still to confirm against a running session: what `trac_status`,
`status_id` and `session_status_id` mean beyond the `F` (finished) and `CL`
(classified) seen on a finished session. The endpoint holds the last session's
final state between sessions, so it can be sampled at any time — but the codes
that only appear live have to be recorded live.

## The timing sheets are the real prize

Every session publishes an **Analysis** PDF at a predictable URL:

```
https://resources.motogp.com/files/results/{year}/{EVT}/{Class}/{SES}/Analysis.pdf
```

for example `.../2025/THA/MotoGP/RAC/Analysis.pdf`. The URLs come back from
`/results/sessions` in `session_files`, so nothing has to be guessed.

Inside, for every rider, every lap:

| Column | Meaning |
|--------|---------|
| Lap | Lap number |
| Lap Time | `1'31.172` |
| T1 – T4 | Finish line → i1, i1 → i2, i2 → i3, i3 → finish |
| Speed | Speed trap, km/h |

and per run: front and rear tyre compound, whether each was new, run count,
total/full/valid laps. Cancelled laps and pit-lane crossings are flagged.

A race is four timing points a lap — roughly one every 1.1 km — for every rider,
plus a speed at the trap, plus tyre compound and age. That is a much thinner
signal than F1's 4 Hz position feed, but it is enough to place a bike on track
to within a corner or two, and it is enough for every panel the app already has
except the on-track speed trace.

Other sheets worth reading: `LapChart.pdf` (position of every rider at the end
of every lap — a free ground truth to validate reconstruction against),
`Grid.pdf`, `FastLapSequence.pdf`, `AverageSpeed.pdf`, `Session.pdf`
(session-level notes and incidents), `analysisbylap.pdf`.

These are PDFs with a two-column layout and riders that flow across pages, so
extraction needs a word-position-aware reader (`pdfplumber` or `pymupdf`;
neither is currently a dependency) rather than `pdftotext`. The layout has been
stable for years, which makes a parser worth writing once.

**Licensing.** Every sheet carries a Dorna copyright notice restricting
reproduction and redistribution. Parsing them locally for a personal replay is
one thing; shipping the extracted data in the repository is another. Cache them
under `computed_data/` like FastF1's cache, fetched on demand per session,
and keep them out of version control.

## Track geometry

The app needs a centreline. Three sources, in order of preference:

**1. The official circuit SVG.** Every one of the 22 circuits on the 2026
calendar exposes one through `/events?seasonYear=`, at
`circuit.tracks[0].assets.info.path` — for example
`photos.motogp.com/events-admin/7/9/{trackId}/info/v2al-info.svg`. Each is a
1080×1080 viewBox holding the circuit as a stroked path, with corner numbers as
text. The track itself is the longest path in the file: 933 characters for
Mugello, 1147 for Valencia, against a few hundred for the numerals. Flatten the
Béziers to a polyline, then scale so the arc length matches the official length
that the same object publishes.

**2. `circuit.tracks[0]`** already gives the numbers the renderer wants:
`lenght` in metres (Valencia 4005, Mugello 5245), `width` (12 m),
`longest_straight` (876 m), `left_corners` and `right_corners`. `src/render/track.py`
currently infers width and corners; here they are stated.

**3. OpenStreetMap** as a fallback and a sanity check. Overpass returns the
main loop for circuits that never see F1 — Buriram comes back as a named
116-point way — in real-world coordinates, which is the only way to get true
north and elevation if a 3D view ever returns.

Two things the geometry sources do not give and that have to be established per
circuit, once:

- **Where the start/finish line sits** on the path. The SVGs carry a red
  element that is a candidate marker, but it has not been confirmed as the line.
- **Where intermediates i1, i2 and i3 sit.** The Analysis PDF header draws them
  on a small circuit diagram; their positions can be lifted from the PDF's
  vector graphics, or set by hand. Twenty-two circuits by three points is a
  one-off dataset, and getting it right is what separates bikes that sit in the
  correct corner from bikes that drift a few hundred metres out.

Until intermediates are placed properly, assuming distance fraction equals time
fraction of the best lap is a workable first approximation, and wrong by most on
circuits that mix a long straight with a tight infield.

## What each F1 concept becomes

| F1 | MotoGP | Where it comes from |
|----|--------|---------------------|
| Position (x, y) at 4 Hz | Reconstructed from 4 sector times a lap | Analysis PDF + centreline |
| Speed trace | Speed trap only, once a lap | Analysis PDF |
| Gear, throttle, brake, DRS | **Nothing.** No equivalent is published | — |
| Tyre compound and age | Front and rear compound, new or used, per run | Analysis PDF |
| Pit stops | `on_pit`, and pit-lane crossings flagged in the sheets | Live feed + PDF |
| Safety car | No safety car. Red flags, and long-lap penalties instead | Session PDF, live status |
| Track status / flags | `session_status_id`, `trac_status` | Live feed, meanings TBC |
| Race control messages | No feed. Penalties appear in the session PDF after the fact | Session PDF |
| Weather | Per session, not per frame: track condition, air, ground, humidity | `/results/sessions` |
| Driver colours | Per rider in the live feed, per team elsewhere | Live feed, `/teams` |
| Driver headshots | Rider portrait, helmet and bike images | `/riders` |
| Sprint | `SPR`, 12 laps, same shape as F1's sprint | Everywhere |
| Practice / qualifying | FP1, PR, FP2, Q1, Q2, WUP | Everywhere |

Two of these are worth calling out because they change the interface, not just
the data layer:

- **No throttle, brake, gear or DRS.** The driver info panel's pedal bars have
  no MotoGP counterpart. The panel needs a per-series layout, not a blanked-out
  F1 one.
- **Three classes race at every round.** MotoGP, Moto2 and Moto3 are separate
  sessions at the same event on the same circuit. The session picker gains a
  class dimension that F1 does not have, and one event yields nine to twelve
  replayable sessions rather than five.

## What this means for the architecture

`fastf1` is imported in ten files, and eight of those are one or two lines.
The real coupling is the shape of the object `get_race_telemetry()` returns —
`frames`, `driver_colors`, `track_statuses`, `race_control_messages`,
`total_laps`, `max_tyre_life`, `session_type` — and the per-driver channels
`frame_store.py` stores. Everything downstream of that dictionary is already
series-agnostic in practice: the renderer, the timing tower, the insights
windows and the telemetry stream all consume frames, not FastF1.

So the seam is already in the right place. The work is:

1. **A `Series` interface** covering what `main.py` and `race_selection.py`
   currently ask FastF1 for: list seasons, list events, list sessions, load a
   session, produce telemetry, produce circuit geometry and rotation.
2. **A MotoGP provider** behind it: pulselive for metadata and schedule,
   Analysis PDF for timing, SVG for geometry.
3. **A sector-to-frames builder** that walks each rider along the centreline
   between intermediates, at the pace their sector times imply. This is new
   code, but it is the mirror image of `rebuild_positions()`, which already
   walks a car along the line at the speed it was doing.
4. **Optional channels.** `frame_store.py` stores a fixed tuple of channels;
   `gear`, `drs`, `throttle` and `brake` need to become absent rather than
   zero, so panels can hide rather than show a flat line.
5. **A MotoGP live source** in `src/live/sources/`, polling
   `livetiming-lite`. The transport is trivial next to SignalR — an HTTP GET on
   a timer — but the frame builder has to interpolate a whole lap forward from
   one crossing, where the F1 builder interpolates a quarter second.

Validation has a free answer: `LapChart.pdf` states the order at the end of
every lap. A reconstruction that disagrees with it is wrong, and that check can
be a test rather than a judgement call.

## Alternatives considered

| Option | Verdict |
|--------|---------|
| **TimingPass** | The only source of live sector-by-sector data and 3D tracking. Subscription, and the config endpoint sits behind Imperva. Not pursued |
| **Sportradar MotoGP API** | Commercial, schedules and post-race results. Nothing the free API lacks |
| **Orange Cat Blacktop** | Free tier of 7,500 requests a month for schedules, results, riders, standings. A wrapper over what pulselive already gives us |
| **MotoSector** | An independent site offering free live timing and 3D tracking. Worth watching to see what it derives and how, but not a data source to depend on |
| **Community scrapers** (`racingmike_motogp_import`, `MarioJurado/MotoGP`, `manaswimishra/MotoGp-Data-Scraping`) | All read the same pulselive endpoints or scrape result tables. Useful as cross-references for field meanings, not as sources |

## Open questions

- What `trac_status`, `status_id` and `session_status_id` take as values during
  a running session, and whether anything appears in the live feed that a
  finished session does not show. Answer by recording a live session, the way
  `SignalRSource(record_path=...)` already does for F1.
- Whether the red element in the circuit SVGs is the start/finish line.
- Whether intermediate positions can be lifted from the Analysis PDF's vector
  header, or need to be placed by hand.
- How the live feed behaves under a red flag and across a session boundary.
- Whether Moto2 and Moto3 sheets share the MotoGP layout. They should; it is
  the same timekeeper.
