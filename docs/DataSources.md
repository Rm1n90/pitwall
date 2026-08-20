# Data Sources

What Pitwall reads today, what else is available, and what each unused source
would let us show. Everything here was checked against the 2026 Hungarian
Grand Prix feed rather than taken from documentation.

## Where data comes from

| Source | Auth | Used for |
|--------|------|----------|
| **F1 live timing** (SignalR + static archive) | Optional F1 account for car data | Live sessions |
| **FastF1** | None | Replays, schedule, circuit geometry |
| **Jolpica** (Ergast successor) | None | Not used yet — championship standings, history |
| **OpenF1** | Free tier is historical only | Not used |

## F1 publishes 33 feeds. We read 11.

### In use

`SessionInfo` · `SessionStatus` · `DriverList` · `TimingData` · `TimingAppData`
· `WeatherData` · `LapCount` · `TrackStatus` · `RaceControlMessages` ·
`Position.z` · `CarData.z` · `ExtrapolatedClock` · `PitStopSeries`

`PitStopSeries` is not part of the SignalR subscription — subscribing to it
returns nothing. It is only in the static archive, so a replay fetches it for
the session and a live session polls it slowly alongside the main feed.

`ExtrapolatedClock` is named for what it expects of a client. It is published
when the clock starts or stops, not every second, and while `Extrapolating` is
set the countdown has to be continued from `Utc` rather than read off
`Remaining`. Under a red flag `Extrapolating` goes false and the value stands.

### Available and worth having

| Feed | What it carries | What it would give us |
|------|-----------------|-----------------------|
| **TimingStats** | Personal best lap, best sector times with field position, best speeds at each trap | A proper timing tower: purple/green sector colouring, speed trap rankings |
| **TyreStintSeries** | Every stint for every driver with compound, age and whether the set was new | A full strategy chart without deriving it from lap data |
| **OvertakeSeries** | Timestamped overtake counts per driver | Overtake markers on the progress bar, an "on the move" indicator |
| **LapSeries** | Each driver's position at the end of every lap | The classic position-change chart across the race |
| **ChampionshipPrediction** | Live projected championship positions for drivers and teams | "If the race ended now" standings |
| **TeamRadio** | Timestamped MP3 clips per driver | Radio messages on the timeline, playable |
| **CurrentTyres** | Current compound and whether new | Simpler and more direct than deriving from `TimingAppData` |
| **TopThree** | Podium positions | A broadcast-style podium panel |
| **DriverRaceInfo** | Position and gap per driver | Cross-check for our own classification |

### Available, lower value

`ArchiveStatus` · `AudioStreams` · `ContentStreams` · `DriverTracker` ·
`Heartbeat` · `PitLaneTimeCollection` (empty in the sessions checked) ·
`PitStop` (single latest stop, superseded by `PitStopSeries`) · `RcmSeries` ·
`SessionData` · `TimingDataF1` · `TlaRcm` · `WeatherDataSeries`

## Data we already fetch but do not use

These arrive in every session and cost nothing extra.

| Field | Where | What it would give us |
|-------|-------|-----------------------|
| **Mini-sector segments** | `TimingData.Lines[car].Sectors[].Segments[].Status` | The circuit split into 22 timed segments (7 + 9 + 6 at the Hungaroring), each with a status per driver. This is what drives the coloured mini-sector map in F1's own app. Observed status codes are `0`, `2048`, `2049`, `2052`, `2064`; the mapping to yellow/green/purple needs confirming against a qualifying session before it is used for colour. |
| **Speed traps** | `TimingData.Lines[car].Speeds` | `I1`, `I2`, `FL`, `ST` speeds with personal and overall best flags |
| **Sector times** | `TimingData.Lines[car].Sectors[].Value` | Live sector times with best-of-session flags |
| **Headshots and country** | `DriverList[car].HeadshotUrl`, `CountryCode` | Driver portraits and flags in the leaderboard |
| **Corner positions** | FastF1 `session.get_circuit_info().corners` | 16 corners with coordinates, numbers and letters — corner labels on the map |
| **Marshal sectors** | FastF1 `get_circuit_info().marshal_sectors` | 19 marshal sectors with coordinates. Combined with the sector referenced in a yellow-flag race control message, we could highlight *exactly* the stretch of track that is under a flag. |
| **Elevation** | `Z` in the position feed | Circuits are not flat. Z is already decoded and thrown away. |

## Other APIs

**Jolpica** (`api.jolpi.ca/ergast/f1/...`) — the maintained Ergast successor,
no key required. Championship standings, full historical results, qualifying
results, constructor data. Verified working: 2025 driver standings returned
NOR 423, VER 421, PIA 410. This is the natural source for season context that
the live feed does not carry.

**OpenF1** (`api.openf1.org`) — a friendlier reshaping of the same F1 feed.
Free tier is historical only; live data needs a paid account. We already read
the underlying feed directly, so this mainly matters as a fallback.

## What is not available

- **Real safety car GPS.** F1 does not transmit it. Ours is simulated ahead of
  the leader.
- **Pit lane geometry.** No feed describes it, but it is now derived: cars are
  flagged `InPit`, so their coordinates during a stop trace the pit lane. Every
  stop gives an independent trace and the middle one is kept. At the 2025
  Hungarian Grand Prix, 29 traces agreed within 360-394 m. A session whose
  position feed has degraded produces traces of zero length and is rejected in
  favour of an earlier year at the same circuit. See `src/lib/pit_lane.py`.
- **Tyre temperatures, fuel load, ERS deployment.** Teams have these; the
  public feed does not.
