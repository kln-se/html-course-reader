"""Построение каталога и правила перехода по материалам."""
import fnmatch
import re
from pathlib import Path
from urllib.parse import urlparse

PAGE_SUFFIXES = {'.html', '.htm', '.mhtml', '.mht'}


def natural_key(value: str) -> tuple:
    """Вернуть ключ естественной сортировки с числовыми группами и устойчивым порядком имён."""
    parts = tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                  for part in re.split(r'(\d+)', value))
    return parts, value.casefold(), value


def matches(path: Path, patterns: list[str]) -> bool:
    """Проверить имя файла по маскам fnmatch без учёта регистра; путь к папке не учитывается."""
    return any(fnmatch.fnmatchcase(path.name.casefold(), p.casefold()) for p in patterns)


def scan(root: Path, patterns: list[str]) -> list[Path]:
    """Собрать подходящие файлы рекурсивным обходом в естественном порядке.

    Символические ссылки и недоступные для перечисления папки пропускаются.
    Возвращаемые пути сохраняют форму заданного root; пустые папки не входят в результат."""
    result = []
    def visit(directory: Path) -> None:
        """Добавить файлы доступной папки и её подкаталогов в общий результат обхода."""
        try:
            children = sorted(directory.iterdir(), key=lambda p: natural_key(p.name))
        except OSError:
            return
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                visit(child)
            elif child.is_file() and matches(child, patterns):
                result.append(child)
    visit(root)
    return result


def adjacent(pages: list[Path], current: Path | None, step: int) -> Path | None:
    """Вернуть соседнюю страницу либо None на границе списка.

    При отсутствии current выбрать первый файл для шага 1 и последний для -1.
    Другой шаг вызывает ValueError; обход не замыкается в кольцо."""
    if step not in (-1, 1):
        raise ValueError('Шаг должен быть -1 или 1')
    if not pages:
        return None
    if current not in pages:
        return pages[0] if step == 1 else pages[-1]
    index = pages.index(current) + step
    return pages[index] if 0 <= index < len(pages) else None


def link_kind(address: str) -> str:
    """Классифицировать схему адреса как internet, local или blocked без проверки существования файла."""
    scheme = urlparse(address).scheme.lower()
    if scheme in ('http', 'https'):
        return 'internet'
    if scheme in ('', 'file'):
        return 'local'
    return 'blocked'
