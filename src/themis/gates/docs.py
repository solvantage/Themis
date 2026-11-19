"""Gate: docs — a page renders as it was written.

These rules read every page a project names, not only its governed documents. What counts as
prose, code or HTML is read by `themis.markdown`, as CommonMark says.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from themis import markdown
from themis.rule import Context, Param, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

PAGES = Param("pages", [str], None, "larger", "the Markdown pages it reads, as path patterns, such as **/*.md")


@rule(
    "docs/no-bare-dollar-pairs",
    "No line of Markdown prose holds two or more bare dollar signs, which a renderer pairs into math.",
    params=(PAGES,),
    requires=("pages",),
    learned="Prices written with bare dollar signs rendered as formulas, two to a line, on a hundred pages.",
)
def no_bare_dollar_pairs(ctx: Context) -> None:
    for name in sorted({name for pattern in ctx.param("pages") for name in ctx.files(pattern)}):
        text = ctx.read(name)
        if text is None:
            ctx.refuse("this page cannot be read as text", where=name,
                       fix="save it as UTF-8 text, or take it out of the pages this rule reads")
            continue
        ctx.inspect()
        for number, line in markdown.dollar_lines(text):
            ctx.breach(f"this line holds {len(markdown.bare_dollars(line))} bare dollar signs, so the words between "
                       "them render as math", where=name, line=number,
                       fix="write each sign as \\$, or put the amounts in code spans")


SETUP = '[rules."docs/no-bare-dollar-pairs"]\npages = ["**/*.md"]\n'
FENCED = """
    # Prices

    One sign to a line is safe: it cost $3.
    Escaped signs are text: \\$12 on a \\$100 stake.
    In code they are text too: `$12` on a ``$100 ` stake``.
    A link target is not prose: [the $1 plan]($2.md) and <https://example.invalid/$3/$4>.

    ```sh
    echo "$HOME $PATH"
    ```

    ~~~
    total=$1 $2
    ~~~

    ````md
    ```
    still code: $1 and $2
    ````

    ```mermaid
    flowchart LR
      A["$1"] --> B["$2"]
    ```

        indented code: $1 and $2

    <div>
    Inside a block tag: $1 and $2
    </div>

    <!-- a comment
    that holds $1 and $2 -->

    <?php echo "$a $b"; ?>
"""


def _pages(world: World, text: str, path: str = "docs/prices.md") -> None:
    world.manifest(SETUP)
    world.write("README.md", "# A small project\n\nSee [the prices](docs/prices.md).\n")
    world.write("scripts/build.sh", 'echo "$1 $2"\n')  # a script is not a page
    world.write(path, text)


@proof("docs/no-bare-dollar-pairs", "every pair sits in code, HTML, a link target or behind a backslash", expect="pass")
def _(world: World) -> None:
    _pages(world, FENCED)


@proof("docs/no-bare-dollar-pairs", "two prices on one line", expect="fail", contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _pages(world, "# Prices\n\nIt made $12 on a $100 stake.\n")


@proof("docs/no-bare-dollar-pairs", "an escaped backslash leaves the sign after it bare", expect="fail",
       contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _pages(world, "It made \\\\$12 on a $100 stake.\n")


@proof("docs/no-bare-dollar-pairs", "a shorter fence inside a long one does not close it", expect="fail",
       contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _pages(world, "````md\n```\n````\nIt made $12 on a $100 stake.\n")


@proof("docs/no-bare-dollar-pairs", "a tilde line does not close a backtick fence", expect="pass")
def _(world: World) -> None:
    _pages(world, "```\n~~~\nstill code: $1 and $2\n```\n")


@proof("docs/no-bare-dollar-pairs", "an indented line inside a list is the item's text", expect="fail",
       contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _pages(world, "- the stake\n\n    It made $12 on a $100 stake.\n")


@proof("docs/no-bare-dollar-pairs", "a lone tag cannot interrupt a paragraph", expect="fail",
       contains="holds 3 bare dollar signs")
def _(world: World) -> None:
    _pages(world, "The stake:\n<span>\nIt made $12 on a $100 stake, $5 a day.\n")


@proof("docs/no-bare-dollar-pairs", "a block tag's HTML block ends at the blank line", expect="fail",
       contains="holds 2 bare dollar signs")
def _(world: World) -> None:
    _pages(world, "<div>\n$1 and $2 stay HTML\n</div>\n\nIt made $12 on a $100 stake.\n", path="notes/stake.md")


@proof("docs/no-bare-dollar-pairs", "a page that is not text", expect="refuse", contains="cannot be read as text")
def _(world: World) -> None:
    _pages(world, "fine\n")
    (world.root / "docs/blob.md").write_bytes(b"\xff\xfe$1 $2")


@proof("docs/no-bare-dollar-pairs", "no page matches", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    world.manifest('[rules."docs/no-bare-dollar-pairs"]\npages = ["handbook/**/*.md"]\n')
    world.write("docs/prices.md", "It made $12 on a $100 stake.\n")
