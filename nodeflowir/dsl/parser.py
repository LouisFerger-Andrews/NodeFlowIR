"""Recursive-descent parser for the NodeFlow DSL syntax tree."""

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from nodeflowir.dsl import ast
from nodeflowir.dsl.errors import DSLParseError, SourceLocation
from nodeflowir.dsl.lexer import Token, tokenize


class Parser:
    """Parse one DSL document without consulting node definitions or runtime state."""

    def __init__(self, source: str) -> None:
        self._tokens = tokenize(source)
        self._index = 0

    @property
    def current(self) -> Token:
        return self._tokens[self._index]

    @property
    def next(self) -> Token:
        return self._tokens[self._index + 1]

    def parse(self) -> ast.FileSyntax:
        start = self.current.location
        self._expect_word("nodeflow")
        language_version = self._parse_version()
        self._expect_word("workflow")
        workflow_location = self.current.location
        name = self._expect_identifier("workflow name").text
        display_name = None
        if self._match_word("named"):
            display_name = self._expect("STRING", "quoted workflow display name").value
            assert isinstance(display_name, str)
        self._expect_word("version")
        version = self._expect_positive_integer("workflow version")
        parameters = self._parse_parameters() if self._match("(") else ()
        body = self._parse_block()
        self._expect("EOF", "end of document")
        workflow = ast.WorkflowSyntax(
            location=workflow_location,
            name=name,
            display_name=display_name,
            version=version,
            parameters=parameters,
            body=body,
        )
        return ast.FileSyntax(location=start, language_version=language_version, workflow=workflow)

    def _parse_parameters(self) -> tuple[ast.ParameterSyntax, ...]:
        parameters: list[ast.ParameterSyntax] = []
        if self._match(")"):
            return ()
        while True:
            location = self.current.location
            name = self._expect_identifier("workflow input name").text
            self._expect(":", "':' after workflow input name")
            type_name = self._expect_identifier("workflow input type").text
            parameters.append(ast.ParameterSyntax(location, name, type_name))
            if self._match(")"):
                return tuple(parameters)
            self._expect(",", "',' or ')' after workflow input")

    def _parse_block(self) -> ast.BlockSyntax:
        location = self.current.location
        self._expect("{", "'{' to start a block")
        statements: list[ast.StatementSyntax] = []
        while self.current.kind != "}":
            if self.current.kind == "EOF":
                self._error("expected '}' to close this block")
            statements.append(self._parse_statement())
        self._advance()
        return ast.BlockSyntax(location, tuple(statements))

    def _parse_statement(self) -> ast.StatementSyntax:
        word = self.current.text if self.current.kind == "IDENT" else None
        if word == "if":
            return self._parse_if()
        if word == "match":
            return self._parse_match()
        if word == "foreach":
            return self._parse_foreach()
        if word == "repeat":
            return self._parse_repeat()
        if word == "parallel":
            return self._parse_parallel()
        if word == "break":
            location = self._advance().location
            return ast.BreakSyntax(location)
        if word == "continue":
            location = self._advance().location
            return ast.ContinueSyntax(location)
        if word == "output":
            return self._parse_output()
        if word == "const":
            return self._parse_constant()
        if word == "run":
            return self._parse_run(alias=None)
        if self.current.kind == "IDENT" and self.next.kind == "=":
            location = self.current.location
            name = self._advance().text
            self._advance()
            if self._is_word("run"):
                return self._parse_run(alias=name, location=location)
            return ast.AssignmentSyntax(location, name, self._parse_expression())
        self._error("expected a workflow statement")

    def _parse_constant(self) -> ast.ConstantSyntax:
        location = self._advance().location
        name = self._expect_identifier("constant name").text
        self._expect(":", "':' after constant name")
        type_name = self._expect_identifier("constant type").text
        self._expect("=", "'=' after constant type")
        return ast.ConstantSyntax(location, name, type_name, self._parse_expression())

    def _parse_if(self) -> ast.IfSyntax:
        location = self._advance().location
        condition = self._parse_expression()
        then = self._parse_block()
        else_if: list[tuple[ast.ExpressionSyntax, ast.BlockSyntax]] = []
        else_body: ast.BlockSyntax | None = None
        while self._match_word("else"):
            if self._match_word("if"):
                branch_condition = self._parse_expression()
                else_if.append((branch_condition, self._parse_block()))
            else:
                else_body = self._parse_block()
                break
        return ast.IfSyntax(location, condition, then, tuple(else_if), else_body)

    def _parse_match(self) -> ast.MatchSyntax:
        location = self._advance().location
        subject = self._parse_expression()
        self._expect("{", "'{' to start a match block")
        cases: list[tuple[ast.ExpressionSyntax, ast.BlockSyntax]] = []
        default: ast.BlockSyntax | None = None
        while self.current.kind != "}":
            if self._match_word("case"):
                if default is not None:
                    self._error("match cases cannot appear after default")
                value = self._parse_expression()
                cases.append((value, self._parse_block()))
                continue
            if self._match_word("default"):
                if default is not None:
                    self._error("match can contain only one default block")
                default = self._parse_block()
                continue
            self._error("expected 'case', 'default', or '}' in match block")
        self._advance()
        if not cases:
            self._error_at(location, "match requires at least one case")
        return ast.MatchSyntax(location, subject, tuple(cases), default)

    def _parse_foreach(self) -> ast.ForeachSyntax:
        location = self._advance().location
        item_name = self._expect_identifier("foreach item name").text
        self._expect_word("in")
        collection = self._parse_expression()
        return ast.ForeachSyntax(location, item_name, collection, self._parse_block())

    def _parse_repeat(self) -> ast.RepeatSyntax:
        location = self._advance().location
        return ast.RepeatSyntax(
            location,
            self._expect_positive_integer("repeat count"),
            self._parse_block(),
        )

    def _parse_parallel(self) -> ast.ParallelSyntax:
        location = self._advance().location
        convergence = "all"
        if self.current.kind == "IDENT" and self.current.text in {"all", "any"}:
            convergence = self._advance().text
        return ast.ParallelSyntax(location, convergence, self._parse_block())

    def _parse_output(self) -> ast.OutputSyntax:
        location = self._advance().location
        self._expect("{", "'{' to start output block")
        assignments = self._parse_assignments_until("}")
        self._expect("}", "'}' to close output block")
        return ast.OutputSyntax(location, assignments)

    def _parse_run(
        self, alias: str | None, location: SourceLocation | None = None
    ) -> ast.RunSyntax:
        location = self._advance().location if location is None else location
        if self._is_word("run"):
            self._advance()
        type_id = self._expect_identifier("node type identifier").text
        type_version = self._parse_version() if self._match("@") else None
        assignments: list[ast.AssignmentSyntax] = []
        retry: ast.RetrySyntax | None = None
        timeout_seconds: float | None = None
        on_error: ast.ErrorSyntax | None = None
        while True:
            if self._match_word("with"):
                if assignments:
                    self._error("a node execution can contain only one with clause")
                assignments.extend(self._parse_with_assignments())
                continue
            if self._match_word("retry"):
                if retry is not None:
                    self._error("a node execution can contain only one retry clause")
                retry = self._parse_retry()
                continue
            if self._match_word("timeout"):
                if timeout_seconds is not None:
                    self._error("a node execution can contain only one timeout clause")
                timeout_seconds = self._parse_duration("timeout")
                continue
            if self._match_word("on"):
                if on_error is not None:
                    self._error("a node execution can contain only one error clause")
                on_error = self._parse_error_clause()
                continue
            break
        return ast.RunSyntax(
            location,
            alias,
            type_id,
            type_version,
            tuple(assignments),
            retry,
            timeout_seconds,
            on_error,
        )

    def _parse_with_assignments(self) -> tuple[ast.AssignmentSyntax, ...]:
        if self._match("{"):
            braced_assignments = self._parse_assignments_until("}")
            self._expect("}", "'}' to close with clause")
            return braced_assignments
        assignments: list[ast.AssignmentSyntax] = []
        while self.current.kind == "IDENT" and self.next.kind == "=":
            location = self.current.location
            name = self._advance().text
            self._advance()
            assignments.append(ast.AssignmentSyntax(location, name, self._parse_expression()))
        if not assignments:
            self._error("expected at least one assignment after 'with'")
        return tuple(assignments)

    def _parse_retry(self) -> ast.RetrySyntax:
        location = self.current.location
        if self.current.kind == "NUMBER":
            attempts = self._expect_positive_integer("retry attempt count")
            return ast.RetrySyntax(location, attempts)
        self._expect("{", "retry attempt count or '{'")
        attempts: int | None = None
        delay_seconds = 0.0
        backoff = "fixed"
        max_delay_seconds: float | None = None
        seen_fields: set[str] = set()
        while self.current.kind != "}":
            key = self._expect_identifier("retry field").text
            if key in seen_fields:
                self._error(f"duplicate retry field '{key}'")
            seen_fields.add(key)
            self._expect("=", "'=' after retry field")
            if key == "attempts":
                attempts = self._expect_positive_integer("retry attempts")
            elif key == "delay":
                delay_seconds = self._parse_duration(key)
            elif key == "max_delay":
                max_delay_seconds = self._parse_duration(key)
            elif key == "backoff":
                backoff = self._expect_identifier("retry backoff strategy").text
            else:
                self._error(f"unknown retry field '{key}'")
            self._match(",")
        self._advance()
        if attempts is None:
            self._error_at(location, "retry block requires 'attempts'")
        return ast.RetrySyntax(
            location,
            attempts=attempts,
            delay_seconds=delay_seconds,
            backoff=backoff,
            max_delay_seconds=max_delay_seconds,
        )

    def _parse_error_clause(self) -> ast.ErrorSyntax:
        location = self.current.location
        self._expect_word("error")
        categories: list[str] = []
        while self.current.kind == "IDENT":
            if self.current.text in {"failed", "timeout", "cancelled"}:
                categories.append(self._advance().text)
                self._match(",")
                continue
            break
        return ast.ErrorSyntax(location, tuple(categories), self._parse_block())

    def _parse_assignments_until(self, terminator: str) -> tuple[ast.AssignmentSyntax, ...]:
        assignments: list[ast.AssignmentSyntax] = []
        while self.current.kind != terminator:
            if self.current.kind == "EOF":
                self._error(f"expected '{terminator}'")
            location = self.current.location
            name = self._expect_identifier("field name").text
            self._expect("=", "'=' after field name")
            assignments.append(ast.AssignmentSyntax(location, name, self._parse_expression()))
            self._match(",")
        return tuple(assignments)

    def _parse_expression(self) -> ast.ExpressionSyntax:
        return self._parse_or()

    def _parse_or(self) -> ast.ExpressionSyntax:
        expression = self._parse_and()
        while self._match_word("or"):
            expression = ast.BinarySyntax(expression.location, "or", expression, self._parse_and())
        return expression

    def _parse_and(self) -> ast.ExpressionSyntax:
        expression = self._parse_comparison()
        while self._match_word("and"):
            expression = ast.BinarySyntax(
                expression.location, "and", expression, self._parse_comparison()
            )
        return expression

    def _parse_comparison(self) -> ast.ExpressionSyntax:
        expression = self._parse_additive()
        operator: str | None = None
        if self.current.kind in {"==", "!=", ">", "<", ">=", "<="}:
            operator = self._advance().text
        elif self._match_word("in"):
            operator = "in"
        elif self._is_word("not") and self.next.kind == "IDENT" and self.next.text == "in":
            self._advance()
            self._advance()
            operator = "not in"
        elif self._match_word("is"):
            if self._match_word("not"):
                self._expect_word("null")
                return ast.UnarySyntax(expression.location, "is_not_null", expression)
            self._expect_word("null")
            return ast.UnarySyntax(expression.location, "is_null", expression)
        if operator is not None:
            expression = ast.BinarySyntax(
                expression.location, operator, expression, self._parse_additive()
            )
        return expression

    def _parse_additive(self) -> ast.ExpressionSyntax:
        expression = self._parse_multiplicative()
        while self.current.kind in {"+", "-"}:
            operator = self._advance().text
            expression = ast.BinarySyntax(
                expression.location, operator, expression, self._parse_multiplicative()
            )
        return expression

    def _parse_multiplicative(self) -> ast.ExpressionSyntax:
        expression = self._parse_unary()
        while self.current.kind in {"*", "/", "%"}:
            operator = self._advance().text
            expression = ast.BinarySyntax(
                expression.location, operator, expression, self._parse_unary()
            )
        return expression

    def _parse_unary(self) -> ast.ExpressionSyntax:
        if self._match_word("not"):
            return ast.UnarySyntax(
                self._tokens[self._index - 1].location, "not", self._parse_unary()
            )
        if self.current.kind == "-" and self.next.kind == "NUMBER":
            location = self._advance().location
            number = self._advance()
            if not isinstance(number.value, (int, float)):
                self._error_at(number.location, "expected a numeric literal")
            return ast.LiteralSyntax(location, -number.value)
        return self._parse_primary()

    def _parse_primary(self) -> ast.ExpressionSyntax:
        token = self.current
        if token.kind == "STRING":
            self._advance()
            return ast.LiteralSyntax(token.location, token.value)
        if token.kind == "NUMBER":
            self._advance()
            return ast.LiteralSyntax(token.location, token.value)
        if token.kind == "DURATION":
            self._advance()
            if not isinstance(token.value, (int, float)):
                self._error_at(token.location, "expected a duration literal")
            return ast.LiteralSyntax(
                token.location, token.value, duration_seconds=float(token.value)
            )
        if self._match_word("true"):
            return ast.LiteralSyntax(token.location, True)
        if self._match_word("false"):
            return ast.LiteralSyntax(token.location, False)
        if self._match_word("null"):
            return ast.LiteralSyntax(token.location, None)
        if self._match_word("object"):
            return self._parse_object(token.location)
        if self._match("["):
            items: list[ast.ExpressionSyntax] = []
            if not self._match("]"):
                while True:
                    items.append(self._parse_expression())
                    if self._match("]"):
                        break
                    self._expect(",", "',' or ']' in list literal")
            return ast.ListSyntax(token.location, tuple(items))
        if self._match("("):
            expression = self._parse_expression()
            self._expect(")", "')' after expression")
            return expression
        if token.kind == "IDENT":
            name = self._advance().text
            if self._match("("):
                arguments: list[ast.ExpressionSyntax] = []
                if not self._match(")"):
                    while True:
                        arguments.append(self._parse_expression())
                        if self._match(")"):
                            break
                        self._expect(",", "',' or ')' in function call")
                return ast.CallSyntax(token.location, name, tuple(arguments))
            return ast.ReferenceSyntax(token.location, name)
        self._error("expected an expression")

    def _parse_object(self, location: SourceLocation) -> ast.ObjectSyntax:
        self._expect("{", "'{' after object")
        fields: list[tuple[str, ast.ExpressionSyntax]] = []
        while self.current.kind != "}":
            if self.current.kind == "STRING":
                name = self._advance().value
                assert isinstance(name, str)
            else:
                name = self._expect_identifier("object field name").text
            self._expect("=", "'=' after object field name")
            fields.append((name, self._parse_expression()))
            self._match(",")
        self._advance()
        return ast.ObjectSyntax(location, tuple(fields))

    def _parse_version(self) -> str:
        first = self._expect("NUMBER", "version number").text
        parts = [first]
        while self._match("."):
            parts.append(self._expect("NUMBER", "version component").text)
        return ".".join(parts)

    def _parse_duration(self, label: str) -> float:
        token = self._expect("DURATION", f"{label} duration such as 30s or 2m")
        if not isinstance(token.value, (int, float)):
            self._error_at(token.location, "expected a duration literal")
        return float(token.value)

    def _expect_positive_integer(self, label: str) -> int:
        token = self._expect("NUMBER", label)
        if not isinstance(token.value, int) or token.value < 1:
            self._error_at(token.location, f"{label} must be a positive integer")
        return token.value

    def _expect_identifier(self, expected: str) -> Token:
        return self._expect("IDENT", expected)

    def _expect_word(self, word: str) -> Token:
        if self._is_word(word):
            return self._advance()
        self._error(f"expected '{word}'")

    def _expect(self, kind: str, expected: str) -> Token:
        if self.current.kind == kind:
            return self._advance()
        self._error(f"expected {expected}")

    def _match(self, kind: str) -> bool:
        if self.current.kind == kind:
            self._advance()
            return True
        return False

    def _match_word(self, word: str) -> bool:
        if self._is_word(word):
            self._advance()
            return True
        return False

    def _is_word(self, word: str) -> bool:
        return self.current.kind == "IDENT" and self.current.text == word

    def _advance(self) -> Token:
        token = self.current
        if token.kind != "EOF":
            self._index += 1
        return token

    def _error(self, message: str) -> NoReturn:
        raise DSLParseError(message, self.current.location)

    @staticmethod
    def _error_at(location: SourceLocation, message: str) -> NoReturn:
        raise DSLParseError(message, location)


def parse(source: str) -> ast.FileSyntax:
    """Parse source text into a temporary syntax tree without compiling it."""

    return Parser(source).parse()


def parse_many(sources: Iterable[str]) -> tuple[ast.FileSyntax, ...]:
    """Parse multiple documents; useful to tools without adding parser state."""

    return tuple(parse(source) for source in sources)
