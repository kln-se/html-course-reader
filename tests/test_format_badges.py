"""Проверки геометрии и оформления меток формата без окон Qt."""

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QFont

from src.course_reader import theme


@pytest.fixture
def fixed_font_metrics(monkeypatch):
    """Подменить внешние метрики шрифта без создания QApplication."""
    measured_fonts = []

    class FixedFontMetrics:
        def __init__(self, font):
            self.font = QFont(font)
            measured_fonts.append(self.font)

        def horizontalAdvance(self, text):
            return len(text) * 7

        def height(self):
            return 12

        def elidedText(self, *args):
            raise AssertionError("Метка формата не должна сокращаться")

    monkeypatch.setattr(theme, "QFontMetrics", FixedFontMetrics)
    return measured_fonts


@pytest.mark.parametrize(
    ("bounds", "expected_badge", "expected_text"),
    [
        ((13, 29, 120, 31), (13, 35, 40, 18), (61, 29, 72, 31)),
        ((13, 29, 72, 19), (13, 29, 40, 18), (61, 29, 24, 19)),
        ((13, 29, 72, 18), (13, 29, 40, 18), (61, 29, 24, 18)),
        ((13, 29, 71, 31), (13, 35, 40, 18), (61, 29, 23, 31)),
        ((13, 29, 40, 31), (13, 35, 40, 18), (61, 29, 0, 31)),
        ((13, 29, 120, 17), (13, 28, 40, 18), (61, 29, 72, 17)),
        ((13, 29, 0, 0), (13, 20, 40, 18), (61, 29, 0, 0)),
    ],
)
def test_badge_rectangles(bounds, expected_badge, expected_text):
    """Given: строка. When: размещение. Then: полная метка и неотрицательный остаток."""
    area = QRect(*bounds)
    original = QRect(area)
    badge, text = theme.badge_rectangles(area, 40, 18)
    assert badge == (QRect() if expected_badge is None else QRect(*expected_badge))
    assert text == QRect(*expected_text)
    assert area == original


@pytest.mark.parametrize(
    ("prefix", "expected_label", "expected_width"),
    [
        ("[.html]", "HTML", 40),
        ("[.mht]", "MHT", 33),
        ("[.mp4]", "MP4", 33),
        ("[.pdf]", "PDF", 33),
    ],
)
def test_badge_label_and_padding(
    fixed_font_metrics, prefix, expected_label, expected_width
):
    """Given: префикс. When: оформление. Then: верхний регистр и поля метки."""
    font = QFont()
    font.setPointSizeF(12.0)
    _, label, size = theme.TreeRowDelegate.badge_style(font, prefix)
    assert label == expected_label
    assert size == QSize(expected_width, 18)


def test_long_extension_remains_complete(fixed_font_metrics):
    """Given: длинное расширение. When: оформление. Then: полный текст метки."""
    font = QFont()
    font.setPointSizeF(12.0)
    _, label, size = theme.TreeRowDelegate.badge_style(font, "[.longextension]")
    assert size == QSize(103, 18)
    assert label == "LONGEXTENSION"


def test_pdf_with_large_metrics_remains_complete(monkeypatch):
    """Given: увеличенные метрики. When: оформление. Then: PDF без сокращения."""

    class LargeMetrics:
        def __init__(self, font):
            pass

        def horizontalAdvance(self, text):
            return len(text) * 70

        def height(self):
            return 120

        def elidedText(self, *args):
            raise AssertionError("Метка PDF не должна сокращаться")

    monkeypatch.setattr(theme, "QFontMetrics", LargeMetrics)
    font = QFont()
    font.setPointSizeF(12.0)
    _, label, size = theme.TreeRowDelegate.badge_style(font, "[.pdf]")
    assert label == "PDF"
    assert size == QSize(222, 126)


@pytest.mark.parametrize(
    ("point_size", "expected_size"), [(12.0, 10.5), (8.0, 8.0), (7.0, 8.0)]
)
def test_badge_font_preserves_input(fixed_font_metrics, point_size, expected_size):
    """Given: шрифт. When: оформление метки. Then: копия Semibold, оригинал сохранён."""
    font = QFont()
    font.setPointSizeF(point_size)
    font.setWeight(QFont.Weight.Normal)
    original = QFont(font)
    badge_font, _, _ = theme.TreeRowDelegate.badge_style(font, "[.html]")
    assert badge_font.weight() == QFont.Weight.DemiBold
    assert badge_font.pointSizeF() == pytest.approx(expected_size)
    assert font == original
    assert fixed_font_metrics == [badge_font]


def test_pixel_sized_font_remains_pixel_sized(fixed_font_metrics):
    """Given: размер в пикселях. When: оформление. Then: единицы и оригинал сохранены."""
    font = QFont()
    font.setPixelSize(16)
    font.setWeight(QFont.Weight.Normal)
    original = QFont(font)
    badge_font, _, _ = theme.TreeRowDelegate.badge_style(font, "[.html]")
    assert badge_font.pixelSize() == 16
    assert badge_font.pointSizeF() == -1
    assert badge_font.weight() == QFont.Weight.DemiBold
    assert font == original
    assert fixed_font_metrics == [badge_font]
