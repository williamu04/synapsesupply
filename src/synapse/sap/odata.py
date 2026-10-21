"""Just enough OData v2 for the mock: wire-format values, $filter / $orderby / key parsing, errors.

Values follow what S/4HANA actually returns (dates as "/Date(ms)/", decimals as strings), so tool
code written against the mock also works against a real system.
"""
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

EPOCH = date(1970, 1, 1)
MS_PER_DAY = 86_400_000


class ODataError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": {"lang": "en", "value": self.message}}}


def bad_request(message: str) -> ODataError:
    return ODataError(400, "SY/530", message)


# --- values -------------------------------------------------------------------------------------

_DATE_RE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d{4})?\)/$")


def to_wire(value: Any, typ: str) -> Any:
    if value is None:
        return None
    if typ == "date":
        return f"/Date({(value - EPOCH).days * MS_PER_DAY})/"
    if typ == "decimal":
        return format(value, "f")
    return value


def from_wire(value: Any, typ: str) -> Any:
    """Accepts OData wire format and plain JSON/ISO values (seed files, hand-written requests)."""
    if value is None:
        return None
    try:
        if typ == "date":
            if isinstance(value, date):
                return value
            if m := _DATE_RE.match(value):
                return EPOCH + timedelta(days=int(m.group(1)) // MS_PER_DAY)
            return datetime.fromisoformat(value).date()
        if isinstance(value, bool) != (typ == "bool"):
            raise TypeError
        if typ == "decimal":
            return Decimal(str(value))
        if typ == "int":
            return int(value)
        if typ == "str" and not isinstance(value, str):
            raise TypeError
        return value
    except (ValueError, TypeError, InvalidOperation, AttributeError):
        raise bad_request(f"Invalid {typ} value: {value!r}") from None


# --- $filter ------------------------------------------------------------------------------------

_TOKEN = re.compile(r"""\s*(?:
    (?P<lparen>\() | (?P<rparen>\)) |
    datetime'(?P<datetime>[^']*)' |
    '(?P<string>(?:[^']|'')*)' |
    (?P<number>-?\d+(?:\.\d+)?)[mMdDlL]?(?![\w.]) |
    (?P<word>[A-Za-z_][A-Za-z0-9_]*)
)""", re.VERBOSE)

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
}
_KEYWORDS = {"and", "or", "not", "true", "false", "null", *_OPS}

Predicate = Callable[[dict], bool]


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(text):
        if text[pos:].isspace():
            break
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise bad_request(f"Invalid $filter near: {text[pos:pos + 20]!r}")
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    return tokens


class _FilterParser:
    def __init__(self, text: str, types: dict[str, str]):
        self.tokens, self.types, self.pos = _tokenize(text), types, 0

    def parse(self) -> Predicate:
        if not self.tokens:
            raise bad_request("Empty $filter")
        pred = self._or()
        if self.pos != len(self.tokens):
            raise bad_request(f"Unexpected token in $filter: {self.tokens[self.pos][1]!r}")
        return pred

    def _peek_word(self, word: str) -> bool:
        return self.pos < len(self.tokens) and self.tokens[self.pos] == ("word", word)

    def _next(self) -> tuple[str, str]:
        if self.pos >= len(self.tokens):
            raise bad_request("Unexpected end of $filter")
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _or(self) -> Predicate:
        terms = [self._and()]
        while self._peek_word("or"):
            self.pos += 1
            terms.append(self._and())
        return terms[0] if len(terms) == 1 else lambda r: any(t(r) for t in terms)

    def _and(self) -> Predicate:
        terms = [self._unary()]
        while self._peek_word("and"):
            self.pos += 1
            terms.append(self._unary())
        return terms[0] if len(terms) == 1 else lambda r: all(t(r) for t in terms)

    def _unary(self) -> Predicate:
        if self._peek_word("not"):
            self.pos += 1
            inner = self._unary()
            return lambda r: not inner(r)
        if self.pos < len(self.tokens) and self.tokens[self.pos][0] == "lparen":
            self.pos += 1
            inner = self._or()
            if self._next()[0] != "rparen":
                raise bad_request("Missing ')' in $filter")
            return inner
        return self._comparison()

    def _comparison(self) -> Predicate:
        kind, prop = self._next()
        if kind != "word" or prop in _KEYWORDS:
            raise bad_request(f"Expected a property name in $filter, got {prop!r}")
        if prop not in self.types:
            raise bad_request(f"Property '{prop}' not found")
        kind, op = self._next()
        if kind != "word" or op not in _OPS:
            raise bad_request(f"Unsupported $filter operator {op!r}")
        literal = self._literal(self.types[prop])
        cmp = _OPS[op]
        if op in ("eq", "ne"):
            return lambda r: cmp(r.get(prop), literal)
        return lambda r: r.get(prop) is not None and literal is not None and cmp(r[prop], literal)

    def _literal(self, typ: str) -> Any:
        kind, value = self._next()
        if kind == "word" and value == "null":
            return None
        expected = {"str": "string", "date": "datetime", "decimal": "number", "int": "number", "bool": "word"}[typ]
        if kind != expected or (typ == "bool" and value not in ("true", "false")):
            raise bad_request(f"Literal {value!r} does not match property type {typ}")
        if typ == "str":
            return value.replace("''", "'")
        if typ == "bool":
            return value == "true"
        return from_wire(value if typ != "int" else int(Decimal(value)), typ)


def parse_filter(text: str, types: dict[str, str]) -> Predicate:
    return _FilterParser(text, types).parse()


def parse_orderby(text: str, types: dict[str, str]) -> list[tuple[str, bool]]:
    """Returns [(property, descending)]."""
    out = []
    for part in text.split(","):
        bits = part.split()
        if not bits or len(bits) > 2 or (len(bits) == 2 and bits[1] not in ("asc", "desc")):
            raise bad_request(f"Invalid $orderby: {text!r}")
        if bits[0] not in types:
            raise bad_request(f"Property '{bits[0]}' not found")
        out.append((bits[0], len(bits) == 2 and bits[1] == "desc"))
    return out


def apply_orderby(rows: list[dict], order: list[tuple[str, bool]]) -> list[dict]:
    for prop, desc in reversed(order):  # stable sort, least significant key first
        present = [r for r in rows if r.get(prop) is not None]
        missing = [r for r in rows if r.get(prop) is None]
        rows = sorted(present, key=lambda r: r[prop], reverse=desc) + missing
    return rows


_KEY_PART = re.compile(r"\s*(\w+)\s*=\s*'((?:[^']|'')*)'\s*(?:,|$)")


def parse_key(text: str, keys: tuple[str, ...]) -> dict[str, str]:
    """`'4500000001'` or `PurchaseOrder='4500000001',PurchaseOrderItem='10'`."""
    text = text.strip()
    if m := re.fullmatch(r"'((?:[^']|'')*)'", text):
        if len(keys) != 1:
            raise bad_request(f"Key must name all of: {', '.join(keys)}")
        return {keys[0]: m.group(1).replace("''", "'")}
    parts, pos = {}, 0
    while pos < len(text):
        m = _KEY_PART.match(text, pos)
        if not m:
            raise bad_request(f"Invalid key predicate: ({text})")
        parts[m.group(1)] = m.group(2).replace("''", "'")
        pos = m.end()
    if set(parts) != set(keys):
        raise bad_request(f"Key must name exactly: {', '.join(keys)}")
    return parts


def format_key(row: dict, keys: tuple[str, ...]) -> str:
    esc = {k: str(row[k]).replace("'", "''") for k in keys}
    if len(keys) == 1:
        return f"'{esc[keys[0]]}'"
    return ",".join(f"{k}='{esc[k]}'" for k in keys)


def literal(value: Any) -> str:
    """Python value -> OData v2 $filter literal (client side)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return f"datetime'{value.isoformat()}T00:00:00'"
    if isinstance(value, int | float | Decimal):
        return format(Decimal(str(value)), "f")
    return "'" + str(value).replace("'", "''") + "'"


def parse_expand(text: str) -> dict:
    """`to_A/to_B,to_C` -> {"to_A": {"to_B": {}}, "to_C": {}}"""
    tree: dict = {}
    for path in filter(None, (p.strip() for p in text.split(","))):
        node = tree
        for seg in path.split("/"):
            node = node.setdefault(seg, {})
    return tree
