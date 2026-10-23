"""Which phrasebook answers this job?

One file per job, loaded as a shelf. The loop asks for the book that matches the job it chose, so a
phase can be added by dropping a file in `phrasebooks/` -- and removed by deleting one -- without
touching the ladder.

This is also the phase boundary made physical: a `greet` book cannot answer an `explain`, because
nothing here will hand it over.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ttrpg_chatbots.decide.variant import Phrasebook, PhrasebookError, load


@dataclass(frozen=True)
class Shelf:
    """Every phrasebook a friend has, keyed by the job it does."""

    books: Mapping[str, Phrasebook]

    def for_job(self, job: str) -> Phrasebook | None:
        """The book for this job, or nothing. No borrowing between jobs."""
        return self.books.get(job)

    def jobs(self) -> tuple[str, ...]:
        """Which jobs can actually be answered, sorted so a report is stable."""
        return tuple(sorted(self.books))

    def __bool__(self) -> bool:
        return bool(self.books)


def load_shelf(directory: Path | str, *, fallback: Path | str | None = None) -> Shelf:
    """Read every ``*.json`` in a phrasebook directory, over a shared set.

    A missing directory is an empty shelf, not an error: a friend with no phrasebooks simply has
    nothing to say, which is a valid state for a half-written character.

    ``fallback`` is the world's shared books, and the override is *per job*: a friend who writes his
    own ``greet.json`` keeps the shared ``hedge.json``. That is the shape the content actually takes --
    a character diverges one phase at a time, and a friend who has to copy every file before he can
    change one would either copy them all or never start.
    """
    books: dict[str, Phrasebook] = {}
    base = Path(directory)
    shared = Path(fallback) if fallback is not None else None
    # An override only makes sense when there *is* a shared set to override.
    overriding = shared is not None and shared != base
    if overriding:
        books.update(load_shelf(shared).books)
    if not base.is_dir():
        return Shelf(books=books)
    for path in sorted(base.glob("*.json")):
        book = load(path)
        if book.job in books:
            if not overriding:
                # Two books in one directory claiming a job is a data error, not an override.
                raise PhrasebookError(f"{path}: two books claim the job {book.job!r}")
            books[book.job] = book
            continue
        books[book.job] = book
    return Shelf(books=books)
