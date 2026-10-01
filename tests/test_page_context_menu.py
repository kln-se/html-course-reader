"""Проверить меню страницы и переходы курса без создания Qt-приложения."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PySide6.QtWebEngineCore import QWebEnginePage

from src.course_reader.window import Window


LABELS = [
    'Предыдущая страница', 'Следующая страница', 'Копировать',
    'Выделить всё', 'Найти на странице',
]


@pytest.fixture
def context_menu(monkeypatch):
    actions = {}
    menu = Mock()

    def add_action(label):
        action = Mock()
        actions[label] = action
        return action

    menu.addAction.side_effect = add_action
    menu.exec.return_value = None
    factory = Mock(return_value=menu)
    monkeypatch.setattr('src.course_reader.window.QMenu', factory)
    state = SimpleNamespace(
        root=Path('course'), current=Path('course/1.html'),
        page=Mock(spec=['hasSelection', 'triggerAction']),
        view=Mock(spec=['mapToGlobal']), move=Mock(), show_find=Mock(),
    )
    state.page.hasSelection.return_value = True
    return state, menu, actions, factory


def test_menu_contains_only_five_russian_actions_and_uses_view_coordinates(context_menu):
    state, menu, actions, factory = context_menu
    position = object()
    Window.page_context_menu(state, position)
    factory.assert_called_once_with(state)
    assert list(actions) == LABELS
    assert menu.addAction.call_args_list == [call(label) for label in LABELS]
    state.view.mapToGlobal.assert_called_once_with(position)
    menu.exec.assert_called_once_with(state.view.mapToGlobal.return_value)
    menu.deleteLater.assert_called_once_with()


@pytest.mark.parametrize('selected', LABELS)
def test_selected_action_routes_to_course_or_page_operation(context_menu, selected):
    state, menu, actions, _ = context_menu
    menu.exec.side_effect = lambda position: actions[selected]
    Window.page_context_menu(state, object())
    expected_move = {
        'Предыдущая страница': [call(-1)], 'Следующая страница': [call(1)],
    }.get(selected, [])
    expected_web = {
        'Копировать': [call(QWebEnginePage.WebAction.Copy)],
        'Выделить всё': [call(QWebEnginePage.WebAction.SelectAll)],
    }.get(selected, [])
    assert state.move.call_args_list == expected_move
    assert state.page.triggerAction.call_args_list == expected_web
    assert state.show_find.call_args_list == ([call()] if selected == LABELS[4] else [])
    menu.deleteLater.assert_called_once_with()


def test_cancel_does_not_navigate_copy_select_or_open_find(context_menu):
    state, menu, _, _ = context_menu
    Window.page_context_menu(state, object())
    state.move.assert_not_called()
    state.page.triggerAction.assert_not_called()
    state.show_find.assert_not_called()
    menu.deleteLater.assert_called_once_with()


@pytest.mark.parametrize('has_course,has_page', [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize('has_selection', [False, True])
def test_action_availability_matches_reader_state(
        context_menu, has_course, has_page, has_selection):
    state, _, actions, _ = context_menu
    state.root = state.root if has_course else None
    state.current = state.current if has_page else None
    state.page.hasSelection.return_value = has_selection
    Window.page_context_menu(state, object())
    for label, enabled in zip(LABELS, [has_course, has_course, has_selection, has_page, has_page]):
        actions[label].setEnabled.assert_called_once_with(enabled)


@pytest.mark.parametrize('failure', ['exec', 'move'])
def test_menu_is_released_when_execution_or_action_fails(context_menu, failure):
    state, menu, actions, _ = context_menu
    if failure == 'exec':
        menu.exec.side_effect = RuntimeError('menu failed')
    else:
        menu.exec.side_effect = lambda position: actions[LABELS[0]]
        state.move.side_effect = RuntimeError('menu failed')
    with pytest.raises(RuntimeError, match='menu failed'):
        Window.page_context_menu(state, object())
    menu.deleteLater.assert_called_once_with()


@pytest.mark.parametrize('current,selected,expected', [
    ('2.html', 0, '1.html'), ('2.html', 1, '3.mhtml'),
    ('1.html', 0, None), ('3.mhtml', 1, None),
])
def test_menu_navigation_uses_course_order_and_reports_boundaries(
        context_menu, monkeypatch, current, selected, expected):
    """Given: страницы и видео курса. When: переход из меню. Then: соседняя страница или граница."""
    state, menu, actions, _ = context_menu
    state.files = [state.root / name for name in ['1.html', 'clip.mp4', '2.html', '3.mhtml']]
    state.current = state.root / current
    state.open_file = Mock()
    state.move = lambda step: Window.move(state, step)
    information = Mock()
    monkeypatch.setattr('src.course_reader.window.QMessageBox.information', information)
    menu.exec.side_effect = lambda position: actions[LABELS[selected]]
    Window.page_context_menu(state, object())
    if expected:
        state.open_file.assert_called_once_with(state.root / expected)
        information.assert_not_called()
    else:
        state.open_file.assert_not_called()
        information.assert_called_once_with(
            state, 'Навигация', 'Больше страниц в этом направлении нет.')
    state.page.triggerAction.assert_not_called()
    menu.deleteLater.assert_called_once_with()
