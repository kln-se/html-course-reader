"""Просмотр локальных страниц и ограничения переходов через Qt WebEngine."""
from PySide6.QtCore import Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor, QWebEngineSettings
from .catalog import link_kind


class OfflineInterceptor(QWebEngineUrlRequestInterceptor):
    """Ограничивать схемы запросов WebEngine для локального чтения.

    Это фильтр запросов, а не гарантия полной изоляции недоверенной страницы."""
    def interceptRequest(self, info):
        """Блокировать запросы со схемами вне file, data, blob, qrc и about."""
        if info.requestUrl().scheme().lower() not in ('file', 'data', 'blob', 'qrc', 'about'):
            info.block(True)


class Page(QWebEnginePage):
    """Согласовывать переходы WebEngine с окном через сигналы и проверку allow_local."""
    internet_requested = Signal(str)
    local_requested = Signal(str, bool)

    def __init__(self, profile, parent=None):
        """Создать страницу в переданном профиле с запретом локальных переходов до настройки allow_local."""
        super().__init__(profile, parent)
        self.allow_local = lambda path: False
        self.pending_restore = None
        self.newWindowRequested.connect(self.open_requested_window)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, False)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        """Разрешить проверенный локальный переход или about:blank.

        Интернет-переход главного фрейма передаётся сигналом окну и отменяется
        внутри WebEngine; остальные неподдерживаемые схемы отклоняются."""
        kind = link_kind(url.toString())
        if kind == 'internet':
            if is_main_frame:
                self.internet_requested.emit(url.toString())
            return False
        if url.scheme() != 'file':
            return url.toString() == 'about:blank'
        if is_main_frame:
            if not self.allow_local(url.toLocalFile()):
                return False
            restore = self.pending_restore == url.toString()
            self.pending_restore = None
            self.local_requested.emit(url.toLocalFile(), restore)
        return True

    def open_saved(self, url):
        """Открыть файл из интерфейса с однократным восстановлением места чтения."""
        self.pending_restore = url.toString()
        self.setUrl(url)

    def open_requested_window(self, request):
        """Обработать запрос нового окна: передать интернет-адрес или открыть разрешённый файл здесь."""
        url = request.requestedUrl()
        if link_kind(url.toString()) == 'internet':
            self.internet_requested.emit(url.toString())
        elif url.scheme() == 'file' and self.allow_local(url.toLocalFile()):
            self.pending_restore = None
            self.setUrl(url)
