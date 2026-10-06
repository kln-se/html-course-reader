"""Проверки компактных действий заметок без создания окон Qt."""
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from src.course_reader import window as window_module
from src.course_reader.theme import PATHS
from src.course_reader.window import Window


ACTIONS = (
    ('Добавить', 'Добавить к открытой странице', 'plus', 'add_note'),
    ('Открыть страницу', 'Открыть страницу', 'open_page', 'open_note_page'),
    ('Изменить', 'Изменить заметку', 'edit', 'edit_note'),
    ('Удалить', 'Удалить заметку', 'delete', 'delete_note'),
)


@pytest.fixture
def note_controls(monkeypatch):
    """Создать действия с подменой виджетов и записываемыми сигналами."""
    buttons = [Mock() for _ in ACTIONS]
    row, layout = Mock(), Mock()
    monkeypatch.setattr(window_module, 'QToolButton', Mock(side_effect=buttons))
    monkeypatch.setattr(window_module, 'QHBoxLayout', Mock(return_value=row))
    previous_icon = (Mock(), 'existing')
    subject = SimpleNamespace(icon_actions=[previous_icon],
                              **{method: Mock() for _, _, _, method in ACTIONS})
    Window.add_note_controls(subject, layout)
    return subject, buttons, row, layout, previous_icon


def test_note_controls_are_compact_accessible_and_registered(note_controls):
    """Given: панель. When: созданы действия. Then: размеры, порядок и доступные имена."""
    subject, buttons, row, layout, previous_icon = note_controls
    assert list(subject.note_buttons) == [key for key, _, _, _ in ACTIONS]
    assert subject.icon_actions == [previous_icon, *[(b, a[2]) for b, a in zip(buttons, ACTIONS)]]
    row.setContentsMargins.assert_called_once_with(0, 0, 0, 0)
    row.setSpacing.assert_called_once_with(4)
    assert row.addWidget.call_args_list == [call(button) for button in buttons]
    row.addStretch.assert_called_once_with()
    layout.addLayout.assert_called_once_with(row)
    for button, (key, label, icon_name, _) in zip(buttons, ACTIONS):
        assert subject.note_buttons[key] is button
        assert icon_name in PATHS
        button.setObjectName.assert_called_once_with('noteControl')
        button.setFixedSize.assert_called_once_with(30, 30)
        button.setIconSize.assert_called_once_with(window_module.QSize(20, 20))
        button.setToolButtonStyle.assert_called_once_with(window_module.Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFocusPolicy.assert_called_once_with(window_module.Qt.FocusPolicy.StrongFocus)
        button.setText.assert_called_once_with(label)
        button.setToolTip.assert_called_once_with(label)
        button.setAccessibleName.assert_called_once_with(label)
        button.setEnabled.assert_called_once_with(False)


@pytest.mark.parametrize('index', range(len(ACTIONS)), ids=[a[3] for a in ACTIONS])
def test_note_control_calls_its_own_action(note_controls, index):
    """Given: кнопка. When: получен сигнал. Then: вызван только её обработчик."""
    subject, buttons, _, _, _ = note_controls
    method = ACTIONS[index][3]
    buttons[index].clicked.connect.assert_called_once_with(getattr(subject, method))
    callback = buttons[index].clicked.connect.call_args.args[0]
    callback()
    for _, _, _, candidate in ACTIONS:
        handler = getattr(subject, candidate)
        if candidate == method:
            handler.assert_called_once_with()
        else:
            handler.assert_not_called()


@pytest.mark.parametrize(('has_root', 'has_current', 'selected'), [
    (True, True, True), (True, False, False), (False, True, False),
    (True, True, False), (True, False, True),
])
def test_note_target_and_action_states(has_root, has_current, selected):
    """Given: состояние страницы. When: обновлены действия. Then: подпись безопасна."""
    root = PurePosixPath('/course')
    current = root / '<b>&"quoted".html'
    subject = SimpleNamespace(
        root=root if has_root else None, current=current if has_current else None,
        selected_note=Mock(return_value=object() if selected else None),
        note_buttons={key: Mock() for key, _, _, _ in ACTIONS}, note_target=Mock(),
    )
    Window.update_note_actions(subject)
    can_add = has_root and has_current
    subject.note_buttons['Добавить'].setEnabled.assert_called_once_with(can_add)
    for key, _, _, _ in ACTIONS[1:]:
        subject.note_buttons[key].setEnabled.assert_called_once_with(selected)
    subject.note_target.set_page.assert_called_once_with(
        '<b>&"quoted".html' if can_add else None)
