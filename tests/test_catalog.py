"""Проверки порядка материалов, масок и классификации переходов."""

from pathlib import Path
from itertools import permutations

import pytest

from course_reader.catalog import adjacent, link_kind, matches, natural_key, scan


def test_natural_sort_orders_numbers_and_ignores_case():
    names = ['10-last.html', '2-beta.html', '01-start.html', '2-Alpha.html']
    assert sorted(names, key=natural_key) == [
        '01-start.html', '2-Alpha.html', '2-beta.html', '10-last.html'
    ]


def test_natural_sort_breaks_numeric_and_case_ties_independently_of_input():
    """Given: равные числовые части. When: разные перечисления. Then: порядок един."""
    expected = ['01-A.html', '01-a.html', '1-A.html', '1-a.html']
    for enumeration in permutations(expected):
        assert sorted(enumeration, key=natural_key) == expected


@pytest.mark.parametrize(('name', 'patterns', 'expected'), [
    ('LESSON.HTML', ['*.html'], True),
    ('lesson.htm', ['*.HTML', '*.HTM'], True),
    ('movie.mp4', ['*.html', '*.mp4'], True),
    ('notes.txt', ['*.html'], False),
    ('lesson.html.bak', ['*.html'], False),
    ('lesson.html', [], False),
])
def test_masks_control_visible_files(name, patterns, expected):
    assert matches(Path(name), patterns) is expected


def test_scan_visits_nested_chapters_in_natural_order(tmp_path):
    """Given: главы и вложения. When: обход. Then: естественный порядок страниц."""
    files = [
        '10-end/1.html', '02-main/10.html', '02-main/2.HTML',
        '01-start/02-nested/1.htm', '01-start/01.html',
        '02-main/movie.mp4', '02-main/style.css',
    ]
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('material', encoding='utf-8')
    pages = scan(tmp_path, ['*.html', '*.htm'])
    assert [p.relative_to(tmp_path).as_posix() for p in pages] == [
        '01-start/01.html', '01-start/02-nested/1.htm',
        '02-main/2.HTML', '02-main/10.html', '10-end/1.html',
    ]
    assert adjacent(pages, pages[1], 1) == tmp_path / '02-main/2.HTML'
    assert adjacent(pages, pages[2], -1) == tmp_path / '01-start/02-nested/1.htm'
    assert tmp_path / '02-main/movie.mp4' in scan(tmp_path, ['*.html', '*.mp4'])


def test_scan_empty_and_missing_directory(tmp_path):
    assert scan(tmp_path, ['*.html']) == []
    assert scan(tmp_path / 'missing', ['*.html']) == []


@pytest.mark.parametrize(('index', 'step', 'expected'), [
    (0, -1, None), (0, 1, 1), (1, -1, 0), (1, 1, 2), (2, 1, None),
])
def test_adjacent_does_not_wrap_at_course_boundaries(index, step, expected):
    pages = [Path('1.html'), Path('2.html'), Path('3.html')]
    assert adjacent(pages, pages[index], step) == (
        None if expected is None else pages[expected]
    )


@pytest.mark.parametrize('step', [-1, 1])
def test_adjacent_handles_no_pages_and_missing_current(step):
    pages = [Path('1.html'), Path('2.html')]
    assert adjacent([], None, step) is None
    expected = pages[0] if step == 1 else pages[-1]
    assert adjacent(pages, None, step) == expected
    assert adjacent(pages, Path('removed.html'), step) == expected


@pytest.mark.parametrize('step', [-2, 0, 2])
def test_adjacent_rejects_invalid_step_even_for_empty_course(step):
    with pytest.raises(ValueError):
        adjacent([], None, step)


@pytest.mark.parametrize(('address', 'expected'), [
    ('https://example.com/lesson', 'internet'),
    ('HTTP://example.com/', 'internet'),
    ('file:///C:/course/01.html', 'local'),
    ('../chapter/02.html', 'local'),
    ('#section', 'local'),
    ('javascript:alert(1)', 'blocked'),
    ('mailto:reader@example.com', 'blocked'),
    ('ftp://example.com/course', 'blocked'),
    ('data:text/html,hello', 'blocked'),
])
def test_link_classification(address, expected):
    assert link_kind(address) == expected
