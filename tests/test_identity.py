"""Проверки иконки и порядка запуска без окон и вызовов Windows API."""

import ctypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from src.course_reader import __main__ as entrypoint
from src.course_reader import identity
import gui_preview


def test_windows_app_id_is_skipped_on_other_platforms(monkeypatch):
    loader = Mock()
    monkeypatch.setattr(identity.sys, 'platform', 'linux')
    monkeypatch.setattr(identity.ctypes, 'WinDLL', loader, raising=False)
    assert identity.set_windows_app_id() is False
    loader.assert_not_called()


@pytest.mark.parametrize('hresult,expected', [(0, True), (1, False), (-2147467259, False)])
def test_windows_app_id_handles_hresult(monkeypatch, hresult, expected):
    setter = Mock(return_value=hresult)
    loader = Mock(return_value=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=setter))
    monkeypatch.setattr(identity.sys, 'platform', 'win32')
    monkeypatch.setattr(identity.ctypes, 'WinDLL', loader, raising=False)
    assert identity.set_windows_app_id() is expected
    loader.assert_called_once_with('shell32', use_last_error=True)
    setter.assert_called_once_with(identity.APP_ID)
    assert setter.argtypes == [ctypes.c_wchar_p]
    assert setter.restype is ctypes.c_long


@pytest.mark.parametrize('error_type', [OSError, AttributeError])
def test_windows_app_id_handles_unavailable_api(monkeypatch, error_type):
    loader = Mock(side_effect=error_type('Windows API unavailable'))
    monkeypatch.setattr(identity.sys, 'platform', 'win32')
    monkeypatch.setattr(identity.ctypes, 'WinDLL', loader, raising=False)
    assert identity.set_windows_app_id() is False
    loader.assert_called_once_with('shell32', use_last_error=True)


def test_windows_app_id_handles_missing_setter(monkeypatch):
    monkeypatch.setattr(identity.sys, 'platform', 'win32')
    monkeypatch.setattr(identity.ctypes, 'WinDLL', Mock(return_value=SimpleNamespace()), raising=False)
    assert identity.set_windows_app_id() is False


@pytest.mark.parametrize('frozen', [False, True])
def test_icon_path_is_relative_to_module_not_working_directory(monkeypatch, tmp_path, frozen):
    """Given: другая рабочая папка. When: поиск ICO. Then: ресурс берётся рядом с модулем."""
    module_path = tmp_path / 'bundle' / 'src' / 'course_reader' / 'identity.py'
    monkeypatch.setattr(identity, '__file__', str(module_path))
    monkeypatch.setattr(identity.sys, 'frozen', frozen, raising=False)
    monkeypatch.chdir(tmp_path)
    assert identity.application_icon_path() == module_path.parent / 'assets' / 'app.ico'


def test_configure_application_sets_name_and_icon(monkeypatch):
    app = Mock()
    icon = Mock()
    icon.isNull.return_value = False
    icon_path = identity.application_icon_path()
    factory = Mock(return_value=icon)
    monkeypatch.setattr(identity, 'QIcon', factory)
    identity.configure_application(app)
    app.setApplicationName.assert_called_once_with('HTML Course Reader')
    app.setApplicationVersion.assert_called_once_with('1.0.0')
    factory.assert_called_once_with(str(icon_path))
    app.setWindowIcon.assert_called_once_with(icon)


def test_configure_application_rejects_unloadable_icon(monkeypatch):
    app = Mock()
    icon = Mock()
    icon.isNull.return_value = True
    icon_path = identity.application_icon_path()
    monkeypatch.setattr(identity, 'QIcon', Mock(return_value=icon))
    with pytest.raises(RuntimeError) as error:
        identity.configure_application(app)
    assert str(error.value) == f'Не удалось загрузить иконку приложения: {icon_path}'
    app.setWindowIcon.assert_not_called()


@pytest.mark.parametrize('app_id_result', [True, False])
def test_main_configures_identity_before_creating_window(monkeypatch, app_id_result):
    """Given: границы Qt заменены. When: запуск. Then: App ID до Qt, иконка до окна."""
    events = Mock()
    app = Mock()
    app.exec.return_value = 7
    store, window = Mock(), Mock()
    app_id = Mock(return_value=app_id_result)
    app_factory = Mock(return_value=app)
    configure = Mock()
    store_factory = Mock(return_value=store)
    window_factory = Mock(return_value=window)
    critical = Mock()
    for name, mocked in (
        ('app_id', app_id), ('application', app_factory), ('configure', configure),
        ('store', store_factory), ('window', window_factory), ('show', window.show),
        ('restore_course', window.restore_course), ('exec', app.exec),
    ):
        events.attach_mock(mocked, name)
    monkeypatch.setattr(entrypoint, 'set_windows_app_id', app_id)
    monkeypatch.setattr(entrypoint, 'QApplication', app_factory)
    monkeypatch.setattr(entrypoint, 'configure_application', configure)
    monkeypatch.setattr(entrypoint, 'Store', store_factory)
    monkeypatch.setattr(entrypoint, 'Window', window_factory)
    monkeypatch.setattr(entrypoint, 'QMessageBox', SimpleNamespace(critical=critical))
    monkeypatch.setattr(entrypoint.sys, 'frozen', False, raising=False)
    assert entrypoint.main() == 7
    directory = Path(entrypoint.__file__).resolve().parents[2]
    assert events.mock_calls == [
        call.app_id(), call.application(entrypoint.sys.argv), call.configure(app),
        call.store(directory), call.window(store), call.show(), call.restore_course(), call.exec(),
    ]
    critical.assert_not_called()


def test_main_reports_unloadable_icon_before_creating_store(monkeypatch):
    app, icon = Mock(), Mock()
    icon.isNull.return_value = True
    icon_path = identity.application_icon_path()
    store_factory, window_factory, critical = Mock(), Mock(), Mock()
    monkeypatch.setattr(identity, 'QIcon', Mock(return_value=icon))
    monkeypatch.setattr(entrypoint, 'set_windows_app_id', Mock(return_value=False))
    monkeypatch.setattr(entrypoint, 'QApplication', Mock(return_value=app))
    monkeypatch.setattr(entrypoint, 'configure_application', identity.configure_application)
    monkeypatch.setattr(entrypoint, 'Store', store_factory)
    monkeypatch.setattr(entrypoint, 'Window', window_factory)
    monkeypatch.setattr(entrypoint, 'QMessageBox', SimpleNamespace(critical=critical))
    monkeypatch.setattr(entrypoint.sys, 'frozen', False, raising=False)
    assert entrypoint.main() == 1
    critical.assert_called_once_with(None, 'Ошибка запуска', f'Не удалось загрузить иконку приложения: {icon_path}')
    store_factory.assert_not_called()
    window_factory.assert_not_called()
    app.setWindowIcon.assert_not_called()
    app.exec.assert_not_called()


def test_preview_configures_identity_before_window(monkeypatch, tmp_path):
    """Given: ручной запуск без реального Qt. When: старт. Then: иконка задана до окна."""
    (tmp_path / 'tests').mkdir()
    monkeypatch.setattr(gui_preview, 'PROJECT', tmp_path)
    events = []
    app, window, store, timer = Mock(), Mock(), Mock(), Mock()
    app.exec.return_value = 3
    store.course.return_value = {'last': ''}
    monkeypatch.setattr(gui_preview, 'set_windows_app_id', lambda: events.append('id'))
    monkeypatch.setattr(gui_preview, 'QApplication', lambda args: events.append('app') or app)
    configure = Mock(side_effect=lambda configured: events.append('icon'))
    monkeypatch.setattr(gui_preview, 'configure_application', configure)
    monkeypatch.setattr(gui_preview, 'Store', lambda directory: store)
    monkeypatch.setattr(gui_preview, 'Window', lambda data: events.append('window') or window)
    monkeypatch.setattr(gui_preview, 'QTimer', timer)

    assert gui_preview.main() == 3

    assert events == ['id', 'app', 'icon', 'window']
    configure.assert_called_once_with(app)
    window.show.assert_called_once_with()
    delay, callback = timer.singleShot.call_args.args
    assert delay == 0
    callback()
    window.set_course.assert_called_once_with(tmp_path / 'tests' / 'manual_course')
