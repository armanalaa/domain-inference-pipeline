#!/usr/bin/env python3
"""
extract_erd.py — Generate an ERD (Mermaid + Graphviz) from a DomainMiner-style schema JSON.

Input is a single JSON file: either a full schema (schema.json) or one subdomain file.
Both share the shape:

    {"_meta": {...},
     "tables": {"<table>": {"columns": [
         {"name": "...", "sql_type": "INT", "key": "PK|FK|", "description": "..."}, ...]}}}

FK columns carry no explicit target; the referenced table is inferred from the column name
against the other tables' names — exact match first, then role/suffix by dropping leading
tokens (original_language_id -> language, manager_staff_id -> staff), with light
singular/plural normalization. A composite-PK column that names another table is treated as a
junction (identifying) FK. An FK whose target table is absent is rendered as a dangling stub.

Usage:
    python extract_erd.py <file.json> [--out DIR] [--no-render]

Writes <stem>.mmd and <stem>.dot into <file's dir>/erd/ (override with --out) and — when the
Graphviz `dot` binary is on PATH — also <stem>.svg and <stem>.png (disable with --no-render).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Column:
    name: str
    sql_type: str
    key: str  # "PK" | "FK" | ""
    description: str = ""

    @property
    def is_pk(self) -> bool:
        return self.key == "PK"

    @property
    def is_fk(self) -> bool:
        return self.key == "FK"


@dataclass
class Table:
    name: str
    description: str
    columns: list[Column]

    @property
    def pk_columns(self) -> list[Column]:
        return [c for c in self.columns if c.is_pk]


@dataclass
class Relationship:
    src_table: str          # table holding the FK (the "many" side)
    src_column: str
    dst_table: str          # referenced table (the "one" side); may be external
    dangling: bool = False  # target table not present in the schema
    via_pk: bool = False    # inferred from a composite-PK junction column (identifying)


@dataclass
class Schema:
    database: str
    tables: dict[str, Table]
    relationships: list[Relationship] = field(default_factory=list)
    dangling: list[Relationship] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing + FK resolution
# --------------------------------------------------------------------------- #
def load_schema(path: Path) -> Schema:
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.get("_meta", {})
    db = meta.get("database") or meta.get("domain_name") or path.stem

    tables: dict[str, Table] = {}
    for tname, tdef in raw["tables"].items():
        cols = [
            Column(
                name=c["name"],
                sql_type=c.get("sql_type", ""),
                key=c.get("key", "") or "",
                description=c.get("description", "") or "",
            )
            for c in tdef.get("columns", [])
        ]
        tables[tname] = Table(tname, tdef.get("_description", "") or "", cols)

    schema = Schema(database=db, tables=tables)
    _resolve_relationships(schema)
    return schema


def _strip_id(name: str) -> str:
    return re.sub(r"_?id$", "", name, flags=re.IGNORECASE)


def _match_table(candidate: str, tables: dict[str, Table]) -> Optional[str]:
    """Resolve a candidate entity name to a real table name.

    Tries the full candidate, then progressively drops leading underscore-tokens
    (manager_staff -> staff, original_language -> language), each with light
    singular/plural normalization. Returns the matched table name or None.
    """
    if not candidate:
        return None
    lower = {t.lower(): t for t in tables}
    parts = candidate.split("_")
    for i in range(len(parts)):
        sub = "_".join(parts[i:]).lower()
        variants = {sub, sub.rstrip("s"), sub + "s"}
        if sub.endswith("ies"):
            variants.add(sub[:-3] + "y")
        for v in variants:
            if v in lower:
                return lower[v]
    return None


def _resolve_relationships(schema: Schema) -> None:
    tables = schema.tables
    seen: set[tuple[str, str, str]] = set()

    for t in tables.values():
        for c in t.columns:
            if c.is_fk:
                via_pk = False
            elif c.is_pk:
                via_pk = True  # candidate junction column (confirmed below)
            else:
                continue

            dst = _match_table(_strip_id(c.name), tables)

            # A plain PK (unresolved, or naming its own table) is not a relationship;
            # only a composite-PK column pointing at ANOTHER table is a junction FK.
            if via_pk and (dst is None or dst == t.name):
                continue

            if dst is None:  # unresolved FK -> dangling external stub
                rel = Relationship(t.name, c.name, _strip_id(c.name) or c.name,
                                   dangling=True)
                schema.dangling.append(rel)
                schema.relationships.append(rel)
                continue

            sig = (t.name, c.name, dst)
            if sig in seen:
                continue
            seen.add(sig)
            schema.relationships.append(Relationship(t.name, c.name, dst, via_pk=via_pk))


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #
_SAFE = re.compile(r"[^0-9A-Za-z_]")

_HDR_BG = "#2d3142"
_PK_BG = "#eef2ff"
_FK_BG = "#fff7ed"
_EXT_BG = "#f3f4f6"
_TYPE_COLOR = "#9096a2"
_PK_COLOR = "#3b5bdb"
_FK_COLOR = "#c2410c"

# edge palette: identifying/junction, plain FK, dangling
_C_IDENT = "#1f2937"
_C_FK = "#6b7280"
_C_DANGLING = "#9ca3af"


def _safe_type(sql_type: str) -> str:
    """Mermaid attribute types must be a single token: VARCHAR(50) -> VARCHAR_50."""
    t = sql_type.strip().replace("(", "_").replace(")", "").replace(",", "_").replace(" ", "_")
    return _SAFE.sub("", t) or "UNKNOWN"


def _slug(name: str) -> str:
    return _SAFE.sub("_", name).strip("_")


def _html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
# Mermaid emitter
# --------------------------------------------------------------------------- #
def to_mermaid(schema: Schema, title: str = "") -> str:
    lines: list[str] = []
    if title:
        lines.append(f"---\ntitle: {title}\n---")
    lines.append("erDiagram")

    for tname, t in schema.tables.items():
        lines.append(f"    {_slug(tname).upper()} {{")
        for c in t.columns:
            marker = "PK" if c.is_pk else ("FK" if c.is_fk else "")
            attr = f"        {_safe_type(c.sql_type)} {_slug(c.name)}"
            lines.append(attr + (f" {marker}" if marker else ""))
        lines.append("    }")

    for name in sorted({r.dst_table for r in schema.dangling}):
        lines.append(f"    {_slug(name).upper()} {{")
        lines.append(f"        UNKNOWN {_slug(name)}_id PK")
        lines.append("    }")

    for r in schema.relationships:
        # identifying (junction/PK) -> solid "--"; non-identifying (FK) -> dashed ".."
        conn = "||--o{" if r.via_pk else "||..o{"
        label = r.src_column + (" (ext)" if r.dangling else "")
        lines.append(f'    {_slug(r.dst_table).upper()} {conn} '
                     f'{_slug(r.src_table).upper()} : "{label}"')

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Graphviz emitter
# --------------------------------------------------------------------------- #
def _node(name: str) -> str:
    return "n_" + _slug(name)


def _port(col_name: str) -> str:
    return "c_" + _slug(col_name)


def to_dot(schema: Schema, title: str = "") -> str:
    tables = schema.tables
    lines = [
        "digraph ERD {",
        '    graph [rankdir=LR, splines=true, nodesep=0.6, ranksep=1.4, '
        'bgcolor="white", pad=0.3, fontname="Helvetica"];',
        '    node [shape=plaintext fontname="Helvetica" fontsize=10];',
        '    edge [fontname="Helvetica" fontsize=8];',
    ]
    if title:
        lines.append(f'    labelloc=t; fontsize=16; label="{_html(title)}";')

    def entity(t: Table) -> str:
        rows = [f'<TR><TD PORT="__hdr" BGCOLOR="{_HDR_BG}" ALIGN="CENTER">'
                f'<FONT COLOR="white"><B>  {_html(t.name)}  </B></FONT></TD></TR>']
        for c in t.columns:
            if c.is_pk:
                bg, name = _PK_BG, f"<B>{_html(c.name)}</B>"
                badge = f' <FONT COLOR="{_PK_COLOR}"><B>PK</B></FONT>'
            elif c.is_fk:
                bg, name = _FK_BG, _html(c.name)
                badge = f' <FONT COLOR="{_FK_COLOR}"><B>FK</B></FONT>'
            else:
                bg, name, badge = "white", _html(c.name), ""
            rows.append(
                f'<TR><TD PORT="{_port(c.name)}" BGCOLOR="{bg}" ALIGN="LEFT">'
                f'{name}  <FONT COLOR="{_TYPE_COLOR}" POINT-SIZE="9">'
                f'{_html(c.sql_type)}</FONT>{badge}</TD></TR>'
            )
        return (f'    {_node(t.name)} [label=<<TABLE BORDER="0" CELLBORDER="1" '
                f'CELLSPACING="0" CELLPADDING="4">{"".join(rows)}</TABLE>>];')

    def ext_node(name: str) -> str:
        return (f'    {_node(name)} [label=<<TABLE BORDER="0" CELLBORDER="1" '
                f'CELLSPACING="0" CELLPADDING="4">'
                f'<TR><TD BGCOLOR="{_EXT_BG}"><B>{_html(name)}</B> '
                f'<FONT COLOR="{_TYPE_COLOR}" POINT-SIZE="9">(external)</FONT></TD></TR>'
                f'<TR><TD PORT="__pk" BGCOLOR="{_EXT_BG}" ALIGN="LEFT">'
                f'<I>{_html(name)}_id</I> <FONT COLOR="{_PK_COLOR}"><B>PK</B></FONT>'
                f'</TD></TR></TABLE>>];')

    for t in tables.values():
        lines.append(entity(t))
    for name in sorted({r.dst_table for r in schema.dangling}):
        lines.append(ext_node(name))

    def dst_port(dst: str) -> str:
        t = tables.get(dst)
        pks = t.pk_columns if t else []
        return _port(pks[0].name) if pks else "__hdr"

    for r in schema.relationships:
        if r.dangling:
            style, dport = f'style=dashed color="{_C_DANGLING}" penwidth=1.0', "__pk"
        elif r.via_pk:
            style, dport = f'color="{_C_IDENT}" penwidth=1.7', dst_port(r.dst_table)
        else:
            style, dport = f'color="{_C_FK}" penwidth=1.0', dst_port(r.dst_table)
        # crow's foot (zero-or-many) at the FK/tail side; tee (one) at the referenced/head side
        lines.append(
            f'    {_node(r.src_table)}:{_port(r.src_column)}:e -> '
            f'{_node(r.dst_table)}:{dport}:w '
            f'[label="{_html(r.src_column)}" {style} dir=both arrowtail=ocrow arrowhead=tee];'
        )

    lines.append('    subgraph cluster_legend {')
    lines.append('        label="Legend"; fontsize=10; fontname="Helvetica"; '
                 'color="#d1d5db"; style="rounded"; margin=8;')
    lines.append(
        f'        __legend [label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="3">'
        f'<TR><TD ALIGN="LEFT"><FONT COLOR="{_C_IDENT}"><B>identifying / junction (PK)</B>'
        f'</FONT></TD></TR>'
        f'<TR><TD ALIGN="LEFT"><FONT COLOR="{_C_FK}">foreign key</FONT></TD></TR>'
        f'<TR><TD ALIGN="LEFT"><FONT COLOR="{_C_DANGLING}">dangling (external)</FONT></TD></TR>'
        f'</TABLE>>];'
    )
    lines.append('    }')

    lines.append("}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path}")


def _render(dot_path: Path) -> None:
    dot_bin = shutil.which("dot")
    if not dot_bin:
        print("  [render] Graphviz `dot` not on PATH -> skipping PNG/SVG "
              "(install Graphviz, or pass --no-render to silence).", file=sys.stderr)
        return
    for fmt in ("svg", "png"):
        out = dot_path.with_suffix(f".{fmt}")
        try:
            subprocess.run([dot_bin, f"-T{fmt}", str(dot_path), "-o", str(out)],
                           check=True, capture_output=True)
            print(f"  rendered {out}")
        except subprocess.CalledProcessError as e:
            print(f"  [render] {fmt} failed: {e.stderr.decode()[:200]}", file=sys.stderr)


def generate(input_path: Path, out_dir: Path, render: bool) -> None:
    schema = load_schema(input_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    title = f"{schema.database} — ERD"

    print(f"Schema '{schema.database}': {len(schema.tables)} tables, "
          f"{len(schema.relationships)} relationships ({len(schema.dangling)} dangling).")
    for r in schema.dangling:
        print(f"  dangling FK: {r.src_table}.{r.src_column} -> {r.dst_table} (external)",
              file=sys.stderr)

    _write(out_dir / f"{stem}.mmd", to_mermaid(schema, title))
    dot_path = out_dir / f"{stem}.dot"
    _write(dot_path, to_dot(schema, title))
    if render:
        _render(dot_path)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate an ERD (Mermaid + Graphviz) from a schema or subdomain JSON file.")
    p.add_argument("input", type=Path, help="Path to the schema/subdomain JSON file")
    p.add_argument("--out", type=Path, default=None,
                   help="Output directory (default: <input's dir>/erd)")
    p.add_argument("--no-render", action="store_true",
                   help="Do not render PNG/SVG even if Graphviz `dot` is available")
    args = p.parse_args(argv)

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2
    out_dir = args.out or (args.input.parent / "erd")
    generate(args.input, out_dir, render=not args.no_render)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
