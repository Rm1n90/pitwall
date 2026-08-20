"""Tests for caching driver portraits."""

import os

import pytest

from src.lib import driver_images


class TestFetchHeadshot:
    def test_downloads_and_caches(self, tmp_path, monkeypatch):
        calls = []

        class _Response:
            def read(self):
                calls.append(1)
                return b"image-bytes"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(driver_images, "urlopen",
                            lambda *a, **k: _Response())

        first = driver_images.fetch_headshot("NOR", "http://x/a.png",
                                             str(tmp_path))
        assert first and os.path.exists(first)

        second = driver_images.fetch_headshot("NOR", "http://x/a.png",
                                              str(tmp_path))
        assert second == first
        assert len(calls) == 1  # the second call came from the cache

    def test_an_empty_address_yields_nothing(self, tmp_path):
        assert driver_images.fetch_headshot("NOR", "", str(tmp_path)) is None

    def test_a_failed_download_is_not_an_error(self, tmp_path, monkeypatch):
        def _boom(*args, **kwargs):
            raise OSError("no network")

        monkeypatch.setattr(driver_images, "urlopen", _boom)
        assert driver_images.fetch_headshot("NOR", "http://x/a.png",
                                            str(tmp_path)) is None

    def test_an_empty_response_yields_nothing(self, tmp_path, monkeypatch):
        class _Empty:
            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(driver_images, "urlopen", lambda *a, **k: _Empty())
        assert driver_images.fetch_headshot("NOR", "http://x/a.png",
                                            str(tmp_path)) is None

    def test_cache_names_are_filesystem_safe(self, tmp_path):
        path = driver_images._cache_path(str(tmp_path), "../etc/passwd")
        assert "/" not in os.path.basename(path)
        assert os.path.basename(path) == "etcpasswd.png"

    def test_the_address_alone_does_not_mean_no_portrait(self, tmp_path,
                                                         monkeypatch):
        # Every portrait address contains a "fallback image" directive from
        # the image pipeline, real portrait or not.
        class _Response:
            def read(self):
                return b"real-image"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(driver_images, "urlopen",
                            lambda *a, **k: _Response())
        url = "https://media.formula1.com/d_driver_fallback_image.png/x/NOR.png"
        assert driver_images.fetch_headshot("NOR", url, str(tmp_path))
