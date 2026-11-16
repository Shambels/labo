"""Workbooks read with openpyxl instead of Docling (step 6): tables found per sheet, values displayed as in Excel.

What Docling loses and this keeps: the sheet name, the title and unit of each table ('Chiffre d'affaires par
région (k€)'), percentages as Excel shows them (-0,7 % rather than -0.00681316572305923), the header next to
every value, and the notes under a table.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook

SMALL_TABLE_ROWS = 30  # up to this, one sentence per row as well; above, only grouped rows and a summary


@dataclass
class Table:
    sheet: str
    title: str | None
    header: list[str]
    rows: list[list[str]]                 # displayed values, aligned with the header
    first_row: int                        # Excel row number of the first data row
    notes: list[str] = field(default_factory=list)


@dataclass
class TextBlock:
    """Lines of a sheet that belong to no table (a 'Commentaires' sheet, a note alone)."""
    sheet: str
    lines: list[str]


def display_value(cell):
    """The value of a cell as Excel shows it: percentages and dates formatted, integers without '.0'.

    Other numbers keep their plain rendering (4568, 41.5), the one the eval snippets were written from.
    """
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "%" in cell.number_format:
        decimals = len(cell.number_format.split(".")[1].rstrip("%")) if "." in cell.number_format else 0
        return f"{value * 100:.{decimals}f} %".replace(".", ",")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def sheet_blocks(ws):
    """The tables and text blocks of a sheet, in order.

    Blocks are separated by empty rows. Before a table, rows of one cell are its title (and subtitle: they are
    joined, so 'Montants en k€' stays with the table); after it, they are notes. The first row with several
    cells is the header. One-cell lines that never meet a table become a TextBlock.
    """
    blocks, pending, table = [], [], None
    for row in ws.iter_rows():
        cells = [c for c in row if c.value is not None and str(c.value).strip()]
        if not cells:                          # an empty row closes the current table
            table = None
            continue
        if len(cells) == 1:
            text = display_value(cells[0])
            if table is not None:
                table.notes.append(text)
            else:
                pending.append(text)
            continue
        if table is None:                      # a new table: this row is its header
            width = max(c.column for c in cells)
            header = [display_value(c) for c in row[:width]]
            table = Table(ws.title, " · ".join(pending) or None, header, [], row[0].row + 1)
            blocks.append(table)
            pending = []
        else:
            table.rows.append([display_value(c) for c in row[:len(table.header)]])
    if pending:
        blocks.append(TextBlock(ws.title, pending))
    return blocks


def read_workbook(path):
    """Every block of every sheet. data_only=True: the values Excel computed, not the formulas."""
    workbook = load_workbook(path, data_only=True)
    return [block for ws in workbook.worksheets for block in sheet_blocks(ws)]


def table_heading(table):
    """'onglet « Ventes par région » · Chiffre d'affaires par région (k€)'"""
    return f"onglet « {table.sheet} »" + (f" · {table.title}" if table.title else "")


def row_sentence(table, row):
    """One self-contained sentence: the table's heading, then every value preceded by its column name."""
    pairs = [f"{header} : {value}" for header, value in zip(table.header, row) if header and value]
    return f"{table_heading(table)} · " + " ; ".join(pairs)


def markdown_rows(table, rows):
    lines = ["| " + " | ".join(table.header) + " |", "|" + "---|" * len(table.header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def table_groups(table, fits):
    """The table as Markdown, cut into groups of consecutive rows that fit (fits(text) -> bool), header repeated.

    Returns [(first row index, last row index, text)]. A row too long to fit alone gets a group of its own anyway.
    """
    groups, start = [], 0
    while start < len(table.rows):
        end = start + 1
        while end < len(table.rows) and fits(group_text(table, start, end + 1)):
            end += 1
        groups.append((start, end - 1, group_text(table, start, end)))
        start = end
    return groups


def group_text(table, start, end):
    span = "" if start == 0 and end == len(table.rows) else f" · lignes {start + 1} à {end}"
    notes = "\n" + "\n".join(table.notes) if table.notes and end == len(table.rows) else ""
    return f"{table_heading(table)}{span}\n{markdown_rows(table, table.rows[start:end])}{notes}"


def summary_text(table):
    columns = ", ".join(h for h in table.header if h)
    notes = (" Notes : " + " ".join(table.notes)) if table.notes else ""
    return f"{table_heading(table)} : tableau de {len(table.rows)} lignes. Colonnes : {columns}.{notes}"


def workbook_pieces(path, fits):
    """The texts to index for a workbook, with their sheet and Excel row: [{'sheet', 'row', 'kind', 'text'}].

    kind: 'row' (one sentence per row, small tables), 'table' (rows grouped as Markdown), 'summary' (big tables),
    'text' (lines outside any table).
    """
    pieces = []
    for block in read_workbook(path):
        if isinstance(block, TextBlock):
            text = f"onglet « {block.sheet} »\n" + "\n".join(block.lines)
            pieces.append({"sheet": block.sheet, "row": None, "kind": "text", "text": text})
            continue
        if not block.rows:
            continue
        small = len(block.rows) <= SMALL_TABLE_ROWS
        if not small:
            pieces.append({"sheet": block.sheet, "row": None, "kind": "summary", "text": summary_text(block)})
        for first, _, text in table_groups(block, fits):
            pieces.append({"sheet": block.sheet, "row": block.first_row + first, "kind": "table", "text": text})
        if small:
            for i, row in enumerate(block.rows):
                if any(row):
                    pieces.append({"sheet": block.sheet, "row": block.first_row + i, "kind": "row",
                                   "text": row_sentence(block, row)})
    return pieces
