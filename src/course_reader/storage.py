"""Хранение переносимых настроек и данных курсов."""

import configparser
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from uuid import uuid4

DEFAULT_PATTERNS = ["*.html", "*.htm", "*.mhtml", "*.mht"]
FORMAT_GROUPS = {
    "pages": DEFAULT_PATTERNS,
    "video": ["*.mp4", "*.m4v", "*.mpeg", "*.mpg", "*.avi", "*.mkv", "*.webm", "*.mov"],
    "other": ["*.pdf", "*.txt"],
}


class CourseData(TypedDict):
    """Проверенная запись курса с путями страниц относительно его корня."""

    last: str
    scroll: dict[str, float]
    favorites: list[str]
    notes: dict[str, list[dict[str, str]]]


class HistoryData(TypedDict):
    """История курсов с необязательным указанием активного корня."""

    courses: dict[str, CourseData]
    active_course: NotRequired[str]


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
        self.settings["app"] = {
            "internet_links": "false",
            "theme": "dark",
            "zoom": "1.0",
        }
        settings_path = directory / "settings.ini"
        if settings_path.exists():
            with settings_path.open(encoding="utf-8") as stream:
                self.settings.read_file(stream)
        self._initialize_file_groups()
        if not self.settings.has_section("remote_resources"):
            self.settings.add_section("remote_resources")
        for key, default in {
            "enabled": "false",
            "images": "true",
            "styles": "true",
            "fonts": "true",
        }.items():
            if key not in self.settings["remote_resources"]:
                self.settings["remote_resources"][key] = default
        history_path = directory / "history.json"
        loaded = (
            json.loads(history_path.read_text(encoding="utf-8"))
            if history_path.exists()
            else {"courses": {}}
        )
        if not isinstance(loaded, dict) or not isinstance(loaded.get("courses"), dict):
            raise ValueError("Некорректный history.json")
        # cast не проверяет JSON: вложенные значения проверяются в _validate().
        self.data = cast(HistoryData, loaded)
        self._validate()

    def _initialize_file_groups(self) -> None:
        """Подготовить группы масок в памяти, сохранив видимость старого visible_patterns.

        При наличии хотя бы одной новой секции она имеет приоритет над старым
        полем. Недостающие группы получают значения по умолчанию. На диск
        изменения попадают только при обычном save().
        """
        legacy = self.settings["app"].get("visible_patterns")
        migrate = legacy is not None and not any(
            self.settings.has_section("files." + group) for group in FORMAT_GROUPS
        )
        buckets: dict[str, list[str]] = {group: [] for group in FORMAT_GROUPS}
        if migrate and legacy is not None:
            for pattern in (part.strip() for part in legacy.split(",")):
                if not pattern:
                    continue
                group = next(
                    (
                        name
                        for name in ("pages", "video")
                        if pattern.lower() in FORMAT_GROUPS[name]
                    ),
                    "other",
                )
                buckets[group].append(pattern)
        for group, defaults in FORMAT_GROUPS.items():
            section = "files." + group
            if not self.settings.has_section(section):
                self.settings.add_section(section)
            values = self.settings[section]
            masks = buckets[group] if migrate and buckets[group] else defaults
            enabled = bool(buckets[group]) if migrate else group == "pages"
            if "patterns" not in values:
                values["patterns"] = ", ".join(masks)
            if "enabled" not in values:
                values["enabled"] = str(enabled).lower()
        self.settings.remove_option("app", "visible_patterns")

    def _validate(self) -> None:
        """Проверить настройки и структуру истории; отклонить некорректные значения через ValueError."""
        self._validate_settings()
        self._validate_history()

    def _validate_settings(self) -> None:
        """Проверить значения INI; дополнить ошибку указанием файла настроек."""
        try:
            self.settings.getboolean("app", "internet_links")
            for key in ("enabled", "images", "styles", "fonts"):
                self.settings.getboolean("remote_resources", key)
            for group in FORMAT_GROUPS:
                self.settings.getboolean("files." + group, "enabled")
            zoom = self.settings.getfloat("app", "zoom")
            if not math.isfinite(zoom) or not 0.25 <= zoom <= 3.0:
                raise ValueError("Масштаб должен быть от 0.25 до 3.0")
            if self.settings["app"]["theme"] not in ("dark", "light"):
                raise ValueError("Тема должна быть dark или light")
        except ValueError as error:
            raise ValueError(f"Некорректный settings.ini: {error}") from error

    def _validate_history(self) -> None:
        """Проверить поля курсов, относительные пути и позиции без изменения истории."""
        active = self.data.get("active_course", "")
        if not isinstance(active, str):
            raise ValueError("Некорректный активный курс в history.json")
        for root, course in self.data["courses"].items():
            if not isinstance(root, str) or not isinstance(course, dict):
                raise ValueError("Некорректный курс в history.json")
            expected = {"last": str, "scroll": dict, "favorites": list, "notes": dict}
            if any(
                not isinstance(course.get(key), kind) for key, kind in expected.items()
            ):
                raise ValueError("Некорректные поля курса в history.json")
            paths = [
                course["last"],
                *course["favorites"],
                *course["scroll"],
                *course["notes"],
            ]
            if any(
                not isinstance(p, str) or Path(p).is_absolute() or ".." in Path(p).parts
                for p in paths
            ):
                raise ValueError("Некорректный относительный путь в history.json")
            if any(
                type(p) not in (int, float) or not math.isfinite(p) or p < 0
                for p in course["scroll"].values()
            ):
                raise ValueError("Некорректная прокрутка в history.json")
            for notes in course["notes"].values():
                self._validate_notes(notes)

    @staticmethod
    def _validate_notes(notes: object) -> None:
        """Проверить поля заметок и уникальность непустых ID в пределах страницы."""
        if not isinstance(notes, list):
            raise ValueError("Некорректные заметки в history.json")
        identifiers = set()
        for note in notes:
            if not isinstance(note, dict) or any(
                not isinstance(note.get(k), str)
                for k in ("id", "text", "created", "updated")
            ):
                raise ValueError("Некорректная заметка в history.json")
            if not note["id"] or note["id"] in identifiers:
                raise ValueError("Повторяющийся идентификатор заметки в history.json")
            identifiers.add(note["id"])

    @property
    def patterns(self) -> list[str]:
        """Вернуть объединение непустых масок включённых групп без изменения их настроек."""
        return [
            pattern.strip()
            for group in FORMAT_GROUPS
            if self.settings.getboolean("files." + group, "enabled")
            for pattern in self.settings["files." + group]["patterns"].split(",")
            if pattern.strip()
        ]

    def course(self, root: Path) -> CourseData:
        """Вернуть изменяемое состояние курса, создав пустую запись для нового абсолютного корня."""
        return self.data["courses"].setdefault(
            str(root.resolve()),
            {"last": "", "scroll": {}, "favorites": [], "notes": {}},
        )

    @property
    def active_course(self) -> Path | None:
        """Вернуть корень активного курса без проверки существования папки.

        Если выбор отсутствует или не связан с записью курса, вернуть None.
        """
        root = self.data.get("active_course", "")
        return Path(root) if root and root in self.data["courses"] else None

    def activate_course(self, root: Path) -> None:
        """Сделать курс активным, при необходимости создав его запись в памяти.

        Корень сохраняется как абсолютный путь. Для записи на диск вызвать save().
        """
        self.course(root)
        self.data["active_course"] = str(root.resolve())

    def remove_course(self, key: str) -> bool:
        """Удалить известную запись по ключу истории, не обращаясь к файлам курса.

        Сбросить активный курс только при совпадении ключа. Вернуть False,
        если записи уже нет. Для записи результата на диск вызвать save().
        """
        if key not in self.data["courses"]:
            return False
        del self.data["courses"][key]
        if self.data.get("active_course") == key:
            self.data.pop("active_course", None)
        return True

    def relocate(self, old: str, new: Path) -> None:
        """Перенести запись old на новый абсолютный корень, сохранив относительные пути.

        Ссылка на активный курс также обновляется, если переносится его запись.
        Файлы курса не перемещаются. Занятый другой записью корень вызывает
        ValueError, отсутствующий old — KeyError. Изменение остаётся в памяти."""
        key = str(new.resolve())
        if key != old and key in self.data["courses"]:
            raise ValueError("Эта папка уже есть в истории")
        self.data["courses"][key] = self.data["courses"].pop(old)
        if self.data.get("active_course") == old:
            self.data["active_course"] = key

    def toggle_favorite(self, root: Path, relative: str) -> bool:
        """Переключить избранное для относительного пути и вернуть новое состояние признака."""
        favorites = self.course(root)["favorites"]
        if relative in favorites:
            favorites.remove(relative)
            return False
        favorites.append(relative)
        return True

    def add_note(self, root: Path, relative: str, text: str) -> dict[str, str]:
        """Добавить заметку и вернуть её изменяемую запись с UUID и временными метками UTC.

        Пустой или пробельный текст вызывает ValueError; исходный текст сохраняется целиком."""
        if not text.strip():
            raise ValueError("Заметка не может быть пустой")
        timestamp = datetime.now(timezone.utc).isoformat()
        note = {
            "id": uuid4().hex,
            "text": text,
            "created": timestamp,
            "updated": timestamp,
        }
        self.course(root)["notes"].setdefault(relative, []).append(note)
        return note

    def edit_note(self, root: Path, relative: str, identifier: str, text: str) -> None:
        """Обновить текст и дату изменения заметки по идентификатору.

        Пустой текст вызывает ValueError, неизвестный идентификатор — KeyError."""
        if not text.strip():
            raise ValueError("Заметка не может быть пустой")
        for note in self.course(root)["notes"].get(relative, []):
            if note["id"] == identifier:
                note["text"] = text
                note["updated"] = datetime.now(timezone.utc).isoformat()
                return
        raise KeyError(identifier)

    def delete_note(self, root: Path, relative: str, identifier: str) -> None:
        """Удалить заметку по идентификатору; при отсутствии совпадения вызвать KeyError."""
        notes = self.course(root)["notes"].get(relative, [])
        for index, note in enumerate(notes):
            if note["id"] == identifier:
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
        self._atomic("settings.ini", stream.getvalue())
        self._atomic(
            "history.json", json.dumps(self.data, ensure_ascii=False, indent=2)
        )

    def _atomic(self, name: str, content: str) -> None:
        """Записать content в name.tmp и заменить целевой файл; передать ошибки ввода-вывода."""
        temporary = self.directory / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, self.directory / name)
