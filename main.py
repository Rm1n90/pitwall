from src.f1_data import get_race_telemetry, enable_cache, get_circuit_rotation, load_session, get_quali_telemetry, list_rounds, list_sprints
from src.run_session import run_arcade_replay, launch_insights_menu
from src.interfaces.qualifying import run_qualifying_replay
import sys
from src.cli.race_selection import cli_load
from src.gui.race_selection import RaceSelectionWindow
from PySide6.QtWidgets import QApplication
from src.lib.practice import is_practice, practice_label
from src.lib.season import get_season
import logging


def _arg_value(name, default=None, cast=str):
    """Read the value that follows ``name`` in argv, if present."""
    if name not in sys.argv:
        return default
    index = sys.argv.index(name) + 1
    if index >= len(sys.argv):
        return default
    try:
        return cast(sys.argv[index])
    except (TypeError, ValueError):
        print(f"Ignoring invalid value for {name}: {sys.argv[index]!r}")
        return default


def session_label(session_type):
    """The name to show in the window title for a session type."""
    if is_practice(session_type):
        return practice_label(session_type)
    return "Sprint" if session_type == "S" else "Race"


def run_live_auth():
    """Handle the Formula 1 sign-in helper flags. Returns an exit code."""
    from src.live import auth

    if "--live-login" in sys.argv:
        return auth.sign_in()
    if "--live-logout" in sys.argv:
        return auth.sign_out()
    return auth.print_status()


def run_live():
    """Watch the session that is running right now.

    Returns the process exit code so the caller can propagate failures.
    """
    from src.live.config import (
        SOURCE_AUTO, SOURCE_SIMULATED, VALID_SOURCES, LiveConfig,
    )
    from src.live.session import LiveSessionUnavailable, run_live_session

    source = _arg_value("--live-source", SOURCE_AUTO)
    if source not in VALID_SOURCES:
        print(f"Unknown --live-source {source!r}; "
              f"expected one of {', '.join(VALID_SOURCES)}")
        return 2

    config = LiveConfig(
        source=source,
        delay_s=_arg_value("--live-delay", None, float),
        no_auth="--live-no-auth" in sys.argv,
        record_path=_arg_value("--live-record"),
        simulated_speed=_arg_value("--live-speed", 1.0, float),
        simulated_start_offset_s=_arg_value("--live-offset", 0.0, float),
    )

    session_path = _arg_value("--live-path")
    if config.source == SOURCE_SIMULATED and not session_path:
        print("The simulated source needs --live-path "
              "(for example 2026/2026-07-26_Hungarian_Grand_Prix/2026-07-26_Race/)")
        return 2

    enable_cache()
    try:
        run_live_session(
            config=config,
            session_path=session_path,
            ready_file=_arg_value("--ready-file"),
            visible_hud="--no-hud" not in sys.argv,
            refresh_track="--refresh-data" in sys.argv,
        )
    except LiveSessionUnavailable as exc:
        print(f"\n{exc}\n")
        return 1
    return 0

def main(year=None, round_number=None, playback_speed=1, session_type='R', visible_hud=True, ready_file=None, show_telemetry_viewer=True):
  print(f"Loading F1 {year} Round {round_number} Session '{session_type}'")
  session = load_session(year, round_number, session_type)

  print(f"Loaded session: {session.event['EventName']} - {session.event['RoundNumber']} - {session_type}")

  # Enable cache for fastf1
  enable_cache()

  if session_type == 'Q' or session_type == 'SQ':

    # Get the drivers who participated and their lap times

    qualifying_session_data = get_quali_telemetry(session, session_type=session_type)

    # Run the arcade screen showing qualifying results

    title = f"{session.event['EventName']} - {'Sprint Qualifying' if session_type == 'SQ' else 'Qualifying Results'}"
    
    run_qualifying_replay(
      session=session,
      data=qualifying_session_data,
      title=title,
      ready_file=ready_file,
    )

  else:

    # Get the drivers who participated in the race

    race_telemetry = get_race_telemetry(session, session_type=session_type)

    # Get example lap for track layout
    # Qualifying lap preferred for DRS zones (fallback to fastest race lap (no DRS data))
    example_lap = None
    
    try:
        print("Attempting to load qualifying session for track layout...")
        quali_session = load_session(year, round_number, 'Q')
        if quali_session is not None and len(quali_session.laps) > 0:
            fastest_quali = quali_session.laps.pick_fastest()
            if fastest_quali is not None:
                quali_telemetry = fastest_quali.get_telemetry()
                if 'DRS' in quali_telemetry.columns:
                    example_lap = quali_telemetry
                    print(f"Using qualifying lap from driver {fastest_quali['Driver']} for DRS Zones")
    except Exception as e:
        print(f"Could not load qualifying session: {e}")

    # fallback: Use fastest race lap
    if example_lap is None:
        fastest_lap = session.laps.pick_fastest()
        if fastest_lap is not None:
            example_lap = fastest_lap.get_telemetry()
            print("Using fastest race lap (DRS detection may use speed-based fallback)")
        else:
            print("Error: No valid laps found in session")
            return

    drivers = session.drivers

    # Get circuit rotation

    circuit_rotation = get_circuit_rotation(session)

    # Corner numbers and the pit lane, for drawing the circuit
    circuit_info = None
    try:
        circuit_info = session.get_circuit_info()
    except Exception as e:
        print(f"Corner markers unavailable: {e}")

    # Real stationary times, published in the timing archive
    pit_stop_times = None
    try:
        from src.lib.pit_stops import fetch_for_session
        pit_stop_times = fetch_for_session(session)
    except Exception as e:
        print(f"Pit stop times unavailable: {e}")

    # Team radio clips, published alongside the timing data
    team_radio = []
    try:
        from src.lib.team_radio import fetch_for_session, to_payload
        offset = float(session.laps["LapStartTime"].dropna().min().total_seconds()) \
            if "LapStartTime" in session.laps else 0.0
        team_radio = to_payload(fetch_for_session(session, offset))
    except Exception as e:
        print(f"Team radio unavailable: {e}")

    # Driver portraits, fetched once and kept on disk
    portraits = {}
    try:
        from src.lib.driver_images import fetch_for_session as fetch_portraits
        portraits = fetch_portraits(session)
    except Exception as e:
        print(f"Driver portraits unavailable: {e}")

    pit_lane = None
    try:
        from src.lib.pit_lane import get_pit_lane
        pit_lane = get_pit_lane(
            session, year, session.event.get('EventName'),
            event_key=f"{session.event.get('EventName')}_{year}",
        )
    except Exception as e:
        print(f"Pit lane unavailable: {e}")
    
    # Prepare session info for display banner
    session_info = {
        'event_name': session.event.get('EventName', ''),
        'circuit_name': session.event.get('Location', ''),  # Circuit location/name
        'country': session.event.get('Country', ''),
        'year': year,
        'round': round_number,
        'date': session.event.get('EventDate', '').strftime('%B %d, %Y') if session.event.get('EventDate') else '',
        'total_laps': race_telemetry['total_laps'],
        'circuit_length_m': float(example_lap["Distance"].max()) if example_lap is not None and "Distance" in example_lap else None,
    }

    # Launch insights menu (always shown with replay)
    launch_insights_menu()
    print("Launching insights menu...")

    # Run the arcade replay

    run_arcade_replay(
      frames=race_telemetry['frames'],
      track_statuses=race_telemetry['track_statuses'],
      example_lap=example_lap,
      drivers=drivers,
      playback_speed=playback_speed,
      driver_colors=race_telemetry['driver_colors'],
      title=f"{session.event['EventName']} - {session_label(session_type)}",
      total_laps=race_telemetry['total_laps'],
      circuit_rotation=circuit_rotation,
      visible_hud=visible_hud,
      ready_file=ready_file,
      session_info=session_info,
      session=session,
      enable_telemetry=True,
      race_control_messages=race_telemetry.get('race_control_messages', []),
      circuit_info=circuit_info,
      pit_lane=pit_lane,
      pit_stop_times=pit_stop_times,
      team_radio=team_radio,
      portraits=portraits,
      session_type=session_type
    )

if __name__ == "__main__":

  if "--verbose" not in sys.argv:# fastf1 logging is disabled by default
    logging.getLogger("fastf1").setLevel(logging.CRITICAL)

  if "--cli" in sys.argv:
    # Run the CLI
    cli_load()
    sys.exit(0)

  if any(flag in sys.argv for flag in
         ("--live-login", "--live-logout", "--live-auth")):
    # Manage the optional Formula 1 sign-in used by the SignalR feed
    sys.exit(run_live_auth())

  if "--live" in sys.argv:
    # Watch the session that is happening right now
    sys.exit(run_live())

  if "--year" in sys.argv:
    year_index = sys.argv.index("--year") + 1
    year = int(sys.argv[year_index])
  else:
    year = get_season()  # Default year

  if "--round" in sys.argv:
    round_index = sys.argv.index("--round") + 1
    round_number = int(sys.argv[round_index])
  else:
    round_number = 12  # Default round number

  if "--list-rounds" in sys.argv:
    list_rounds(year)
  elif "--list-sprints" in sys.argv:
    list_sprints(year)
  else:
    playback_speed = 1

  if "--viewer" in sys.argv:
  
    visible_hud = True
    if "--no-hud" in sys.argv:
      visible_hud = False

    # Session type selection
    if "--practice" in sys.argv:
      number = _arg_value("--practice", 1, int)
      if number not in (1, 2, 3):
        print(f"Practice sessions are numbered 1 to 3, not {number}")
        sys.exit(2)
      session_type = f"FP{number}"
    elif "--sprint-qualifying" in sys.argv:
      session_type = 'SQ'
    elif "--sprint" in sys.argv:
      session_type = 'S'
    elif "--qualifying" in sys.argv:
      session_type = 'Q'
    else:
      session_type = 'R'


    # Optional ready-file path used when spawned from the GUI to signal ready state
    ready_file = None
    if "--ready-file" in sys.argv:
      idx = sys.argv.index("--ready-file") + 1
      if idx < len(sys.argv):
        ready_file = sys.argv[idx]

    main(year, round_number, playback_speed, session_type=session_type, visible_hud=visible_hud, ready_file=ready_file)
    sys.exit(0)

  # Run the GUI

  app = QApplication(sys.argv)
  win = RaceSelectionWindow()
  win.show()
  sys.exit(app.exec())