"""DBF -> JSON conversion logic (dBase III/IV, FoxPro, Visual FoxPro)."""

from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from dbfread import DBF

# DBF field type codes -> human readable names
FIELD_TYPES = {
    "C": "Character",
    "N": "Numeric",
    "F": "Float",
    "L": "Logical",
    "D": "Date",
    "T": "DateTime",
    "@": "Timestamp",
    "M": "Memo",
    "G": "General",
    "P": "Picture",
    "B": "Double/Binary",
    "I": "Integer",
    "Y": "Currency",
    "+": "Autoincrement",
    "O": "Double",
    "V": "Varchar",
    "Q": "Varbinary",
    "0": "Flags",
}

# Language driver byte -> codepage name not covered well by dbfread defaults
FALLBACK_ENCODING = "cp1252"


@dataclass
class ConvertOptions:
    encoding: str | None = None  # None = auto-detect from header
    include_deleted: bool = False
    lowercase_names: bool = False
    include_schema: bool = True
    indent: int | None = 2


def to_jsonable(value: Any) -> Any:
    """Convert values returned by dbfread to JSON-serializable types."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        # NaN/Infinity are not valid JSON
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"$binary": base64.b64encode(raw).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return str(value)


def open_dbf(path: Path, options: ConvertOptions) -> DBF:
    kwargs = dict(
        load=False,
        ignore_missing_memofile=True,
        char_decode_errors="replace",
        lowernames=options.lowercase_names,
    )
    if options.encoding:
        kwargs["encoding"] = options.encoding
    try:
        table = DBF(str(path), **kwargs)
    except LookupError:
        # Unknown codepage in header -> fall back to a sane default
        kwargs["encoding"] = FALLBACK_ENCODING
        table = DBF(str(path), **kwargs)
    return table


def describe(table: DBF) -> dict[str, Any]:
    last_update = None
    try:
        last_update = table.date.isoformat() if table.date else None
    except Exception:
        pass
    return {
        "table": table.name,
        "encoding": table.encoding,
        "dbversion": table.dbversion,
        "version_code": f"0x{table.header.dbversion:02x}",
        "last_update": last_update,
        "record_count": len(table),
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "type_name": FIELD_TYPES.get(f.type, "Unknown"),
                "length": f.length,
                "decimals": f.decimal_count,
            }
            for f in table.fields
        ],
    }


def iter_records(table: DBF, options: ConvertOptions) -> Iterator[dict[str, Any]]:
    sources = [iter(table)]
    if options.include_deleted:
        sources.append(iter(table.deleted))
    for i, src in enumerate(sources):
        for record in src:
            row = {k: to_jsonable(v) for k, v in record.items()}
            if options.include_deleted:
                row["_deleted"] = i == 1
            yield row


def stream_json(path: Path, options: ConvertOptions) -> Iterator[str]:
    """Yield the JSON document in chunks so large files never sit fully in memory."""
    table = open_dbf(path, options)
    indent = options.indent
    nl = "\n" if indent else ""
    pad = " " * indent if indent else ""
    sep = "," + nl

    def dump(obj: Any, level: int) -> str:
        text = json.dumps(obj, ensure_ascii=False, indent=indent)
        if indent and level:
            text = text.replace("\n", "\n" + pad * level)
        return text

    if options.include_schema:
        meta = describe(table)
        yield "{" + nl
        for key, value in meta.items():
            yield f'{pad}"{key}": {dump(value, 1)},{nl}'
        yield f'{pad}"records": [{nl}'
        level = 2
    else:
        yield "[" + nl
        level = 1

    first = True
    buffer: list[str] = []
    for row in iter_records(table, options):
        piece = ("" if first else sep) + pad * level + dump(row, level)
        first = False
        buffer.append(piece)
        if len(buffer) >= 500:
            yield "".join(buffer)
            buffer.clear()
    if buffer:
        yield "".join(buffer)

    if options.include_schema:
        yield f"{nl}{pad}]{nl}}}{nl}"
    else:
        yield f"{nl}]{nl}"
