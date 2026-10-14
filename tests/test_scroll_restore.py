"""Проверки восстановления HTML/HTM из дисковой истории на границах Qt."""

from types import MethodType, SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage

from src.course_reader.storage import Store
from src.course_reader.viewer import Page
from src.course_reader.window import Window


@pytest.fixture
def make_reader(tmp_path):
    """Соединить реальные обработчики; заменить только Qt и обновление панелей."""

    def create(zoom=1.0):
        state = SimpleNamespace(
            store=Store(tmp_path),
            root=None,
            current=None,
            loading=True,
            closing=False,
            navigation_generation=0,
            scripts=[],
            opened=[],
            messages=[],
            timers=[],
            address=QUrl("about:blank"),
            tree_search=Mock(),
            notes_search=Mock(),
            catalog_timer=Mock(),
            catalog_fallback=Mock(),
            rebuild=Mock(),
            refresh_metadata=Mock(),
            choose_course=Mock(),
        )
        state.save_timer = SimpleNamespace(start=state.timers.append)
        state.statusBar = lambda: SimpleNamespace(showMessage=state.messages.append)
        state.view = SimpleNamespace(
            url=lambda: state.address,
            zoomFactor=lambda: zoom,
            setUrl=lambda url: setattr(state, "address", url),
        )
        for name in ("persist", "set_course", "open_file", "local_link", "allow_local"):
            setattr(state, name, MethodType(getattr(Window, name), state))
        state.page = SimpleNamespace(
            pending_restore=None,
            setUrl=state.opened.append,
            allow_local=state.allow_local,
            local_requested=SimpleNamespace(emit=state.local_link),
            runJavaScript=lambda script, callback: state.scripts.append(
                (script, callback)
            ),
        )
        state.page.open_saved = MethodType(Page.open_saved, state.page)
        return state

    return create


def finish_navigation(reader, success=True):
    """Доставить переход и loadFinished вручную; JavaScript не исполняется."""
    url = reader.opened[-1]
    assert (
        Page.acceptNavigationRequest(
            reader.page,
            url,
            QWebEnginePage.NavigationType.NavigationTypeLinkClicked,
            True,
        )
        is True
    )
    reader.address = url
    Window.loaded(reader, success)


def create_page(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<html><body>Учебная страница</body></html>", encoding="utf-8")
    return path.resolve()


@pytest.mark.parametrize("suffix", [".html", ".htm"])
@pytest.mark.parametrize("position", [0, 425.5])
@pytest.mark.parametrize("zoom", [1.0, 1.1])
def test_scroll_survives_restart_and_is_protected_until_restore_callback(
    make_reader,
    tmp_path,
    suffix,
    position,
    zoom,
):
    """Given: сохранённая прокрутка. When: новый Store. Then: она передана в JS без обнуления."""
    root = tmp_path / "Курс"
    page = create_page(root / "Глава" / ("Урок" + suffix))
    relative = page.relative_to(root).as_posix()
    reader = make_reader(zoom)
    reader.set_course(root)
    reader.open_file(page)
    finish_navigation(reader)
    reader.scripts[-1][1](None)
    Window.scroll_changed(reader, cast(QPointF, SimpleNamespace(y=lambda: 99)))
    reader.persist()
    Window.scroll_changed(reader, cast(QPointF, SimpleNamespace(y=lambda: position)))
    reader.persist()
    assert reader.timers == [700, 700]

    restarted = make_reader(zoom)
    assert restarted.store.course(root)["scroll"] == {relative: position}
    Window.restore_course(restarted)
    assert restarted.opened == [QUrl.fromLocalFile(str(page))]
    finish_navigation(restarted)
    assert restarted.current == page
    assert restarted.store.course(root)["last"] == relative
    assert restarted.choose_course.call_count == 0
    assert len(restarted.scripts) == 1
    script, callback = restarted.scripts[0]
    assert script == f"window.scrollTo(0, {float(position) / zoom});"
    assert restarted.loading is True
    Window.scroll_changed(restarted, cast(QPointF, SimpleNamespace(y=lambda: 0)))
    restarted.persist()
    assert Store(tmp_path).course(root)["scroll"] == {relative: position}
    assert restarted.timers == []

    callback(None)
    assert restarted.loading is False
    Window.scroll_changed(restarted, SimpleNamespace(y=lambda: 610))
    restarted.persist()
    assert Store(tmp_path).course(root)["scroll"] == {relative: 610}
    assert restarted.timers == [700]


def test_restart_and_course_switch_restore_each_pages_own_position(
    make_reader, tmp_path
):
    """Given: два курса и три страницы. When: повторные открытия. Then: позиции независимы."""
    first, second = tmp_path / "Первый", tmp_path / "Второй"
    pages = [
        (first, create_page(first / "1.html"), 120),
        (first, create_page(first / "2.htm"), 240),
        (second, create_page(second / "1.html"), 360),
    ]
    reader = make_reader()
    for root, page, position in pages:
        if reader.root != root:
            reader.set_course(root)
        reader.open_file(page)
        finish_navigation(reader)
        reader.scripts[-1][1](None)
        Window.scroll_changed(
            reader, cast(QPointF, SimpleNamespace(y=lambda value=position: value))
        )
        reader.persist()

    restarted = make_reader()
    Window.restore_course(restarted)
    finish_navigation(restarted)
    assert restarted.current == pages[2][1]
    assert restarted.scripts[-1][0] == "window.scrollTo(0, 360.0);"
    restarted.scripts[-1][1](None)
    restarted.set_course(first)
    finish_navigation(restarted)
    assert restarted.current == pages[1][1]
    assert restarted.scripts[-1][0] == "window.scrollTo(0, 240.0);"
    restarted.scripts[-1][1](None)
    restarted.open_file(pages[0][1])
    finish_navigation(restarted)
    assert restarted.scripts[-1][0] == "window.scrollTo(0, 120.0);"
    assert restarted.store.course(first)["scroll"] == {"1.html": 120, "2.htm": 240}
    assert restarted.store.course(second)["scroll"] == {"1.html": 360}
