"""Reading a shell command the way the shell will run it, for the agent hook.

The reader is strict. It gives back a line's simple commands, each with its assignments, its words
and its redirections, and the operators between them. Each word says what the shell would still do
to it: expand a variable or a substitution, a glob, a brace list, a tilde. The text of each command
substitution is kept, so it can be read in turn, and so is each here-document. Whatever the reader
does not follow it refuses with Unreadable: an arithmetic expansion, `[[`, `case`, a function or an
array, a parameter expansion that runs a command, an unclosed quote or here-document.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Operators that end a simple command, longest first.
CONTROL = (";;&", "&&", "||", ";;", ";&", "|&", ";", "&", "|", "(", ")", "\n")
#: Redirections, longest first, with zsh's clobber and append forms (`&>!`, `>&|`, `>>&` …).
_REDIRECT = re.compile(r"(\d*)(&>>!|&>>\||>>&!|>>&\||&>!|&>\||>&!|>&\||>>&|&>>|<<<|<<-|<<|<>|<&|<(?!\()"
                       r"|>>!|>>\||>>|>\||>!|>&|>(?!\()|&>)")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")
#: Words that open a construct the reader does not follow.
UNSUPPORTED = {"case", "[[", "select", "coproc", "function", "((", "esac"}
#: Redirections that only read.
READS = {"<", "<<", "<<-", "<<<"}


class Unreadable(ValueError):
    """The command uses shell syntax the reader does not follow."""


@dataclass
class Word:
    text: str = ""  # the word with its quotes taken off; expansions as written
    raw: str = ""  # the word as written
    quoted: bool = False  # an expansion inside double quotes: one word, its value unknown
    bare: bool = False  # an expansion outside quotes: split into words and globbed by the shell
    glob: bool = False  # an unquoted * ? or [
    brace: bool = False  # an unquoted brace list, {a,b} or {1..3}
    tilde: bool = False  # an unquoted ~ (or zsh's =) at the start
    extended: bool = False  # an unquoted #, ^ or ~ inside it: a glob under zsh's extended_glob
    subs: list[str] = field(default_factory=list)  # the text of each command substitution in it

    @property
    def expands(self) -> bool:
        """True when the shell puts a value of its own into the word."""
        return self.quoted or self.bare

    @property
    def literal(self) -> bool:
        """True when the shell passes the word on exactly as its text."""
        return not (self.expands or self.glob or self.brace or self.tilde)


@dataclass
class Redirect:
    op: str  # one of the forms in _REDIRECT
    fd: str = ""  # the descriptor written before it, if any
    target: Word = field(default_factory=Word)
    body: str | None = None  # a here-document's text

    @property
    def reads(self) -> bool:
        return self.op in READS or (self.op == "<&" and _is_descriptor(self.target))

    @property
    def duplicates(self) -> bool:
        """True for `>&2`, `2>&1`, `>&-`: a descriptor copied or closed, no file named."""
        return self.op in (">&", "<&") and _is_descriptor(self.target)


@dataclass
class Simple:
    assigns: list[Word] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.assigns or self.words or self.redirects)

    def all_words(self) -> list[Word]:
        return [*self.assigns, *self.words, *(redirect.target for redirect in self.redirects)]


def _is_descriptor(word: Word) -> bool:
    return word.literal and (word.text.isdigit() or word.text == "-")


def parse(text: str) -> list[Simple | str]:
    """The line as simple commands and the operators between them. Raises Unreadable, also for a
    control or invisible character other than a tab or a newline: a shell reads a carriage return
    as part of a word, and a reader that does not would see another path than the shell."""
    for char in text:
        if char not in "\t\n" and (unicodedata.category(char)[0] == "C" or unicodedata.category(char) in ("Zl", "Zp")):
            raise Unreadable(f"the command holds the character U+{ord(char):04X}")
    reader = _Reader(text)
    return reader.read(stop=False)


class _Reader:
    def __init__(self, text: str) -> None:
        self.s, self.i = text, 0
        self.pending: list[tuple[Redirect, str, bool]] = []  # here-documents whose text follows the next newline

    # -- the line -------------------------------------------------------------------------------

    def read(self, *, stop: bool) -> list[Simple | str]:
        """Read to the end, or with `stop` to the `)` that closes a substitution."""
        pieces: list[Simple | str] = []
        current, depth = Simple(), 0

        def close() -> None:
            nonlocal current
            if not current.empty:
                pieces.append(current)
            current = Simple()

        while True:
            self._blanks()
            if self.i >= len(self.s):
                if stop:
                    raise Unreadable("a substitution is not closed")
                if self.pending:
                    raise Unreadable("a here-document is not closed")
                close()
                return pieces
            char = self.s[self.i]
            if char == "#":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
                continue
            found = _REDIRECT.match(self.s, self.i)
            if found and not self.s.startswith(("<(", ">("), self.i + len(found.group(1))):
                self.i = found.end()
                current.redirects.append(self._redirect(found.group(2), found.group(1)))
                continue
            op = next((op for op in CONTROL if self.s.startswith(op, self.i)), None)
            if op is not None:
                self.i += len(op)
                if op == ")" and stop and depth == 0:
                    close()
                    return pieces
                if op == "(":
                    if not current.empty:
                        raise Unreadable("a function or an array")
                    if self.s[self.i:].lstrip(" \t").startswith("("):
                        raise Unreadable("an arithmetic command")
                    depth += 1
                elif op == ")":
                    depth -= 1
                    if depth < 0:
                        raise Unreadable("a parenthesis is not opened")
                close()
                pieces.append(op)
                if op == "\n":
                    self._bodies()
                continue
            word = self._word()
            if not current.words and _ASSIGNMENT.match(word.raw):
                current.assigns.append(word)
            else:
                if not current.words and word.text in UNSUPPORTED and not word.raw.startswith(("'", '"', "\\")):
                    raise Unreadable(f"`{word.text}` is not read")
                current.words.append(word)

    def _blanks(self) -> None:
        while self.i < len(self.s):
            if self.s[self.i] in " \t":
                self.i += 1
            elif self.s.startswith("\\\n", self.i):
                self.i += 2
            else:
                return

    def _redirect(self, op: str, fd: str) -> Redirect:
        self._blanks()
        if self.i >= len(self.s) or self.s[self.i] in "\n;&|()<>":
            raise Unreadable("a redirection names nothing")
        redirect = Redirect(op=op, fd=fd, target=self._word())
        if redirect.target.raw.startswith(("!", "|")):
            raise Unreadable("a redirection whose form this reader does not know")
        if op in ("<<", "<<-"):
            plain = not any(char in redirect.target.raw for char in "'\"\\")
            self.pending.append((redirect, redirect.target.text, plain))
        return redirect

    def _bodies(self) -> None:
        """Read the here-documents that begin on the line just ended."""
        for redirect, delimiter, expands in self.pending:
            lines = []
            while True:
                if self.i >= len(self.s):
                    raise Unreadable("a here-document is not closed")
                end = self.s.find("\n", self.i)
                line = self.s[self.i:] if end < 0 else self.s[self.i:end]
                self.i = len(self.s) if end < 0 else end + 1
                if (line.lstrip("\t") if redirect.op == "<<-" else line) == delimiter:
                    break
                lines.append(line)
            redirect.body = "\n".join(lines)
            if expands and ("`" in redirect.body or "$(" in redirect.body or "${" in redirect.body):
                raise Unreadable("a here-document runs a substitution")
        self.pending = []

    # -- words ----------------------------------------------------------------------------------

    def _word(self) -> Word:
        word, out, start = Word(), [], self.i
        opened = separated = False  # an unquoted { seen, and a , or .. after it
        while self.i < len(self.s):
            char = self.s[self.i]
            if char in "<>" and self.s.startswith(("<(", ">("), self.i):
                self.i += 2
                word.subs.append(self._substitution())
                word.bare = True
                out.append("<(…)")
                continue
            if char in " \t\n;&|()<>":
                break
            if char == "\\":
                if self.i + 1 >= len(self.s):
                    raise Unreadable("a backslash ends the command")
                if self.s[self.i + 1] != "\n":
                    out.append(self.s[self.i + 1])
                self.i += 2
            elif char == "'":
                end = self.s.find("'", self.i + 1)
                if end < 0:
                    raise Unreadable("a quote is not closed")
                out.append(self.s[self.i + 1:end])
                self.i = end + 1
            elif char == '"':
                self._double(word, out)
            elif char == "$":
                self._dollar(word, out, quoted=False)
            elif char == "`":
                word.subs.append(self._backtick())
                word.bare = True
                out.append("`…`")
            else:
                if char in "*?[":
                    word.glob = True
                elif char == "{":
                    opened = True
                elif opened and (char == "," or self.s.startswith("..", self.i)):
                    separated = True
                elif char == "}" and opened and separated:
                    word.brace = True
                elif char in "~=" and self.i == start:
                    word.tilde = True
                elif char in "#^~":
                    word.extended = True
                out.append(char)
                self.i += 1
        word.text, word.raw = "".join(out), self.s[start:self.i]
        if self.i == start:
            raise Unreadable("an empty word")
        return word

    def _double(self, word: Word, out: list[str]) -> None:
        self.i += 1
        while self.i < len(self.s):
            char = self.s[self.i]
            if char == '"':
                self.i += 1
                return
            if char == "\\" and self.i + 1 < len(self.s) and self.s[self.i + 1] in '$`"\\\n':
                if self.s[self.i + 1] != "\n":
                    out.append(self.s[self.i + 1])
                self.i += 2
            elif char == "$":
                self._dollar(word, out, quoted=True)
            elif char == "`":
                word.subs.append(self._backtick())
                word.quoted = True
                out.append("`…`")
            else:
                out.append(char)
                self.i += 1
        raise Unreadable("a quote is not closed")

    def _dollar(self, word: Word, out: list[str], *, quoted: bool) -> None:
        s, i = self.s, self.i
        after = s[i + 1] if i + 1 < len(s) else ""
        start = i
        if after == "(":
            if s.startswith("$((", i):
                raise Unreadable("an arithmetic expansion")
            self.i = i + 2
            word.subs.append(self._substitution())
        elif after == "{":
            end = s.find("}", i + 2)
            if end < 0:
                raise Unreadable("a parameter expansion is not closed")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[@*#?$!-]", s[i + 2:end]):
                # Flags, defaults that assign, prompts, subscripts: only the plain ${NAME} is read.
                raise Unreadable("a parameter expansion other than ${NAME}")
            self.i = end + 1
        elif after == "'" and not quoted:
            j = i + 2
            while j < len(s) and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            if j >= len(s):
                raise Unreadable("a quote is not closed")
            self.i = j + 1
            word.quoted = True  # $'…': the shell decodes it, so its value is taken as unknown
            out.append(s[start:self.i])
            return
        elif after == '"' and not quoted:
            self.i = i + 1
            self._double(word, out)
            word.quoted = True
            return
        elif after == "[":
            raise Unreadable("an arithmetic expansion")
        elif after and after in "=~^+":
            raise Unreadable("a zsh expansion flag")  # $~X globs the value, and a glob qualifier can run code
        elif after and (after.isdigit() or after in "@*#?$!-"):
            self.i = i + 2
        elif after and _NAME.match(after):
            self.i = _NAME.match(s, i + 1).end()  # type: ignore[union-attr]
        else:
            out.append("$")
            self.i = i + 1
            return
        if quoted:
            word.quoted = True
        else:
            word.bare = True
        out.append(s[start:self.i])

    def _substitution(self) -> str:
        """The text inside `$(…)`, `<(…)` or `>(…)`, read through to its closing parenthesis."""
        start = self.i
        self.read(stop=True)
        return self.s[start:self.i - 1]

    def _backtick(self) -> str:
        j, inner = self.i + 1, []
        while j < len(self.s):
            if self.s[j] == "\\" and j + 1 < len(self.s) and self.s[j + 1] in "`$\\":
                inner.append(self.s[j + 1])
                j += 2
            elif self.s[j] == "`":
                self.i = j + 1
                return "".join(inner)
            else:
                inner.append(self.s[j])
                j += 1
        raise Unreadable("a backtick is not closed")
