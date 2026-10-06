"""Проверить заметки всего курса на границах Qt без запуска окна."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox, QPlainTextEdit

from src.course_reader.storage import Store
from src.course_reader.window import Window


class NoteItem:
    """Хранить данные строки списка без создания GUI."""

    def __init__(self, text):
        self.text = text
        self.values = {}
        self.item_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        self.font_value = Mock()
        self.hidden = False

    def setHidden(self, value):
        self.hidden = value

    def isHidden(self):
        return self.hidden

    def setIcon(self, value):
        self.icon = value

    def setData(self, role, value):
        self.values[role] = value

    def data(self, role):
        return self.values.get(role)

    def flags(self):
        return self.item_flags

    def setFlags(self, value):
        self.item_flags = value

    def font(self):
        return self.font_value

    def setFont(self, value):
        self.font_value = value

    def setToolTip(self, value):
        self.tooltip = value


class NotesList:
    """Моделировать список и выбор, очищаемый вместе со строками."""

    def __init__(self):
        self.items = []
        self.focused = False
        self.current = None
        self.selected = []

    def currentItem(self):
        return self.current

    def clear(self):
        self.items.clear()
        self.current = None
        self.selected = []

    def addItem(self, item):
        self.items.append(item)

    def setCurrentItem(self, item):
        self.current = item
        self.selected = [item] if item is not None else []

    def clearSelection(self):
        self.selected = []

    def setCurrentRow(self, row):
        self.current = self.items[row] if row >= 0 else None

    def clearFocus(self):
        self.focused = False


@pytest.fixture
def reader(tmp_path, monkeypatch):
    root = tmp_path / 'course'
    root.mkdir()
    state = SimpleNamespace(
        root=root, current=root / '1.html', store=Store(tmp_path),
        notes_list=NotesList(), notes_action=Mock(), persist=Mock(),
        notes_search=Mock(text=Mock(return_value='')), notes_hint=Mock(),
        note_target=Mock(), notes_dock=Mock(),
        collapsed_note_groups=set(), note_groups={},
        confirm_note_deletion=Mock(return_value=True),
        note_buttons={label: Mock() for label in
                      ('Добавить', 'Открыть страницу', 'Изменить', 'Удалить')},
        page=SimpleNamespace(open_saved=Mock()),
    )
    for name in ('refresh_notes', 'selected_note', 'update_note_actions', 'open_file',
                 'update_note_group_icons', 'toggle_note_group'):
        setattr(state, name, getattr(Window, name).__get__(state))
    monkeypatch.setattr('src.course_reader.window.QListWidgetItem', NoteItem)
    monkeypatch.setattr('src.course_reader.window.icon', lambda name, theme: (name, theme))
    state.dialog = Mock(return_value=('new text', True))
    state.warning = Mock()
    state.note_text_dialog = state.dialog
    monkeypatch.setattr('src.course_reader.window.QMessageBox.warning', state.warning)
    return state


def select_note(reader, relative, note):
    reader.refresh_notes()
    key = (str(reader.root), relative, note['id'])
    reader.notes_list.setCurrentItem(next(
        item for item in reader.notes_list.items
        if item.data(Qt.ItemDataRole.UserRole) == key))


def test_refresh_groups_all_pages_in_natural_order_and_counts_notes(reader):
    for page, text in [('10.html', 'ten'), ('2.html', 'two'), ('2.html', 'second')]:
        reader.store.add_note(reader.root, page, text)
    reader.store.course(reader.root)['notes']['empty.html'] = []
    reader.refresh_notes()
    headings = [item for item in reader.notes_list.items if not item.data(Qt.ItemDataRole.UserRole)]
    assert [item.text for item in headings] == ['2.html (2)', '10.html (1)']
    assert all(item.flags() == Qt.ItemFlag.ItemIsEnabled for item in headings)
    reader.notes_action.setText.assert_called_with('Заметки (3)')
    reader.current = reader.root / 'unrelated.html'
    reader.refresh_notes()
    reader.notes_action.setText.assert_called_with('Заметки (3)')
    assert len(reader.notes_list.items) == 5


def test_selection_survives_refresh_by_page_and_id(reader):
    first = reader.store.add_note(reader.root, '10.html', 'selected')
    other = reader.store.add_note(reader.root, '2.html', 'other')
    other['id'] = first['id']
    select_note(reader, '10.html', first)
    reader.store.add_note(reader.root, '1.html', 'earlier group')
    reader.refresh_notes()
    assert reader.selected_note() == ('10.html', first)


def test_root_switch_rejects_old_selection_even_with_same_page_and_id(reader, tmp_path):
    original = reader.store.add_note(reader.root, '2.html', 'old course')
    select_note(reader, '2.html', original)
    reader.current = None
    reader.root = tmp_path / 'other_course'
    other = reader.store.add_note(reader.root, '2.html', 'new course')
    other['id'] = original['id']
    assert reader.selected_note() is None
    Window.edit_note(reader)
    Window.delete_note(reader)
    Window.open_note_page(reader)
    reader.dialog.assert_not_called()
    reader.confirm_note_deletion.assert_not_called()
    reader.page.open_saved.assert_not_called()
    reader.refresh_notes()
    assert reader.selected_note() is None
    assert other['text'] == 'new course'


def test_add_targets_displayed_page_even_when_other_page_note_selected(reader):
    other = reader.store.add_note(reader.root, '2.html', 'other')
    select_note(reader, '2.html', other)
    Window.add_note(reader)
    notes = reader.store.course(reader.root)['notes']
    assert [note['text'] for note in notes['1.html']] == ['new text']
    assert notes['2.html'] == [other]
    reader.dialog.assert_called_once_with('1.html')
    reader.persist.assert_called_once_with()


def test_edit_targets_selected_page_and_preserves_same_id_on_current_page(reader):
    current = reader.store.add_note(reader.root, '1.html', 'current')
    other = reader.store.add_note(reader.root, '2.html', 'other')
    other['id'] = current['id']
    select_note(reader, '2.html', other)
    Window.edit_note(reader)
    assert other['text'] == 'new text'
    assert current['text'] == 'current'
    assert reader.selected_note() == ('2.html', other)
    reader.dialog.assert_called_once_with('2.html', 'other', editing=True)
    reader.persist.assert_called_once_with()


def test_delete_targets_selected_page_only(reader):
    current = reader.store.add_note(reader.root, '1.html', 'current')
    other = reader.store.add_note(reader.root, '2.html', 'other')
    other['id'] = current['id']
    select_note(reader, '2.html', other)
    Window.delete_note(reader)
    reader.confirm_note_deletion.assert_called_once_with('2.html')
    assert reader.store.course(reader.root)['notes'] == {'1.html': [current], '2.html': []}
    reader.notes_action.setText.assert_called_with('Заметки (1)')
    assert reader.selected_note() is None
    reader.persist.assert_called_once_with()


@pytest.mark.parametrize('method', ['add_note', 'edit_note'])
@pytest.mark.parametrize('answer', [('cancelled', False), (' \n ', True)])
def test_cancel_or_blank_text_leaves_notes_unchanged(reader, method, answer):
    note = reader.store.add_note(reader.root, '2.html', 'original')
    select_note(reader, '2.html', note)
    before = deepcopy(reader.store.data)
    reader.dialog.return_value = answer
    getattr(Window, method)(reader)
    assert reader.store.data == before
    reader.persist.assert_not_called()


def test_cancel_delete_leaves_selected_note(reader):
    note = reader.store.add_note(reader.root, '2.html', 'original')
    select_note(reader, '2.html', note)
    before = deepcopy(reader.store.data)
    reader.confirm_note_deletion.return_value = False
    Window.delete_note(reader)
    reader.confirm_note_deletion.assert_called_once_with('2.html')
    assert reader.store.data == before
    assert reader.selected_note() == ('2.html', note)
    reader.persist.assert_not_called()


def test_without_current_page_notes_remain_available_but_add_is_disabled(reader):
    note = reader.store.add_note(reader.root, '2.html', 'original')
    select_note(reader, '2.html', note)
    reader.current = None
    reader.refresh_notes()
    reader.note_buttons['Добавить'].setEnabled.assert_called_with(False)
    for label in ('Открыть страницу', 'Изменить', 'Удалить'):
        reader.note_buttons[label].setEnabled.assert_called_with(True)
    assert reader.selected_note() == ('2.html', note)
    Window.add_note(reader)
    reader.dialog.assert_not_called()


@pytest.mark.parametrize('selection', ['heading', 'missing', 'deleted'])
def test_invalid_selection_disables_actions_without_opening_dialogs(reader, selection):
    note = reader.store.add_note(reader.root, '2.html', 'original')
    select_note(reader, '2.html', note)
    if selection == 'heading':
        reader.notes_list.setCurrentItem(reader.notes_list.items[0])
    elif selection == 'missing':
        reader.notes_list.setCurrentItem(None)
    else:
        reader.store.delete_note(reader.root, '2.html', note['id'])
    reader.update_note_actions()
    for label in ('Открыть страницу', 'Изменить', 'Удалить'):
        reader.note_buttons[label].setEnabled.assert_called_with(False)
    Window.edit_note(reader)
    Window.delete_note(reader)
    Window.open_note_page(reader)
    reader.dialog.assert_not_called()
    reader.confirm_note_deletion.assert_not_called()
    reader.page.open_saved.assert_not_called()


def test_open_selected_note_page_uses_its_path(reader):
    target = reader.root / '2.html'
    target.write_text('<p>two</p>', encoding='utf-8')
    note = reader.store.add_note(reader.root, '2.html', 'original')
    select_note(reader, '2.html', note)
    Window.open_note_page(reader)
    address = reader.page.open_saved.call_args.args[0]
    assert address.toLocalFile() == target.as_posix()
    reader.warning.assert_not_called()


def test_open_missing_page_warns_without_discarding_notes(reader):
    note = reader.store.add_note(reader.root, 'missing.html', 'keep me')
    select_note(reader, 'missing.html', note)
    before = deepcopy(reader.store.data)
    Window.open_note_page(reader)
    reader.warning.assert_called_once()
    reader.page.open_saved.assert_not_called()
    assert reader.store.data == before
    assert reader.selected_note() == ('missing.html', note)


def test_no_course_clears_list_and_disables_all_actions(reader):
    reader.store.add_note(reader.root, '2.html', 'original')
    reader.refresh_notes()
    reader.root = None
    reader.current = None
    reader.refresh_notes()
    assert reader.notes_list.items == []
    reader.notes_action.setText.assert_called_with('Заметки (0)')
    for button in reader.note_buttons.values():
        button.setEnabled.assert_called_with(False)


def test_target_label_follows_current_page_not_selected_note(reader):
    note = reader.store.add_note(reader.root, '2.html', 'other page')
    select_note(reader, '2.html', note)
    for relative in ('1.html', 'chapter/3.html'):
        reader.current = reader.root / relative
        reader.update_note_actions()
        reader.note_target.set_page.assert_called_with(relative)
        assert reader.selected_note() == ('2.html', note)
    reader.current = None
    reader.update_note_actions()
    reader.note_target.set_page.assert_called_with(None)


@pytest.mark.parametrize('has_current_page', [True, False])
def test_show_notes_clears_old_selection_and_focus_on_reopen(reader, has_current_page):
    note = reader.store.add_note(reader.root, '2.html', 'selected before closing')
    select_note(reader, '2.html', note)
    reader.notes_list.focused = True
    if not has_current_page:
        reader.current = None
    reader.notes_dock.isVisible.side_effect = [True, False]
    Window.show_notes(reader)
    reader.notes_dock.setVisible.assert_called_with(False)
    assert reader.selected_note() == ('2.html', note)
    Window.show_notes(reader)
    reader.notes_dock.setVisible.assert_called_with(True)
    assert reader.notes_list.selected == []
    assert reader.notes_list.currentItem() is None
    assert reader.selected_note() is None
    assert reader.notes_list.focused is False
    for label in ('Открыть страницу', 'Изменить', 'Удалить'):
        reader.note_buttons[label].setEnabled.assert_called_with(False)
    reader.note_buttons['Добавить'].setEnabled.assert_called_with(has_current_page)
    for button in reader.note_buttons.values():
        button.setFocus.assert_not_called()
    assert reader.store.course(reader.root)['notes']['2.html'] == [note]


@pytest.mark.parametrize('action', ['delete', 'cancel', 'close'])
def test_confirm_deletion_uses_russian_buttons_and_defaults_to_cancel(reader, monkeypatch, action):
    remove = object()
    cancel = object()
    dialog = Mock()
    dialog.addButton.side_effect = [remove, cancel]
    dialog.clickedButton.return_value = {'delete': remove, 'cancel': cancel, 'close': None}[action]
    message_box = Mock(return_value=dialog)
    message_box.Icon = QMessageBox.Icon
    message_box.ButtonRole = QMessageBox.ButtonRole
    monkeypatch.setattr('src.course_reader.window.QMessageBox', message_box)

    assert Window.confirm_note_deletion(reader, 'chapter/2.html') is (action == 'delete')

    message_box.assert_called_once_with(reader)
    dialog.setWindowTitle.assert_called_once_with('Удаление заметки')
    dialog.setTextFormat.assert_called_once_with(Qt.TextFormat.PlainText)
    dialog.setText.assert_called_once_with('Удалить выбранную заметку?\nchapter/2.html')
    dialog.setIcon.assert_called_once_with(QMessageBox.Icon.Question)
    assert [call.args for call in dialog.addButton.call_args_list] == [
        ('Удалить', QMessageBox.ButtonRole.DestructiveRole),
        ('Отмена', QMessageBox.ButtonRole.RejectRole),
    ]
    dialog.setDefaultButton.assert_called_once_with(cancel)
    dialog.setEscapeButton.assert_called_once_with(cancel)
    dialog.exec.assert_called_once_with()


@pytest.mark.parametrize('editing', [False, True])
@pytest.mark.parametrize('result', [QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
def test_note_text_dialog_uses_russian_buttons_and_returns_acceptance(monkeypatch, editing, result):
    """Given: создание или правка заметки. When: диалог закрыт. Then: русские кнопки и верный результат."""
    parent = object()
    initial_text = 'Первая строка\n<b>Обычный текст</b> & "цитата"'
    dialog = Mock()
    dialog.exec.return_value = result
    editor = Mock(spec=['setLineWrapMode', 'setWordWrapMode'])
    dialog.findChild.return_value = editor

    def check_editor_before_exec():
        dialog.findChild.assert_called_once_with(QPlainTextEdit)
        editor.setLineWrapMode.assert_called_once_with(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setWordWrapMode.assert_called_once_with(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        dialog.setTextValue.assert_called_once_with(initial_text)
        return result

    dialog.exec.side_effect = check_editor_before_exec
    dialog.textValue.return_value = 'Первая строка\nВторая строка'
    factory = Mock(return_value=dialog)
    factory.InputMode = QInputDialog.InputMode
    factory.InputDialogOption = QInputDialog.InputDialogOption
    monkeypatch.setattr('src.course_reader.window.QInputDialog', factory)

    assert Window.note_text_dialog(parent, 'chapter/2.html', initial_text, editing=editing) == (
        'Первая строка\nВторая строка', result == QDialog.DialogCode.Accepted)

    factory.assert_called_once_with(parent)
    dialog.setWindowTitle.assert_called_once_with('Изменить заметку' if editing else 'Заметка')
    dialog.setInputMode.assert_called_once_with(QInputDialog.InputMode.TextInput)
    dialog.setOption.assert_called_once_with(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput, True)
    dialog.setLabelText.assert_called_once_with('Страница: chapter/2.html\nТекст:')
    dialog.setTextValue.assert_called_once_with(initial_text)
    dialog.setOkButtonText.assert_called_once_with('Сохранить' if editing else 'Добавить')
    dialog.setCancelButtonText.assert_called_once_with('Отмена')
    dialog.exec.assert_called_once_with()
