"""Decoding helpers for the F1 live timing feeds.

Both feeds the app can consume carry the same payloads, only wrapped
differently:

* the SignalR feed delivers ``[topic, payload, timestamp]`` lists (plus one
  keyframe snapshot when subscribing);
* the public static feed serves ``<topic>.jsonStream`` files where every line
  is a 12 character session timestamp followed by the payload.

The ``.z`` topics (``Position.z`` and ``CarData.z``) carry their payload as
base64 encoded raw-deflate data; everything else is plain JSON.
"""

import base64
import json
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, NamedTuple, Optional

# Length of the 'HH:MM:SS.mmm' prefix used in the static .jsonStream files.
TIMESTAMP_LENGTH = 12

# Topics whose payload is base64 + raw-deflate encoded.
COMPRESSED_TOPICS = ("Position.z", "CarData.z")

# CarData channel identifiers. Channel 45 (DRS) was dropped for the 2026
# regulations, so it is always read defensively.
CHANNEL_RPM = "0"
CHANNEL_SPEED = "2"
CHANNEL_GEAR = "3"
CHANNEL_THROTTLE = "4"
CHANNEL_BRAKE = "5"
CHANNEL_DRS = "45"

# Throttle and brake are percentages, but the feed publishes 104 when a car's
# pedal data is not currently being transmitted. Anything above 100 therefore
# means "unknown" rather than "more than full".
PEDAL_UNKNOWN_THRESHOLD = 100


class LiveMessage(NamedTuple):
    """A single decoded feed message.

    Attributes:
        topic: Topic name with any ``.z`` suffix stripped.
        data: Decoded JSON payload.
        stream_time: Session timestamp string as sent by F1, or ``''``.
    """

    topic: str
    data: Any
    stream_time: str = ""


def normalise_topic(topic: str) -> str:
    """Strip the compression suffix from a topic name."""
    return topic[:-2] if topic.endswith(".z") else topic


def decompress_payload(payload: str) -> dict:
    """Decode a base64 + raw-deflate payload from a ``.z`` topic."""
    raw = zlib.decompress(base64.b64decode(payload), -zlib.MAX_WBITS)
    return json.loads(raw.decode("utf-8-sig"))


def decode_payload(topic: str, payload: Any) -> Any:
    """Decode a payload for ``topic``, decompressing it when required."""
    if topic in COMPRESSED_TOPICS and isinstance(payload, str):
        return decompress_payload(payload)
    if isinstance(payload, str):
        # Non-compressed topics are occasionally delivered as a JSON string.
        stripped = payload.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return payload
    return payload


def parse_stream_line(topic: str, line: str) -> Optional[LiveMessage]:
    """Parse one line of a static ``<topic>.jsonStream`` file.

    Returns ``None`` when the line is empty or cannot be decoded, so that a
    single corrupt line never interrupts a live session.
    """
    line = line.strip("\r\n")
    if len(line) <= TIMESTAMP_LENGTH:
        return None

    stream_time = line[:TIMESTAMP_LENGTH]
    payload = line[TIMESTAMP_LENGTH:]
    try:
        data = decode_payload(topic, payload)
    except (ValueError, zlib.error, json.JSONDecodeError):
        return None

    return LiveMessage(normalise_topic(topic), data, stream_time)


def split_feed_lines(text: str):
    """Split feed text into lines.

    The feeds separate records with ``\r\n``, but a file read back through
    Python's universal newline translation will only have ``\n``. Both are
    handled here; ``str.splitlines`` is deliberately avoided because it also
    breaks on characters that can legitimately appear inside a message.
    """
    return text.replace("\r\n", "\n").split("\n")


def iter_stream_lines(topic: str, text: str) -> Iterator[LiveMessage]:
    """Yield every decodable message from a chunk of a ``.jsonStream`` file."""
    for line in split_feed_lines(text):
        message = parse_stream_line(topic, line)
        if message is not None:
            yield message


def split_trailing_partial(text: str) -> tuple:
    """Split ``text`` into complete lines and a trailing partial line.

    Polling the tail of a growing file will regularly cut a line in half. The
    partial tail is carried over to the next poll instead of being discarded.
    """
    index = text.rfind("\n")
    if index == -1:
        return "", text
    return text[: index + 1], text[index + 1:]


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    """Parse an F1 UTC timestamp into a timezone-aware ``datetime``.

    F1 sends timestamps such as ``2026-07-26T12:36:08.838571Z`` with a varying
    number of fractional digits, which ``datetime.fromisoformat`` cannot
    always handle, so fractional seconds are normalised to 6 digits first.
    """
    if not value or not isinstance(value, str):
        return None

    text = value.strip().rstrip("Zz")
    if not text:
        return None

    if "." in text:
        head, _, fraction = text.partition(".")
        fraction = "".join(ch for ch in fraction if ch.isdigit())[:6]
        text = f"{head}.{fraction.ljust(6, '0')}"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def parse_stream_time(value: Optional[str]) -> Optional[timedelta]:
    """Parse an ``HH:MM:SS.mmm`` session timestamp into a ``timedelta``."""
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def parse_gmt_offset(value: Optional[str]) -> timedelta:
    """Parse a ``SessionInfo.GmtOffset`` value such as ``'02:00:00'``."""
    offset = parse_stream_time(value)
    return offset if offset is not None else timedelta(0)


def parse_lap_time(value: Optional[str]) -> Optional[float]:
    """Parse a lap or sector time string (``'1:22.491'``) into seconds."""
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def iter_position_samples(payload: dict) -> Iterator[tuple]:
    """Yield ``(utc, entries)`` tuples from a decoded ``Position.z`` payload."""
    for sample in payload.get("Position", []) or []:
        utc = parse_utc(sample.get("Timestamp"))
        entries = sample.get("Entries") or {}
        if utc is not None and entries:
            yield utc, entries


def iter_car_samples(payload: dict) -> Iterator[tuple]:
    """Yield ``(utc, cars)`` tuples from a decoded ``CarData.z`` payload."""
    for entry in payload.get("Entries", []) or []:
        utc = parse_utc(entry.get("Utc"))
        cars = entry.get("Cars") or {}
        if utc is not None and cars:
            yield utc, cars


def channels_to_telemetry(channels: dict) -> dict:
    """Convert a raw CarData channel dict into named telemetry values."""
    def _num(key, default=0.0):
        value = channels.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _pedal(key):
        """Return a pedal percentage, or ``None`` when it is not transmitted."""
        if key not in channels:
            return None
        value = _num(key, -1.0)
        if value < 0 or value > PEDAL_UNKNOWN_THRESHOLD:
            return None
        return value

    throttle = _pedal(CHANNEL_THROTTLE)
    brake = _pedal(CHANNEL_BRAKE)

    return {
        "rpm": _num(CHANNEL_RPM),
        "speed": _num(CHANNEL_SPEED),
        "gear": int(_num(CHANNEL_GEAR)),
        "throttle": throttle,
        # Replay frames carry brake as 0.0/1.0 because FastF1 exposes it as a
        # boolean, while the raw channel is 0 or 100.
        "brake": None if brake is None else (1.0 if brake >= 50.0 else 0.0),
        # DRS is not part of the 2026 feed at all; a missing channel is "off".
        "drs": int(_num(CHANNEL_DRS)),
    }


def merge_patch(target: dict, patch: dict) -> dict:
    """Recursively merge a live timing delta ``patch`` into ``target``.

    The timing feeds send partial updates where dictionaries are merged and
    scalars replaced. Lists are sent either as a plain list (replace) or as a
    dict keyed by stringified index (patch individual items), which is how
    sector and segment updates arrive.
    """
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_patch(target[key], value)
        elif isinstance(value, dict) and isinstance(target.get(key), list):
            _merge_indexed_patch(target[key], value)
        elif isinstance(value, dict):
            target[key] = merge_patch({}, value)
        else:
            target[key] = value
    return target


def _merge_indexed_patch(target: list, patch: dict) -> None:
    """Apply an index-keyed dict patch to a list in place."""
    for raw_index, value in patch.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        while len(target) <= index:
            target.append({})
        if isinstance(value, dict) and isinstance(target[index], dict):
            merge_patch(target[index], value)
        else:
            target[index] = value
