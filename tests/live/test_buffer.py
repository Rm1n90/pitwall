"""Tests for the growing live frame buffer."""

import pytest

from src.live.buffer import LiveFrameBuffer


def _fill(buffer, count, start=0):
    for index in range(start, start + count):
        buffer.append({"t": index})


class TestEmptyBuffer:
    def test_is_falsy_and_empty(self):
        buffer = LiveFrameBuffer()
        assert not buffer
        assert len(buffer) == 0
        assert buffer.latest is None
        assert buffer.latest_index == -1

    def test_indexing_an_empty_buffer_raises(self):
        with pytest.raises(IndexError):
            LiveFrameBuffer()[0]


class TestGrowingBuffer:
    def test_append_returns_absolute_indices(self):
        buffer = LiveFrameBuffer()
        assert buffer.append({"t": 0}) == 0
        assert buffer.append({"t": 1}) == 1

    def test_reports_length_and_latest(self):
        buffer = LiveFrameBuffer()
        _fill(buffer, 10)
        assert len(buffer) == 10
        assert buffer.latest == {"t": 9}
        assert buffer.latest_index == 9

    def test_supports_negative_indexing_and_iteration(self):
        buffer = LiveFrameBuffer()
        _fill(buffer, 5)
        assert buffer[-1] == {"t": 4}
        assert [frame["t"] for frame in buffer] == [0, 1, 2, 3, 4]

    def test_supports_slicing(self):
        buffer = LiveFrameBuffer()
        _fill(buffer, 5)
        assert [frame["t"] for frame in buffer[1:3]] == [1, 2]


class TestTrimming:
    def test_keeps_absolute_indices_after_trimming(self):
        buffer = LiveFrameBuffer(max_frames=20)
        _fill(buffer, 60)

        assert len(buffer) == 60
        assert buffer[59] == {"t": 59}
        assert buffer.offset > 0

    def test_clamps_indices_that_have_been_trimmed_away(self):
        # A viewer rewound a long way should stop at the oldest retained
        # frame rather than crashing the window.
        buffer = LiveFrameBuffer(max_frames=20)
        _fill(buffer, 60)

        assert buffer[0] == buffer[buffer.offset]

    def test_memory_stays_bounded(self):
        buffer = LiveFrameBuffer(max_frames=100)
        _fill(buffer, 5000)

        retained = len(list(buffer))
        assert retained <= 100 + max(1, 100 // 4)
