from __future__ import annotations

import hashlib
import re

from .errors import SqlSafetyError


_DOLLAR_QUOTE_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def normalize_migration_bytes(raw: bytes) -> bytes:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SqlSafetyError("migration files must not contain a UTF-8 BOM")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SqlSafetyError("migration files must be valid UTF-8") from exc
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def migration_checksum(raw: bytes) -> str:
    return hashlib.sha256(normalize_migration_bytes(raw)).hexdigest()


def _skip_quoted(text: str, start: int, quote: str, *, backslash_escapes: bool = False) -> int:
    index = start + 1
    while index < len(text):
        if backslash_escapes and text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            if index + 1 < len(text) and text[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    kind = "string" if quote == "'" else "quoted identifier"
    raise SqlSafetyError(f"unterminated SQL {kind}")


def _skip_block_comment(text: str, start: int) -> int:
    depth = 1
    index = start + 2
    while index < len(text):
        if text.startswith("/*", index):
            depth += 1
            index += 2
        elif text.startswith("*/", index):
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    raise SqlSafetyError("unterminated nested SQL block comment")


def top_level_statement_tokens(sql: str) -> tuple[tuple[str, ...], ...]:
    statements: list[tuple[str, ...]] = []
    current: list[str] = []
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            index = _skip_block_comment(sql, index)
            continue

        char = sql[index]
        if char == "'":
            escape_prefix = (
                index > 0
                and sql[index - 1] in {"e", "E"}
                and (index == 1 or not (sql[index - 2].isalnum() or sql[index - 2] in {"_", "$"}))
            )
            index = _skip_quoted(sql, index, "'", backslash_escapes=escape_prefix)
            continue
        if char == '"':
            index = _skip_quoted(sql, index, '"')
            continue
        if char == "$":
            match = _DOLLAR_QUOTE_RE.match(sql, index)
            if match is not None:
                delimiter = match.group(0)
                end = sql.find(delimiter, match.end())
                if end < 0:
                    raise SqlSafetyError(f"unterminated SQL dollar quote {delimiter}")
                index = end + len(delimiter)
                continue
        if char == ";":
            if current:
                statements.append(tuple(current))
                current = []
            index += 1
            continue

        word = _WORD_RE.match(sql, index)
        if word is not None:
            current.append(word.group(0).upper())
            index = word.end()
            continue
        index += 1

    if current:
        statements.append(tuple(current))
    return tuple(statements)


def _forbidden_operation(tokens: tuple[str, ...]) -> str | None:
    if not tokens:
        return None
    first = tokens[0]
    if first in {"BEGIN", "COMMIT", "ROLLBACK", "VACUUM"}:
        return first
    if tokens[:2] == ("START", "TRANSACTION"):
        return "START TRANSACTION"
    if tokens[:2] in {("CREATE", "DATABASE"), ("DROP", "DATABASE"), ("ALTER", "SYSTEM")}:
        return " ".join(tokens[:2])
    if len(tokens) >= 3 and tokens[:2] == ("CREATE", "INDEX") and tokens[2] == "CONCURRENTLY":
        return "CREATE INDEX CONCURRENTLY"
    if len(tokens) >= 4 and tokens[:3] == ("CREATE", "UNIQUE", "INDEX") and tokens[3] == "CONCURRENTLY":
        return "CREATE UNIQUE INDEX CONCURRENTLY"
    if len(tokens) >= 3 and tokens[:2] == ("DROP", "INDEX") and tokens[2] == "CONCURRENTLY":
        return "DROP INDEX CONCURRENTLY"
    if first == "REINDEX" and "CONCURRENTLY" in tokens:
        return "REINDEX CONCURRENTLY"
    return None


def validate_transactional_sql(sql: str) -> None:
    for tokens in top_level_statement_tokens(sql):
        operation = _forbidden_operation(tokens)
        if operation is not None:
            raise SqlSafetyError(f"transactional migration contains forbidden top-level operation: {operation}")


def normalize_catalog_sql(value: str | None) -> str | None:
    if value is None:
        return None
    output: list[str] = []
    pending_space = False
    index = 0
    while index < len(value):
        char = value[index]
        if char.isspace():
            pending_space = bool(output)
            index += 1
            continue
        if value.startswith("--", index) or value.startswith("/*", index):
            raise SqlSafetyError("catalog SQL unexpectedly contains a comment")
        if pending_space:
            output.append(" ")
            pending_space = False
        if char == "'":
            end = _skip_quoted(value, index, "'")
            output.append(value[index:end])
            index = end
            continue
        if char == '"':
            end = _skip_quoted(value, index, '"')
            output.append(value[index:end])
            index = end
            continue
        if char == "$":
            match = _DOLLAR_QUOTE_RE.match(value, index)
            if match is not None:
                delimiter = match.group(0)
                end = value.find(delimiter, match.end())
                if end < 0:
                    raise SqlSafetyError(f"unterminated catalog SQL dollar quote {delimiter}")
                end += len(delimiter)
                output.append(value[index:end])
                index = end
                continue
        output.append(char)
        index += 1
    return "".join(output).strip()
