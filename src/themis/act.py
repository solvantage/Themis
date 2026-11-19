"""`themis act`: a guarded command runs only with the owner's grant, and spends it.

    themis act ACTION TARGET -- COMMAND   run COMMAND with an unspent grant for ACTION on TARGET
    themis act --verify ACTION TARGET     from inside COMMAND: exit 0 only when it runs under act

The grant is spent before the command starts. The action receipt that names it is written first,
so a command that fails, or two acts started at once, cannot use one grant twice. A pack may write
records of its own for an action before the command starts (`Pack.actions`), such as the look a
sealed data window's rules count.

The command is given a token in THEMIS_ACT_TOKEN, and its receipt holds only the token's hash.
`--verify` accepts the token while the act that gave it runs, for the action and target it was
given for. So a script can refuse to run outside `act`, as a delete or a spend that runs inside a
script, where no hook can see it, must.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themis import grants as grants_of
from themis import receipts, records
from themis.gitlog import Git

if TYPE_CHECKING:
    from themis.manifest import Manifest

PASS, FAIL, REFUSE = 0, 1, 2
TOKEN = "THEMIS_ACT_TOKEN"
CLAIMS = Path(receipts.LOCAL).parent / "act"  # one claim for each grant being spent, never committed


class Refused(Exception):
    """The action may not run. The command did not start, and no grant was spent."""


def _moment(now: dt.datetime | None = None) -> dt.datetime:
    """The time to record, in UTC and to the second. A time with no zone is taken to be UTC."""
    now = now or dt.datetime.now(dt.timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(dt.timezone.utc).replace(microsecond=0)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _named(receipt: dict[str, Any]) -> str | None:
    name = receipt.get("grant")
    return name.strip() if isinstance(name, str) and name.strip() else None


def unspent(root: Path, manifest: Manifest, action: str, target: str) -> records.Record:
    """The grant that opens this action on this target: one that can be read, is not marked spent and
    is named by no action receipt. Raises Refused when there is none."""
    used = {_named(receipt) for receipt in receipts.read_all(root, "action")}
    held = [grant for grant in records.load_kind(root, manifest, "grant", Git(root).all_files())
            if not grant.problems and grant.id not in used]
    found = grants_of.find_grant(held, action, target)
    if found is None:
        raise Refused(f"there is no unspent grant for {action} on {target}, so the command did not run. "
                      f"The owner runs `themis grant {action} {target} --reason ...`; each grant opens it once")
    return found


def _found(command: list[str], root: Path) -> bool:
    """True when the command's program can be started from the project's root."""
    program = command[0]
    return shutil.which(program) is not None or (root / program).is_file()


def _claim(root: Path, grant: str, moment: dt.datetime) -> Path:
    """Claim the grant for this act. A second act that reaches for it at the same moment is refused."""
    folder = root / CLAIMS
    folder.mkdir(parents=True, exist_ok=True)
    (root / CLAIMS.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    claim = folder / f"{grant}.claim"
    try:
        with claim.open("x", encoding="utf-8") as handle:
            handle.write(f"{moment.isoformat()}\n")
    except FileExistsError:
        raise Refused(f"the grant {grant} is already being spent by another act") from None
    return claim


def _pack_records(root: Path, manifest: Manifest, action: str, target: str, grant: str,
                  moment: dt.datetime) -> list[Path]:
    """What the turned-on packs write for this action before its command starts."""
    written: list[Path] = []
    for loaded in manifest.packs:
        handler = loaded.actions.get(action)
        if handler is None:
            continue
        try:
            written += handler(root, manifest, target, grant=grant, now=moment)
        except ValueError as error:
            raise Refused(f"the {loaded.name} pack refused {action} on {target}: {error}") from None
    return written


def run(root: Path, manifest: Manifest, action: str, target: str, command: list[str], *,
        by: str | None = None, now: dt.datetime | None = None) -> tuple[int, Path, list[Path]]:
    """Spend the grant, write what the packs and the core record, run the command, and close the
    receipt with how the command ended. Returns the command's exit status, the receipt and the
    pack records. Raises Refused, with nothing spent, when the action may not run."""
    root = Path(root)
    if not command:
        raise Refused("give the command to run after `--`")
    if not _found(command, root):
        raise Refused(f"`{command[0]}` cannot be found, so it did not run and no grant was spent")
    moment = _moment(now)
    grant = unspent(root, manifest, action, target)
    claim = _claim(root, grant.id, moment)
    try:
        written = _pack_records(root, manifest, action, target, grant.id, moment)
    except BaseException:
        claim.unlink(missing_ok=True)  # nothing was spent: the grant is free again
        raise
    token = secrets.token_hex(32)
    wrote = [path.relative_to(root).as_posix() for path in written]
    receipt = grants_of.record_action(root, action, target, grant=grant, by=by, now=moment,
                                      details={"command": command, "token_sha256": _digest(token), "wrote": wrote})
    status = 127
    try:
        done = subprocess.run(command, cwd=root, env={**os.environ, TOKEN: token}, check=False)  # noqa: S603
        status = done.returncode
    except OSError as error:
        print(f"themis: `{command[0]}` could not be started ({error.__class__.__name__})", file=sys.stderr)
    finally:
        held = json.loads(receipt.read_text(encoding="utf-8"))
        held.update(exit_status=status, ended_at=_moment().isoformat())
        receipt.write_text(json.dumps(held, indent=2) + "\n", encoding="utf-8")
    return status, receipt, written


def verify(root: Path, action: str, target: str, token: str | None) -> str | None:
    """Why this token does not show a command runs under `themis act` for this action and target, in
    plain words. None when it does: its act is still running, and wrote what its receipt names."""
    if not token:
        return f"there is no {TOKEN}, so this is not running inside `themis act {action} {target}`"
    digest = _digest(token)
    for receipt in receipts.read_all(Path(root), "action"):
        if receipt.get("token_sha256") != digest:
            continue
        if (receipt.get("action"), receipt.get("target")) != (action, target):
            return (f"the token was given for {receipt.get('action')} on {receipt.get('target')}, "
                    f"not {action} on {target}")
        if receipt.get("ended_at"):
            return f"the act that gave this token ended at {receipt['ended_at']}"
        missing = [name for name in receipt.get("wrote") or [] if not (Path(root) / str(name)).is_file()]
        if not _named(receipt) or missing:
            return "the receipt that holds this token names no grant, or a record it names is gone"
        return None
    return "the token matches no action receipt, so it was not given by `themis act`"


def main(root: Path, manifest: Manifest, action: str, target: str, command: list[str], *, verify_only: bool) -> int:
    """The command line's `themis act`: an exit code, and a line that says what happened."""
    if verify_only:
        problem = verify(root, action, target, os.environ.get(TOKEN))
        print(f"themis: REFUSE. {problem}." if problem else f"themis: this runs under `themis act {action} {target}`.",
              file=sys.stderr)
        return REFUSE if problem else PASS
    try:
        status, receipt, written = run(root, manifest, action, target, command)
    except Refused as refusal:
        print(f"themis: REFUSE. {refusal}.", file=sys.stderr)
        return REFUSE
    for path in written:
        print(f"Wrote {path.relative_to(root)}.")
    print(f"themis: the command exited {status}. The grant is spent; receipt: {receipt.relative_to(root)}")
    return PASS if status == 0 else FAIL
