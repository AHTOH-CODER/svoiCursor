from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".go": "go",
}

KEYWORDS = {
    "python": [
        "and",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "class",
        "continue",
        "def",
        "del",
        "elif",
        "else",
        "except",
        "False",
        "finally",
        "for",
        "from",
        "global",
        "if",
        "import",
        "in",
        "is",
        "lambda",
        "None",
        "nonlocal",
        "not",
        "or",
        "pass",
        "raise",
        "return",
        "True",
        "try",
        "while",
        "with",
        "yield",
    ],
    "c": [
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "restrict",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
    ],
    "cpp": [
        "alignas",
        "auto",
        "bool",
        "break",
        "case",
        "catch",
        "char",
        "class",
        "concept",
        "const",
        "constexpr",
        "continue",
        "decltype",
        "default",
        "delete",
        "do",
        "double",
        "else",
        "enum",
        "explicit",
        "export",
        "extern",
        "false",
        "float",
        "for",
        "friend",
        "if",
        "inline",
        "int",
        "long",
        "namespace",
        "new",
        "noexcept",
        "nullptr",
        "operator",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "template",
        "this",
        "throw",
        "true",
        "try",
        "typedef",
        "typename",
        "union",
        "unsigned",
        "using",
        "virtual",
        "void",
        "while",
    ],
    "go": [
        "break",
        "case",
        "chan",
        "const",
        "continue",
        "default",
        "defer",
        "else",
        "fallthrough",
        "for",
        "func",
        "go",
        "goto",
        "if",
        "import",
        "interface",
        "map",
        "package",
        "range",
        "return",
        "select",
        "struct",
        "switch",
        "type",
        "var",
    ],
}


def language_for_path(path: Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document, language: str | None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(document)
        self.language = language
        self.rules = self._build_rules(language)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API name.
        for pattern, text_format in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)

    def _build_rules(self, language: str | None) -> list[tuple[QRegularExpression, QTextCharFormat]]:
        keyword_format = self._format("#569cd6", bold=True)
        type_format = self._format("#4ec9b0")
        string_format = self._format("#ce9178")
        comment_format = self._format("#6a9955")
        number_format = self._format("#b5cea8")
        function_format = self._format("#dcdcaa")
        preprocessor_format = self._format("#c586c0")

        rules: list[tuple[QRegularExpression, QTextCharFormat]] = [
            (QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), string_format),
            (QRegularExpression(r"'[^'\\]*(\\.[^'\\]*)*'"), string_format),
            (QRegularExpression(r"\b\d+(\.\d+)?\b"), number_format),
            (QRegularExpression(r"\b[A-Za-z_]\w*(?=\s*\()"), function_format),
        ]

        if language == "python":
            rules.extend(
                [
                    (QRegularExpression(r"#.*$"), comment_format),
                    (QRegularExpression(r"\bself\b"), type_format),
                ]
            )
        elif language in {"c", "cpp", "go"}:
            rules.extend(
                [
                    (QRegularExpression(r"//.*$"), comment_format),
                    (QRegularExpression(r"/\*.*\*/"), comment_format),
                    (QRegularExpression(r"^\s*#\w+.*$"), preprocessor_format),
                ]
            )

        for keyword in KEYWORDS.get(language or "", []):
            rules.append((QRegularExpression(rf"\b{keyword}\b"), keyword_format))

        return rules

    def _format(self, color: str, bold: bool = False) -> QTextCharFormat:
        text_format = QTextCharFormat()
        text_format.setForeground(QColor(color))
        if bold:
            text_format.setFontWeight(QFont.Bold)
        return text_format
