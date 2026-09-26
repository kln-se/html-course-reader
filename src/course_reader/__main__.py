"""Запуск приложения с данными рядом с программой."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from .storage import Store
from .window import Window


def main() -> int:
    """Создать приложение, восстановить активный курс и вернуть код завершения Qt.

    При отсутствии активного курса или его папки открывается выбор курса.
    Данные размещаются у EXE в сборке или в корне исходников. Ошибка
    создания хранилища или окна выводится в диалоге и возвращает код 1."""
    app = QApplication(sys.argv)
    app.setApplicationName('Course Reader')
    directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    try:
        store = Store(directory)
        window = Window(store)
    except Exception as error:
        QMessageBox.critical(None, 'Ошибка запуска', str(error))
        return 1
    window.show()
    window.restore_course()
    return app.exec()
