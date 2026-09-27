"""Optional text interface for the canonical NodeFlowIR workflow model."""

from nodeflowir.dsl.ast import FileSyntax
from nodeflowir.dsl.compiler import Compiler, compile, compile_dsl, compile_syntax
from nodeflowir.dsl.errors import (
    DSLCompileError,
    DSLFormatError,
    DSLParseError,
    DSLValidationError,
    NodeFlowDSLError,
    SourceLocation,
)
from nodeflowir.dsl.formatter import format, format_dsl, format_workflow
from nodeflowir.dsl.parser import Parser, parse

parse_dsl = parse
parse_workflow = parse
compile_workflow = compile_dsl

__all__ = [
    "Compiler",
    "DSLCompileError",
    "DSLFormatError",
    "DSLParseError",
    "DSLValidationError",
    "FileSyntax",
    "NodeFlowDSLError",
    "Parser",
    "SourceLocation",
    "compile",
    "compile_dsl",
    "compile_workflow",
    "compile_syntax",
    "format",
    "format_dsl",
    "format_workflow",
    "parse",
    "parse_dsl",
    "parse_workflow",
]
