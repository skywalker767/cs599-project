"""Tests for aspect ratio resolution."""

import pytest

from app.tools.aspect_ratio import resolve_aspect_ratio


@pytest.mark.parametrize(
    "ratio,expected_size,orientation",
    [
        ("1:1", "1024x1024", "square"),
        ("16:9", "1792x1024", "landscape"),
        ("9:16", "1024x1792", "portrait"),
        ("4:5", "1024x1536", "portrait"),
        ("3:4", "1024x1536", "portrait"),
        ("4:3", "1536x1024", "landscape"),
        ("A4 portrait", "1024x1536", "portrait"),
        ("A4 landscape", "1536x1024", "landscape"),
    ],
)
def test_aspect_ratio_not_all_square(ratio, expected_size, orientation):
    res = resolve_aspect_ratio(ratio)
    assert res.size == expected_size
    assert res.orientation == orientation
    assert not (res.width == 1024 and res.height == 1024) or ratio == "1:1"


def test_distinct_sizes_for_common_ratios():
    sizes = {resolve_aspect_ratio(r).size for r in ["1:1", "16:9", "9:16", "4:3"]}
    assert len(sizes) >= 3


def test_unsupported_aspect_ratio_normalized_with_warning():
    res = resolve_aspect_ratio("21:9")
    assert res.normalized is True
    assert res.normalization_reason
    assert res.width > 0 and res.height > 0
