"""The documents name the rules that exist, in the words the code uses.

A catalogue kept by hand drifts from the rules it lists. So each document's rule tables are held
to the code: every rule of the pack has a row, no row names a rule that does not exist, and the
promise in the row is the rule's own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from themis import gates, pack
from themis.packs.trading import forward, process
from themis.rule import RULES

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\| `([a-z-]+/[a-z-]+)` \| (.*?) \|")
DOCUMENTS = {"core": "DESIGN.md", "trading": "docs/packs/trading.md", "marketing": "docs/packs/marketing.md"}

gates.load_all()
for name in ("trading", "marketing"):
    pack.load(name)


def rows(owner: str) -> list[tuple[str, str]]:
    """Every table row of the document that starts with a rule id, as (id, the next cell)."""
    lines = (ROOT / DOCUMENTS[owner]).read_text(encoding="utf-8").splitlines()
    return [(found.group(1), found.group(2)) for found in map(ROW.match, lines) if found]


@pytest.mark.parametrize("owner", DOCUMENTS)
def test_the_document_has_a_row_for_every_rule_of_its_pack(owner: str) -> None:
    listed = {rule_id for rule_id, _ in rows(owner)}
    missing = sorted(rule.id for rule in RULES.values() if rule.pack == owner and rule.id not in listed)
    assert not missing, f"{DOCUMENTS[owner]} has no row for: {', '.join(missing)}"


@pytest.mark.parametrize("owner", DOCUMENTS)
def test_the_document_names_no_rule_that_does_not_exist(owner: str) -> None:
    unknown = sorted({rule_id for rule_id, _ in rows(owner) if rule_id not in RULES})
    assert not unknown, f"{DOCUMENTS[owner]} names rules that are not registered: {', '.join(unknown)}"


@pytest.mark.parametrize("owner", DOCUMENTS)
def test_each_rules_promise_in_the_document_is_the_rules_own(owner: str) -> None:
    first: dict[str, str] = {}
    for rule_id, cell in rows(owner):
        if rule_id in RULES and RULES[rule_id].pack == owner:
            first.setdefault(rule_id, cell)
    wrong = [f"{rule_id}: the document says {cell!r}, the rule says {RULES[rule_id].promise!r}"
             for rule_id, cell in sorted(first.items()) if cell != RULES[rule_id].promise]
    assert not wrong, "\n".join(wrong)


def test_the_design_counts_the_core_rules_and_gates_as_they_are() -> None:
    core = [rule.id for rule in RULES.values() if rule.pack == "core"]
    rules, gates_ = len(core), len({rule_id.split("/")[0] for rule_id in core})
    ones = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    rules_said = {4: "Forty", 5: "Fifty", 6: "Sixty"}[rules // 10] + (f"-{ones[rules % 10]}" if rules % 10 else "")
    gates_said = ["fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"][gates_ - 14]
    assert f"{rules_said} rules in {gates_said} gates" in (ROOT / "DESIGN.md").read_text(encoding="utf-8")


# -- counts, pack tables and commands -----------------------------------------------------------
#
# Each check below is a function of a page's text, so a planted miss (a row deleted, a count off
# by one) can be shown to fail it without editing the real page.

PACKS = ("trading", "marketing")
#: Each pack page's sections that hold its kinds table, its gate-functions table and its parameters.
SECTIONS = {
    "trading": {"kinds": "## 2. Kinds of work", "gates": "## 6. The gate functions", "params": "## 7. Parameters"},
    "marketing": {"kinds": "## 3. Kinds of work", "gates": "## 8. The results gate", "params": "## 9. Parameters"},
}
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
NUMBER = {**{word: n for n, word in enumerate(ONES)},
          **{TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else ""): n for n in range(20, 100)}}
COUNT = re.compile(r"\b([A-Za-z]+(?:-[a-z]+)?|\d+)(?: core)? rules in ([a-z]+|\d+) gates\b", re.IGNORECASE)
TICKED = re.compile(r"`([^`]+)`")


def counts(owner: str) -> tuple[int, int]:
    """How many rules, and in how many gates, the owner (core or a pack) has."""
    ids = [rule.id for rule in RULES.values() if rule.pack == owner]
    return len(ids), len({rule_id.split("/")[0] for rule_id in ids})


def _number(said: str) -> int | None:
    return int(said) if said.isdigit() else NUMBER.get(said.lower())


def count_problems(text: str, owner: str, *, opening: bool = False) -> list[str]:
    """Every "N rules in M gates" in the text must be its owner's count, and the page's own owner
    must be counted once at least; with `opening`, in the page's opening paragraph. A count in
    brackets after a pack's name, "the trading pack (19 rules in 6 gates)", is that pack's."""
    problems, own = [], 0
    for hit in COUNT.finditer(text):
        named = re.search(r"\b(trading|marketing)\b[^.()]*\($", text[max(0, hit.start() - 40):hit.start()])
        whose = named.group(1) if named else owner
        own += whose == owner
        rules_, gates_ = counts(whose)
        if (_number(hit.group(1)), _number(hit.group(2))) != (rules_, gates_):
            problems.append(f"{hit.group(0)!r}: the {whose} has {rules_} rules in {gates_} gates")
    if not own:
        problems.append(f"no count of the {owner}'s rules and gates")
    if opening:
        head = text.split("\n\n", 2)[1] if text.count("\n\n") >= 1 else text  # the paragraph after the title
        if not COUNT.search(head):
            problems.append("the opening paragraph does not count the rules and gates")
    return problems


def section(text: str, heading: str) -> str:
    """The text from a heading to the next heading of the same level or higher."""
    start = text.index(heading + "\n")
    level = len(heading) - len(heading.lstrip("#"))
    after = re.search(rf"^#{{1,{level}}} ", text[start + len(heading):], re.MULTILINE)
    return text[start:start + len(heading) + (after.start() if after else len(text))]


def table_rows(text: str, first_header: str | None = None) -> list[tuple[str, list[str]]]:
    """Each body row of every table in the text, as (its first cell, every ticked token in the row).
    A row whose first cell is empty continues the row above it. With `first_header`, only the first
    table whose first header cell is that word."""
    found: list[tuple[str, list[str]]] = []
    lines, keep, tables = text.splitlines(), False, 0
    for number, line in enumerate(lines):
        if not line.startswith("|") or re.match(r"^\|[\s|:-]+\|$", line):
            continue
        if number + 1 < len(lines) and re.match(r"^\|[\s|:-]+\|$", lines[number + 1]):
            keep = first_header is None or (line.split("|")[1].strip() == first_header and not tables)
            tables += keep
            continue
        if not keep:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        first = cells[0] or (found[-1][0] if found else "")
        tokens = TICKED.findall(line) + (found[-1][1] if not cells[0] and found else [])
        found.append((first, tokens))
    return found


def _first_tokens(rows: list[tuple[str, list[str]]]) -> set[str]:
    return {token for first, _ in rows for token in TICKED.findall(first)}


def kinds_problems(text: str, name: str) -> list[str]:
    listed = _first_tokens(table_rows(section(text, SECTIONS[name]["kinds"]), "Kind"))
    kinds = set(pack.load(name).kinds)
    return ([f"no row for the kind {kind}" for kind in sorted(kinds - listed)]
            + [f"a row for {kind}, which is not a kind of the pack" for kind in sorted(listed - kinds)])


def gate_problems(text: str, name: str) -> list[str]:
    listed = _first_tokens(table_rows(section(text, SECTIONS[name]["gates"]), "Gate"))
    gates_ = set(pack.load(name).gates)
    return ([f"no row for the gate function {gate}" for gate in sorted(gates_ - listed)]
            + [f"a row for {gate}, which is not a gate function of the pack" for gate in sorted(listed - gates_)])


def _schema_keys(spec: object, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Every leaf key of a pack's schema as its path, at any depth. A `*` (any name) is kept as `*`
    on the way down; a last `*` names no key, so `costs.*.*` is the key `costs.*`, the table itself."""
    if isinstance(spec, dict):
        return {key for inner, value in spec.items() for key in _schema_keys(value, (*path, inner))}
    path = path[:-1] if path[-1:] == ("*",) else path
    return {path} if path else set()


def _key_path(token: str, name: str) -> tuple[str, ...]:
    """`[trading.windows.<name>]` or `rulebooks.<name>.file` as a key path: `<...>` is `*`, and the
    pack's own name is dropped."""
    parts = [part.strip('"') for part in re.findall(r'"[^"]*"|[^.]+', token.strip("[]"))]
    path = tuple("*" if part.startswith("<") else part for part in parts)
    return path[1:] if path[:1] == (name,) else path


def _documented_keys(rows: list[tuple[str, list[str]]], name: str) -> set[tuple[str, ...]]:
    """Each key path a parameters row names: its first cell's table or key, and that table joined
    with each other key the row ticks."""
    found = set()
    for first, tokens in rows:
        for where in TICKED.findall(first):
            base = _key_path(where, name)
            found.add(base)
            found |= {base + _key_path(token, name) for token in tokens if token != where}
    return found


def param_problems(text: str, name: str) -> list[str]:
    """Every parameter of every pack rule has a row that names the rule and the parameter; every key
    of the pack's own table is named; no row names a rule that does not exist."""
    rows = table_rows(section(text, SECTIONS[name]["params"]))
    tokens = [set(found) for _, found in rows]
    problems = [f"no row names {rule.id} with its parameter {param.name}"
                for rule in sorted(RULES.values(), key=lambda rule: rule.id) if rule.pack == name
                for param in rule.params if not any({rule.id, param.name} <= row for row in tokens)]
    named = _documented_keys(rows, name)
    problems += [f"no row names the key {'.'.join(key)} of [{name}]"
                 for key in sorted(_schema_keys(pack.load(name).schema)) if key not in named]
    problems += [f"a row names {token}, which is not a rule" for row in tokens for token in sorted(row)
                 if re.fullmatch(r"[a-z-]+/[a-z-]+", token) and token not in RULES]
    return problems


def commands() -> list[str]:
    from themis.cli import build_parser

    parser = build_parser()
    [sub] = [action for action in parser._actions if action.dest == "command"]
    return sorted(sub.choices)


def command_problems(text: str, names: list[str]) -> list[str]:
    listed = {match.group(1) for first, _ in table_rows(section(text, "## 15. Interfaces"))
              for match in re.finditer(r"`themis ([a-z-]+)", first)}
    return [f"themis {name} is not in DESIGN.md section 15" for name in names if name not in listed]


def page(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# -- seals, records, incidents, the standard and the calibration --------------------------------

RECORD = "results/week-YYYY-WW.json"  # a forward run's weekly record, inside its study
INCIDENTS = {"trading": "## 12. Where the rules come from"}
CALIBRATED = {"trading": "Says yes to noise"}  # the header of each pack page's calibration table


def seal_problems(text: str, name: str = "trading") -> list[str]:
    """Each kind's row in the kinds table ticks every field its seal must state (`process.NEEDS`)."""
    rows = table_rows(section(text, SECTIONS[name]["kinds"]), "Kind")
    found = []
    for kind, needed in sorted(process.NEEDS.items()):
        ticked = {token for first, tokens in rows if kind in TICKED.findall(first) for token in tokens}
        found += [f"the {kind} row does not tick {field}" for field in needed if field not in ticked]
    return found


def record_problems(text: str) -> list[str]:
    """The text ticks the weekly record's path and every top-level key of `forward.WEEK`, outside its
    fenced examples."""
    ticked = set(TICKED.findall(re.sub(r"^```.*?^```[^\n]*$", "", text, flags=re.MULTILINE | re.DOTALL)))
    found = [] if any(token.endswith(RECORD) for token in ticked) else [f"the record's path, {RECORD}, is not ticked"]
    return found + [f"the record's key {key} is not ticked" for key in forward.WEEK if key not in ticked]


def incident_problems(text: str, name: str = "trading") -> list[str]:
    """The section on where the rules come from has a row for each of the pack's rules, whose
    incident is the rule's own `learned` line."""
    cells = {found.group(1): found.group(2) for found in map(ROW.match, section(text, INCIDENTS[name]).splitlines())
             if found}
    found = []
    for rule in sorted(RULES.values(), key=lambda rule: rule.id):
        if rule.pack != name:
            continue
        if rule.id not in cells:
            found.append(f"no incident row for {rule.id}")
        elif cells[rule.id] != rule.learned:
            found.append(f"{rule.id}: the page says {cells[rule.id]!r}, the rule {rule.learned!r}")
    return found


def standard_problems(text: str, standard: str = "themis-trading/1", name: str = "trading") -> list[str]:
    """The standard's paragraph names each rule the standard holds at its level: by its id, ticked, or
    by its gate's word in the prose around the ticks ("the order, prereg ... rules")."""
    start = text.index("**The standard.**")
    paragraph = text[start:text.find("\n\n", start)]
    ticked, words = set(TICKED.findall(paragraph)), set(re.findall(r"[a-z]+", TICKED.sub(" ", paragraph).lower()))
    return [f"the standard's paragraph does not name {rule_id}" for rule_id in sorted(pack.load(name).standards[standard].levels)
            if rule_id not in ticked and rule_id.split("/")[0] not in words]


def calibration_problems(text: str, name: str) -> list[str]:
    """`--gate <name>` appears on the page for each gate function, and its calibration table, where
    the page has one, has a row for each."""
    names = sorted(pack.load(name).gates)
    found = [f"--gate {gate} appears nowhere on the page" for gate in names if f"--gate {gate}" not in text]
    if name in CALIBRATED:
        lines = text.splitlines()
        start = next((number for number, line in enumerate(lines) if line.startswith("|") and CALIBRATED[name] in line),
                     len(lines))
        listed = set()
        for line in lines[start + 2:]:
            if not line.startswith("|"):
                break
            listed |= set(TICKED.findall(line.split("|")[1]))
        found += [f"the calibration table has no row for the gate {gate}" for gate in names if gate not in listed]
    return found


def test_each_kind_row_ticks_every_field_its_seal_must_state() -> None:
    assert seal_problems(page(DOCUMENTS["trading"])) == []


@pytest.mark.parametrize(("path", "heading"), [(DOCUMENTS["trading"], "## 3. Records"),
                                               ("docs/extending.md", "### Adapters")])
def test_the_weekly_record_is_described_key_by_key(path: str, heading: str) -> None:
    assert record_problems(section(page(path), heading)) == []


def test_each_trading_rule_has_its_incident_row() -> None:
    assert incident_problems(page(DOCUMENTS["trading"])) == []


def test_the_standard_paragraph_names_every_rule_it_holds() -> None:
    assert standard_problems(page(DOCUMENTS["trading"])) == []


@pytest.mark.parametrize("name", PACKS)
def test_each_gate_function_is_named_and_calibrated_on_its_page(name: str) -> None:
    assert calibration_problems(page(DOCUMENTS[name]), name) == []


def test_the_readme_counts_the_core_rules_and_gates_as_they_are() -> None:
    assert count_problems(page("README.md"), "core") == []


def test_the_design_counts_every_time_as_the_code_does() -> None:
    assert count_problems(page("DESIGN.md"), "core") == []


@pytest.mark.parametrize("name", PACKS)
def test_each_pack_page_opens_with_its_count_and_every_count_on_it_is_right(name: str) -> None:
    assert count_problems(page(DOCUMENTS[name]), name, opening=True) == []


@pytest.mark.parametrize("name", PACKS)
def test_each_pack_page_has_a_row_for_every_kind(name: str) -> None:
    assert kinds_problems(page(DOCUMENTS[name]), name) == []


@pytest.mark.parametrize("name", PACKS)
def test_each_pack_page_has_a_row_for_every_gate_function(name: str) -> None:
    assert gate_problems(page(DOCUMENTS[name]), name) == []


@pytest.mark.parametrize("name", PACKS)
def test_each_pack_page_lists_every_parameter(name: str) -> None:
    assert param_problems(page(DOCUMENTS[name]), name) == []


def test_every_command_the_help_lists_is_in_the_interfaces_section() -> None:
    assert "act" in commands() and "hooks" in commands()
    assert command_problems(page("DESIGN.md"), commands()) == []


# -- each check fails on a planted miss -------------------------------------------------------


def _off_by_one(text: str, owner: str) -> str:
    rules_, _ = counts(owner)
    hit = next(hit for hit in COUNT.finditer(text) if _number(hit.group(1)) == rules_)
    wrong = str(rules_ + 1) if hit.group(1).isdigit() else next(w for w, n in NUMBER.items() if n == rules_ + 1)
    return text[:hit.start(1)] + (wrong.capitalize() if hit.group(1)[0].isupper() else wrong) + text[hit.end(1):]


def _without_row(text: str, start: str) -> str:
    lines = text.splitlines(keepends=True)
    index = next(number for number, line in enumerate(lines) if line.startswith(start))
    return "".join(lines[:index] + lines[index + 1:])


def test_a_count_off_by_one_in_the_readme_fails() -> None:
    assert count_problems(_off_by_one(page("README.md"), "core"), "core")
    rules_, gates_ = counts("trading")
    planted = page("README.md").replace(f"trading pack ({rules_} rules", f"trading pack ({rules_ - 1} rules")
    assert count_problems(planted, "core") == [
        f"'{rules_ - 1} rules in {gates_} gates': the trading has {rules_} rules in {gates_} gates"]


@pytest.mark.parametrize("name", PACKS)
def test_a_count_off_by_one_on_a_pack_page_fails(name: str) -> None:
    assert count_problems(_off_by_one(page(DOCUMENTS[name]), name), name, opening=True)


def test_a_pack_page_whose_opening_has_no_count_fails() -> None:
    text = page(DOCUMENTS["trading"])
    opening = text.split("\n\n", 2)[1]
    planted = text.replace(opening, COUNT.sub("built", opening), 1)
    assert "the opening paragraph does not count the rules and gates" in count_problems(planted, "trading",
                                                                                         opening=True)


@pytest.mark.parametrize(("name", "row"), [("trading", "| `tune` | Searches"), ("trading", "| `forward` | Trades live"),
                                           ("marketing", "| `asset` |")])
def test_a_kinds_row_deleted_fails(name: str, row: str) -> None:
    assert kinds_problems(_without_row(page(DOCUMENTS[name]), row), name)


@pytest.mark.parametrize(("name", "row"), [("trading", "| `entry` | Is an entry"), ("trading", "| `forward` | Is a live"),
                                           ("marketing", "| `results` |")])
def test_a_gate_function_row_deleted_fails(name: str, row: str) -> None:
    assert gate_problems(_without_row(page(DOCUMENTS[name]), row), name)


@pytest.mark.parametrize(("name", "row"), [("trading", "| | `absent` |"), ("trading", "| `[trading]` | `work` |"),
                                           ("trading", "| `forward/same-dates-control` | `fields` |"),
                                           ("trading", "| | `looks` |"), ("trading", "| `[trading.costs.<name>]` |"),
                                           ("marketing", "| `min_loops` |"), ("marketing", "| `spend.unit` |"),
                                           ("marketing", "| `results.retire.views_below_share_of_baseline` |"),
                                           ("marketing", "| `rulebooks.<name>.applies_to` |")])
def test_a_parameter_row_deleted_fails(name: str, row: str) -> None:
    assert param_problems(_without_row(page(DOCUMENTS[name]), row), name)


def test_a_row_for_a_kind_or_rule_that_does_not_exist_fails() -> None:
    text = page(DOCUMENTS["trading"])
    assert kinds_problems(text.replace("| `data` | Describes", "| `ghost` | Describes"), "trading")
    assert param_problems(text.replace("| `validity/baselines` | `extra`", "| `validity/ghost` | `extra`"), "trading")


def test_a_command_missing_from_the_interfaces_section_fails() -> None:
    assert command_problems(_without_row(page("DESIGN.md"), "| `themis act ACTION"), commands()) == [
        "themis act is not in DESIGN.md section 15"]


def test_a_seal_field_left_out_of_its_kinds_row_fails() -> None:
    text = page(DOCUMENTS["trading"])
    assert seal_problems(text.replace("`min_trades`, `stop_rule`, ", "`min_trades`, ", 1)) == [
        "the forward row does not tick stop_rule"]
    planted = text.replace("The same five: `binding`, `gate`, `nulls`, `windows`, `mde`", "The same five")
    assert seal_problems(planted) == [f"the signal row does not tick {field}" for field in process.TESTED]


def test_a_record_key_or_its_path_left_unticked_fails() -> None:
    records_ = section(page(DOCUMENTS["trading"]), "## 3. Records")
    assert record_problems(records_.replace("`fill_costs`", "fill_costs")) == ["the record's key fill_costs is not ticked"]
    assert record_problems(records_.replace(f"/{RECORD}`", "/week.json`")) == [
        f"the record's path, {RECORD}, is not ticked"]
    adapters = section(page("docs/extending.md"), "### Adapters")
    assert record_problems(adapters.replace("| `range` |", "| range |")) == ["the record's key range is not ticked"]


def test_an_incident_row_deleted_or_reworded_fails() -> None:
    text = page(DOCUMENTS["trading"])
    learned = RULES["forward/risk-line"].learned
    assert incident_problems(_without_row(text, f"| `forward/risk-line` | {learned[:20]}")) == [
        "no incident row for forward/risk-line"]
    planted = text.replace(f"| `forward/no-retune` | {RULES['forward/no-retune'].learned}",
                           "| `forward/no-retune` | Settings were changed.")
    assert incident_problems(planted) == [
        f"forward/no-retune: the page says 'Settings were changed.', the rule {RULES['forward/no-retune'].learned!r}"]


def test_a_rule_the_standard_holds_left_out_of_its_paragraph_fails() -> None:
    text = page(DOCUMENTS["trading"])
    planted = text.replace("`config/locked`, `config/no-silent-weakening`", "`config/no-silent-weakening`", 1)
    assert standard_problems(planted) == ["the standard's paragraph does not name config/locked"]
    planted = text.replace("prereg, trials, holdout", "prereg, holdout", 1)
    assert standard_problems(planted) == ["the standard's paragraph does not name trials/count-feeds-adjustment",
                                          "the standard's paragraph does not name trials/settings-counted"]


def test_a_gate_left_off_its_page_or_its_calibration_table_fails() -> None:
    text = page(DOCUMENTS["trading"])
    assert calibration_problems(_without_row(text, "| `forward` | 0% |"), "trading") == [
        "the calibration table has no row for the gate forward"]
    assert calibration_problems(text.replace("--gate tune", "--gate tuning"), "trading") == [
        "--gate tune appears nowhere on the page"]
    assert calibration_problems(page(DOCUMENTS["marketing"]).replace("--gate results", "--gate result"), "marketing") == [
        "--gate results appears nowhere on the page"]
