"""The ``themis`` command.

Exit code 0 is PASS, 1 is FAIL, 2 is REFUSE. A call that checked nothing is a REFUSE, because it
must never look like a pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from themis import __version__, configguard, engine, proofs, reporters, standards
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


def _catalogue(manifest: manifests.Manifest | None) -> str:
    """Every rule of the core and of every pack Themis can find, as Markdown tables."""
    import pkgutil
    from importlib import metadata

    from themis import gates, pack, packs

    gates.load_all()
    names = {found.name for found in pkgutil.iter_modules(packs.__path__) if found.ispkg}
    names |= {entry.name for entry in metadata.entry_points(group="themis.packs")}
    for name in sorted(names):
        try:
            pack.load(name)
        except pack.PackError:
            continue  # a pack that cannot load has no rules to list; `themis doctor` names it
    usable = manifest if manifest is not None and manifest.present and not manifest.problems else None
    active = {rule.id for rule in usable.active_rules()} if usable else set()
    owners = sorted({rule.pack for rule in RULES.values()}, key=lambda owner: (owner != "core", owner))
    lines = [
        "# Themis rule catalogue", "",
        f"Written by `themis describe --markdown` (themis {__version__}), from the rules themselves: every rule of "
        "the core and of each pack, with its gate, its promise, its level and the proofs it carries.", "",
        "Level is " + (f"the one project {usable.name} sets; `pack off` marks a pack it has not turned on."
                       if usable else "the default: a rule a project does not name runs at `warn`."), "",
    ]
    for owner in owners:
        rules = sorted((rule for rule in RULES.values() if rule.pack == owner), key=lambda rule: rule.id)
        gate_names = {rule.gate for rule in rules}
        lines += [f"## {owner}", "", f"{len(rules)} rules in {len(gate_names)} gates.", "",
                  "| Rule | Gate | Promise | Level | Proofs |", "| --- | --- | --- | --- | --- |"]
        for rule in rules:
            level = (usable.setting(rule).level if rule.id in active else "pack off") if usable else "warn"
            promise = rule.promise.replace("|", "\\|")
            lines.append(f"| `{rule.id}` | {rule.gate} | {promise} | {level} | {len(PROOFS.get(rule.id, []))} |")
        lines.append("")
    return "\n".join(lines)


def command_describe(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.markdown:
        found = manifests.load(root)
        print(_catalogue(found), end="")
        return EXIT_PASS
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
        # A rule can learn it is not configured only by running: a table it reads may be missing. So
        # each rule runs, with or without --status, and both count the same.
        result = engine.run_rule(rule, manifest)
        standing = proofs.standing(rule.id)
        state = "not configured" if result.status == "not configured" else manifest.setting(rule).level
        if standing != "proven" or state in ("off", "not configured"):
            unproven += 1
        now = f"  now: {result.verdict.value}" if args.status and result.verdict is not None else ""
        lines.append(f"   {rule.id:<34} {state:<15} {standing}{now}")
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
    from themis.pack import kit

    short = [(loaded.name, problem) for loaded in manifest.packs for problem in kit.problems(loaded)]
    lacking = sorted(rule_id for rule_id in active if proofs.standing(rule_id) != "proven" and (not wanted or rule_id in wanted))
    lacking += [table["id"] for table in manifest.external if proofs.external_standing(table) != "proven"
                and (not wanted or table["id"] in wanted)]
    print(f"\n {len(outcomes) - len(failed)} of {len(outcomes)} proofs held")
    for name in lacking:
        print(f" unproven: {name}")
    for name, problem in short:
        print(f" the pack {name} falls short of the pack contract: {problem}")
    print("FAIL" if failed or short else "PASS")
    return EXIT_FAIL if failed or short else EXIT_PASS


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


def _ready(args: argparse.Namespace) -> tuple[Path, manifests.Manifest] | None:
    """The root and a usable manifest, or None after saying why not."""
    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return None
    if manifest.problems:
        _say(f"themis: {manifests.MANIFEST_FILE} is not valid:")
        for problem in manifest.problems:
            _say(f"  {problem}")
        return None
    return root, manifest


def _param(manifest: manifests.Manifest, rule_id: str, name: str) -> object:
    rule = RULES.get(rule_id)
    return manifest.setting(rule).params.get(name) if rule else None


def _work_patterns(manifest: manifests.Manifest) -> list[str]:
    """Where this project keeps its units of work, one pattern or several: the first place that says so."""
    from themis import work

    for rule_id in ("order/logged-first", "order/sealed-first", "claims/receipt", "ledger/complete"):
        found = work.patterns(_param(manifest, rule_id, "work"))  # type: ignore[arg-type]
        if found:
            return found
    for loaded in manifest.packs:
        found = work.patterns(manifest.table(loaded.name).get("work"))
        if found:
            return found
    return []


def _unit(root: Path, manifest: manifests.Manifest, name: str) -> str | None:
    """A unit's folder, from its path or its folder name. None, after saying why, when unknown."""
    from themis import work
    from themis.gitlog import Git

    patterns = _work_patterns(manifest)
    if not patterns:
        _say("themis: this project has not said where its work lives. Set `work` for a pack or for order/logged-first.")
        return None
    units = work.units(Git(root).all_files(), patterns)
    wanted = name.strip("/")
    found = [unit for unit in units if unit == wanted] or [unit for unit in units if unit.rsplit("/", 1)[-1] == wanted]
    if len(found) != 1:
        _say(f"themis: {name!r} names {len(found)} unit(s) of work under {', '.join(patterns)}.")
        return None
    return found[0]


def command_grant(args: argparse.Namespace) -> int:
    """The owner's yes to one action. The shipped hook stops this command for the owner's click."""
    from themis import grants

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    target = args.target or (configguard.effective_hash(manifest) if args.action == "config" else None)
    if not target:
        _say("themis: name what the grant is for: `themis grant ACTION TARGET --reason ...`.")
        return EXIT_REFUSE
    try:
        path = grants.new_grant(root, args.action, target, granted_by=args.by, reason=args.reason,
                                ceiling=args.ceiling, unit=args.unit)
    except ValueError as error:
        _say(f"themis: the grant was not written: {error}")
        return EXIT_REFUSE
    print(f"Wrote {path.relative_to(root)}. Commit it: a grant is visible in review, and is used once.")
    return EXIT_PASS


def command_attest(args: argparse.Namespace) -> int:
    from themis import grants

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, _ = ready
    try:
        path = grants.new_attestation(root, args.subject, args.row, args.judge, args.by, note=args.note,
                                      author=args.author, shown=args.shown or None)
    except ValueError as error:
        _say(f"themis: the attestation was not written: {error}")
        return EXIT_REFUSE
    print(f"Wrote {path.relative_to(root)}. It names the file's hash: judge the file again if it changes.")
    return EXIT_PASS


def command_cite(args: argparse.Namespace) -> int:
    from themis import claims, work
    from themis.gitlog import Git

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    patterns = _work_patterns(manifest)
    if not patterns:
        _say("themis: this project has not said where its work lives, so no record can be cited.")
        return EXIT_REFUSE
    metrics = str(_param(manifest, "claims/receipt", "metrics") or "results/metrics.json")
    try:
        print(claims.cite(root, work.units(Git(root).all_files(), patterns), args.work, args.key, metrics, args.decimals))
    except ValueError as error:
        _say(f"themis: nothing to cite: {error}")
        return EXIT_REFUSE
    return EXIT_PASS


def command_checkpoint(args: argparse.Namespace) -> int:
    from themis import checkpoint

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    path = checkpoint.refresh(root, manifest)
    print(f"Refreshed {path.relative_to(root)}. The first two headline lines are facts; write Changed and Next.")
    return EXIT_PASS


def command_new(args: argparse.Namespace) -> int:
    """Log a unit of work before it runs: a ledger record, and the folder the work will live in."""
    import datetime as dt

    from themis import grants, records

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    patterns = _work_patterns(manifest)
    home = records.home_of(manifest, "ledger")
    folder = home.rsplit("/", 1)[0] if "/" in home else "."
    if args.under:
        if args.under.strip("/") not in patterns:
            _say(f"themis: {args.under} is not one of the places work lives: {', '.join(patterns) or 'none is set'}.")
            return EXIT_REFUSE
        patterns = [args.under.strip("/")]
    choices = [pattern for pattern in patterns if pattern.count("*") == 1]
    if len(choices) > 1:
        _say(f"themis: work lives in several places; name one with --under: {', '.join(choices)}.")
        return EXIT_REFUSE
    if not choices or "*" in folder:
        _say("themis: set where work lives (one * in the pattern) and where the ledger is, then log the unit again.")
        return EXIT_REFUSE
    pattern = choices[0]
    today = dt.date.today().isoformat()
    name = f"{today}_{grants.slug(args.name)}"
    unit = pattern.replace("*", name)
    path = root / folder / f"{name}.toml"
    if path.exists():
        _say(f"themis: {path.relative_to(root)} already exists; a ledger record is never replaced.")
        return EXIT_FAIL
    record = {"work": unit, "question": args.question, "state": "promised", "logged": today, "variants": args.variants}
    if args.kind:
        record["kind"] = args.kind
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(grants.to_toml(record), encoding="utf-8")
    print(f"Logged {path.relative_to(root)}. The work lives in {unit}/. Seal its plan before anything runs.")
    return EXIT_PASS


def command_run(args: argparse.Namespace) -> int:
    """Run a unit's work under guard: a clean tree, a seal already on the main line, then a receipt."""
    import hashlib
    import json
    import os
    import subprocess

    from themis import paths, receipts, work
    from themis.gitlog import Git

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    unit = _unit(root, manifest, args.work)
    command = list(args.command)
    if unit is None or not command:
        if unit is not None:
            _say("themis: give the command to run after `--`.")
        return EXIT_REFUSE
    git = Git(root)
    main = git.main_ref(manifest.project.get("main"))
    dirty = git.dirty()
    if main is None or dirty:
        _say("themis: REFUSE. " + ("There is no main line." if main is None else
                                   f"The tree is dirty ({', '.join(dirty[:4])}); a result made on it pins nothing."))
        return EXIT_REFUSE
    seals = _param(manifest, "order/sealed-first", "seal") or []
    sealed = [name for name in work.inside(unit, git.all_files(), seals) if name in git.arrivals(main)]
    if seals and not sealed:
        _say(f"themis: REFUSE. The plan of {unit} is not on the main line yet. Merge its seal first, on its own.")
        return EXIT_REFUSE
    commit, tree = git.head(), git.tree_id()
    try:
        done = subprocess.run(command, cwd=root, check=False)  # noqa: S603 - the project's own command
    except (FileNotFoundError, PermissionError) as error:
        _say(f"themis: REFUSE. `{command[0]}` could not be started ({error.__class__.__name__}).")
        return EXIT_REFUSE
    at = receipts.now()
    receipt = {"work": unit, "command": command, "exit_status": done.returncode, "at": at, "commit": commit,
               "tree": tree, "role": os.environ.get("THEMIS_ROLE")}
    rule_files = _param(manifest, "scope/rules-current", "rule_files")
    if rule_files:
        from themis.gates.scope import rules_hash

        read = sorted({name for pattern in rule_files for name in paths.select(git.all_files(), pattern)})
        receipt["rules_hash"] = rules_hash(root, read)
    name = f"{work.file_name(unit)}-{at.replace(':', '').replace('-', '')[:15]}"
    receipts.write(root, "run", name, receipt, committed=True)
    if args.input and done.returncode == 0:
        inputs = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in args.input}
        target = root / unit / "results" / "provenance.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"commit": commit, "clean": True, "inputs": inputs, "at": at}, indent=2) + "\n",
                          encoding="utf-8")
    print(f"themis: the command exited {done.returncode}. Receipt: receipts/run/{name}.json")
    return EXIT_PASS if done.returncode == 0 else EXIT_FAIL


def _stored_work(path: Path) -> str | None:
    """The work a stored decision names, or None when there is no readable decision there."""
    import json

    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(found.get("work", "")).strip("/") if isinstance(found, dict) else None


def command_decide(args: argparse.Namespace) -> int:
    """Ask a gate function for the decision on a unit's numbers, and store what it says."""
    import json

    from themis import receipts, work

    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    builder = next((loaded.inputs[args.gate] for loaded in manifest.packs if args.gate in loaded.inputs), None)
    # A gate with a builder decides about a subject that is not one folder of work, such as a series.
    unit = args.work.strip("/") if builder else _unit(root, manifest, args.work)
    if unit is None:
        return EXIT_REFUSE
    record: dict[str, object] = {"work": unit, "gate": args.gate, "decided_at": receipts.now()}
    built = None
    if builder and args.by != "owner":
        try:
            built = builder(root, manifest, unit, args.rival)
        except ValueError as error:
            _say(f"themis: REFUSE. The numbers could not be built from the records: {error}")
            return EXIT_REFUSE
        inputs = root / "decision-inputs" / f"{unit.replace('/', '-')}.json"
        inputs.parent.mkdir(parents=True, exist_ok=True)
        inputs.write_text(json.dumps(built, indent=2) + "\n", encoding="utf-8")
        record["inputs"] = inputs.relative_to(root).as_posix()
    if args.by == "owner":
        if not (args.decision and args.verdict and args.reason):
            _say("themis: the owner's own call needs --decision, --verdict and --reason.")
            return EXIT_REFUSE
        record.update(decision=args.decision, verdict=args.verdict, reason=args.reason, by="owner", gate_version="owner")
    else:
        found = next(((loaded, loaded.gates[args.gate]) for loaded in manifest.packs if args.gate in loaded.gates), None)
        if found is None:
            _say(f"themis: no pack this project turned on has a gate named {args.gate!r}.")
            return EXIT_REFUSE
        loaded, gate = found
        metrics_path = root / unit / str(_param(manifest, "decision/issued-by-gate", "metrics") or "results/metrics.json")
        try:
            answer = gate(built if built is not None else json.loads(metrics_path.read_text(encoding="utf-8")))
        except Exception as error:  # noqa: BLE001 - a gate that cannot run has decided nothing
            _say(f"themis: REFUSE. The gate could not decide: {error.__class__.__name__}: {error}")
            return EXIT_REFUSE
        record.update(decision=answer["decision"], verdict=answer["verdict"], gate_version=loaded.gate_versions.get(args.gate, "1"))
        record.update({key: answer[key] for key in ("enough_evidence", "reason", "numbers", "level") if key in answer})
    # Named by the unit's whole path: two units that share a folder name keep a decision each.
    path = root / "decisions" / f"{work.file_name(unit)}.json"
    held = _stored_work(path)
    if held is not None and held != unit:
        _say(f"themis: REFUSE. {path.relative_to(root)} holds the decision of {held}, not of {unit}.")
        return EXIT_REFUSE
    earlier = root / "decisions" / f"{unit.rsplit('/', 1)[-1]}.json"
    if earlier != path and _stored_work(earlier) == unit:
        earlier.replace(path)  # a decision stored under 0.1.0's folder-name file moves to the unit's own name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    verdict = Verdict(str(record["verdict"]))
    print(f"{verdict.value.upper()}: {record['decision']}. {record.get('reason', '')}".rstrip())
    print(f"Stored in {path.relative_to(root)}.")
    return {Verdict.PASS: EXIT_PASS, Verdict.FAIL: EXIT_FAIL, Verdict.REFUSE: EXIT_REFUSE}[verdict]


def command_report(args: argparse.Namespace) -> int:
    ready = _ready(args)
    if ready is None:
        return EXIT_REFUSE
    root, manifest = ready
    unit = _unit(root, manifest, args.work)
    if unit is None:
        return EXIT_REFUSE
    builders = [loaded for loaded in manifest.packs if loaded.report is not None]
    if not builders:
        _say("themis: no pack this project turned on builds a report.")
        return EXIT_REFUSE
    try:
        written = [path for loaded in builders for path in loaded.report(root, manifest, unit)]
    except (ValueError, OSError) as error:
        _say(f"themis: REFUSE. The report could not be built: {error}")
        return EXIT_REFUSE
    for path in written:
        print(f"Wrote {path.relative_to(root)}")
    return EXIT_PASS if written else EXIT_REFUSE


def command_hooks(args: argparse.Namespace) -> int:
    from themis import hooks

    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return EXIT_REFUSE
    if args.git:
        folder = args.path or hooks.GIT_HOOKS
        try:
            written = hooks.install_git(root, folder, args.run_with, force=args.force)
        except (ValueError, OSError) as error:
            _say(f"themis: the git hooks could not be installed: {error}")
            return EXIT_REFUSE
        names = ", ".join(path.relative_to(root.resolve()).as_posix() for path in written)
        print(f"Installed the git hooks: {names}; core.hooksPath is {folder}. Commit them.")
        if manifest.table("agents").get("git_hooks") != folder:
            print(f'Declare them under [agents] as git_hooks = "{folder}", so agents/hooks-installed checks them.')
        return EXIT_PASS
    try:
        path = hooks.install(root, args.run_with)
    except (ValueError, OSError) as error:
        _say(f"themis: the hooks could not be installed: {error}")
        return EXIT_REFUSE
    print(f"Installed the hooks in {path.relative_to(root)}. They take effect in the next session.")
    return EXIT_PASS


def command_hook(args: argparse.Namespace) -> int:
    """Called by the agent host, with the event as JSON on standard input."""
    import json
    import os

    from themis import hooks

    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    # The project is --root, else the host's project folder; the payload's cwd only places relative paths.
    root = hooks.project_root(args.root, os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd"))
    if args.event == "pretool":
        answer = hooks.pretool(payload, root)
        if answer:
            print(json.dumps(answer))
        return EXIT_PASS
    if args.event == "start":
        hooks.start(payload, root)
        return EXIT_PASS
    code, for_agent, for_owner = hooks.stop(payload, root)
    if code == 2:
        _say(for_agent)
        return 2
    if for_owner:
        print(json.dumps({"systemMessage": for_owner}))
    return EXIT_PASS


def command_render(args: argparse.Namespace) -> int:
    from themis import render

    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return EXIT_REFUSE
    if manifest.problems:
        _say(f"themis: {manifests.MANIFEST_FILE} is not valid, so nothing can be written.")
        return EXIT_REFUSE
    pages = dict(manifest.views)
    instructions = manifest.table("agents").get("instructions")
    if instructions:
        pages[instructions] = "rules"
    if not pages:
        _say("themis: no generated page is declared. List them under [views], or name the instructions under [agents].")
        return EXIT_REFUSE
    stale = []
    for path, name in sorted(pages.items()):
        wanted = render.expected(root, manifest, path, name)
        if wanted is None:
            _say(f"themis: there is no view named {name!r} (for {path}).")
            return EXIT_REFUSE
        current = (root / path).read_text(encoding="utf-8") if (root / path).is_file() else None
        if current != wanted:
            stale.append(path)
            if not args.check:
                render.write(root, manifest, path, name)
    if args.check:
        for path in stale:
            print(f"stale: {path}")
        print("FAIL" if stale else "PASS")
        return EXIT_FAIL if stale else EXIT_PASS
    print(f"Wrote {len(stale)} page(s); {len(pages) - len(stale)} already current.")
    return EXIT_PASS


def command_calibrate(args: argparse.Namespace) -> int:
    from themis import receipts
    from themis.pack import kit

    root = Path(args.root).resolve()
    manifest = _load(root)
    if manifest is None:
        return EXIT_REFUSE
    rule = RULES.get("decision/calibrated")
    params = manifest.setting(rule).params if rule else {}
    most, least = params.get("max_false_alarm", 0.1), params.get("min_power", 0.8)
    measured, failed = 0, 0
    for loaded in manifest.packs:
        for gate in sorted(loaded.gates):
            if args.gates and gate not in args.gates:
                continue
            found = kit.calibrate(loaded, gate)
            alarm, power = found["false_alarm_rate"], found["power"]
            if alarm is None or power is None:
                print(f" ? {loaded.name}/{gate}: no noise case or no planted case; it cannot be calibrated")
                failed += 1
                continue
            measured += 1
            good = alarm <= most and power >= least
            failed += not good
            receipts.write(root, "calibration", f"{loaded.name}-{gate}", {**found, "at": receipts.now()}, committed=True)
            print(f" {'✓' if good else '✗'} {loaded.name}/{gate} v{found['gate_version']}: "
                  f"says yes to noise {alarm:.1%} of the time (limit {most:.0%}); "
                  f"finds a planted effect {power:.1%} of the time (floor {least:.0%})")
    if not measured and not failed:
        _say("themis: no gate function to calibrate. Turn a pack on under [project].")
        return EXIT_REFUSE
    print("FAIL" if failed else "PASS — the receipts are in receipts/calibration/; commit them.")
    return EXIT_FAIL if failed else EXIT_PASS


def command_doctor(args: argparse.Namespace) -> int:
    from themis import gates, hooks, packs
    from themis.gitlog import Git

    root = Path(args.root).resolve()
    manifest = manifests.load(root)
    found = [f"a gate module failed to load: {name}: {why}" for name, why in sorted(gates.BROKEN.items())]
    found += [f"a pack module failed to load: {name}: {why}" for name, why in sorted(packs.BROKEN.items())]
    if not manifest.present:
        found.append(f"there is no {manifests.MANIFEST_FILE}: run `themis init`")
    found += [f"{manifests.MANIFEST_FILE}: {problem}" for problem in manifest.problems]
    git = Git(root)
    if not git.is_repo:
        found.append("this folder is not a git repository of its own; rules that read history will refuse")
    elif git.main_ref(manifest.project.get("main")) is None:
        found.append("there is no main line yet; rules that compare with it will refuse")
    if manifest.present and not manifest.problems and manifest.table("agents").get("host"):
        absent = hooks.missing(root)
        found += ["the host's settings file cannot be read"] if absent is None else [
            f"the {event} hook is not installed: run `themis hooks install`" for event in absent]
    if manifest.present and not manifest.problems and manifest.table("agents").get("git_hooks") and git.is_repo:
        found += [f"{what}: run `themis hooks install --git`"
                  for what, _ in hooks.git_missing(root, manifest.table("agents")["git_hooks"])]
    for line in found:
        print(f" - {line}")
    print("Nothing is wrong with the setup." if not found else f"{len(found)} thing(s) to put right.")
    return EXIT_REFUSE if found else EXIT_PASS


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
    describe.add_argument("--status", action="store_true", help="also show what each rule finds on this repository now")
    describe.add_argument("--markdown", action="store_true",
                          help="print the full catalogue, every core and pack rule, as Markdown tables")

    prove = add("prove", command_prove, "Show that each rule and each external check can fail.")
    prove.add_argument("rules", nargs="*", help="only these rule ids")

    explain = add("explain", command_explain, "Explain one rule: its promise, why it exists, its parameters.")
    explain.add_argument("rule")

    add("init", command_init, "Write a starter themis.toml.")

    config = add("config", command_config, "Show what a manifest change weakens, or refresh the lock.")
    config.add_argument("action", choices=["diff", "lock"])
    config.add_argument("--against", help="the commit to compare with (default: the main line)")

    install = add("hooks", command_hooks, "Install the agent hooks into the host's settings, or with --git the git hooks.")
    install.add_argument("action", choices=["install"])
    install.add_argument("--run-with",
                         help="how the hooks start themis (default: `uv run --frozen --quiet themis` in a uv project)")
    install.add_argument("--git", action="store_true",
                         help="write the git hooks (pre-commit: check --changed; pre-push: check) and set core.hooksPath")
    install.add_argument("--path", help="with --git: the folder for the git hooks (default: .githooks)")
    install.add_argument("--force", action="store_true", help="with --git: replace a different hook already there")

    hook = add("hook", command_hook, "Answer one hook event from the agent host. Not for people.")
    hook.add_argument("event", choices=["pretool", "start", "stop"])
    hook.set_defaults(root=None)  # unset: the host's project folder, then the payload's folder, decide

    render = add("render", command_render, "Write the generated pages from the records and the rules.")
    render.add_argument("--check", action="store_true", help="write nothing; fail when a page is stale")

    calibrate = add("calibrate", command_calibrate, "Measure each gate function on noise and on a planted effect.")
    calibrate.add_argument("gates", nargs="*", help="only these gate functions")

    add("doctor", command_doctor, "Say what is wrong with this project's setup.")

    grant = add("grant", command_grant, "The owner's yes to one action that cannot be taken back.")
    grant.add_argument("action", help="what is allowed, such as config, holdout, spend or publish")
    grant.add_argument("target", nargs="?", help="what it applies to (for config: this exact configuration)")
    grant.add_argument("--reason", required=True)
    grant.add_argument("--ceiling", type=float, help="the most that may be spent")
    grant.add_argument("--unit", help="the ceiling's unit")
    grant.add_argument("--by", default="owner")

    attest = add("attest", command_attest, "Record that someone judged a file, and the file's hash.")
    attest.add_argument("subject", help="the file that was judged")
    attest.add_argument("row", help="the check that was judged, such as a checklist row's id")
    attest.add_argument("--judge", required=True, help="the judge the row names")
    attest.add_argument("--by", required=True, help="who did the judging")
    attest.add_argument("--note")
    attest.add_argument("--author", help="who made the file, for a second reader's attestation")
    attest.add_argument("--shown", action="append", help="what the reader was given (repeatable)")

    cite = add("cite", command_cite, "Print a number with the tag that names its record, ready to paste.")
    cite.add_argument("work")
    cite.add_argument("key")
    cite.add_argument("--decimals", type=int)

    add("checkpoint", command_checkpoint, "Refresh the facts in the checkpoint: the commit and the suite receipt.")

    new = add("new", command_new, "Log a unit of work before it runs.")
    new.add_argument("name")
    new.add_argument("--question", required=True, help="what the work is meant to find out")
    new.add_argument("--kind")
    new.add_argument("--variants", type=int, default=1, help="how many variants this unit covers")
    new.add_argument("--under", help="which work pattern the unit goes under, when work names several")

    run = add("run", command_run, "Run a unit's work under guard, and write the run's receipt.")
    run.add_argument("work")
    run.add_argument("--input", action="append", help="a file the work reads; its hash goes in the provenance (repeatable)")
    run.set_defaults(command=[])  # everything after `--`; main() splits it off before the options are read

    decide = add("decide", command_decide, "Ask a gate function for the decision on a unit's numbers.")
    decide.add_argument("work")
    decide.add_argument("--gate", required=True)
    decide.add_argument("--by", choices=["gate", "owner"], default="gate")
    decide.add_argument("--rival", help="what the subject is compared with, for a gate that compares two")
    decide.add_argument("--decision")
    decide.add_argument("--verdict", choices=["pass", "fail", "refuse"])
    decide.add_argument("--reason")

    report = add("report", command_report, "Build a unit's report from its records.")
    report.add_argument("work")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # `themis run WORK [options] -- COMMAND...`: what follows `--` is the command, never an option.
    after = argv[argv.index("--") + 1:] if "--" in argv else []
    args = parser.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    if after:
        args.command = after
    if not getattr(args, "handler", None):
        parser.print_help(sys.stderr)
        _say("\nthemis: no command was given. Nothing was checked.")
        return EXIT_REFUSE
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
