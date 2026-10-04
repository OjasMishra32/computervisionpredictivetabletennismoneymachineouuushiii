"""Check every number printed in the paper against the file it says it comes from.

    python sponsors/snowflake/check_all.py                       # numbers file + docs/NOTE.pdf
    python sponsors/snowflake/check_all.py --pdf path/to/paper.pdf

Reads results/note_numbers.json if present, else results/paper/numbers.json: one entry per printed number, with the
printed text and a source (`file::json.path`, `file.csv[filters] expr`, `D: formula`, `a <- b`, code line, git log).
For each entry it resolves the source from the committed files (CSV sources through DuckDB), formats the value the
way the paper prints it and compares. Where row-level data exists it recomputes the number from the rows instead of
reading a stored summary (daily P&L -> Sharpe and $/day). Then it reads pages 1-5 of the PDF and lists numbers
printed there that the numbers file does not contain.

Statuses: recomputed (derived here from rows or a formula, agrees with the print), lookup (stored value read,
agrees), MISMATCH, unresolvable (source not machine-readable; listed for a human). Writes out/check_all.md and .json.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
MINUS = "−"


class Unresolvable(Exception):
    pass


# ---------------------------------------------------------------- printed text -> numbers

NUM = re.compile(r"(?<![A-Za-z_\d.])[-+]?\$?\d[\d,]*(?:\.\d+)?(?:[%kKMB×x](?![A-Za-z]))?")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], 1)}


def printed_numbers(text: str) -> list[tuple[float, float, str]]:
    """(value, rounding step, unit flag) for each number in a printed string. '$73,000' -> step 1000;
    '27%' -> unit '%'; '$2.84B' -> 2.84e9 with step 0.01e9."""
    t = text.replace(MINUS, "-").replace("–", " ").replace("—", " ")
    t = re.sub(r"(\d) (million|billion)\b", lambda m: m.group(1) + {"million": "M", "billion": "B"}[m.group(2)], t)
    out = []
    for m in NUM.finditer(t):
        tok = m.group(0)
        sign = -1.0 if tok.startswith("-") else 1.0
        body = tok.lstrip("+-").lstrip("$")
        unit = ""
        if body[-1] in "%kKMB×x":
            unit, body = body[-1], body[:-1]
        body = body.replace(",", "")
        if not body or body == ".":
            continue
        if "." in body:
            step = 10.0 ** -len(body.split(".")[1])
        else:
            z = len(body) - len(body.rstrip("0"))
            step = 10.0 ** min(z, 3) if body.strip("0") and len(body) > 3 else 1.0
        v = sign * float(body)
        scale = {"k": 1e3, "K": 1e3, "M": 1e6, "B": 1e9}.get(unit, 1.0)
        out.append((v * scale, step * scale, unit))
    return out


def flatten_values(v) -> list:
    if isinstance(v, dict):
        return [x for vv in v.values() for x in flatten_values(vv)]
    if isinstance(v, (list, tuple)):
        return [x for vv in v for x in flatten_values(vv)]
    return [v]


def as_float(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return None if (isinstance(x, float) and math.isnan(x)) else float(x)
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


SCALES = [(1.0, ""), (100.0, "x100"), (0.01, "/100"), (1000.0, "x1000"), (0.001, "/1000")]


def compare(printed: str, value) -> tuple[bool, str]:
    """Does value print as `printed`? Numbers are compared at the printed precision (half-step tolerance), in order;
    a unit scale (x100 for percent, x1000 for s->ms) is accepted and reported. Dates and words compared as text."""
    if isinstance(value, dict) and "value" in value:          # {'value': x, 'source': ..., 'formula': ...}
        value = value["value"]
    vals = [v for v in flatten_values(value)]
    p0 = printed.strip()
    if isinstance(value, bool) or (len(vals) == 1 and isinstance(vals[0], bool)):
        b = vals[0]
        return (p0.lower() in (("yes", "true") if b else ("none", "no", "false", "0"))), "bool"
    if re.match(r"\d{4}-\d{2}-\d{2}", p0):                       # timestamps: compare to the minute
        try:
            pt = pd.Timestamp(p0.replace(" UTC", ""), tz="UTC")
            def ts(v):
                t = pd.Timestamp(str(v).replace(" UTC", ""))
                return t.tz_localize("UTC") if t.tzinfo is None else t
            return any(abs((ts(v) - pt).total_seconds()) < 60
                       for v in vals if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v)), "timestamp"
        except ValueError:
            pass
    if re.fullmatch(r"[0-9a-f]{7,40}", p0) or re.fullmatch(r"\d{1,2}:\d{2}", p0):   # commit hashes, clock times
        return any(p0 in str(v) for v in vals if str(v)), "text"
    cm = re.fullmatch(r"(?:([A-Z][a-z]{2}) (\d{1,2}), )?(\d{1,2}:\d{2})(?: UTC)?", p0)          # 'Oct 3, 07:10 UTC'
    if cm and vals and isinstance(vals[0], str) and re.match(r"\d{4}-\d{2}-\d{2}", vals[0]):
        t = pd.Timestamp(vals[0])
        t = t.tz_convert("UTC") if t.tzinfo else t
        ok = t.strftime("%H:%M") == cm.group(3).zfill(5) and (cm.group(1) is None or
             (MONTHS[cm.group(1).lower()] == t.month and int(cm.group(2)) == t.day))
        return ok, "timestamp"
    if re.fullmatch(r"\d+", p0) and vals and all(isinstance(v, str) for v in vals) and len(vals) > 1:
        return int(p0) == len(vals), "count of list"
    if re.fullmatch(r"\d+", p0) and isinstance(value, (dict, list)) and len(value) > 1 and \
            any(isinstance(x, (dict, list)) for x in (value.values() if isinstance(value, dict) else value)):
        return int(p0) == len(value), "count of entries"
    ym = re.fullmatch(r"(\d{4})\u2013(\d{2})", p0)                    # '2020–26'
    if ym:
        ys = {int(x) for x in flatten_values(value) if as_float(x) is not None}
        return {int(ym.group(1)), int(ym.group(1)[:2] + ym.group(2))} == ys, "year range"
    vals = [re.sub(r"(?<=\d)_(?=\d)", "", v) if isinstance(v, str) else v for v in vals]   # 5_000 in code
    pn = printed_numbers(printed)
    nums = [f for f in (as_float(v) for v in vals) if f is not None]
    # dates: 'Feb 1', 'Oct 8, 2025', '2026-10-03 09:50 UTC'
    dm = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2})(?:, (\d{4}))?", printed.strip())
    if dm and vals and isinstance(vals[0], str):
        try:
            d = pd.Timestamp(vals[0])
            ok = MONTHS[dm.group(1).lower()] == d.month and int(dm.group(2)) == d.day and \
                (dm.group(3) is None or int(dm.group(3)) == d.year)
            return ok, "date"
        except (ValueError, KeyError):
            pass
    if not pn:
        sv = json.dumps(value, default=str).lower()
        p = p0.lower()
        if p and p in sv:
            return True, "text"
        words = re.findall(r"[a-z]{2,}", p)                              # every word of the print is in the source
        have = set(re.findall(r"[a-z]{2,}", sv))
        return bool(words) and all(w in have for w in words), "text-words"
    if not nums and all(isinstance(v, str) for v in vals):       # numbers inside a text value (code line, note)
        nums = [as_float(t.replace(",", "")) for v in vals for t in re.findall(r"-?\d[\d,]*\.?\d*", v)]
        nums = [x for x in nums if x is not None]
    if re.search(r"\d\s*[\u2013-]\s*\d", printed) and len(pn) == 2 and len(nums) >= 2:   # 'a–b' = range of a list
        nums = [min(nums), max(nums)]
    if not nums:
        sv = " ".join(str(v) for v in vals)
        return all(re.sub(r"[^\d.]", "", f"{abs(p[0]):g}") in sv.replace(",", "") for p in pn), "text-digits"
    if len(nums) < len(pn):
        return False, f"printed {len(pn)} numbers, source has {len(nums)}"
    for scale, tag in SCALES:
        ok = all(abs(n * scale - p) <= s / 2 + 1e-9 * max(1, abs(p)) or
                 (u == "%" and abs(n * scale - p) <= s / 2 + 1e-9)
                 for (p, s, u), n in zip(pn, nums[:len(pn)] if len(nums) != len(pn) else nums))
        if ok:
            return True, tag or "exact"
        if len(pn) == 2 and len(nums) == 2 and re.search(r"\d\s*[\u2013-]\s*\d", printed):
            a = sorted(abs(n * scale) for n in nums)
            if all(abs(x - p) <= s_ / 2 + 1e-9 for x, (p, s_, _) in zip(a, sorted(pn, key=lambda z: abs(z[0])))):
                return True, (tag or "exact") + ",abs-range"
        # sign-insensitive (a loss printed with its sign dropped, e.g. 'loses 1.5c')
        if all(abs(abs(n * scale) - abs(p)) <= s / 2 + 1e-9 * max(1, abs(p)) for (p, s, u), n in zip(pn, nums)):
            return True, (tag or "exact") + ",abs"
    return False, "differs"


# ---------------------------------------------------------------- source resolution

class Resolver:
    def __init__(self, root: Path, numbers: dict):
        self.root, self.numbers = root, numbers
        self.json_cache: dict[str, object] = {}
        self.db = duckdb.connect()
        self.prev_source = ""

    # --- files
    def find(self, rel: str) -> Path:
        p = self.root / rel
        if p.exists():
            return p
        if "/" not in rel:                                # bare name, e.g. 'latency_sweep.json'
            hits = [h for h in self.root.glob(f"results/**/{rel}")]
            if len(hits) == 1:
                return hits[0]
        raise Unresolvable(f"file missing: {rel}")

    def jload(self, rel: str):
        if rel not in self.json_cache:
            p = self.find(rel)
            self.json_cache[rel] = json.loads(p.read_text())
        return self.json_cache[rel]

    # --- json path with keys that may contain dots, [index]/[selector], {a,b}
    def walk(self, obj, rest: str, where: str):
        rest = rest.strip()
        if not rest:
            return obj
        if rest.startswith("."):
            return self.walk(obj, rest[1:], where)
        if rest.startswith("{"):
            j = rest.index("}")
            keys = [k.strip() for k in rest[1:j].split(",")]
            vals = [self.walk(obj, k, where) for k in keys]
            return vals if not rest[j + 1:].strip(". ") else [self.walk(v, rest[j + 1:], where) for v in vals]
        if rest.startswith("["):
            j = rest.index("]")
            sel, after = rest[1:j], rest[j + 1:]
            if sel == "*":
                return self.each(obj, after, where)
            return self.walk(self.select(obj, sel, where), after, where)
        m = re.match(r"(\w*)\*(.*)", rest)
        if m and isinstance(obj, (dict, list)):                # '*' or 'name*': every matching child
            kids = obj if isinstance(obj, list) else [v for k, v in obj.items() if str(k).startswith(m.group(1))]
            return self.each(kids, m.group(2), where)
        if isinstance(obj, dict):
            cands = [k for k in obj if rest == k or rest.startswith(k + ".") or rest.startswith(k + "[")
                     or rest.startswith(k + "{")]
            if not cands:
                raise Unresolvable(f"key not found at '{rest[:60]}' in {where}")
            k = max(cands, key=len)
            return self.walk(obj[k], rest[len(k):], where)
        if isinstance(obj, list):
            m = re.match(r"(-?\d+)(.*)", rest)
            if m:
                return self.walk(obj[int(m.group(1))], m.group(2), where)
        raise Unresolvable(f"cannot descend '{rest[:60]}' in {where}")

    def each(self, obj, rest: str, where: str) -> list:
        kids = obj if isinstance(obj, list) else list(obj.values())
        out = []
        for k in kids:
            try:
                out.append(self.walk(k, rest, where))
            except (Unresolvable, KeyError, IndexError, TypeError):
                pass
        if not out:
            raise Unresolvable(f"wildcard matched nothing at '{rest[:40]}' in {where}")
        return out

    @staticmethod
    def select(obj, sel: str, where: str):
        sel = sel.strip()
        if re.fullmatch(r"-?\d+", sel) and isinstance(obj, list):
            return obj[int(sel)]
        if sel == "*":
            return list(obj.values()) if isinstance(obj, dict) else obj
        want = [w.strip() for w in re.split(r",(?![^()]*\))", sel)]
        if isinstance(obj, dict):
            if sel in obj:
                return obj[sel]
            for k in obj:          # a dict keyed by 'a|b|c' style composite keys
                if all(w in re.split(r"[|/,]", str(k)) for w in want):
                    return obj[k]
            vals = [v for v in obj.values() if isinstance(v, dict) and all(w in map(str, v.values()) for w in want)]
            if len(vals) == 1:
                return vals[0]
        if isinstance(obj, list):
            hits = [e for e in obj if isinstance(e, dict) and all(w in map(str, e.values()) for w in want)]
            if not hits:
                pre = lambda w, v: str(v) == w or str(v).startswith(w + " ")
                hits = [e for e in obj if isinstance(e, dict) and all(any(pre(w, v) for v in e.values()) for w in want)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise Unresolvable(f"selector [{sel}] matched {len(hits)} list items in {where}")
        raise Unresolvable(f"selector [{sel}] not found in {where}")

    def json_source(self, src: str):
        f, path = src.split("::", 1)
        rx = re.search(r"\s*\(regex '(.+)'\)\s*$", path)
        if rx:
            path = path[:rx.start()]
        note = None
        mn = re.search(r"\s+\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$", path) if not rx else None
        if mn:
            note, path = mn.group(1).strip().lower(), path[:mn.start()]
        v = self.walk(self.jload(f.strip()), path.strip(), f)
        if note == "negated":
            v = -as_float(v)
        elif note and note.startswith("len"):
            v = len(v)
        elif note and note.startswith("sum"):
            v = sum(as_float(x) for x in flatten_values(v) if as_float(x) is not None)
        elif note and re.match(r"(largest|max)\b", note):
            v = max(as_float(k) for k in (v.keys() if isinstance(v, dict) else flatten_values(v)) if as_float(k) is not None)
        elif note and re.match(r"(smallest|min)\b(?!-)", note):
            v = min(as_float(k) for k in (v.keys() if isinstance(v, dict) else flatten_values(v)) if as_float(k) is not None)
        elif note == "regex" and isinstance(v, str):
            nums = re.findall(r"-?\d+\.?\d*", v)
            if not nums:
                raise Unresolvable("(regex) on a text value with no number")
            v = float(nums[0])
        if rx:
            m = re.search(rx.group(1), str(v) if not isinstance(v, (dict, list)) else json.dumps(v))
            if not m:
                raise Unresolvable(f"regex {rx.group(1)!r} found nothing")
            v = m.group(1)
        return v

    # --- CSV rows through DuckDB: file.csv[v1,v2,col=v] expr  |  .col.agg
    def csv_source(self, src: str, key: str):
        m = re.match(r"(?P<f>\S+?\.csv)\[(?P<filt>[^\]]*)\](?P<rest>.*)$", src.strip())
        if not m:
            raise Unresolvable("unparsed CSV source")
        f = m.group("f")
        p = self.root / f
        if not p.exists():
            raise Unresolvable(f"file missing: {f}")
        cols = self.db.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{p}')").fetchall()
        names = [c[0] for c in cols]
        textcols = [c[0] for c in cols if c[1] in ("VARCHAR",)]
        where = []
        for tok in [t.strip() for t in m.group("filt").split(",") if t.strip()]:
            if "=" in tok:
                c, v = [x.strip() for x in tok.split("=", 1)]
                where.append(f'"{c}" = {v}' if as_float(v) is not None else f"\"{c}\" = '{v}'")
            else:
                where.append("(" + " OR ".join(f"\"{c}\" = '{tok}'" for c in textcols) + ")")
        rest = m.group("rest").strip()
        agg = re.fullmatch(r"\.?(\w+)\.(min|max|sum|mean|median|count|first|last)", rest)
        wsql = " AND ".join(where) or "TRUE"
        if agg:
            fn = {"mean": "AVG", "first": "FIRST", "last": "LAST"}.get(agg.group(2), agg.group(2).upper())
            sql = f'SELECT {fn}("{agg.group(1)}") FROM read_csv_auto(\'{p}\') WHERE {wsql}'
            return self.db.execute(sql).fetchone()[0], True
        expr = rest.lstrip(".").split(" (")[0].strip()
        expr_sql = self.expr_sql(expr, names, key)
        rows = self.db.execute(f"SELECT {expr_sql} FROM read_csv_auto('{p}') WHERE {wsql}").fetchall()
        if len(rows) != 1:
            raise Unresolvable(f"CSV filter matched {len(rows)} rows")
        return rows[0][0], bool(re.search(r"[-+*/]", expr))

    def expr_sql(self, expr: str, cols: list[str], key: str) -> str:
        def sub(m):
            w = m.group(0)
            if w in cols:
                return f'"{w}"'
            sib = key.rsplit(".", 1)[0] + "." + w            # sibling key, e.g. 'ret' for cv.pre.is.vol
            if sib in self.numbers and as_float(self.numbers[sib].get("raw")) is not None:
                return repr(float(self.numbers[sib]["raw"]))
            raise Unresolvable(f"unknown name '{w}' in expression")
        if not re.fullmatch(r"[\w\s.+\-*/()]+", expr):
            raise Unresolvable(f"expression not arithmetic: {expr[:50]}")
        return re.sub(r"[A-Za-z_]\w*", sub, expr)

    def json_formula(self, f: str, expr: str):
        """'a.b.c - .1.IS.x', 'p.q.usd_traded / capital_usd / calendar_days x 365', '... x sqrt(365)'."""
        doc = self.jload(f)
        expr = expr.split(" (")[0].replace(" x ", " * ")
        toks = list(re.finditer(r"\.?[A-Za-z_\d][\w.|/\[\]-]*", expr))
        paths = [t.group(0) for t in toks if not re.fullmatch(r"[\d.]+", t.group(0)) and t.group(0) != "sqrt"]
        if not paths:
            raise Unresolvable("no path in formula")
        first = paths[0]
        segs = first.split(".")
        def val(tok):
            if re.fullmatch(r"[\d.]+", tok) or tok == "sqrt":
                return tok
            if tok.startswith("."):                       # relative: replace the tail of the first path
                rel = tok[1:].split(".")
                path = ".".join(segs[:len(segs) - len(rel)] + rel)
                return repr(as_float(self.walk(doc, path, f)))
            try:
                return repr(as_float(self.walk(doc, tok, f)))
            except Unresolvable:
                parent = first.rsplit(".", 1)[0]          # sibling of the first path's leaf
                return repr(as_float(self.walk(doc, parent + "." + tok, f)))
        out, pos = [], 0
        for t in toks:
            out += [expr[pos:t.start()], val(t.group(0))]
            pos = t.end()
        ex = "".join(out + [expr[pos:]])
        if "None" in ex or not re.fullmatch(r"[\d\s.+\-*/()e]+|.*sqrt.*", ex) or re.search(r"[A-Za-z_]", ex.replace("sqrt", "")):
            raise Unresolvable("formula over a JSON file not arithmetic")
        return eval(ex, {"__builtins__": {}, "sqrt": math.sqrt})

    # --- derived formulas over other keys
    def derived(self, formula: str, key: str):
        body = formula[2:].strip()
        if re.match(r"\S+\.csv\[", body):
            return self.csv_source(body, key)[0]
        m = re.match(r"(\S+\.json)::(.+)$", body)
        if m:
            try:
                return self.json_formula(m.group(1), m.group(2))
            except Unresolvable:
                pass
        m = re.match(r"(\S+\.json)::(\S+)\s+(.+)$", body)
        if m:
            base = self.walk(self.jload(m.group(1)), m.group(2), m.group(1))
            expr = m.group(3).split(" (")[0]
            def sub(t):
                v = as_float(self.walk(base, t.group(0), m.group(1)))
                if v is None:
                    raise Unresolvable(f"'{t.group(0)}' is not numeric")
                return f"({v!r})"
            ex = re.sub(r"[A-Za-z_][\w.]*", sub, expr)
            if not re.fullmatch(r"[\d\s.+\-*/()e]+", ex):
                raise Unresolvable("formula over a JSON file not arithmetic")
            return eval(ex, {"__builtins__": {}})
        if "::" in body:
            raise Unresolvable("derived formula over a JSON file (free text)")
        keys = sorted((k for k in self.numbers if k in body), key=len, reverse=True)
        if not keys:
            raise Unresolvable("free-text formula")
        expr = body.split(" (")[0]
        for k in keys:
            raw = as_float(self.numbers[k].get("raw"))
            if raw is None:
                raise Unresolvable(f"referenced key {k} is not numeric")
            expr = expr.replace(k, f"({raw!r})")
        if not re.fullmatch(r"[\d\s.+\-*/()e]+", expr):
            raise Unresolvable("formula has words left after substituting keys")
        return eval(expr, {"__builtins__": {}})     # arithmetic only, checked by the regex above

    # --- dispatch
    def resolve(self, key: str, src: str):
        """-> (value, kind) where kind is 'lookup' or 'recomputed'."""
        src = src.strip()
        if src.startswith("…"):                       # '…stream.dropped': continue the previous source
            first = src[1:].split(".")[0]
            i = self.prev_source.rfind("." + first + ".")
            if i < 0:
                raise Unresolvable("continuation without a matching previous source")
            src = self.prev_source[:i + 1] + src[1:]
        else:
            self.prev_source = src.split(" <- ")[0]
        if " ; " in src:
            parts = [x.strip() for x in src.split(" ; ")]
            agg = re.search(r"\((max|min)\b", parts[-1])
            parts[-1] = re.sub(r"\s*\((max|min)\b.*$", "", parts[-1])
            vals = []
            for part in parts:
                v, _ = self.resolve(key, part.split(" <- ")[0].strip())
                vals.append(v["value"] if isinstance(v, dict) and "value" in v else v)
            if agg:
                return (max if agg.group(1) == "max" else min)(as_float(v) for v in vals), "recomputed"
            return vals, "lookup"
        if src.startswith("D:"):
            return self.derived(src, key), "recomputed"
        if " <- " in src:
            left = src.split(" <- ")[0].strip()
            return self.resolve(key, left)
        if re.match(r"\S+\.csv\[", src):
            v, computed = self.csv_source(src, key)
            return v, "recomputed" if computed else "lookup"
        m = re.fullmatch(r"(\S+\.csv) \((\w+) == (\w+)\)", src)
        if m:
            return self.db.execute(f"SELECT COUNT(*) FROM read_csv_auto('{self.root / m.group(1)}') "
                                   f"WHERE \"{m.group(2)}\" = '{m.group(3)}'").fetchone()[0], "recomputed"
        m = re.fullmatch(r"(\S+\.csv) rows", src)
        if m:
            return self.db.execute(f"SELECT COUNT(*) FROM read_csv_auto('{self.root / m.group(1)}')").fetchone()[0], \
                "recomputed"
        if "::" in src and re.match(r"\S+\.json::", src):
            return self.json_source(src), "lookup"
        m = re.fullmatch(r"(\S+\.\w+):(\d+)", src)
        if m:
            p = self.root / m.group(1)
            if not p.exists():
                raise Unresolvable(f"file missing: {m.group(1)}")
            return p.read_text().splitlines()[int(m.group(2)) - 1], "lookup"
        m = re.fullmatch(r"git log --diff-filter=A -- (\S+)", src)
        if m:
            r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%h|%cI", "--", m.group(1)], cwd=self.root,
                               capture_output=True, text=True)
            if not r.stdout.strip():
                raise Unresolvable("git log found no commit adding the file")
            h, t = r.stdout.strip().splitlines()[-1].split("|")
            ts = pd.Timestamp(t).tz_convert("UTC")
            return ([h, ts.strftime("%Y-%m-%d %H:%M UTC")]), "lookup"
        m = re.fullmatch(r"(\S+\.md) \(line '(.+?)'\)", src)
        if m:
            p = self.root / m.group(1)
            if not p.exists():
                raise Unresolvable(f"file missing: {m.group(1)}")
            pat = re.escape(m.group(2)).replace(r"\.\.\.", ".*")
            hit = next((l for l in p.read_text().splitlines() if re.search(pat, l)), None)
            if hit is None:
                raise Unresolvable("line not found")
            return hit, "lookup"
        m = re.fullmatch(r"(\S+\.log) \(first line '(.+?)'\)", src)
        if m:
            hit = next((l for l in self.find(m.group(1)).read_text().splitlines() if m.group(2) in l), None)
            if hit is None:
                raise Unresolvable("log line not found")
            return hit, "lookup"
        m = re.fullmatch(r"(\S+\.log) \(lines.*\)", src)
        if m:
            return len(self.find(m.group(1)).read_text().splitlines()), "recomputed"
        m = re.fullmatch(r"(\S+\.py)::(\w+)\['(\w+)'\]", src)
        if m:
            t = self.find(m.group(1)).read_text()
            d = re.search(m.group(2) + r"\s*=\s*\{([^}]*)\}", t)
            v = d and re.search(r"['\"]" + m.group(3) + r"['\"]\s*:\s*([-\d.]+)", d.group(1))
            if not v:
                raise Unresolvable("constant not found")
            return float(v.group(1)), "lookup"
        m = re.fullmatch(r"(\S+\.json) \(sum of (\w+)\)", src)
        if m:
            fam = self.jload(m.group(1))[m.group(2)]
            return sum(as_float(e.get("count")) for e in fam), "recomputed"
        raise Unresolvable("source form not recognised")


# ---------------------------------------------------------------- checked by hand (source note not machine-readable)

HAND = {
    "plat.pbo": "PBO over research/rigor/out/verify.json::pbo.sharpe* block choices = 0.092-0.243 -> 9-24%",
    "ft.months.cal": "alpha.json A_source months: 9 IS + 3 OOS, all fast_net30_c > 0; Aug in both -> 11 calendar months",
    "gate.sweep": "rally_gate_eval.json emit gates 0.5/0.8/1.2 (post hoc) and 2.0 (a_priori); printed range is the "
                  "post hoc sweep: check the sentence says so",
}


# ---------------------------------------------------------------- recompute from rows

def recompute_from_rows(root: Path, db) -> dict[str, tuple[float, str]]:
    """Headline numbers re-derived from row-level files where those rows are committed. Conventions from the repo:
    Sharpe = mean / sd of calendar-daily P&L (zero-filled) x sqrt(365)."""
    out = {}
    daily = root / "results/lowloss/daily.csv"
    if daily.exists():
        for per, book in (("is", "u1_is"), ("oos", "u1_oos")):
            r = db.execute(f"""
                WITH d AS (SELECT CAST(date AS DATE) AS day, SUM(pnl_usd) AS pnl FROM read_csv_auto('{daily}')
                           WHERE run = 'a' AND book = '{book}' AND policy = 'v2' GROUP BY 1),
                     cal AS (SELECT CAST(g AS DATE) AS day FROM generate_series(
                               (SELECT MIN(day) FROM d), (SELECT MAX(day) FROM d), INTERVAL 1 DAY) t(g)),
                     z AS (SELECT cal.day, COALESCE(d.pnl, 0) AS pnl FROM cal LEFT JOIN d USING (day))
                SELECT AVG(pnl) / STDDEV_SAMP(pnl) * SQRT(365), AVG(pnl), COUNT(*) FROM z""").fetchone()
            out[f"v2.{per}.sr"] = (r[0], f"results/lowloss/daily.csv run a/{book}/v2: calendar-daily P&L, "
                                         f"{r[2]} days, mean/sd x sqrt(365)")
            out[f"v2.{per}.usd"] = (r[1], f"results/lowloss/daily.csv run a/{book}/v2: mean calendar-daily P&L")
    return out


# ---------------------------------------------------------------- PDF scan

def pdf_unlisted(pdf: Path, numbers: dict) -> list[dict]:
    """Numbers printed on pages 1-5 that no entry of the numbers file prints. Skips years, section / figure / table /
    reference numbers and page numbers; what is left is for a human to judge."""
    import pymupdf as fitz

    known = set()
    for x in numbers.values():
        for v, _, _ in printed_numbers(str(x.get("value", ""))):
            known.add(round(abs(v), 6))
    doc = fitz.open(pdf)
    hits = []
    for pno in range(min(5, len(doc))):
        text = doc[pno].get_text()
        for m in NUM.finditer(text.replace(MINUS, "-")):
            tok = m.group(0)
            pv = printed_numbers(tok)
            if not pv:
                continue
            v = abs(pv[0][0])
            ctx = text[max(0, m.start() - 45):m.end() + 35].replace("\n", " ")
            before = text[max(0, m.start() - 8):m.start()]
            if 1900 <= v <= 2030 and "." not in tok and "$" not in tok:      # years, incl. citation years
                continue
            if re.search(r"(Fig\.?|Figure|Table|§|Section|Eq\.|\[|p\.|Appendix|^)\s*$", before) and v < 40 and \
                    "." not in tok.strip("."):
                continue
            if round(v, 6) in known or round(v / 1e3, 6) in known or round(v / 1e6, 6) in known:
                continue
            if v in (0, 1) and "%" not in tok and "$" not in tok:
                continue
            hits.append({"page": pno + 1, "printed": tok, "context": " ".join(ctx.split())})
    return hits


def template_literals(tpl: Path, numbers: dict) -> list[dict]:
    """Digits typed straight into the paper template (outside << V('key') >>) whose value equals a number the paper
    prints from the numbers file: a result typed by hand goes stale when the result changes. Literals that are part
    of a neighbouring key's name (33 ms next to V('bt.call.33')) are rule labels and skipped."""
    vals = {}
    for k, x in numbers.items():
        for v, _, _ in printed_numbers(str(x.get("value", ""))):
            vals.setdefault(round(abs(v), 6), []).append(k)
    out = []
    for i, line in enumerate(tpl.read_text().splitlines(), 1):
        if line.lstrip().startswith("%") or line.lstrip().startswith("<#"):
            continue
        keys_here = " ".join(re.findall(r"V\('([^']+)'\)", line))
        t = re.sub(r"<<.*?>>", " ", line)
        t = re.sub(r"\\(cite\w*|ref|label|[cC]ref|includegraphics|fontsize|hspace|vspace|multicolumn|cmidrule)\b(\[[^\]]*\])*(\{[^{}]*\})*",
                   " ", t)
        for m in re.finditer(r"(?<![A-Za-z_\d.{])\d[\d,]*(?:\.\d+)?(?![\d}])", t):
            v = round(float(m.group(0).replace(",", "")), 6)
            if v in vals and not (1900 <= v <= 2030) and m.group(0) not in keys_here and v not in (0, 1, 2, 3):
                out.append({"line": i, "literal": m.group(0), "same_value_as": vals[v][:3],
                            "context": " ".join(t[max(0, m.start() - 50):m.end() + 40].split())})
    return out


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="repo checkout to check (default: this one)")
    ap.add_argument("--numbers", type=Path, help="numbers file (default: results/note_numbers.json, else "
                                                  "results/paper/numbers.json)")
    ap.add_argument("--pdf", type=Path, help="paper PDF (default: docs/NOTE.pdf)")
    args = ap.parse_args()
    root = args.root.resolve()
    nf = args.numbers or next((root / p for p in ("results/note_numbers.json", "results/paper/numbers.json")
                               if (root / p).exists()), None)
    if nf is None:
        raise SystemExit("no numbers file found")
    meta = json.loads(Path(nf).read_text())
    numbers = meta["numbers"] if "numbers" in meta else meta
    R = Resolver(root, numbers)
    rows_recomputed = recompute_from_rows(root, R.db)

    res = []
    for key, x in numbers.items():
        printed, src = str(x.get("value", x.get("text", ""))), str(x.get("source", ""))
        rec = {"key": key, "printed": printed, "source": src}
        try:
            v, kind = R.resolve(key, src)
            ok, how = compare(printed, v)
            if not ok and " <- " in src:                  # 'a <- b': the right side is the underlying source
                try:
                    v2, kind2 = R.resolve(key, src.split(" <- ", 1)[1])
                    ok2, how2 = compare(printed, v2)
                    if ok2:
                        v, kind, ok, how = v2, kind2, True, how2 + " (right of <-)"
                except Unresolvable:
                    pass
            rec.update(value=v if not isinstance(v, float) else round(v, 6), how=how)
            if key in rows_recomputed:
                rv, note = rows_recomputed[key]
                rok, rhow = compare(printed, rv)
                rec.update(rows_value=round(rv, 6), rows_note=note)
                ok, kind, how = (ok and rok), "recomputed", f"{how}; rows {rhow}"
            rec["status"] = kind if ok else "MISMATCH"
        except Unresolvable as e:
            rec.update(status="unresolvable", why=str(e))
        except Exception as e:                                    # a broken source is a finding, not a crash
            rec.update(status="unresolvable", why=f"{type(e).__name__}: {e}")
        if rec["status"] in ("MISMATCH", "unresolvable") and key in HAND:
            rec.update(status="lookup", how="checked by hand: " + HAND[key])
        # the numbers file's own raw value must print the same way too
        if rec["status"] != "unresolvable" and "raw" in x:
            rok, _ = compare(printed, x["raw"])
            if not rok:
                rec["raw_note"] = f"numbers file raw {x['raw']!r} does not print as {printed!r}"
        res.append(rec)

    pdf = args.pdf or root / "docs/NOTE.pdf"
    unlisted = pdf_unlisted(pdf, numbers) if pdf.exists() else None

    tpl = root / "docs/paper/note.tex.j2"
    literals = template_literals(tpl, numbers) if tpl.exists() else None

    st = pd.Series([r["status"] for r in res]).value_counts()
    n, mm, un = len(res), int(st.get("MISMATCH", 0)), int(st.get("unresolvable", 0))
    line = (f"{n} checked: {int(st.get('recomputed', 0))} match (recomputed), {int(st.get('lookup', 0))} lookup-only, "
            f"{mm} mismatched, {un} unresolvable")
    print(line)
    if unlisted is not None:
        print(f"PDF pages 1-5: {len(unlisted)} printed numbers not in the numbers file (for review)")

    L = ["# Every number in the paper, checked", "",
         f"Run {datetime.now():%Y-%m-%d %H:%M} local · numbers file `{Path(nf).relative_to(root) if Path(nf).is_relative_to(root) else nf}` "
         f"(generated {meta.get('generated_utc', '?')}) · PDF `{pdf.name if pdf.exists() else 'not found'}` · "
         "script `sponsors/snowflake/check_all.py`", "", f"**{line}**", "",
         "*recomputed* = derived here from rows or a formula (DuckDB for CSV sources) and agrees with the print; "
         "*lookup-only* = the stored value agrees with the print; a unit scale (x100 for percent, x1000 for s -> ms) "
         "and a dropped minus sign are accepted and shown in the `how` column.", ""]
    for title, sel in (("Mismatches", "MISMATCH"), ("Unresolvable sources", "unresolvable")):
        sub = [r for r in res if r["status"] == sel]
        L += [f"## {title} ({len(sub)})", ""]
        if sub:
            L += ["| key | printed | recomputed / read | source |" if sel == "MISMATCH" else
                  "| key | printed | why | source |", "|---|---|---|---|"]
            for r in sub:
                mid = (json.dumps(r.get("value"))[:60] + (f" · rows {r['rows_value']}" if "rows_value" in r else "")
                       if sel == "MISMATCH" else r.get("why", "")[:90])
                L.append(f"| `{r['key']}` | {r['printed']} | {mid} | `{r['source'][:110]}` |")
            L.append("")
    loose = [r for r in res if r["status"] in ("lookup", "recomputed") and r.get("how", "exact").split(";")[0].split(" (")[0]
             not in ("exact", "date", "timestamp", "text", "bool")]
    if loose:
        L += [f"## Matches that needed a looser rule ({len(loose)}): check these by eye", "",
              "A unit scale (x100, x1000, ...), a dropped sign, a range of a list, a count, or digits inside text.", "",
              "| key | printed | read | rule | source |", "|---|---|---|---|---|"] + \
             [f"| `{r['key']}` | {r['printed']} | {json.dumps(r.get('value'), default=str)[:50]} | {r['how']} | "
              f"`{r['source'][:90]}` |" for r in loose] + [""]
    notes = [r for r in res if r.get("raw_note")]
    if notes:
        L += [f"## Numbers-file raw values that print differently ({len(notes)})", ""] + \
             [f"- `{r['key']}`: {r['raw_note']}" for r in notes] + [""]
    if unlisted is not None:
        L += [f"## Numbers on PDF pages 1-5 that are not in the numbers file ({len(unlisted)})", "",
              "Candidates for hard-coded numbers. Years, section/figure/table/reference numbers and 0/1 are skipped; "
              "many of the rest are harmless (ranges, rule thresholds, citations) and need a human look.", "",
              "| page | printed | context |", "|---|---|---|"] + \
             [f"| {h['page']} | {h['printed']} | {h['context'].replace('|', '/')} |" for h in unlisted] + [""]
    if literals:
        L += [f"## Template digits that equal a printed result ({len(literals)})", "",
              "Typed into `docs/paper/note.tex.j2` instead of `<< V('key') >>`. Most are rule constants that happen to "
              "equal a result; any that *is* the result should use the macro so it can't go stale.", "",
              "| line | literal | same value as | context |", "|---|---|---|---|"] + \
             [f"| {h['line']} | {h['literal']} | {', '.join(h['same_value_as'])} | {h['context'].replace('|', '/')} |"
              for h in literals] + [""]
    rr = [r for r in res if "rows_value" in r]
    if rr:
        L += ["## Recomputed from row-level files", ""] + \
             [f"- `{r['key']}` printed {r['printed']}: rows give {r['rows_value']:.4g} ({r['rows_note']})" for r in rr] + [""]
    OUT.mkdir(exist_ok=True)
    (OUT / "check_all.md").write_text("\n".join(L) + "\n")
    (OUT / "check_all.json").write_text(json.dumps({"summary": line, "results": res, "pdf_unlisted": unlisted,
                                                    "template_literals": literals},
                                                   indent=1, default=str))
    print("wrote sponsors/snowflake/out/check_all.md")
    return 0 if mm == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
