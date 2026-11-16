"""The ``themis`` command.

Exit code 0 is PASS, 1 is FAIL, 2 is REFUSE. A call that checked nothing is a REFUSE, because it
must never look like a pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from themis import __version__, configguard, engine, external, proofs, reporters, standards
from themis import manifest as manifests
from themis.rule import PROOFS, RULES
from themis.verdict import Verdict

EXIT_PASS, EXIT_FAIL, EXIT_REFUSE = 0, 1, 2

STARTER = """\
# Themis reads this file strictly: an unknown key is an error, never a silent default.

[project]
name = "{name}"
# packs = ["trading"]            # turn on a field's rules
# standard = "themis-trading/1"  # the floor this project says it holds

# Every rule starts at "warn": it runs and is shown, and cannot fail the run.
# Move a rule to "enforce" when the project is ready for it.
[rules]
"config/valid" = "enforce"

# A check this project already has, run as a rule. Give it a plant, so it is shown able to fail.
# [[checks.external]]
# id = "ext/tests"
# description = "The test suite passes"
# command = ["python3", "-m", "pytest", "-q"]
"""


def _say(text: str) -> None:
    print(text, file=sys.stderr)


def _load(root: Path) -> manifests.Manifest | None:
    """The project's manifest, or None after saying why there is nothing to check."""
    manifest = manifests.load(root)
    if not manifest.present:
        _say(f"themis: there is no {manifests.MANIFEST_FILE} in {root}. Nothing was checked. Run `themis init`.")
        return None
    return manifest


def _emit(args: argparse.Namespace, report: engine.Report) -> None:
    wanted = args.reporter or ["terminal"]
    to_stdout = [name for name in wanted if ":" not in name]
    if len(to_stdout) > 1:
        raise SystemExit("themis: only one reporter can write to the screen; give the others a file, as json:out.json")
    for item in wanted:
        name, _, target = item.partition(":")
        if name not in reporters.REPORTERS:
            raise SystemExit(f"themis: no reporter named {name!r}; choose from {', '.join(reporters.REPORTERS)}")
        text = reporters.REPORTERS[name](report)
        if target:
            path = Path(target) if Path(target).is_absolute() else Path(args.root) / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return EXIT_REFUSE
    changed = None
    if args.changed:
        from themis.gitlog import Git

        git = Git(root)
        main = git.main_ref(manifest.project.get("main"))
        changed = git.changed_against(main) if main else None
    report = engine.run(manifest, changed=changed, only=set(args.rules) or None)
    _emit(args, report)
    return report.exit_code


def command_describe(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return EXIT_REFUSE
    if manifest.problems:
        _say(f"themis: {manifests.MANIFEST_FILE} is not valid, so nothing can be described:")
        for problem in manifest.problems:
            _say(f"  {problem}")
        return EXIT_REFUSE
    lines = [f"themis describe · {manifest.name}", ""]
    packs = ", ".join(loaded.name for loaded in manifest.packs) or "none"
    lines.append(f" packs: {packs}")
    standard = standards.declared(manifest)
    if standard:
        found = standards.deviations(manifest, standard)
        lines.append(f" standard: {standard.id} — " + ("conforming" if not found else f"deviating in {len(found)} place(s)"))
        lines += [f"   below   {deviation.rule:<32} {deviation.what}" for deviation in found]
    else:
        lines.append(" standard: none declared")
    unproven, gate = 0, None
    for rule in sorted(manifest.active_rules(), key=lambda rule: rule.id):
        if rule.gate != gate:
            gate = rule.gate
            lines += ["", f" {gate}"]
        result = engine.run_rule(rule, manifest) if args.status else None
        setting = manifest.setting(rule)
        standing = proofs.standing(rule.id)
        configured = not [name for name in rule.requires if setting.params.get(name) in (None, "", [], {})]
        state = setting.level if configured else "not configured"
        if result is not None and result.status == "not configured":
            state = "not configured"
        if standing != "proven" or state in ("off", "not configured"):
            unproven += 1
        lines.append(f"   {rule.id:<34} {state:<15} {standing}")
        lines.append(f"       {rule.promise}")
    if manifest.external:
        lines += ["", " ext"]
        for table in manifest.external:
            standing = proofs.external_standing(table)
            unproven += standing != "proven"
            lines.append(f"   {table['id']:<34} {table.get('level', 'enforce'):<15} {standing}")
            lines.append(f"       {table['description']}  ·  runs: {' '.join(table['command'])}")
    lines += ["", f" {unproven} rule(s) are off, not configured or unproven: their silence is not a pass"]
    print("\n".join(lines))
    return EXIT_PASS


def command_prove(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    manifest = manifests.load(root)
    if manifest.present and manifest.problems:
        _say(f"themis: {manifests.MANIFEST_FILE} is not valid, so nothing can be proven:")
        for problem in manifest.problems:
            _say(f"  {problem}")
        return EXIT_REFUSE
    wanted = set(args.rules) or None
    active = {rule.id for rule in manifest.active_rules()}
    outcomes = proofs.run_native((wanted & active) if wanted else active)
    if manifest.present:
        outcomes += [outcome for outcome in proofs.run_external(manifest) if not wanted or outcome.rule in wanted]
    if not outcomes:
        _say("themis: no proof ran. Nothing was proven.")
        return EXIT_REFUSE
    rule = None
    for outcome in outcomes:
        if outcome.rule != rule:
            rule = outcome.rule
            print(f" {rule}")
        actual = outcome.actual.value if outcome.actual else "none"
        print(f"   {'✓' if outcome.held else '✗'} {outcome.name}  (expected {outcome.expect.value}, got {actual})")
        if not outcome.held and outcome.detail:
            print(f"       {outcome.detail}")
    failed = [outcome for outcome in outcomes if not outcome.held]
    lacking = sorted(rule_id for rule_id in active if proofs.standing(rule_id) != "proven" and (not wanted or rule_id in wanted))
    lacking += [table["id"] for table in manifest.external if proofs.external_standing(table) != "proven"
                and (not wanted or table["id"] in wanted)]
    print(f"\n {len(outcomes) - len(failed)} of {len(outcomes)} proofs held")
    for name in lacking:
        print(f" unproven: {name}")
    print("FAIL" if failed else "PASS")
    return EXIT_FAIL if failed else EXIT_PASS


def command_explain(args: argparse.Namespace) -> int:
    manifests.load(Path(args.root).resolve())  # loads the gates and this project's packs
    rule = RULES.get(args.rule)
    if rule is None:
        _say(f"themis: no rule named {args.rule!r}. `themis describe` lists them.")
        return EXIT_REFUSE
    lines = [rule.id, f"  {rule.promise}", ""]
    if rule.learned:
        lines += [f"  Why it exists: {rule.learned}", ""]
    if rule.params:
        lines.append("  Parameters:")
        for param in rule.params:
            need = " (required)" if param.name in rule.requires else ""
            way = f", stricter when {param.stricter}" if param.stricter else ""
            lines.append(f"    {param.name}{need}: {param.help or 'no description'} [default {param.default!r}{way}]")
        lines.append("")
    lines.append("  Proofs:")
    lines += [f"    expects {proof.expect.value:<6} {proof.name}" for proof in PROOFS.get(rule.id, [])] or ["    none"]
    print("\n".join(lines))
    return EXIT_PASS


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    path = root / manifests.MANIFEST_FILE
    if path.exists():
        print(f"{manifests.MANIFEST_FILE} already exists; it was left as it is.")
        return EXIT_PASS
    path.write_text(STARTER.format(name=root.name), encoding="utf-8")
    local = root / ".themis"
    local.mkdir(exist_ok=True)
    (local / ".gitignore").write_text("*\n", encoding="utf-8")
    print(f"Wrote {manifests.MANIFEST_FILE}. Next: `themis describe`, then `themis check`.")
    return EXIT_PASS


def command_config(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return EXIT_REFUSE
    if manifest.problems:
        _say(f"themis: {manifests.MANIFEST_FILE} is not valid:")
        for problem in manifest.problems:
            _say(f"  {problem}")
        return EXIT_REFUSE
    if args.action == "lock":
        path = configguard.write_lock(manifest)
        print(f"Wrote {path.name}. Commit it with the manifest.")
        return EXIT_PASS
    from themis.gitlog import Git

    git = Git(root)
    against = args.against or git.main_ref(manifest.project.get("main"))
    if against is None:
        _say("themis: there is no main line to compare the manifest with.")
        return EXIT_REFUSE
    old = configguard.parse(git.show(against, manifests.MANIFEST_FILE))
    if old is None:
        print(f"{manifests.MANIFEST_FILE} is not on {against}: every setting is new, so nothing is weakened.")
        return EXIT_PASS
    changes = configguard.classify(old, manifest.raw)
    for kind in ("weakening", "tightening", "neutral"):
        found = [change for change in changes if change.kind == kind]
        if found:
            print(f" {kind}:")
            for change in found:
                print(f"   {change.what}")
    weakened = any(change.kind == "weakening" for change in changes)
    print("No change." if not changes else ("Weakened: this needs the owner's grant." if weakened else "Tightened only."))
    return EXIT_FAIL if weakened else EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="themis", description="Guardrails as code for work done by AI agents.")
    parser.add_argument("--version", action="version", version=f"themis {__version__}")
    commands = parser.add_subparsers(dest="command")

    def add(name: str, handler, help: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help, description=help)
        sub.add_argument("--root", default=".", help="the repository to work on (default: this folder)")
        sub.set_defaults(handler=handler)
        return sub

    check = add("check", command_check, "Run the rules on this repository.")
    check.add_argument("rules", nargs="*", help="only these rule ids")
    check.add_argument("--changed", action="store_true", help="skip external checks whose paths did not change")
    check.add_argument("--reporter", action="append", help="terminal, compact, json or sarif; add :FILE to write a file")

    describe = add("describe", command_describe, "List every gate, rule and proof, and what is not in force.")
    describe.add_argument("--status", action="store_true", help="also run each rule, to show which are not configured")

    prove = add("prove", command_prove, "Show that each rule and each external check can fail.")
    prove.add_argument("rules", nargs="*", help="only these rule ids")

    explain = add("explain", command_explain, "Explain one rule: its promise, why it exists, its parameters.")
    explain.add_argument("rule")

    add("init", command_init, "Write a starter themis.toml.")

    config = add("config", command_config, "Show what a manifest change weakens, or refresh the lock.")
    config.add_argument("action", choices=["diff", "lock"])
    config.add_argument("--against", help="the commit to compare with (default: the main line)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help(sys.stderr)
        _say("\nthemis: no command was given. Nothing was checked.")
        return EXIT_REFUSE
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
