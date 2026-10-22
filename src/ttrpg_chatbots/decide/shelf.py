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


def load_shelf(directory: Path | str) -> Shelf:
    """Read every ``*.json`` in a phrasebook directory.

    A missing directory is an empty shelf, not an error: a friend with no phrasebooks simply has
    nothing to say, which is a valid state for a half-written character.
    """
    base = Path(directory)
    books: dict[str, Phrasebook] = {}
    if not base.is_dir():
        return Shelf(books={})
    for path in sorted(base.glob("*.json")):
        book = load(path)
        if book.job in books:
            raise PhrasebookError(f"{path}: two books claim the job {book.job!r}")
        books[book.job] = book
    return Shelf(books=books)
