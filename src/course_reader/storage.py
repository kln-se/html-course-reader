"""Хранение переносимых настроек и данных курсов."""
import configparser
import json
import os
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_PATTERNS = ['*.html', '*.htm', '*.mhtml', '*.mht']


class Store:
    """Хранить настройки и изменяемое состояние курсов в памяти с явным сохранением.

    Курсы индексируются абсолютным корнем, страницы — относительным путём.
    Методы изменения не записывают файлы: вызывающая сторона использует save()."""
    def __init__(self, directory: Path):
        """Загрузить settings.ini и history.json из существующей папки directory.

        При отсутствии файлов использовать значения по умолчанию. Ошибки чтения,
        разбора и проверки данных передаются вызывающей стороне; папка не создаётся."""
        self.directory = directory
        self.settings = configparser.ConfigParser(interpolation=None)
        self.settings['app'] = {'visible_patterns': ', '.join(DEFAULT_PATTERNS),
                                'internet_links': 'false', 'theme': 'dark', 'zoom': '1.0'}
        settings_path = directory / 'settings.ini'
        if settings_path.exists():
            with settings_path.open(encoding='utf-8') as stream:
                self.settings.read_file(stream)
        history_path = directory / 'history.json'
        self.data = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {'courses': {}}
        if not isinstance(self.data, dict) or not isinstance(self.data.get('courses'), dict):
            raise ValueError('Некорректный history.json')
        self._validate()

    def _validate(self) -> None:
        """Проверить настройки и структуру истории; отклонить некорректные значения через ValueError."""
        try:
            self.settings.getboolean('app', 'internet_links')
            zoom = self.settings.getfloat('app', 'zoom')
            if not math.isfinite(zoom) or not 0.25 <= zoom <= 3.0:
                raise ValueError('Масштаб должен быть от 0.25 до 3.0')
            if self.settings['app']['theme'] not in ('dark', 'light'):
                raise ValueError('Тема должна быть dark или light')
        except ValueError as error:
            raise ValueError(f'Некорректный settings.ini: {error}') from error
        for root, course in self.data['courses'].items():
            if not isinstance(root, str) or not isinstance(course, dict):
                raise ValueError('Некорректный курс в history.json')
            expected = {'last': str, 'scroll': dict, 'favorites': list, 'notes': dict}
            if any(not isinstance(course.get(key), kind) for key, kind in expected.items()):
                raise ValueError('Некорректные поля курса в history.json')
            paths = [course['last'], *course['favorites'], *course['scroll'], *course['notes']]
            if any(not isinstance(p, str) or Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
                raise ValueError('Некорректный относительный путь в history.json')
            if any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 for p in course['scroll'].values()):
                raise ValueError('Некорректная прокрутка в history.json')
            for notes in course['notes'].values():
                if not isinstance(notes, list):
                    raise ValueError('Некорректные заметки в history.json')
                identifiers = set()
                for note in notes:
                    if not isinstance(note, dict) or any(not isinstance(note.get(k), str) for k in ('id', 'text', 'created', 'updated')):
                        raise ValueError('Некорректная заметка в history.json')
                    if not note['id'] or note['id'] in identifiers:
                        raise ValueError('Повторяющийся идентификатор заметки в history.json')
                    identifiers.add(note['id'])

    @property
    def patterns(self) -> list[str]:
        """Вернуть непустые маски из visible_patterns, разделённых запятыми, без краевых пробелов."""
        return [p.strip() for p in self.settings['app']['visible_patterns'].split(',') if p.strip()]

    def course(self, root: Path) -> dict:
        """Вернуть изменяемое состояние курса, создав пустую запись для нового абсолютного корня."""
        return self.data['courses'].setdefault(str(root.resolve()),
            {'last': '', 'scroll': {}, 'favorites': [], 'notes': {}})

    def relocate(self, old: str, new: Path) -> None:
        """Перенести запись old на новый абсолютный корень, сохранив относительные пути.

        Файлы курса не перемещаются. Занятый другой записью корень вызывает
        ValueError, отсутствующий old — KeyError. Изменение остаётся в памяти."""
        key = str(new.resolve())
        if key != old and key in self.data['courses']:
            raise ValueError('Эта папка уже есть в истории')
        self.data['courses'][key] = self.data['courses'].pop(old)

    def toggle_favorite(self, root: Path, relative: str) -> bool:
        """Переключить избранное для относительного пути и вернуть новое состояние признака."""
        favorites = self.course(root)['favorites']
        if relative in favorites:
            favorites.remove(relative)
            return False
        favorites.append(relative)
        return True

    def add_note(self, root: Path, relative: str, text: str) -> dict:
        """Добавить заметку и вернуть её изменяемую запись с UUID и временными метками UTC.

        Пустой или пробельный текст вызывает ValueError; исходный текст сохраняется целиком."""
        if not text.strip():
            raise ValueError('Заметка не может быть пустой')
        timestamp = datetime.now(timezone.utc).isoformat()
        note = {'id': uuid4().hex, 'text': text, 'created': timestamp, 'updated': timestamp}
        self.course(root)['notes'].setdefault(relative, []).append(note)
        return note

    def edit_note(self, root: Path, relative: str, identifier: str, text: str) -> None:
        """Обновить текст и дату изменения заметки по идентификатору.

        Пустой текст вызывает ValueError, неизвестный идентификатор — KeyError."""
        if not text.strip():
            raise ValueError('Заметка не может быть пустой')
        for note in self.course(root)['notes'].get(relative, []):
            if note['id'] == identifier:
                note['text'] = text
                note['updated'] = datetime.now(timezone.utc).isoformat()
                return
        raise KeyError(identifier)

    def delete_note(self, root: Path, relative: str, identifier: str) -> None:
        """Удалить заметку по идентификатору; при отсутствии совпадения вызвать KeyError."""
        notes = self.course(root)['notes'].get(relative, [])
        for index, note in enumerate(notes):
            if note['id'] == identifier:
                del notes[index]
                return
        raise KeyError(identifier)

    def save(self) -> None:
        """Записать настройки и историю в UTF-8 с заменой каждого файла через временный.

        Две записи не составляют общую транзакцию: ошибка второй не отменяет первую.
        Ошибки файловой системы передаются вызывающей стороне."""
        from io import StringIO
        stream = StringIO()
        self.settings.write(stream)
        self._atomic('settings.ini', stream.getvalue())
        self._atomic('history.json', json.dumps(self.data, ensure_ascii=False, indent=2))

    def _atomic(self, name: str, content: str) -> None:
        """Записать content в name.tmp и заменить целевой файл; передать ошибки ввода-вывода."""
        temporary = self.directory / (name + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        os.replace(temporary, self.directory / name)
