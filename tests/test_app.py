import datetime as dt
import json
import struct

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FIELDS = [("NOM", "C", 20, 0), ("AGE", "N", 3, 0), ("SOLDE", "N", 10, 2),
          ("NAISS", "D", 8, 0), ("ACTIF", "L", 1, 0), ("NOTE", "M", 10, 0)]

ROWS = [
    ("Élodie", 34, 1250.5, dt.date(1991, 3, 14), True, "Première note"),
    ("Jean", 51, -20, dt.date(1974, 11, 2), False, None),
    ("Supprimé", 1, 0, None, None, None),  # flagged deleted
]


def build_dbf(with_memo: bool = True) -> tuple[bytes, bytes]:
    fields = FIELDS if with_memo else FIELDS[:-1]
    record_len = 1 + sum(f[2] for f in fields)
    header_len = 32 + 32 * len(fields) + 1
    version = 0x83 if with_memo else 0x03
    header = struct.pack("<BBBBIHH20x", version, 124, 10, 7, len(ROWS), header_len, record_len)
    header = header[:29] + b"\x03" + header[30:]  # language driver: cp1252
    for name, typ, length, dec in fields:
        header += struct.pack("<11sc4xBB14x", name.encode(), typ.encode(), length, dec)
    header += b"\r"

    memo_blocks = [b""]  # block 0 = header
    body = b""
    for i, row in enumerate(ROWS):
        rec = b"*" if i == 2 else b" "
        for (name, typ, length, dec), value in zip(fields, row):
            if typ == "C":
                raw = value.encode("cp1252").ljust(length)
            elif typ == "N":
                raw = f"{value:.{dec}f}".rjust(length).encode()
            elif typ == "D":
                raw = value.strftime("%Y%m%d").encode() if value else b" " * 8
            elif typ == "L":
                raw = b"?" if value is None else (b"T" if value else b"F")
            else:  # memo
                if value is None:
                    raw = b" " * length
                else:
                    raw = str(len(memo_blocks)).rjust(length).encode()
                    memo_blocks.append(value.encode("cp1252") + b"\x1a\x1a")
            rec += raw
        body += rec
    dbf = header + body + b"\x1a"

    memo = b""
    if with_memo:
        memo = struct.pack("<I", len(memo_blocks)).ljust(512, b"\0")
        for block in memo_blocks[1:]:
            memo += block.ljust(512, b"\0")
    return dbf, memo


def post(path, with_memo=True, **data):
    dbf, memo = build_dbf(with_memo)
    files = {"dbf": ("clients.dbf", dbf, "application/octet-stream")}
    if with_memo:
        files["memo"] = ("clients.dbt", memo, "application/octet-stream")
    return client.post(path, files=files, data=data)


def test_inspect_reads_schema_and_preview():
    res = post("/api/inspect")
    assert res.status_code == 200, res.text
    info = res.json()
    assert info["record_count"] == 2
    assert info["encoding"] == "cp1252"
    assert info["version_code"] == "0x83"
    assert [f["name"] for f in info["fields"]] == [f[0] for f in FIELDS]
    first = info["preview"][0]
    assert first == {"NOM": "Élodie", "AGE": 34, "SOLDE": 1250.5, "NAISS": "1991-03-14",
                     "ACTIF": True, "NOTE": "Première note"}


def test_convert_streams_valid_json_with_schema():
    res = post("/api/convert")
    assert res.status_code == 200
    assert 'filename="clients.json"' in res.headers["content-disposition"]
    doc = json.loads(res.content)
    assert doc["record_count"] == 2
    assert len(doc["records"]) == 2
    assert doc["records"][1]["SOLDE"] == -20
    assert doc["records"][1]["NOTE"] is None


@pytest.mark.parametrize("pretty", ["true", "false"])
def test_convert_records_only_and_options(pretty):
    res = post("/api/convert", include_schema="false", pretty=pretty,
               lowercase="true", include_deleted="true")
    assert res.status_code == 200
    rows = json.loads(res.content)
    assert isinstance(rows, list) and len(rows) == 3
    assert "nom" in rows[0]
    assert rows[2]["_deleted"] is True and rows[2]["nom"] == "Supprimé"


def test_missing_memo_file_still_converts():
    dbf, _ = build_dbf(True)
    res = client.post("/api/convert", files={"dbf": ("t.dbf", dbf)})
    assert res.status_code == 200
    assert json.loads(res.content)["records"][0]["NOTE"] is None


def test_without_memo_table():
    res = post("/api/convert", with_memo=False)
    assert res.status_code == 200
    assert len(json.loads(res.content)["records"]) == 2


def test_rejects_non_dbf_and_garbage():
    assert client.post("/api/convert", files={"dbf": ("x.txt", b"hi")}).status_code == 400
    assert client.post("/api/convert", files={"dbf": ("x.dbf", b"garbage")}).status_code == 422
    assert post("/api/convert", encoding="nope").status_code == 400


def test_index_served():
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
