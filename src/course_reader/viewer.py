"""Просмотр локальных страниц и ограничения переходов через Qt WebEngine."""

from collections.abc import Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWebEngineCore import (
    QWebEngineNewWindowRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

from .catalog import link_kind


class OfflineInterceptor(QWebEngineUrlRequestInterceptor):
    """Ограничивать схемы запросов WebEngine для локального чтения.

    Это фильтр запросов, а не гарантия полной изоляции недоверенной страницы."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Начать с полной блокировки сетевых ресурсов."""
        super().__init__(parent)
        self.allowed_types: frozenset[QWebEngineUrlRequestInfo.ResourceType] = (
            frozenset()
        )

    def configure(
        self, *, enabled: bool, images: bool, styles: bool, fonts: bool
    ) -> None:
        """Заменить неизменяемый набор разрешений для последующих запросов."""
        types = QWebEngineUrlRequestInfo.ResourceType
        self.allowed_types = frozenset(
            kind
            for selected, kind in (
                (images, types.ResourceTypeImage),
                (styles, types.ResourceTypeStylesheet),
                (fonts, types.ResourceTypeFontResource),
            )
            if enabled and selected
        )

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        """Разрешить локальные схемы и выбранные типы HTTP/HTTPS GET-запросов.

        Тип определяет WebEngine, а не расширение URL. Другие сетевые запросы,
        включая документы, скрипты, XHR и видео, блокируются.
        """
        scheme = info.requestUrl().scheme().lower()
        if scheme in ("file", "data", "blob", "qrc", "about"):
            return
        allowed = self.allowed_types
        if (
            scheme in ("http", "https")
            and allowed
            and info.resourceType() in allowed
            and info.requestMethod().data() == b"GET"
        ):
            return
        info.block(True)


class Page(QWebEnginePage):
    """Согласовывать переходы WebEngine с окном через сигналы и проверку allow_local."""

    internet_requested = Signal(str)
    local_requested = Signal(str, bool)

    def __init__(
        self, profile: QWebEngineProfile, parent: QObject | None = None
    ) -> None:
        """Создать страницу в переданном профиле с запретом локальных переходов до настройки allow_local."""
        super().__init__(profile, parent)
        self.allow_local: Callable[[str], bool] = lambda path: False
        self.pending_restore: str | None = None
        self.newWindowRequested.connect(self.open_requested_window)
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False
        )

    def acceptNavigationRequest(
        self,
        url: QUrl | str,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        """Разрешить проверенный локальный переход или about:blank.

        Интернет-переход главного фрейма передаётся сигналом окну и отменяется
        внутри WebEngine; остальные неподдерживаемые схемы отклоняются."""
        url = QUrl(url)
        kind = link_kind(url.toString())
        if kind == "internet":
            if is_main_frame:
                self.internet_requested.emit(url.toString())
            return False
        if url.scheme() != "file":
            return url.toString() == "about:blank"
        if is_main_frame:
            if not self.allow_local(url.toLocalFile()):
                return False
            restore = self.pending_restore == url.toString()
            self.pending_restore = None
            self.local_requested.emit(url.toLocalFile(), restore)
        return True

    def open_saved(self, url: QUrl) -> None:
        """Открыть файл из интерфейса с однократным восстановлением места чтения."""
        self.pending_restore = url.toString()
        self.setUrl(url)

    def open_requested_window(self, request: QWebEngineNewWindowRequest) -> None:
        """Обработать запрос нового окна: передать интернет-адрес или открыть разрешённый файл здесь."""
        url = request.requestedUrl()
        if link_kind(url.toString()) == "internet":
            self.internet_requested.emit(url.toString())
        elif url.scheme() == "file" and self.allow_local(url.toLocalFile()):
            self.pending_restore = None
            self.setUrl(url)
