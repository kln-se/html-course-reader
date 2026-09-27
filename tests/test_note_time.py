"""Проверить локальное отображение времени заметок без GUI и системных изменений."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QDate, QDateTime, QLocale, QTime, QTimeZone, Qt

from src.course_reader import window
from test_course_notes import reader


@pytest.fixture
def local_clock(monkeypatch):
    """Подменить системные границы Qt, сохранив настоящее форматирование дат."""
    zone = QTimeZone(3 * 60 * 60)
    locale = QLocale('ru_RU')
    monkeypatch.setattr(window, 'QDateTime', SimpleNamespace(
        fromMSecsSinceEpoch=lambda value: QDateTime.fromMSecsSinceEpoch(value, zone),
    ))
    monkeypatch.setattr(window, 'QLocale', SimpleNamespace(
        system=lambda: locale, FormatType=QLocale.FormatType,
    ))
    return zone, locale


@pytest.mark.parametrize('value', [
    '2026-01-01T22:15:00Z',
    '2026-01-02T03:45:00+05:30',
    '2026-01-01T22:15:00',
])
def test_equivalent_offsets_and_naive_utc_represent_same_instant(local_clock, value):
    assert window.format_note_time(value) == window.format_note_time('2026-01-01T22:15:00+00:00')


@pytest.mark.parametrize('locale_name', ['ru_RU', 'en_US'])
def test_time_uses_system_locale_short_format(local_clock, monkeypatch, locale_name):
    zone, _ = local_clock
    locale = QLocale(locale_name)
    monkeypatch.setattr(window.QLocale, 'system', lambda: locale)
    expected = locale.toString(
        QDateTime(QDate(2026, 1, 2), QTime(1, 15), zone),
        QLocale.FormatType.ShortFormat,
    )
    assert window.format_note_time('2026-01-01T22:15:00Z') == expected


def test_local_timezone_conversion_crosses_date_boundary(local_clock):
    zone, locale = local_clock
    expected = locale.toString(
        QDateTime(QDate(2027, 1, 1), QTime(2, 30), zone),
        QLocale.FormatType.ShortFormat,
    )
    assert window.format_note_time('2026-12-31T23:30:00+00:00') == expected


def test_invalid_timestamp_has_readable_fallback(local_clock):
    for value in ('', 'invalid', '2026-02-30T12:00:00Z', '2026-01-01T25:00:00Z'):
        assert window.format_note_time(value) == 'неизвестно'


def test_refresh_displays_updated_time_without_changing_store(reader, local_clock):
    note = reader.store.add_note(reader.root, '1.html', 'Текст заметки')
    note['created'] = '2025-06-01T10:00:00Z'
    note['updated'] = '2026-01-01T22:15:00+00:00'
    before = deepcopy(reader.store.data)

    reader.refresh_notes()

    items = [item for item in reader.notes_list.items if item.data(Qt.ItemDataRole.UserRole)]
    assert len(items) == 1
    assert items[0].text == 'Текст заметки\nИзменено: ' + window.format_note_time(note['updated'])
    assert window.format_note_time(note['created']) not in items[0].text
    assert reader.store.data == before
    reader.persist.assert_not_called()
