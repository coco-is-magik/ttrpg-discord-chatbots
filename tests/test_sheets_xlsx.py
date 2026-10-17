"""The workbook reader: references, merges, and the ways a file can be wrong."""

from __future__ import annotations

import zipfile

import pytest

from sheets_support import house_workbook, write_workbook
from ttrpg_chatbots.sheets.xlsx import (
    Grid,
    WorkbookError,
    column_index,
    column_letters,
    join_ref,
    read_grid,
    sheet_names,
    split_ref,
)


def test_columns_round_trip() -> None:
    for index in (1, 2, 26, 27, 52, 703):
        assert column_index(column_letters(index)) == index
    assert column_letters(1) == "A"
    assert column_letters(27) == "AA"
    with pytest.raises(ValueError):
        column_letters(0)


def test_references_parse_both_ways() -> None:
    assert split_ref("B7") == (7, 2)
    assert split_ref("aa12") == (12, 27)
    assert join_ref(7, 2) == "B7"
    with pytest.raises(WorkbookError, match="not a cell reference"):
        split_ref("seven")


def test_values_come_out_of_shared_strings_and_numbers(tmp_path) -> None:
    path = write_workbook(
        tmp_path / "book.xlsx",
        {"First": {"A1": "Name", "B1": "Brannoc", "C1": 4, "D1": 1.5}},
    )
    grid = read_grid(path)
    assert grid.name == "First"
    assert grid.text("A1") == "Name"
    assert grid.text("B1") == "Brannoc"
    assert grid.number("C1") == 4.0
    assert grid.integer("C1") == 4
    assert grid.number("D1") == 1.5


def test_a_merged_range_reads_from_its_top_left(tmp_path) -> None:
    path = house_workbook(tmp_path / "house.xlsx", attributes={"Dexterity": 4})
    grid = read_grid(path, "House Games")
    # B8 holds 4 and is merged across B8:C8, as in the real workbook.
    assert grid.integer("B8") == 4
    assert grid.integer("C8") == 4
    assert grid.integer("B7") == 0


def test_sheets_can_be_chosen_by_name_or_position(tmp_path) -> None:
    path = write_workbook(
        tmp_path / "book.xlsx",
        {"First": {"A1": "one"}, "House Games": {"A1": "two"}},
    )
    assert sheet_names(path) == ("First", "House Games")
    assert read_grid(path).name == "First"
    assert read_grid(path, 1).name == "House Games"
    assert read_grid(path, "house games").name == "House Games"


def test_an_unknown_sheet_name_lists_the_real_ones(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"First": {"A1": "one"}})
    with pytest.raises(WorkbookError) as caught:
        read_grid(path, "Nowhere")
    assert "Nowhere" in str(caught.value)
    assert "First" in str(caught.value)


def test_an_out_of_range_index_lists_the_real_ones(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"First": {"A1": "one"}})
    with pytest.raises(WorkbookError, match="out of range"):
        read_grid(path, 9)


def test_a_file_that_is_not_a_workbook_is_refused(tmp_path) -> None:
    path = tmp_path / "notes.xlsx"
    path.write_text("this is not a spreadsheet", encoding="utf-8")
    with pytest.raises(WorkbookError, match="cannot open workbook"):
        read_grid(path)


def test_a_zip_without_a_workbook_part_is_refused(tmp_path) -> None:
    path = tmp_path / "archive.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "nothing to see")
    with pytest.raises(WorkbookError, match="not an .xlsx workbook"):
        read_grid(path)


def test_a_non_numeric_cell_names_the_cell(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"First": {"A1": "many"}})
    grid = read_grid(path)
    with pytest.raises(WorkbookError, match="First!A1 is not a number"):
        grid.number("A1", strict=True)


def test_a_non_numeric_cell_is_recorded_when_not_strict(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"First": {"A1": "many"}})
    grid = read_grid(path)
    assert grid.number("A1", default=2.0) == 2.0
    assert grid.notes == ["A1: expected a number, found 'many'; using 2.0"]
    # Asking twice does not duplicate the complaint.
    grid.number("A1", default=2.0)
    assert len(grid.notes) == 1


def test_empty_cells_have_defaults(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"First": {"A1": "x"}})
    grid = read_grid(path)
    assert grid.value("Z99") == ""
    assert grid.number("Z99") == 0.0
    assert grid.number("Z99", default=-1.0) == -1.0
    assert grid.integer("Z99", default=7) == 7
    assert grid.filled("Z99") is False
    assert grid.filled("A1") is True


def test_text_collapses_whitespace(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"First": {"A1": "  Animal   Ken "}})
    assert read_grid(path).text("A1") == "Animal Ken"


def test_a_grid_can_be_built_by_hand() -> None:
    grid = Grid(name="X", cells={"B2": "value"}, merged=((2, 2, 2, 3),))
    assert grid.value("C2") == "value"
    assert grid.value("B2") == "value"


def test_a_styled_but_empty_cell_still_counts_as_a_row(tmp_path) -> None:
    """An answer someone cleared keeps its row; the sheet does not end early."""
    path = write_workbook(
        tmp_path / "book.xlsx",
        {"Q": {"A1": "question?", "A2": ""}},
        wrapped={"Q": ("A2",)},
    )
    grid = read_grid(path)
    assert grid.text("A2") == ""
    assert grid.wrapped("A2") is True
    assert grid.max_row == 2
