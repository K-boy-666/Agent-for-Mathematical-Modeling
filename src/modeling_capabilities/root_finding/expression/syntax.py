"""Tokenizer, Pratt parser, and immutable AST for math-expr-v1."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Literal, TypeAlias

from modeling_core.contracts.common import JsonObject

UnaryOperator: TypeAlias = Literal["positive", "negative"]
BinaryOperator: TypeAlias = Literal[
    "add", "subtract", "multiply", "divide", "power"
]
FunctionName: TypeAlias = Literal[
    "abs", "sqrt", "exp", "log", "sin", "cos", "tan"
]
ConstantName: TypeAlias = Literal["pi", "e"]


@dataclass(frozen=True, slots=True)
class NumberNode:
    value: float
    kind: ClassVar[Literal["number"]] = "number"

    def __post_init__(self) -> None:
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, float)
            or not math.isfinite(self.value)
        ):
            raise ValueError("number AST values must be finite binary64")
        if self.value == 0.0:
            object.__setattr__(self, "value", 0.0)


@dataclass(frozen=True, slots=True)
class VariableNode:
    name: Literal["x"] = "x"
    kind: ClassVar[Literal["variable"]] = "variable"

    def __post_init__(self) -> None:
        if self.name != "x":
            raise ValueError("the only variable is x")


@dataclass(frozen=True, slots=True)
class ConstantNode:
    name: ConstantName
    kind: ClassVar[Literal["constant"]] = "constant"

    def __post_init__(self) -> None:
        if self.name not in {"pi", "e"}:
            raise ValueError("unknown constant")


@dataclass(frozen=True, slots=True)
class UnaryNode:
    op: UnaryOperator
    operand: ExpressionAst
    kind: ClassVar[Literal["unary"]] = "unary"

    def __post_init__(self) -> None:
        if self.op not in {"positive", "negative"}:
            raise ValueError("unknown unary operator")


@dataclass(frozen=True, slots=True)
class BinaryNode:
    op: BinaryOperator
    left: ExpressionAst
    right: ExpressionAst
    kind: ClassVar[Literal["binary"]] = "binary"

    def __post_init__(self) -> None:
        if self.op not in {
            "add",
            "subtract",
            "multiply",
            "divide",
            "power",
        }:
            raise ValueError("unknown binary operator")


@dataclass(frozen=True, slots=True)
class CallNode:
    name: FunctionName
    argument: ExpressionAst
    kind: ClassVar[Literal["call"]] = "call"

    def __post_init__(self) -> None:
        if self.name not in {
            "abs",
            "sqrt",
            "exp",
            "log",
            "sin",
            "cos",
            "tan",
        }:
            raise ValueError("unknown function")


ExpressionAst: TypeAlias = (
    NumberNode
    | VariableNode
    | ConstantNode
    | UnaryNode
    | BinaryNode
    | CallNode
)


@dataclass(frozen=True, slots=True)
class ExpressionLimits:
    max_utf8_bytes: int = 4096
    max_numeric_literal_chars: int = 64
    max_ast_nodes: int = 256
    max_ast_depth: int = 32

    def __post_init__(self) -> None:
        fixed_caps = {
            "max_utf8_bytes": 4096,
            "max_numeric_literal_chars": 64,
            "max_ast_nodes": 256,
            "max_ast_depth": 32,
        }
        for name, fixed_cap in fixed_caps.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= fixed_cap
            ):
                raise ValueError(
                    f"{name} must be an integer from 1 through {fixed_cap}"
                )


class ExpressionSyntaxError(ValueError):
    """The source contains syntax outside math-expr-v1."""

    def __init__(self, message: str, position: int | None = None) -> None:
        self.position = position
        suffix = "" if position is None else f" at character {position}"
        super().__init__(message + suffix)


class ExpressionLimitError(ValueError):
    """The source or resulting canonical AST exceeds a fixed limit."""

    def __init__(
        self, resource: str, limit: int, observed: int | None = None
    ) -> None:
        self.resource = resource
        self.limit = limit
        self.observed = observed
        observed_text = "" if observed is None else f", observed {observed}"
        super().__init__(f"{resource} limit {limit} exceeded{observed_text}")


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    position: int


@dataclass(frozen=True, slots=True)
class _Parsed:
    node: ExpressionAst
    nodes: int
    depth: int


_ASCII_WHITESPACE = frozenset(" \t\n\r\f\v")
_FUNCTIONS = frozenset({"abs", "sqrt", "exp", "log", "sin", "cos", "tan"})
_CONSTANTS = frozenset({"pi", "e"})
_SINGLE_TOKENS = {
    "+": "PLUS",
    "-": "MINUS",
    "*": "STAR",
    "/": "SLASH",
    "(": "LPAREN",
    ")": "RPAREN",
}
_INFIX: dict[str, tuple[int, int, BinaryOperator]] = {
    "PLUS": (10, 11, "add"),
    "MINUS": (10, 11, "subtract"),
    "STAR": (20, 21, "multiply"),
    "SLASH": (20, 21, "divide"),
    "POWER": (40, 40, "power"),
}
_UNARY_BINDING_POWER = 30


def _is_ascii_letter(char: str) -> bool:
    return "a" <= char <= "z" or "A" <= char <= "Z"


def _is_ascii_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _scan_number(
    source: str,
    start: int,
    limits: ExpressionLimits,
) -> tuple[_Token, int]:
    index = start
    length = len(source)
    if source[index] == ".":
        index += 1
        while index < length and _is_ascii_digit(source[index]):
            index += 1
    else:
        while index < length and _is_ascii_digit(source[index]):
            index += 1
        if index < length and source[index] == ".":
            index += 1
            while index < length and _is_ascii_digit(source[index]):
                index += 1
    if index < length and source[index] in {"e", "E"}:
        exponent_marker = index
        index += 1
        if index < length and source[index] in {"+", "-"}:
            index += 1
        exponent_digits = index
        while index < length and _is_ascii_digit(source[index]):
            index += 1
        if exponent_digits == index:
            raise ExpressionSyntaxError(
                "numeric exponent requires digits", exponent_marker
            )
    text = source[start:index]
    literal_chars = len(text)
    if literal_chars > limits.max_numeric_literal_chars:
        raise ExpressionLimitError(
            "numeric_literal_chars",
            limits.max_numeric_literal_chars,
            literal_chars,
        )
    try:
        value = float(text)
    except ValueError as error:
        raise ExpressionSyntaxError("invalid numeric literal", start) from error
    if not math.isfinite(value):
        raise ExpressionSyntaxError("numeric literal must be finite", start)
    return _Token("NUMBER", text, start), index


def _tokenize(source: str, limits: ExpressionLimits) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char in _ASCII_WHITESPACE:
            index += 1
            continue
        if _is_ascii_digit(char) or (
            char == "."
            and index + 1 < len(source)
            and _is_ascii_digit(source[index + 1])
        ):
            token, index = _scan_number(source, index, limits)
            tokens.append(token)
            continue
        if _is_ascii_letter(char):
            end = index + 1
            while end < len(source) and (
                _is_ascii_letter(source[end])
                or _is_ascii_digit(source[end])
            ):
                end += 1
            tokens.append(_Token("NAME", source[index:end], index))
            index = end
            continue
        if source.startswith("**", index):
            tokens.append(_Token("POWER", "**", index))
            index += 2
            continue
        token_kind = _SINGLE_TOKENS.get(char)
        if token_kind is not None:
            tokens.append(_Token(token_kind, char, index))
            index += 1
            continue
        raise ExpressionSyntaxError("forbidden character", index)
    tokens.append(_Token("EOF", "", len(source)))
    return tuple(tokens)


def _collapse_redundant_parentheses(
    tokens: tuple[_Token, ...],
) -> tuple[_Token, ...]:
    stack: list[int] = []
    matching: dict[int, int] = {}
    for index, token in enumerate(tokens[:-1]):
        if token.kind == "LPAREN":
            stack.append(index)
        elif token.kind == "RPAREN":
            if not stack:
                raise ExpressionSyntaxError(
                    "unexpected closing parenthesis", token.position
                )
            opening = stack.pop()
            matching[opening] = index
    if stack:
        unclosed_token = tokens[stack[-1]]
        raise ExpressionSyntaxError(
            "missing closing parenthesis", unclosed_token.position
        )

    redundant: set[int] = set()
    for opening, closing in matching.items():
        nested_opening = opening + 1
        if (
            nested_opening < closing
            and tokens[nested_opening].kind == "LPAREN"
            and matching.get(nested_opening) == closing - 1
        ):
            redundant.update({opening, closing})
    if not redundant:
        return tokens
    return tuple(
        token for index, token in enumerate(tokens) if index not in redundant
    )


class _Parser:
    def __init__(
        self, tokens: tuple[_Token, ...], limits: ExpressionLimits
    ) -> None:
        self._tokens = tokens
        self._limits = limits
        self._index = 0

    def parse(self) -> ExpressionAst:
        if self._peek().kind == "EOF":
            raise ExpressionSyntaxError("expression must not be empty", 0)
        parsed = self._parse_bp(0)
        trailing = self._peek()
        if trailing.kind != "EOF":
            raise ExpressionSyntaxError("unexpected trailing token", trailing.position)
        return parsed.node

    def _peek(self) -> _Token:
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self._peek()
        self._index += 1
        return token

    def _checked(
        self, node: ExpressionAst, nodes: int, depth: int
    ) -> _Parsed:
        if nodes > self._limits.max_ast_nodes:
            raise ExpressionLimitError(
                "ast_nodes", self._limits.max_ast_nodes, nodes
            )
        if depth > self._limits.max_ast_depth:
            raise ExpressionLimitError(
                "ast_depth", self._limits.max_ast_depth, depth
            )
        return _Parsed(node=node, nodes=nodes, depth=depth)

    def _leaf(self, node: ExpressionAst) -> _Parsed:
        return self._checked(node, 1, 1)

    def _unary(self, op: UnaryOperator, operand: _Parsed) -> _Parsed:
        return self._checked(
            UnaryNode(op=op, operand=operand.node),
            operand.nodes + 1,
            operand.depth + 1,
        )

    def _binary(
        self, op: BinaryOperator, left: _Parsed, right: _Parsed
    ) -> _Parsed:
        return self._checked(
            BinaryNode(op=op, left=left.node, right=right.node),
            left.nodes + right.nodes + 1,
            max(left.depth, right.depth) + 1,
        )

    def _call(self, name: FunctionName, argument: _Parsed) -> _Parsed:
        return self._checked(
            CallNode(name=name, argument=argument.node),
            argument.nodes + 1,
            argument.depth + 1,
        )

    def _parse_bp(self, minimum_binding_power: int) -> _Parsed:
        left = self._parse_prefix()
        while True:
            infix = _INFIX.get(self._peek().kind)
            if infix is None:
                break
            left_binding_power, right_binding_power, operator = infix
            if left_binding_power < minimum_binding_power:
                break
            operator_token = self._advance()
            right = self._parse_bp(right_binding_power)
            if operator == "power" and (
                not isinstance(right.node, NumberNode)
                or not -1024.0 <= right.node.value <= 1024.0
            ):
                raise ExpressionSyntaxError(
                    "power exponent must be a number from -1024 through 1024",
                    operator_token.position,
                )
            left = self._binary(operator, left, right)
        return left

    def _parse_prefix(self) -> _Parsed:
        token = self._advance()
        if token.kind == "NUMBER":
            return self._leaf(NumberNode(float(token.text)))
        if token.kind in {"PLUS", "MINUS"}:
            directly_targets_number = self._peek().kind == "NUMBER"
            operand = self._parse_bp(_UNARY_BINDING_POWER)
            operator: UnaryOperator = (
                "positive" if token.kind == "PLUS" else "negative"
            )
            if directly_targets_number and isinstance(
                operand.node, NumberNode
            ):
                sign = 1.0 if operator == "positive" else -1.0
                return self._leaf(NumberNode(sign * operand.node.value))
            return self._unary(operator, operand)
        if token.kind == "LPAREN":
            value = self._parse_bp(0)
            closing = self._peek()
            if closing.kind != "RPAREN":
                raise ExpressionSyntaxError(
                    "missing closing parenthesis", closing.position
                )
            self._advance()
            return value
        if token.kind == "NAME":
            if token.text == "x":
                return self._leaf(VariableNode())
            if token.text in _CONSTANTS:
                constant: ConstantName = (
                    "pi" if token.text == "pi" else "e"
                )
                return self._leaf(ConstantNode(name=constant))
            if token.text in _FUNCTIONS:
                opening = self._peek()
                if opening.kind != "LPAREN":
                    raise ExpressionSyntaxError(
                        "function call requires parentheses", opening.position
                    )
                self._advance()
                if self._peek().kind == "RPAREN":
                    raise ExpressionSyntaxError(
                        "function requires one argument", self._peek().position
                    )
                argument = self._parse_bp(0)
                closing = self._peek()
                if closing.kind != "RPAREN":
                    raise ExpressionSyntaxError(
                        "function requires one argument", closing.position
                    )
                self._advance()
                function: FunctionName
                if token.text == "abs":
                    function = "abs"
                elif token.text == "sqrt":
                    function = "sqrt"
                elif token.text == "exp":
                    function = "exp"
                elif token.text == "log":
                    function = "log"
                elif token.text == "sin":
                    function = "sin"
                elif token.text == "cos":
                    function = "cos"
                else:
                    function = "tan"
                return self._call(function, argument)
            raise ExpressionSyntaxError("unknown name", token.position)
        raise ExpressionSyntaxError("expected expression", token.position)


def parse_expression(
    source: str, limits: ExpressionLimits
) -> ExpressionAst:
    """Parse untrusted math-expr-v1 source without Python execution."""

    if not isinstance(source, str):
        raise TypeError("expression source must be a string")
    try:
        encoded = source.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ExpressionSyntaxError(
            "expression must be valid Unicode"
        ) from error
    byte_count = len(encoded)
    if byte_count > limits.max_utf8_bytes:
        raise ExpressionLimitError(
            "expression_bytes", limits.max_utf8_bytes, byte_count
        )
    try:
        tokens = _collapse_redundant_parentheses(
            _tokenize(source, limits)
        )
        return _Parser(tokens, limits).parse()
    except RecursionError as error:
        raise ExpressionLimitError(
            "ast_depth", limits.max_ast_depth
        ) from error


def ast_to_canonical_json(ast: ExpressionAst) -> JsonObject:
    """Project an immutable AST to its only allowed JSON representation."""

    if isinstance(ast, NumberNode):
        return {"kind": "number", "value": ast.value}
    if isinstance(ast, VariableNode):
        return {"kind": "variable", "name": ast.name}
    if isinstance(ast, ConstantNode):
        return {"kind": "constant", "name": ast.name}
    if isinstance(ast, UnaryNode):
        return {
            "kind": "unary",
            "op": ast.op,
            "operand": ast_to_canonical_json(ast.operand),
        }
    if isinstance(ast, BinaryNode):
        return {
            "kind": "binary",
            "op": ast.op,
            "left": ast_to_canonical_json(ast.left),
            "right": ast_to_canonical_json(ast.right),
        }
    if isinstance(ast, CallNode):
        return {
            "kind": "call",
            "name": ast.name,
            "argument": ast_to_canonical_json(ast.argument),
        }
    raise TypeError("unknown expression AST node")


__all__ = [
    "BinaryNode",
    "CallNode",
    "ConstantNode",
    "ExpressionAst",
    "ExpressionLimitError",
    "ExpressionLimits",
    "ExpressionSyntaxError",
    "NumberNode",
    "UnaryNode",
    "VariableNode",
    "ast_to_canonical_json",
    "parse_expression",
]
