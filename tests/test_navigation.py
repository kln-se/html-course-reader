"""Проверять логику навигации на границах Qt без создания приложения или окон."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QMessageBox

from src.course_reader.storage import Store
from src.course_reader.viewer import Page, OfflineInterceptor
from src.course_reader.window import Window


@pytest.fixture
def reader(tmp_path):
    """Создать состояние читателя с реальным хранилищем и наблюдаемыми Qt-границами."""
    root = tmp_path / 'course'
    root.mkdir()
    current = root / '1.html'
    current.write_text('<p>first</p>', encoding='utf-8')
    scripts, messages, timers = [], [], []
    state = SimpleNamespace(
        root=root, current=current, loading=True, navigation_generation=1,
        restore_position=True, closing=False,
        store=Store(tmp_path), scripts=scripts, messages=messages, timers=timers,
        address=QUrl.fromLocalFile(str(current)),
        page=SimpleNamespace(runJavaScript=lambda script, callback: scripts.append((script, callback))),
        save_timer=SimpleNamespace(start=timers.append),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )
    state.view = SimpleNamespace(url=lambda: state.address)
    state.store.course(root)['scroll']['1.html'] = 425
    return state


def test_loaded_restores_position_before_allowing_scroll_recording(reader):
    Window.loaded(reader, True)
    assert reader.loading is True
    assert len(reader.scripts) == 1
    script, callback = reader.scripts[0]
    assert script == 'window.scrollTo(0, 425.0);'
    callback(None)
    assert reader.loading is False
    Window.scroll_changed(reader, SimpleNamespace(y=lambda: 510))
    assert reader.store.course(reader.root)['scroll'] == {'1.html': 510}
    assert reader.timers == [700]


def test_loaded_without_saved_position_restores_top(reader):
    reader.store.course(reader.root)['scroll'].clear()
    Window.loaded(reader, True)
    assert reader.scripts[0][0] == 'window.scrollTo(0, 0.0);'


def test_loaded_anchor_keeps_browser_position(reader):
    reader.address.setFragment('section-2')
    Window.loaded(reader, True)
    assert reader.scripts == []
    assert reader.loading is False


def test_loaded_ignores_url_of_previous_page(reader):
    reader.address = QUrl.fromLocalFile(str(reader.root / 'old.html'))
    Window.loaded(reader, True)
    assert reader.scripts == []
    assert reader.loading is True
    assert reader.messages == []
    assert reader.store.course(reader.root)['scroll'] == {'1.html': 425}


def test_stale_javascript_callback_cannot_finish_new_navigation(reader):
    """Given: отложенный callback. When: начат другой переход. Then: его прокрутка защищена."""
    Window.loaded(reader, True)
    stale_callback = reader.scripts[0][1]
    reader.navigation_generation += 1
    reader.current = reader.root / '2.html'
    reader.address = QUrl.fromLocalFile(str(reader.current))
    stale_callback(None)
    assert reader.loading is True
    Window.scroll_changed(reader, SimpleNamespace(y=lambda: 0))
    assert reader.store.course(reader.root)['scroll'] == {'1.html': 425}
    assert reader.timers == []
    Window.loaded(reader, True)
    reader.scripts[1][1](None)
    assert reader.loading is False


def test_failed_load_reports_page_without_overwriting_scroll(reader):
    Window.loaded(reader, False)
    assert reader.messages == ['Не удалось отобразить: ' + str(reader.current)]
    assert reader.scripts == []
    Window.scroll_changed(reader, SimpleNamespace(y=lambda: 0))
    assert reader.store.course(reader.root)['scroll'] == {'1.html': 425}
    assert reader.timers == []


@pytest.mark.parametrize('success', [False, True])
def test_load_event_without_current_page_does_nothing(reader, success):
    reader.current = None
    Window.loaded(reader, success)
    assert reader.scripts == []
    assert reader.messages == []


@pytest.mark.parametrize('missing', ['loading', 'current', 'root'])
def test_scroll_is_ignored_until_current_page_is_ready(reader, missing):
    reader.loading = missing == 'loading'
    if missing != 'loading':
        setattr(reader, missing, None)
    Window.scroll_changed(reader, SimpleNamespace(y=lambda: 0))
    assert reader.timers == []
    course = next(iter(reader.store.data['courses'].values()))
    assert course['scroll'] == {'1.html': 425}


@pytest.mark.parametrize(('enabled', 'answer', 'question_count', 'open_count'), [
    (False, QMessageBox.StandardButton.Yes, 0, 0),
    (True, QMessageBox.StandardButton.No, 1, 0),
    (True, QMessageBox.StandardButton.Yes, 1, 1),
])
def test_internet_link_requires_setting_and_confirmation(
    reader, monkeypatch, enabled, answer, question_count, open_count,
):
    questions, opened = [], []

    def question(*args):
        """Записать обращение к внешнему диалогу и вернуть заданный ответ."""
        questions.append(args)
        return answer

    monkeypatch.setattr('src.course_reader.window.QMessageBox.question', question)
    monkeypatch.setattr('src.course_reader.window.QDesktopServices.openUrl', opened.append)
    reader.store.settings['app']['internet_links'] = str(enabled).lower()
    address = 'https://example.com/lesson'
    Window.internet_link(reader, address)
    assert len(questions) == question_count
    assert [url.toString() for url in opened] == [address] * open_count
    if questions:
        assert address in questions[0][2]


@pytest.fixture
def page_policy(reader):
    """Предоставить сигналы и setUrl; проверять локальный путь настоящим Window.allow_local."""
    internet, local, opened, external = [], [], [], []
    reader.external_file = external.append
    return SimpleNamespace(
        internet_requested=SimpleNamespace(emit=internet.append),
        local_requested=SimpleNamespace(emit=lambda path, restore: local.append((path, restore))),
        pending_restore=None,
        allow_local=lambda filename: Window.allow_local(reader, filename),
        setUrl=opened.append, internet=internet, local=local, opened=opened, external=external,
    )


@pytest.mark.parametrize('main_frame', [False, True])
def test_internet_navigation_is_cancelled_and_only_main_frame_signals(page_policy, main_frame):
    address = 'https://example.com/lesson'
    assert Page.acceptNavigationRequest(page_policy, QUrl(address), None, main_frame) is False
    assert page_policy.internet == ([address] if main_frame else [])
    assert page_policy.local == []
    assert page_policy.opened == []


def test_local_navigation_accepts_course_page_and_signals_path(page_policy, reader):
    url = QUrl.fromLocalFile(str(reader.current))
    url.setFragment('section')
    assert Page.acceptNavigationRequest(page_policy, url, None, True) is True
    assert page_policy.local == [(url.toLocalFile(), False)]
    assert page_policy.internet == []


@pytest.mark.parametrize('target', ['outside', 'missing', 'video'])
def test_main_frame_rejects_unavailable_or_external_files(page_policy, reader, tmp_path, target):
    path = {'outside': tmp_path / 'outside.html', 'missing': reader.root / 'missing.html',
            'video': reader.root / 'video.mp4'}[target]
    if target != 'missing':
        path.write_bytes(b'material')
    assert Page.acceptNavigationRequest(page_policy, QUrl.fromLocalFile(str(path)), None, True) is False
    assert page_policy.local == []
    assert page_policy.external == ([path] if target == 'video' else [])


@pytest.mark.parametrize(('address', 'accepted'), [
    ('about:blank', True), ('javascript:alert(1)', False),
    ('mailto:test@example.com', False), ('data:text/html,hello', False),
])
def test_navigation_rejects_unsupported_schemes(page_policy, address, accepted):
    assert Page.acceptNavigationRequest(page_policy, QUrl(address), None, True) is accepted
    assert page_policy.internet == []
    assert page_policy.local == []


def test_local_subframe_does_not_change_current_page(page_policy, reader):
    url = QUrl.fromLocalFile(str(reader.current))
    assert Page.acceptNavigationRequest(page_policy, url, None, False) is True
    assert page_policy.local == []


@pytest.mark.parametrize('target', ['internet', 'local', 'outside', 'unsupported'])
def test_new_window_request_routes_to_existing_view_or_confirmation(page_policy, reader, tmp_path, target):
    outside = tmp_path / 'outside.html'
    outside.write_text('outside', encoding='utf-8')
    url = {
        'internet': QUrl('https://example.com/lesson'),
        'local': QUrl.fromLocalFile(str(reader.current)),
        'outside': QUrl.fromLocalFile(str(outside)),
        'unsupported': QUrl('javascript:alert(1)'),
    }[target]
    Page.open_requested_window(page_policy, SimpleNamespace(requestedUrl=lambda: url))
    assert page_policy.internet == ([url.toString()] if target == 'internet' else [])
    assert page_policy.opened == ([url] if target == 'local' else [])
    assert page_policy.local == []


@pytest.mark.parametrize(('address', 'blocked'), [
    ('https://example.com/image.png', True), ('http://example.com/font.woff', True),
    ('wss://example.com/socket', True), ('ftp://example.com/file', True),
    ('file:///C:/course/style.css', False), ('data:image/png;base64,AA==', False),
    ('blob:https://example.com/local-id', False), ('qrc:/resource', False),
    ('about:blank', False),
])
def test_resource_interceptor_blocks_network_schemes(address, blocked):
    calls = []
    info = SimpleNamespace(requestUrl=lambda: QUrl(address), block=calls.append)
    OfflineInterceptor.interceptRequest(SimpleNamespace(allowed_types=frozenset()), info)
    assert calls == ([True] if blocked else [])


def test_open_saved_restoration_is_consumed_once(page_policy, reader):
    """Given: файл выбран в дереве. When: затем ссылка Наверх. Then: восстановление только при выборе."""
    url = QUrl.fromLocalFile(str(reader.current))
    scripts = reader.scripts
    page_policy.runJavaScript = reader.page.runJavaScript
    page_policy.open_saved = lambda address: Page.open_saved(page_policy, address)
    reader.page = page_policy
    reader.persist = reader.store.save
    reader.refresh_metadata = lambda: None

    def local_signal(path, restore):
        """Доставить сигнал настоящему обработчику без создания Qt-объектов."""
        page_policy.local.append((path, restore))
        Window.local_link(reader, path, restore)

    page_policy.local_requested.emit = local_signal
    Window.open_file(reader, reader.current)
    assert page_policy.opened == [url]
    assert page_policy.pending_restore == url.toString()
    assert Page.acceptNavigationRequest(page_policy, url, None, True) is True
    assert page_policy.pending_restore is None
    assert reader.restore_position is True
    Window.loaded(reader, True)
    assert len(scripts) == 1
    scripts[0][1](None)

    # Та же страница по обычной ссылке не должна возвращать читателя вниз.
    assert Page.acceptNavigationRequest(page_policy, url, None, True) is True
    assert reader.restore_position is False
    Window.loaded(reader, True)
    assert len(scripts) == 1
    assert reader.loading is False
    assert page_policy.local == [(url.toLocalFile(), True), (url.toLocalFile(), False)]


def test_pending_restore_does_not_apply_to_another_local_url(page_policy, reader):
    first = QUrl.fromLocalFile(str(reader.current))
    second_path = reader.root / '2.html'
    second_path.write_text('second', encoding='utf-8')
    second = QUrl.fromLocalFile(str(second_path))
    Page.open_saved(page_policy, first)
    assert Page.acceptNavigationRequest(page_policy, second, None, True) is True
    assert page_policy.pending_restore is None
    assert Page.acceptNavigationRequest(page_policy, first, None, True) is True
    assert page_policy.local == [(second.toLocalFile(), False), (first.toLocalFile(), False)]


def test_target_blank_local_link_clears_pending_restore(page_policy, reader):
    url = QUrl.fromLocalFile(str(reader.current))
    Page.open_saved(page_policy, url)
    Page.open_requested_window(page_policy, SimpleNamespace(requestedUrl=lambda: url))
    assert page_policy.pending_restore is None
    assert Page.acceptNavigationRequest(page_policy, url, None, True) is True
    assert page_policy.local == [(url.toLocalFile(), False)]
    assert page_policy.opened == [url, url]


@pytest.mark.parametrize('fragment', ['', 'top'])
def test_ordinary_link_never_restores_saved_position(reader, fragment):
    reader.restore_position = False
    if fragment:
        reader.address.setFragment(fragment)
    Window.loaded(reader, True)
    assert reader.scripts == []
    assert reader.loading is False
    assert reader.store.course(reader.root)['scroll']['1.html'] == 425


@pytest.mark.parametrize('suffix', ['.mhtml', '.mht', '.MHTML', '.MHT'])
def test_archive_page_does_not_attempt_javascript_restore(reader, suffix):
    reader.current = reader.root / ('archive' + suffix)
    reader.address = QUrl.fromLocalFile(str(reader.current))
    reader.store.course(reader.root)['scroll'][reader.current.name] = 425
    Window.loaded(reader, True)
    assert reader.scripts == []
    assert reader.loading is False


@pytest.fixture
def lifecycle(reader, monkeypatch):
    """Записать внешние операции закрытия вместо уничтожения реальных Qt-объектов."""
    calls = []
    reader.save_timer.stop = lambda: calls.append('timer.stop')
    reader.catalog_timer = SimpleNamespace(stop=lambda: calls.append('catalog.stop'))
    reader.catalog_fallback = SimpleNamespace(stop=lambda: calls.append('fallback.stop'))
    reader.catalog_watcher = SimpleNamespace(blockSignals=lambda value: calls.append(('watcher.block', value)))
    reader.persist = lambda: calls.append('persist')
    reader.view.stop = lambda: calls.append('view.stop')
    reader.profile = object()
    event = SimpleNamespace(accept=lambda: calls.append('accept'))

    def delete(obj):
        """Отследить порядок обращения к границе shiboken.delete."""
        if obj is reader.view:
            calls.append('delete.view')
        elif obj is reader.profile:
            calls.append('delete.profile')
        else:
            pytest.fail('Unexpected deletion target')

    monkeypatch.setattr('src.course_reader.window.delete', delete)
    return event, calls


def test_close_destroys_view_before_profile_and_is_idempotent(reader, lifecycle):
    event, calls = lifecycle
    generation = reader.navigation_generation
    Window.closeEvent(reader, event)
    assert calls == ['timer.stop', 'catalog.stop', 'fallback.stop', ('watcher.block', True), 'persist', 'view.stop', 'delete.view', 'delete.profile', 'accept']
    assert reader.closing is True
    assert reader.loading is True
    assert reader.navigation_generation == generation + 1
    Window.closeEvent(reader, event)
    assert calls == ['timer.stop', 'catalog.stop', 'fallback.stop', ('watcher.block', True), 'persist', 'view.stop', 'delete.view', 'delete.profile', 'accept', 'accept']
    assert reader.navigation_generation == generation + 1


def test_callback_after_close_cannot_resume_scroll_saving(reader, lifecycle):
    Window.loaded(reader, True)
    callback = reader.scripts[0][1]
    Window.closeEvent(reader, lifecycle[0])
    callback(None)
    assert reader.loading is True
    Window.scroll_changed(reader, SimpleNamespace(y=lambda: 0))
    assert reader.timers == []
    assert reader.store.course(reader.root)['scroll']['1.html'] == 425


def test_callback_checks_closing_even_without_generation_change(reader):
    Window.loaded(reader, True)
    callback = reader.scripts[0][1]
    reader.closing = True
    callback(None)
    assert reader.loading is True


@pytest.mark.parametrize('success', [False, True])
def test_load_event_after_close_does_not_access_destroyed_view(reader, success):
    reader.closing = True
    reader.view = None
    reader.page = None
    Window.loaded(reader, success)
    assert reader.scripts == []
    assert reader.messages == []
