"""Adaptive Cards Templating, the subset our templates use (a Python port of the widget mock's engine).

Supports ``${expr}`` interpolation, ``$data`` (object scope or array repeat), ``$when``, ``$root``, ``$index``,
member/index access, string/number/boolean literals, ``== != < > <= >= && || !`` and the functions
``count()``, ``if()``, ``concat()``, ``toUpper()``. Expressions are parsed, never ``eval``-ed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Scope:
    data: Any
    root: Any
    index: int | None = None


_TOKEN = re.compile(r"\s+|(?P<num>\d+(?:\.\d+)?)|(?P<str>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")|(?P<id>[A-Za-z_$][A-Za-z0-9_$]*)|(?P<op>==|!=|<=|>=|&&|\|\||[<>!])|(?P<punc>[.\[\](),])")


def tokenize(src: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise ValueError(f"Unexpected character {src[pos]!r} in expression: {src}")
        pos = m.end()
        kind = m.lastgroup
        if not kind:
            continue
        value = m.group(kind)
        if kind == "str":
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        out.append((kind, value))
    return out


def _count(x: Any) -> int:
    return len(x) if isinstance(x, (list, str)) else 0


FUNCTIONS = {
    "count": _count,
    "if": lambda c, a, b: a if c else b,
    "concat": lambda *xs: "".join("" if x is None else str(x) for x in xs),
    "toUpper": lambda x: str(x or "").upper(),
}


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], scope: Scope):
        self.t = tokens
        self.pos = 0
        self.scope = scope

    def parse(self) -> Any:
        v = self.or_()
        if self.pos < len(self.t):
            raise ValueError("Unexpected trailing tokens")
        return v

    def peek(self, value: str | None = None) -> tuple[str, str] | None:
        if self.pos >= len(self.t):
            return None
        tok = self.t[self.pos]
        return tok if value is None or tok[1] == value else None

    def take(self, value: str | None = None) -> tuple[str, str]:
        tok = self.peek(value)
        if tok is None:
            raise ValueError(f"Expected {value or 'token'}")
        self.pos += 1
        return tok

    def or_(self) -> Any:
        left = self.and_()
        while self.peek("||"):
            self.take()
            right = self.and_()
            left = bool(left) or bool(right)
        return left

    def and_(self) -> Any:
        left = self.compare()
        while self.peek("&&"):
            self.take()
            right = self.compare()
            left = bool(left) and bool(right)
        return left

    def compare(self) -> Any:
        left = self.unary()
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in ("==", "!=", "<", ">", "<=", ">="):
            self.take()
            right = self.unary()
            op = tok[1]
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            try:
                return {"<": left < right, ">": left > right, "<=": left <= right, ">=": left >= right}[op]
            except TypeError:
                return False
        return left

    def unary(self) -> Any:
        if self.peek("!"):
            self.take()
            return not self.unary()
        return self.postfix()

    def postfix(self) -> Any:
        value = self.primary()
        while True:
            if self.peek("."):
                self.take()
                name = self.take()[1]
                value = value.get(name) if isinstance(value, dict) else None
            elif self.peek("["):
                self.take()
                key = self.or_()
                self.take("]")
                if isinstance(value, dict):
                    value = value.get(key)
                elif isinstance(value, list) and isinstance(key, (int, float)) and 0 <= int(key) < len(value):
                    value = value[int(key)]
                else:
                    value = None
            else:
                return value

    def primary(self) -> Any:
        kind, value = self.take()
        if kind == "num":
            return float(value) if "." in value else int(value)
        if kind == "str":
            return value
        if value == "(":
            v = self.or_()
            self.take(")")
            return v
        if kind == "id":
            if value in ("true", "false"):
                return value == "true"
            if value == "null":
                return None
            if self.peek("("):
                self.take("(")
                args = []
                while not self.peek(")"):
                    args.append(self.or_())
                    if self.peek(","):
                        self.take(",")
                self.take(")")
                fn = FUNCTIONS.get(value)
                if not fn:
                    raise ValueError(f"Unknown function {value}")
                return fn(*args)
            if value == "$root":
                return self.scope.root
            if value == "$data":
                return self.scope.data
            if value == "$index":
                return self.scope.index
            return self.scope.data.get(value) if isinstance(self.scope.data, dict) else None
        raise ValueError(f"Unexpected token {value}")


def evaluate(expression: str, scope: Scope) -> Any:
    return _Parser(tokenize(expression), scope).parse()


_WHOLE = re.compile(r"^\$\{([^{}]+)\}$")
_PART = re.compile(r"\$\{([^{}]+)\}")


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def bind_string(value: str, scope: Scope) -> Any:
    whole = _WHOLE.match(value)
    if whole:
        return evaluate(whole.group(1), scope)
    return _PART.sub(lambda m: _fmt(evaluate(m.group(1), scope)), value)


def _expand(node: Any, scope: Scope) -> list[Any]:
    if isinstance(node, list):
        return [[x for child in node for x in _expand(child, scope)]]
    if isinstance(node, str):
        return [bind_string(node, scope)]
    if not isinstance(node, dict):
        return [node]
    if "$data" in node:
        rest = {k: v for k, v in node.items() if k != "$data"}
        bound = bind_string(node["$data"], scope) if isinstance(node["$data"], str) else node["$data"]
        if isinstance(bound, list):
            return [x for i, item in enumerate(bound) for x in _expand(rest, Scope(item, scope.root, i))]
        return _expand(rest, Scope(bound, scope.root))
    if "$when" in node:
        rest = {k: v for k, v in node.items() if k != "$when"}
        ok = bind_string(node["$when"], scope) if isinstance(node["$when"], str) else node["$when"]
        return _expand(rest, scope) if ok else []
    out: dict[str, Any] = {}
    for k, v in node.items():
        expanded = _expand(v, scope)
        if expanded:  # a property whose value was dropped by $when disappears, as in the JS SDK
            out[k] = expanded[0]
    return [out]


def expand_template(template: Any, data: Any) -> Any:
    """Bind a template to data and return a plain Adaptive Card."""
    return _expand(template, Scope(data, data))[0]
