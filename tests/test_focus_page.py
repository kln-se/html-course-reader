"""Проверки поиска открытой страницы в дереве без окон и WebEngine."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from src.course_reader.window import Window
from test_catalog_refresh import rebuild_state


@pytest.fixture
def focus_state(rebuild_state):
    state = rebuild_state
    state.tree.scrollToItem = Mock()
    state.tree.setFocus = Mock()
    state.open_file = Mock()
    state.view = Mock()
    state.page = Mock()
    return state


def test_focus_expands_only_current_ancestry_and_preserves_reader(focus_state):
    state = focus_state
    page = state.root / 'chapter' / 'nested' / '1.html'
    other = state.root / 'other' / '2.html'
    state.current = page
    Window.rebuild(state, [page, other])
    state.tree.setCurrentItem(state.items[str(other)])
    state.loading, state.navigation_generation = False, 7

    Window.focus_current_page(state)

    assert state.tree.currentItem() is state.items[str(page)]
    assert state.directory_items[str(page.parent)].isExpanded()
    assert state.directory_items[str(page.parent.parent)].isExpanded()
    assert not state.directory_items[str(other.parent)].isExpanded()
    state.tree.scrollToItem.assert_called_once_with(state.items[str(page)])
    state.tree.setFocus.assert_called_once_with()
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []
    assert state.current == page
    assert state.loading is False and state.navigation_generation == 7
    assert state.focus_page_button.enabled


@pytest.mark.parametrize('opened', [False, True])
def test_unavailable_current_page_disables_button_and_does_nothing(focus_state, opened):
    state = focus_state
    visible = state.root / 'visible.html'
    state.current = state.root / 'hidden.html' if opened else None
    Window.rebuild(state, [visible])
    selected = state.items[str(visible)]
    state.tree.setCurrentItem(selected)

    Window.focus_current_page(state)

    assert not state.focus_page_button.enabled
    assert state.tree.currentItem() is selected
    state.tree.scrollToItem.assert_not_called()
    state.tree.setFocus.assert_not_called()
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_filter_and_catalog_deletion_readdition_update_button(focus_state):
    state = focus_state
    page = state.root / '1.html'
    page.write_text('page', encoding='utf-8')
    state.current = page
    state.store = NS(patterns=['*.html'])
    state.sync_catalog_watches = Mock()
    state.closing = False
    state.rebuild = lambda files=None: Window.rebuild(state, files)
    state.rebuild()
    assert state.focus_page_button.enabled

    state.store.patterns = ['*.txt']
    state.rebuild()
    assert not state.focus_page_button.enabled
    state.store.patterns = ['*.html']
    state.rebuild()
    assert state.focus_page_button.enabled

    page.unlink()
    Window.refresh_catalog(state)
    assert not state.focus_page_button.enabled
    page.write_text('returned', encoding='utf-8')
    Window.refresh_catalog(state)
    assert state.focus_page_button.enabled
    assert state.current == page
    state.open_file.assert_not_called()
    assert state.view.mock_calls == [] and state.page.mock_calls == []


def test_switch_course_clears_old_current_and_disables_focus(focus_state):
    state = focus_state
    state.current = state.root / 'old.html'
    Window.rebuild(state, [state.current])
    assert state.focus_page_button.enabled
    new_root = state.root / 'new'
    new_root.mkdir()
    state.persist = Mock()
    state.catalog_timer = Mock()
    state.catalog_fallback = Mock()
    state.store = NS(patterns=['*.html'], activate_course=Mock(), course=lambda root: {'last': ''})
    state.sync_catalog_watches = Mock()
    state.rebuild = lambda: Window.rebuild(state)
    state.refresh_metadata = state.update_focus_button
    state.statusBar = Mock()

    Window.set_course(state, new_root)

    assert state.root == new_root.resolve()
    assert state.current is None and state.items == {}
    assert not state.focus_page_button.enabled
    state.open_file.assert_not_called()


def test_metadata_refresh_updates_button_after_local_page_changes(focus_state):
    state = focus_state
    page = state.root / '1.html'
    Window.rebuild(state, [page])
    state.favorites = Mock()
    state.refresh_notes = Mock()
    state.favorite_action = Mock()
    state.store = NS(course=lambda root: {'favorites': []})
    state.statusBar = Mock()

    state.current = page
    Window.refresh_metadata(state)
    assert state.focus_page_button.enabled
    state.current = state.root / 'filtered.html'
    Window.refresh_metadata(state)
    assert not state.focus_page_button.enabled
