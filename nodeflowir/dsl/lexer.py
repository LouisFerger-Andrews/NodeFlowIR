"""A compact, location-aware lexer for the indentation-independent DSL."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from nodeflowir.dsl.errors import DSLParseError, SourceLocation


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    location: SourceLocation


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def tokenize(source: str) -> tuple[Token, ...]:
    """Tokenize DSL source while preserving enough context for good errors."""

    tokens: list[Token] = []
    index = 0
    line = 1
    column = 1
    source_lines = source.splitlines()

    def location() -> SourceLocation:
        source_line = source_lines[line - 1] if line <= len(source_lines) else ""
        return SourceLocation(line=line, column=column, source_line=source_line)

    def advance(text: str) -> None:
        nonlocal line, column
        newline_count = text.count("\n")
        if newline_count:
            line += newline_count
            column = len(text) - text.rfind("\n")
        else:
            column += len(text)

    while index < len(source):
        character = source[index]
        if character in " \t\r":
            advance(character)
            index += 1
            continue
        if character == "\n":
            advance(character)
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            text = source[index:end]
            advance(text)
            index = end
            continue

        token_location = location()
        if character == '"':
            end = index + 1
            escaped = False
            while end < len(source):
                current = source[end]
                if current == "\n" and not escaped:
                    raise DSLParseError("unterminated string literal", token_location)
                if current == '"' and not escaped:
                    end += 1
                    break
                escaped = current == "\\" and not escaped
                if current != "\\":
                    escaped = False
                end += 1
            else:
                raise DSLParseError("unterminated string literal", token_location)
            text = source[index:end]
            try:
                value = json.loads(text)
            except json.JSONDecodeError as error:
                raise DSLParseError("invalid JSON-style string literal", token_location) from error
            tokens.append(Token("STRING", text, value, token_location))
            advance(text)
            index = end
            continue

        if character.isdigit():
            match = _NUMBER.match(source, index)
            assert match is not None
            text = match.group(0)
            end = match.end()
            unit = next(
                (
                    candidate
                    for candidate in sorted(_DURATION_UNITS, key=len, reverse=True)
                    if source.startswith(candidate, end)
                ),
                None,
            )
            if unit is not None:
                duration_text = text + unit
                tokens.append(
                    Token(
                        "DURATION",
                        duration_text,
                        float(text) * _DURATION_UNITS[unit],
                        token_location,
                    )
                )
                advance(duration_text)
                index = end + len(unit)
            else:
                value: int | float = float(text) if "." in text else int(text)
                tokens.append(Token("NUMBER", text, value, token_location))
                advance(text)
                index = end
            continue

        identifier = _IDENTIFIER.match(source, index)
        if identifier is not None:
            text = identifier.group(0)
            tokens.append(Token("IDENT", text, text, token_location))
            advance(text)
            index = identifier.end()
            continue

        two_character = source[index : index + 2]
        if two_character in {"==", "!=", ">=", "<="}:
            tokens.append(Token(two_character, two_character, two_character, token_location))
            advance(two_character)
            index += 2
            continue
        if character in "{}()[],:.=@+-*/%><":
            tokens.append(Token(character, character, character, token_location))
            advance(character)
            index += 1
            continue
        raise DSLParseError(f"unexpected character '{character}'", token_location)

    tokens.append(Token("EOF", "", None, location()))
    return tuple(tokens)
