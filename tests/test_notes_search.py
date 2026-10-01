"""Проверки фильтра заметок и действий с результатами без запуска GUI."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt

from src.course_reader.window import Window
from test_course_notes import reader, select_note


def search(reader, query):
    reader.notes_search.text.return_value = query
    reader.refresh_notes()


def visible_keys(reader):
    return [item.data(Qt.ItemDataRole.UserRole) for item in reader.notes_list.items
            if item.data(Qt.ItemDataRole.UserRole)]


@pytest.mark.parametrize('query,expected', [
    ('  тЕоРиЯ  ', [0, 2]), ('STRASSE', [1]), ('строка\nвторая', [2]),
    ('missing', []), ('needle.html', []), ('[.*]', []), ('2026-01', []),
    ('  ', [0, 1, 2]), ('', [0, 1, 2]),
])
def test_search_matches_only_note_text_without_mutation_or_navigation(reader, query, expected):
    notes = [reader.store.add_note(reader.root, page, text) for page, text in [
        ('2.html', 'Теория и практика'), ('2.html', 'Straße'),
        ('needle.html', 'ТЕОРИЯ: строка\nвторая'),
    ]]
    for note in notes:
        note['updated'] = '2026-01-01T12:00:00Z'
    before = deepcopy(reader.store.data)
    current = reader.current
    search(reader, query)
    expected_keys = [(str(reader.root), '2.html' if index < 2 else 'needle.html', notes[index]['id'])
                     for index in expected]
    assert visible_keys(reader) == expected_keys
    assert reader.store.data == before
    assert reader.current == current
    assert reader.selected_note() is None
    reader.notes_action.setText.assert_called_with('Заметки (3)')
    reader.persist.assert_not_called()
    reader.page.open_saved.assert_not_called()


def test_filter_counts_matching_groups_and_clear_restores_all_notes(reader):
    for page, text in [('10.html', 'yes'), ('2.html', 'yes'), ('2.html', 'no'), ('3.html', 'no')]:
        reader.store.add_note(reader.root, page, text)
    search(reader, 'yes')
    headings = [item for item in reader.notes_list.items if not item.data(Qt.ItemDataRole.UserRole)]
    assert [item.text for item in headings] == ['2.html (1)', '10.html (1)']
    assert all(item.flags() == Qt.ItemFlag.NoItemFlags for item in headings)
    reader.notes_action.setText.assert_called_with('Заметки (4)')
    search(reader, 'missing')
    assert reader.notes_list.items == []
    reader.notes_hint.setText.assert_called_with('Ничего не найдено')
    search(reader, '')
    assert len(visible_keys(reader)) == 4
    assert [item.text for item in reader.notes_list.items if not item.data(Qt.ItemDataRole.UserRole)] == [
        '2.html (2)', '3.html (1)', '10.html (1)']
    reader.notes_hint.setText.assert_called_with(
        'Заметок пока нет. Добавьте первую заметку к открытой странице.')


def test_filter_preserves_selection_by_page_and_id_then_clears_hidden_selection(reader):
    first = reader.store.add_note(reader.root, '1.html', 'match first')
    selected = reader.store.add_note(reader.root, '2.html', 'match second')
    selected['id'] = first['id']
    select_note(reader, '2.html', selected)
    search(reader, 'match')
    assert reader.selected_note() == ('2.html', selected)
    search(reader, 'first')
    assert reader.selected_note() is None
    for label in ('Открыть страницу', 'Изменить', 'Удалить'):
        reader.note_buttons[label].setEnabled.assert_called_with(False)
    search(reader, '')
    assert reader.selected_note() is None


def test_edit_result_out_of_filter_does_not_touch_same_id_on_current_page(reader):
    current = reader.store.add_note(reader.root, '1.html', 'match current')
    selected = reader.store.add_note(reader.root, '2.html', 'match selected')
    selected['id'] = current['id']
    select_note(reader, '2.html', selected)
    search(reader, 'match')
    Window.edit_note(reader)
    assert selected['text'] == 'new text'
    assert current['text'] == 'match current'
    assert reader.selected_note() is None
    assert visible_keys(reader) == [(str(reader.root), '1.html', current['id'])]
    assert reader.notes_search.text() == 'match'
    for label in ('Открыть страницу', 'Изменить', 'Удалить'):
        reader.note_buttons[label].setEnabled.assert_called_with(False)
    reader.notes_action.setText.assert_called_with('Заметки (2)')
    reader.persist.assert_called_once_with()


@pytest.mark.parametrize('text,matches', [('match new', True), ('other', False)])
def test_add_under_filter_targets_current_page_and_preserves_query(reader, text, matches):
    selected = reader.store.add_note(reader.root, '2.html', 'match selected')
    select_note(reader, '2.html', selected)
    search(reader, 'match')
    reader.dialog.return_value = (text, True)
    Window.add_note(reader)
    assert [note['text'] for note in reader.store.course(reader.root)['notes']['1.html']] == [text]
    assert reader.selected_note() == ('2.html', selected)
    assert len(visible_keys(reader)) == 1 + int(matches)
    assert reader.notes_search.text() == 'match'
    reader.notes_action.setText.assert_called_with('Заметки (2)')
    reader.dialog.assert_called_once_with('1.html')


def test_delete_result_preserves_hidden_same_id_note_and_filter(reader):
    current = reader.store.add_note(reader.root, '1.html', 'hidden')
    selected = reader.store.add_note(reader.root, '2.html', 'match')
    selected['id'] = current['id']
    select_note(reader, '2.html', selected)
    search(reader, 'match')
    Window.delete_note(reader)
    assert reader.store.course(reader.root)['notes'] == {'1.html': [current], '2.html': []}
    assert visible_keys(reader) == []
    assert reader.selected_note() is None
    assert reader.notes_search.text() == 'match'
    reader.notes_hint.setText.assert_called_with('Ничего не найдено')
    reader.notes_action.setText.assert_called_with('Заметки (1)')


def test_course_switch_clears_query_and_rejects_same_page_and_id_selection(reader, tmp_path):
    selected = reader.store.add_note(reader.root, '2.html', 'match')
    select_note(reader, '2.html', selected)
    search(reader, 'match')
    target = tmp_path / 'new-course'
    target.mkdir()
    other = reader.store.add_note(target, '2.html', 'different')
    other['id'] = selected['id']
    reader.notes_search.clear.side_effect = lambda: search(reader, '')
    for name in ('catalog_timer', 'catalog_fallback', 'tree_search', 'view', 'rebuild', 'statusBar'):
        setattr(reader, name, Mock())
    reader.refresh_metadata = reader.refresh_notes
    Window.set_course(reader, target)
    assert reader.root == target.resolve()
    assert reader.notes_search.text() == ''
    reader.notes_search.clear.assert_called_once_with()
    assert visible_keys(reader) == [(str(target.resolve()), '2.html', other['id'])]
    assert reader.selected_note() is None
    reader.page.open_saved.assert_not_called()
