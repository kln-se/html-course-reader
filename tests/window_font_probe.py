"""Проверка шрифтов настоящего окна без курсов, сети и записи настроек."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QLabel, QToolButton
from course_reader.storage import Store
from course_reader.window import Window


def main() -> int:
    """Сравнить запуск, отмену и применение настоящего диалога настроек."""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # Уникальный несуществующий путь; save заменён, записи на диск нет.
    store = Store(Path(__file__).parent / ('font-probe-' + uuid4().hex))
    store.save = lambda: None
    window = Window(store)
    window.setWindowTitle('Диагностика шрифтов — автоматическое закрытие')
    window.notes_dock.show()
    widgets = dict(tree=window.tree, notes=window.notes_list,
                   zoom=window.zoom_label, status=window.status_bar,
                   brand=window.findChild(QLabel, 'brand'))
    for index, button in enumerate(window.findChildren(QToolButton)):
        if button.text():
            widgets[f'button-{index}-{button.text()}'] = button
    baseline = None
    failures = []
    stages = iter(('cancel', 'dark', 'dark', 'light', 'dark'))

    def report(stage: str) -> None:
        """Сравнить гарнитуру, размер и метрики со стартовым состоянием."""
        nonlocal baseline
        snapshot = {}
        print(stage, flush=True)
        for name, widget in widgets.items():
            font = widget.font()
            actual = QFontInfo(font)
            expected_size = 17.0 if name == 'brand' else 9.5 if name == 'status' else 10.5
            assert font.pointSizeF() == expected_size, (
                f'{name}: expected {expected_size} pt, got {font.pointSizeF()}'
            )
            snapshot[name] = (font.family(), font.pointSizeF(), actual.family(),
                              actual.pointSizeF(), widget.fontMetrics().height())
            print(name, snapshot[name], flush=True)
        if baseline is None:
            baseline = snapshot
        elif snapshot != baseline:
            failures.append(stage)

    def finish(code: int) -> None:
        """Освободить WebEngine штатным закрытием и вернуть результат."""
        window.close()
        app.exit(code)

    def step() -> None:
        """Открыть настоящий диалог и нажать его кнопку по таймеру."""
        try:
            report('snapshot')
            stage = next(stages, None)
            if stage is None:
                print('FONT_REGRESSION_FAIL' if failures else 'FONT_REGRESSION_PASS',
                      failures, flush=True)
                finish(1 if failures else 0)
                return

            def respond() -> None:
                """Снять показания с открытыми настройками и выбрать действие."""
                try:
                    dialog = app.activeModalWidget()
                    assert dialog is not None, 'Нет диалога настроек'
                    report('dialog-open-' + stage)
                    if stage != 'cancel':
                        combo = dialog.findChild(QComboBox)
                        assert combo is not None, 'Нет выбора темы'
                        theme_index = combo.findData(stage)
                        assert theme_index >= 0, f'Нет темы {stage}'
                        combo.setCurrentIndex(theme_index)
                    buttons = dialog.findChild(QDialogButtonBox)
                    choice = (QDialogButtonBox.StandardButton.Cancel if stage == 'cancel'
                              else QDialogButtonBox.StandardButton.Ok)
                    buttons.button(choice).click()
                except Exception as error:
                    failures.append(str(error))
                    dialog = app.activeModalWidget()
                    if dialog is not None:
                        dialog.reject()

            QTimer.singleShot(250, respond)
            window.settings_dialog()
            if stage != 'cancel':
                assert store.settings['app']['theme'] == stage, 'Тема не применилась'
            QTimer.singleShot(250, step)
        except Exception as error:
            print('FONT_REGRESSION_FAIL:', error, flush=True)
            finish(1)

    window.show()
    QTimer.singleShot(250, step)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
