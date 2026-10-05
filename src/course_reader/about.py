"""Окно сведений о читалке и явные переходы к страницам проекта."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .identity import APP_NAME, APP_VERSION, AUTHOR_HANDLE, AUTHOR_URL, ISSUES_URL
from .theme import PALETTES


class AboutDialog(QDialog):
    """Показать версию и авторство без чтения материалов курса или отправки данных.

    Ссылки открываются только по действию пользователя во внешнем браузере;
    настройка ссылок внутри страниц курса на них не распространяется.
    """

    def __init__(self, parent: QWidget, theme: str) -> None:
        """Создать диалог в переданной теме оформления с русскими кнопками."""
        super().__init__(parent)
        self.setWindowTitle('О приложении')
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(QApplication.windowIcon().pixmap(64, 64))
        header.addWidget(logo)
        titles = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName('brand')
        titles.addWidget(title)
        version = QLabel(f'Версия {APP_VERSION}')
        version.setObjectName('caption')
        titles.addWidget(version)
        header.addLayout(titles, 1)
        layout.addLayout(header)

        author = QLabel(
            f'Разработано <a href="{AUTHOR_URL}" '
            f'style="color: {PALETTES[theme]["accent"]};">{AUTHOR_HANDLE}</a> '
            'совместно с AI Coding Agent'
        )
        author.setWordWrap(True)
        author.setTextFormat(Qt.TextFormat.RichText)
        author.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        author.setOpenExternalLinks(False)
        author.linkActivated.connect(lambda _url: self.open_profile())
        layout.addWidget(author)

        buttons = QHBoxLayout()
        report = QPushButton('Сообщить об ошибке')
        report.setAutoDefault(False)
        report.clicked.connect(self.report_issue)
        buttons.addWidget(report)
        buttons.addStretch()
        close = QPushButton('Закрыть')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def open_profile(self) -> None:
        """Открыть согласованный профиль автора во внешнем браузере."""
        self._open_external(AUTHOR_URL)

    def report_issue(self) -> None:
        """Открыть список GitHub Issues без создания обращения или передачи данных."""
        self._open_external(ISSUES_URL)

    def _open_external(self, address: str) -> None:
        """Передать сервисную ссылку браузеру, сообщив о неудаче запуска."""
        if not QDesktopServices.openUrl(QUrl(address)):
            QMessageBox.warning(self, 'Не удалось открыть ссылку',
                                f'Откройте адрес в браузере вручную:\n{address}')
