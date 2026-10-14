"""Редактирование разрешённых типов удалённых ресурсов без изменения настроек до применения."""

from configparser import SectionProxy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .theme import icon, style_checkbox


class RemoteResourcesSettings(QGroupBox):
    """Показывать режим загрузки и сохраняемый выбор трёх типов ресурсов."""

    def __init__(
        self, values: SectionProxy, theme: str, parent: QWidget | None = None
    ) -> None:
        """Загрузить значения секции INI в независимые элементы управления."""
        super().__init__("Ресурсы из интернета", parent)
        layout = QVBoxLayout(self)
        self.off = QRadioButton("Не загружать", self)
        self.on = QRadioButton("Загружать выбранные типы", self)
        for radio in (self.off, self.on):
            style_checkbox(radio, theme)
            layout.addWidget(radio)
        self.options = QWidget(self)
        options_layout = QVBoxLayout(self.options)
        options_layout.setContentsMargins(24, 0, 0, 0)
        self.checks = {}
        for key, label in (
            ("images", "Изображения"),
            ("styles", "Стили"),
            ("fonts", "Шрифты"),
        ):
            check = QCheckBox(label, self.options)
            style_checkbox(check, theme)
            check.setChecked(bool(values.getboolean(key)))
            self.checks[key] = check
            options_layout.addWidget(check)
            check.toggled.connect(self.update_message)
        layout.addWidget(self.options)
        row = QHBoxLayout()
        self.warning = QLabel(self)
        self.warning.setPixmap(icon("warning", theme).pixmap(20, 20))
        self.warning.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        row.addWidget(self.warning)
        row.addWidget(self.message, 1)
        layout.addLayout(row)
        explanation = QLabel(
            "Для загрузки ранее заблокированных ресурсов откройте страницу заново.",
            self,
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("caption")
        layout.addWidget(explanation)
        enabled = bool(values.getboolean("enabled"))
        self.off.setChecked(not enabled)
        self.on.setChecked(enabled)
        self.on.toggled.connect(self.update_message)
        self.update_message()

    def update_message(self, _checked: bool = False) -> None:
        """Обновить доступность чекбоксов и сообщение, сохранив выбранные типы."""
        enabled = self.on.isChecked()
        self.options.setEnabled(enabled)
        self.warning.setVisible(enabled)
        if not enabled:
            text = "Загрузка ресурсов из интернета заблокирована"
        elif any(check.isChecked() for check in self.checks.values()):
            text = (
                "Загрузка выбранных ресурсов из интернета разрешена. "
                "Страницы могут обращаться к внешним серверам."
            )
        else:
            text = "Типы ресурсов не выбраны — загрузка остаётся заблокированной"
        self.message.setText(text)

    def values(self) -> dict[str, str]:
        """Вернуть строковые значения INI без изменения исходной секции настроек."""
        return {
            "enabled": str(self.on.isChecked()).lower(),
            **{
                key: str(check.isChecked()).lower()
                for key, check in self.checks.items()
            },
        }
