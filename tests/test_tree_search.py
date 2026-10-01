"""Проверки поиска файлов и восстановления дерева без GUI и WebEngine."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from src.course_reader.window import Window
from test_catalog_refresh import rebuild_state
from test_focus_page import focus_state
from test_escape import escape_state


@pytest.fixture
def search_state(focus_state):
    state = focus_state
    state.current = state.root / 'Теория' / 'Введение.HTML'
    state.loading = False
    state.navigation_generation = 7
    Window.rebuild(state, [state.current, state.root / 'Практика' / 'nested' / 'Straße.html',
                           state.root / 'Практика' / 'video.mp4'])
    return state


@pytest.mark.parametrize('query,expected', [
    ('вВеДеНиЕ', ['Теория/Введение.HTML']),
    ('  практика\\NESTED  ', ['Практика/nested/Straße.html']),
    ('STRASSE', ['Практика/nested/Straße.html']),
    ('Практика', ['Практика/nested/Straße.html', 'Практика/video.mp4']),
    ('missing', []),
    ('[.html]', []),
    ('  ', ['Теория/Введение.HTML', 'Практика/nested/Straße.html', 'Практика/video.mp4']),
])
def test_query_filters_relative_paths_and_keeps_only_matching_ancestors(search_state, query, expected):
    state = search_state
    original_files = state.files
    selected = state.tree.currentItem()
    state.tree_search.setText(query)
    assert [path.relative_to(state.root).as_posix() for path in state.files
            if not state.items[str(path)].hidden] == expected
    expected_parents = {str(parent) for name in expected
                        for parent in (state.root / name).parents if parent != state.root
                        and parent.is_relative_to(state.root)}
    for path, node in state.directory_items.items():
        assert node.hidden == (bool(query.strip()) and path not in expected_parents)
        if query.strip() and path in expected_parents:
            assert node.expanded
    assert state.tree_search_empty.visible == (bool(query.strip()) and not expected)
    assert state.files is original_files
    assert state.tree.currentItem() is selected
    assert state.current == state.root / 'Теория' / 'Введение.HTML'
    assert state.loading is False and state.navigation_generation == 7
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_clear_restores_expansion_and_reveals_current_without_reloading(search_state):
    state = search_state
    practice = state.directory_items[str(state.root / 'Практика')]
    practice.setExpanded(True)
    state.tree_search.setText('Straße')
    assert state.directory_items[str(state.root / 'Практика' / 'nested')].expanded
    state.tree_search.setText('missing')
    state.tree_search.clear()
    assert practice.expanded
    assert not state.directory_items[str(state.root / 'Практика' / 'nested')].expanded
    assert state.directory_items[str(state.current.parent)].expanded
    assert all(not item.hidden for item in [*state.items.values(), *state.directory_items.values()])
    assert state.tree.currentItem() is state.items[str(state.current)]
    state.tree.scrollToItem.assert_called_once_with(state.items[str(state.current)])
    assert state.tree_search_expanded is None
    assert not state.tree_search_empty.visible
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_rebuild_reapplies_query_to_new_files_and_format_filter(search_state):
    state = search_state
    state.store = NS(patterns=['*.html', '*.mp4'])
    state.sync_catalog_watches = Mock()
    state.closing = False
    state.rebuild = lambda files=None: Window.rebuild(state, files)
    state.current = None
    state.rebuild([])
    state.tree_search.setText('lesson')
    assert state.tree_search_empty.visible
    html, video, other = [state.root / name for name in ('lesson.html', 'lesson.mp4', 'other.html')]
    for path in (html, video, other):
        path.write_text('material', encoding='utf-8')
    Window.refresh_catalog(state)
    assert set(state.files) == {html, video, other}
    assert not state.items[str(html)].hidden and not state.items[str(video)].hidden
    assert state.items[str(other)].hidden
    assert not state.tree_search_empty.visible
    state.store.patterns = ['*.html']
    state.rebuild()
    assert set(state.files) == {html, other}
    assert not state.items[str(html)].hidden and state.items[str(other)].hidden
    assert state.tree_search.text() == 'lesson'
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_show_hide_clears_filter_and_moves_focus_without_touching_page(search_state):
    state = search_state
    Window.show_tree_search(state)
    assert state.tree_search.isVisible()
    state.tree_search.setFocus.assert_called_once_with()
    state.tree_search.setText('missing')
    Window.hide_tree_search(state)
    assert state.tree_search.text() == '' and not state.tree_search.isVisible()
    assert all(not item.hidden for item in state.items.values())
    state.tree.setFocus.assert_called_once_with()
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_locate_clears_query_and_selects_previously_hidden_current(search_state):
    state = search_state
    state.tree_search.setText('missing')
    Window.focus_current_page(state)
    assert state.tree_search.text() == ''
    assert state.tree.currentItem() is state.items[str(state.current)]
    assert not state.items[str(state.current)].hidden
    state.tree.setFocus.assert_called_once_with()
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_course_switch_resets_query_and_snapshot(search_state):
    state = search_state
    state.tree_search.setText('missing')
    state.tree_search.show()
    new_root = state.root / 'new'
    new_root.mkdir()
    state.persist = Mock()
    state.notes_search = Mock()
    state.catalog_timer = Mock()
    state.catalog_fallback = Mock()
    state.store = NS(patterns=['*.html'], activate_course=Mock(), course=lambda root: {'last': ''})
    state.sync_catalog_watches = Mock()
    state.rebuild = lambda: Window.rebuild(state)
    state.refresh_metadata = state.update_focus_button
    state.statusBar = Mock()
    Window.set_course(state, new_root)
    assert state.root == new_root.resolve() and state.current is None
    assert state.tree_search.text() == '' and not state.tree_search.isVisible()
    assert state.tree_search_expanded is None and not state.tree_search_empty.visible
    assert state.items == {} and state.files == []
    state.open_file.assert_not_called()


@pytest.mark.parametrize('focus_name,find,notes,expected', [
    ('tree_search', True, True, 'tree_search'),
    ('tree', True, True, 'tree_search'),
    ('tree_child', True, True, 'tree_search'),
    ('notes_child', True, True, 'notes'),
    ('page_child', True, True, 'find'),
    ('page_child', False, True, 'notes'),
    ('page_child', False, False, 'tree_search'),
])
def test_escape_prioritizes_focused_search_and_preserves_other_panel_priority(
        escape_state, focus_name, find, notes, expected):
    state, app, notes_child, page_child, _ = escape_state
    tree_child = object()
    state.isAncestorOf = lambda widget: True
    state.tree.isAncestorOf.side_effect = lambda widget: widget is tree_child
    state.tree_search.isVisible.return_value = True
    state.find_bar.isVisible.return_value = find
    state.notes_dock.isVisible.return_value = notes
    app.focusWidget.return_value = {'tree_search': state.tree_search, 'tree': state.tree,
                                   'tree_child': tree_child, 'notes_child': notes_child,
                                   'page_child': page_child}[focus_name]
    assert Window.escape_target(state) == expected


@pytest.mark.parametrize('blocker', ['activeModalWidget', 'activePopupWidget'])
def test_escape_does_not_close_tree_search_behind_modal_or_popup(escape_state, blocker):
    state, app, *_ = escape_state
    state.tree_search.isVisible.return_value = True
    app.focusWidget.return_value = state.tree_search
    state.isAncestorOf = lambda widget: True
    getattr(app, blocker).return_value = object()
    assert Window.escape_target(state) is None
