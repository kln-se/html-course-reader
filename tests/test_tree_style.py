"""Проверки типографики и подтверждения внешнего файла без приложения и окон Qt."""
from types import SimpleNamespace as NS

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QMessageBox

from src.course_reader import theme
from src.course_reader.window import Window


@pytest.mark.parametrize(('folder', 'weight'), [
    (True, QFont.Weight.Bold), (False, QFont.Weight.Normal),
])
def test_tree_font_distinguishes_folders_and_resets_file_weight(monkeypatch, folder, weight):
    """Given: исходный Bold. When: стиль строки. Then: файл Normal, папка Bold."""
    monkeypatch.setattr(theme.RowDelegate, 'initStyleOption', lambda *args: None)
    monkeypatch.setattr(theme, 'QFontMetrics', lambda font: ('metrics', font.weight()))
    font = QFont()
    font.setWeight(QFont.Weight.Bold)
    option = NS(font=font)
    index = NS(data=lambda role: folder if role == theme.TREE_FOLDER_ROLE else None)
    delegate = theme.TreeRowDelegate()
    delegate.initStyleOption(option, index)
    assert option.font.weight() == weight
    assert option.fontMetrics == ('metrics', weight)


class Confirmation:
    """Записать настройки диалога и вернуть выбранную кнопку без создания QWidget."""
    Icon = QMessageBox.Icon
    ButtonRole = QMessageBox.ButtonRole

    def __init__(self, parent):
        self.parent = parent
        self.buttons = []
        self.executed = False

    def setWindowTitle(self, title):
        self.title = title

    def setTextFormat(self, value):
        self.text_format = value

    def setText(self, text):
        self.text = text

    def setIcon(self, value):
        self.icon = value

    def addButton(self, text, role):
        button = NS(text=text, role=role)
        self.buttons.append(button)
        return button

    def setDefaultButton(self, button):
        self.default = button

    def setEscapeButton(self, button):
        self.escape = button

    def exec(self):
        self.executed = True

    def clickedButton(self):
        assert self.executed
        return self.buttons[self.choice] if self.choice is not None else None


@pytest.mark.parametrize(('choice', 'success', 'launches', 'warnings'), [
    (0, True, 1, 0), (1, True, 0, 0), (None, True, 0, 0), (0, False, 1, 1),
], ids=['open', 'cancel', 'window-close', 'windows-open-failed'])
def test_external_file_requires_open_and_reports_launch_failure(
    tmp_path, monkeypatch, choice, success, launches, warnings,
):
    """Given: ответ диалога. When: внешний файл. Then: запуск только после Открыть."""
    dialogs, opened, reported = [], [], []

    class Dialog(Confirmation):
        def __init__(self, parent):
            super().__init__(parent)
            self.choice = choice
            dialogs.append(self)

        @staticmethod
        def warning(*args):
            reported.append(args)

    def open_url(url):
        opened.append(url.toLocalFile())
        return success

    monkeypatch.setattr('src.course_reader.window.QMessageBox', Dialog)
    monkeypatch.setattr('src.course_reader.window.QDesktopServices.openUrl', open_url)
    state = NS()
    path = tmp_path / '<материал> с пробелами &.mp4'
    Window.external_file(state, path)
    assert opened == [str(path).replace('\\', '/')] * launches
    assert len(reported) == warnings
    dialog, = dialogs
    assert dialog.parent is state
    assert dialog.title == 'Внешний файл'
    assert dialog.text_format == Qt.TextFormat.PlainText
    assert str(path) in dialog.text
    assert [(button.text, button.role) for button in dialog.buttons] == [
        ('Открыть', QMessageBox.ButtonRole.AcceptRole),
        ('Отмена', QMessageBox.ButtonRole.RejectRole),
    ]
    assert dialog.default is dialog.buttons[1]
    assert dialog.escape is dialog.buttons[1]
    if reported:
        assert reported == [(state, 'Ошибка открытия', 'Windows не удалось открыть файл.')]