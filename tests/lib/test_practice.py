"""Tests for practice session timing.

Practice has no grid and no finishing order: the running order is simply who
has set the quickest lap so far, which changes the moment a lap is completed.
"""

import unittest

from src.lib.practice import (
    CompletedLap, PracticeTiming, is_practice, practice_label, read_laps,
    time_remaining,
)


def lap(code, number, time_s, end_s, deleted=False):
    return CompletedLap(code=code, lap_number=number, lap_time_s=time_s,
                        end_time_s=end_s, deleted=deleted)


class SessionTypeTest(unittest.TestCase):

    def test_practice_types_are_recognised(self):
        for name in ("FP1", "FP2", "FP3"):
            self.assertTrue(is_practice(name), name)

    def test_other_session_types_are_not_practice(self):
        for name in ("R", "S", "Q", "SQ"):
            self.assertFalse(is_practice(name), name)

    def test_labels_read_the_way_a_timing_screen_reads(self):
        self.assertEqual(practice_label("FP1"), "Practice 1")
        self.assertEqual(practice_label("FP3"), "Practice 3")


class BestLapTest(unittest.TestCase):

    def setUp(self):
        self.timing = PracticeTiming(
            [
                lap("VER", 3, 80.5, 300.0),
                lap("VER", 8, 79.9, 700.0),
                lap("NOR", 4, 80.1, 400.0),
            ],
            codes=["VER", "NOR", "LEC"],
        )

    def test_no_lap_yet_means_no_time(self):
        self.assertIsNone(self.timing.best_at("VER", 0.0))
        self.assertIsNone(self.timing.best_at("LEC", 9999.0))

    def test_a_lap_counts_from_the_moment_it_is_completed(self):
        self.assertIsNone(self.timing.best_at("VER", 299.9))
        self.assertAlmostEqual(self.timing.best_at("VER", 300.0), 80.5)

    def test_only_an_improvement_replaces_the_best(self):
        self.assertAlmostEqual(self.timing.best_at("VER", 500.0), 80.5)
        self.assertAlmostEqual(self.timing.best_at("VER", 700.0), 79.9)

    def test_a_slower_later_lap_does_not_replace_the_best(self):
        timing = PracticeTiming(
            [lap("VER", 1, 79.0, 100.0), lap("VER", 2, 85.0, 200.0)],
            codes=["VER"],
        )
        self.assertAlmostEqual(timing.best_at("VER", 250.0), 79.0)

    def test_deleted_laps_do_not_count(self):
        # A lap deleted for track limits never appears on the timing screen.
        timing = PracticeTiming(
            [lap("VER", 1, 78.0, 100.0, deleted=True),
             lap("VER", 2, 80.0, 200.0)],
            codes=["VER"],
        )
        self.assertIsNone(timing.best_at("VER", 150.0))
        self.assertAlmostEqual(timing.best_at("VER", 250.0), 80.0)


class OrderTest(unittest.TestCase):

    def setUp(self):
        self.timing = PracticeTiming(
            [
                lap("VER", 3, 80.5, 300.0),
                lap("NOR", 4, 80.1, 400.0),
                lap("VER", 8, 79.9, 700.0),
            ],
            codes=["VER", "NOR", "LEC"],
        )

    def test_before_anyone_runs_the_order_is_stable(self):
        self.assertEqual(self.timing.order_at(0.0), ["VER", "NOR", "LEC"])

    def test_the_only_driver_with_a_time_leads(self):
        self.assertEqual(self.timing.order_at(300.0)[0], "VER")

    def test_a_quicker_lap_takes_the_top_spot(self):
        self.assertEqual(self.timing.order_at(400.0), ["NOR", "VER", "LEC"])

    def test_improving_takes_it_back(self):
        self.assertEqual(self.timing.order_at(700.0), ["VER", "NOR", "LEC"])

    def test_drivers_without_a_time_line_up_behind_those_with_one(self):
        order = self.timing.order_at(400.0)
        self.assertEqual(order[-1], "LEC")

    def test_positions_are_one_based_and_cover_every_driver(self):
        positions = self.timing.positions_at(400.0)
        self.assertEqual(positions, {"NOR": 1, "VER": 2, "LEC": 3})


class SessionBestTest(unittest.TestCase):

    def test_session_best_tracks_the_quickest_lap_so_far(self):
        timing = PracticeTiming(
            [lap("VER", 3, 80.5, 300.0), lap("NOR", 4, 80.1, 400.0)],
            codes=["VER", "NOR"],
        )
        self.assertIsNone(timing.session_best_at(0.0))
        self.assertAlmostEqual(timing.session_best_at(300.0), 80.5)
        self.assertAlmostEqual(timing.session_best_at(400.0), 80.1)

    def test_gap_is_measured_to_the_session_best(self):
        timing = PracticeTiming(
            [lap("VER", 3, 80.5, 300.0), lap("NOR", 4, 80.1, 400.0)],
            codes=["VER", "NOR"],
        )
        self.assertAlmostEqual(timing.gap_at("VER", 400.0), 0.4, places=3)
        self.assertAlmostEqual(timing.gap_at("NOR", 400.0), 0.0, places=3)
        self.assertIsNone(timing.gap_at("VER", 0.0))


class LapCountTest(unittest.TestCase):

    def test_laps_completed_counts_every_lap_including_deleted_ones(self):
        # A deleted lap still put mileage on the car.
        timing = PracticeTiming(
            [lap("VER", 1, 80.0, 100.0, deleted=True),
             lap("VER", 2, 81.0, 200.0)],
            codes=["VER"],
        )
        self.assertEqual(timing.laps_completed("VER", 50.0), 0)
        self.assertEqual(timing.laps_completed("VER", 150.0), 1)
        self.assertEqual(timing.laps_completed("VER", 250.0), 2)


class SeriesTest(unittest.TestCase):

    def test_best_series_matches_point_lookups(self):
        # The frame builder needs one value per driver per frame, so the
        # vectorised path has to agree with the scalar one.
        timing = PracticeTiming(
            [lap("VER", 3, 80.5, 300.0), lap("VER", 8, 79.9, 700.0)],
            codes=["VER"],
        )
        timeline = [0.0, 299.0, 300.0, 500.0, 700.0, 900.0]
        series = timing.best_series("VER", timeline)

        self.assertEqual(len(series), len(timeline))
        for index, t in enumerate(timeline):
            expected = timing.best_at("VER", t)
            if expected is None:
                self.assertNotEqual(series[index], series[index])  # NaN
            else:
                self.assertAlmostEqual(float(series[index]), expected, places=4)


class StubLaps:
    """Enough of a FastF1 laps table for the reader to work on."""

    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        return enumerate(self._rows)


class StubSession:

    def __init__(self, rows, total_s=3600.0):
        self.laps = StubLaps(rows)
        self.session_start_time = Delta(0.0)
        self.t0_date = None
        self._total_s = total_s


class Delta:
    """Stands in for a pandas Timedelta."""

    def __init__(self, seconds):
        self._seconds = seconds

    def total_seconds(self):
        return self._seconds


def row(code, number, lap_time, end, deleted=False, **extra):
    data = {
        "Driver": code,
        "LapNumber": number,
        "LapTime": Delta(lap_time) if lap_time is not None else None,
        "Time": Delta(end) if end is not None else None,
        "Deleted": deleted,
    }
    data.update(extra)
    return data


class ReadLapsTest(unittest.TestCase):

    def test_laps_are_read_onto_the_replay_clock(self):
        session = StubSession([row("VER", 3, 80.5, 1000.0)])
        laps = read_laps(session, time_offset_s=900.0)

        self.assertEqual(len(laps), 1)
        self.assertEqual(laps[0].code, "VER")
        self.assertAlmostEqual(laps[0].end_time_s, 100.0)
        self.assertAlmostEqual(laps[0].lap_time_s, 80.5)

    def test_deleted_laps_are_kept_but_marked(self):
        session = StubSession([row("VER", 3, 80.5, 1000.0, deleted=True)])
        laps = read_laps(session, time_offset_s=0.0)

        self.assertTrue(laps[0].deleted)

    def test_laps_without_a_time_are_skipped(self):
        # An in-progress lap has no lap time yet.
        session = StubSession([row("VER", 3, None, 1000.0),
                               row("VER", 4, 80.0, 1100.0)])
        laps = read_laps(session, time_offset_s=0.0)

        self.assertEqual([lap.lap_number for lap in laps], [4])

    def test_laps_without_an_end_time_are_skipped(self):
        session = StubSession([row("VER", 3, 80.0, None)])
        self.assertEqual(read_laps(session, time_offset_s=0.0), [])

    def test_a_session_with_no_laps_reads_as_empty(self):
        self.assertEqual(read_laps(StubSession([]), 0.0), [])

    def test_a_malformed_row_does_not_sink_the_session(self):
        # A replay is still worth watching without one lap.
        session = StubSession([{"Driver": "VER"},
                               row("NOR", 1, 80.0, 100.0)])
        laps = read_laps(session, time_offset_s=0.0)

        self.assertEqual([lap.code for lap in laps], ["NOR"])


class SessionLengthTest(unittest.TestCase):

    def test_the_clock_counts_down_to_the_scheduled_end(self):
        remaining = time_remaining(t=0.0, session_length_s=3600.0)
        self.assertAlmostEqual(remaining, 3600.0)

    def test_the_clock_stops_at_zero(self):
        self.assertAlmostEqual(time_remaining(4000.0, 3600.0), 0.0)

    def test_the_clock_runs_down_with_the_replay(self):
        self.assertAlmostEqual(time_remaining(600.0, 3600.0), 3000.0)


if __name__ == "__main__":
    unittest.main()
