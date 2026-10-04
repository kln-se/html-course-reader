"""Запуск приложения с данными рядом с программой."""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from .storage import Store
from .window import Window
from .identity import configure_application, set_windows_app_id


def main() -> int:
    """Настроить приложение, восстановить активный курс и запустить цикл событий Qt.

    При отсутствии активного курса или его папки открывается выбор курса.
    Иконка назначается до создания окна. Данные размещаются у EXE в сборке
    или в корне исходников. Возвращается код завершения Qt; ошибка загрузки
    иконки, создания хранилища или окна выводится в диалоге и возвращает код 1.
    """
    set_windows_app_id()
    app = QApplication(sys.argv)
    directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    try:
        configure_application(app)
        store = Store(directory)
        window = Window(store)
    except Exception as error:
        QMessageBox.critical(None, 'Ошибка запуска', str(error))
        return 1
    window.show()
    window.restore_course()
    return app.exec()
