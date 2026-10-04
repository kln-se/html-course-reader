"""Иконка приложения и идентификатор группировки окон Windows."""

import ctypes
from pathlib import Path
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


APP_ID = 'HtmlCourseReader.Desktop'


def set_windows_app_id() -> bool:
    """Задать идентификатор процесса до создания QApplication и окон.

    Возвращает False вне Windows или при отказе системного API; это не мешает
    запуску читалки. Не изменяет реестр, ярлыки или настройки пользователя.
    """
    if sys.platform != 'win32':
        return False
    try:
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        setter = shell.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        return setter(APP_ID) == 0
    except (AttributeError, OSError):
        return False


def application_icon_path() -> Path:
    """Найти ICO рядом с модулем в исходниках или ресурсах portable-сборки."""
    return Path(__file__).resolve().parent / 'assets' / 'app.ico'


def configure_application(app: QApplication) -> None:
    """Назначить имя и общую иконку до создания окон и диалогов.

    Raises:
        RuntimeError: Иконка отсутствует или не читается; сборка неполна.
    """
    app.setApplicationName('Course Reader')
    path = application_icon_path()
    icon = QIcon(str(path))
    if icon.isNull():
        raise RuntimeError(f'Не удалось загрузить иконку приложения: {path}')
    app.setWindowIcon(icon)
