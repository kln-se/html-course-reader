"""Проверки внешних ссылок и жизненного цикла окна «О приложении»."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from src.course_reader import about as about_module
from src.course_reader import window as window_module


@pytest.mark.parametrize('method_name,expected_url', [
    ('open_profile', 'https://github.com/kln-se'),
    ('report_issue', 'https://github.com/kln-se/html-course-reader/issues'),
])
@pytest.mark.parametrize('opened', [True, False])
def test_about_external_link(monkeypatch, method_name, expected_url, opened):
    open_url = Mock(return_value=opened)
    warning = Mock()
    monkeypatch.setattr(about_module, 'QDesktopServices', SimpleNamespace(openUrl=open_url))
    monkeypatch.setattr(about_module, 'QMessageBox', SimpleNamespace(warning=warning))
    dialog = SimpleNamespace()
    dialog._open_external = MethodType(about_module.AboutDialog._open_external, dialog)

    getattr(about_module.AboutDialog, method_name)(dialog)

    open_url.assert_called_once()
    (url,), kwargs = open_url.call_args
    assert url.toString() == expected_url
    assert kwargs == {}
    if opened:
        warning.assert_not_called()
    else:
        warning.assert_called_once_with(dialog, 'Не удалось открыть ссылку',
                                       f'Откройте адрес в браузере вручную:\n{expected_url}')


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('outcome', ['rejected', 'accepted', 'error'])
def test_show_about_disposes_dialog(monkeypatch, theme, outcome):
    execution_error = RuntimeError('dialog execution failed')
    dialog = SimpleNamespace(
        exec=Mock(return_value=1 if outcome == 'accepted' else 0,
                  side_effect=execution_error if outcome == 'error' else None),
        deleteLater=Mock(),
    )
    factory = Mock(return_value=dialog)
    monkeypatch.setattr(window_module, 'AboutDialog', factory)
    reader = SimpleNamespace(store=SimpleNamespace(settings={'app': {'theme': theme}}))

    if outcome == 'error':
        with pytest.raises(RuntimeError) as caught:
            window_module.Window.show_about(reader)
        assert caught.value is execution_error
    else:
        window_module.Window.show_about(reader)

    factory.assert_called_once_with(reader, theme)
    dialog.exec.assert_called_once_with()
    dialog.deleteLater.assert_called_once_with()
