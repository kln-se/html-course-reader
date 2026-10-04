"""Проверки создания заметки из выделенного текста страницы."""

from copy import deepcopy

import pytest

from src.course_reader.window import Window
from test_course_notes import reader
from test_page_context_menu import context_menu


@pytest.mark.parametrize('selection', ['', ' ', '\t\r\n'])
def test_blank_selection_disables_add_note(context_menu, selection):
    state, menu, actions, _ = context_menu
    state.page.hasSelection.return_value = True
    state.page.selectedText.return_value = selection
    menu.exec.side_effect = lambda position: actions['Добавить в заметки']

    Window.page_context_menu(state, object())

    actions['Добавить в заметки'].setEnabled.assert_called_once_with(False)
    state.add_note.assert_not_called()


def test_menu_saves_edited_quote_for_original_page(reader, context_menu):
    """Given: цитата страницы. When: страница меняется в меню. Then: источник сохранён."""
    state, menu, actions, _ = context_menu
    original_root = reader.root
    original_page = reader.current
    relative = original_page.relative_to(original_root).as_posix()
    quote = 'Первая строка\n<b>Это обычный текст</b> & "цитата"'
    edited = quote + '\nМоё пояснение'
    state.root = original_root
    state.current = original_page
    state.page.selectedText.return_value = quote
    state.add_note = lambda **kwargs: Window.add_note(reader, **kwargs)
    reader.note_text_dialog.return_value = (edited, True)

    def choose_add_note(position):
        reader.current = original_root / 'other.html'
        state.current = reader.current
        state.page.selectedText.return_value = 'Уже другое выделение'
        return actions['Добавить в заметки']

    menu.exec.side_effect = choose_add_note
    Window.page_context_menu(state, object())

    reader.note_text_dialog.assert_called_once_with(relative, quote)
    notes = reader.store.course(original_root)['notes']
    assert set(notes) == {relative}
    assert [note['text'] for note in notes[relative]] == [edited]
    reader.persist.assert_called_once_with()


def test_page_change_in_editor_keeps_original_note_target(reader):
    """Given: редактор. When: меняется страница. Then: заметка сохраняет источник."""
    original_root = reader.root
    relative = reader.current.relative_to(original_root).as_posix()

    def accept_note(relative, initial_text):
        reader.current = original_root / 'other.html'
        return initial_text, True

    reader.note_text_dialog.side_effect = accept_note
    Window.add_note(reader, initial_text='Цитата')

    notes = reader.store.course(original_root)['notes']
    assert set(notes) == {relative}
    assert [note['text'] for note in notes[relative]] == ['Цитата']


@pytest.mark.parametrize('result_text,accepted', [('Цитата', False), ('', True), (' \t\r\n', True)])
def test_cancelled_or_blank_quote_is_not_saved(reader, result_text, accepted):
    before = deepcopy(reader.store.data)
    reader.note_text_dialog.return_value = (result_text, accepted)

    Window.add_note(reader, initial_text='Исходная цитата')

    assert reader.store.data == before
    reader.persist.assert_not_called()


def test_course_change_in_editor_cancels_saving(reader):
    """Given: редактор цитаты. When: изменился курс. Then: заметка не сохраняется."""
    original_root = reader.root
    before = deepcopy(reader.store.data)

    def accept_after_course_change(relative, initial_text):
        reader.root = original_root.parent / 'other-course'
        reader.current = reader.root / '1.html'
        return 'Отредактированная цитата', True

    reader.note_text_dialog.side_effect = accept_after_course_change
    Window.add_note(reader, initial_text='Исходная цитата')

    assert reader.store.data == before
    reader.persist.assert_not_called()


def test_stale_course_snapshot_does_not_open_editor(reader):
    stale_root = reader.root.parent / 'previous-course'
    before = deepcopy(reader.store.data)

    Window.add_note(reader, initial_text='Цитата', source=(stale_root, stale_root / '1.html'))

    reader.note_text_dialog.assert_not_called()
    reader.persist.assert_not_called()
    assert reader.store.data == before
