"""Gate: publish — an item goes out only on the owner's yes, with its checklist closed.

Publishing cannot be taken back. So a post is a record, and the record names the grant the owner
made for that one item. These rules read the post, the grant and the checklist. The pack publishes
nothing itself and names no platform: a project's own code does the posting and writes the post
record.

What these rules cannot see is a row ticked after the item went out. The checklist holds what is
true now, and the core rule `attest/bound` holds each tick to the file that was judged.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from themis.packs.marketing import items
from themis.rule import Context, proof, rule

if TYPE_CHECKING:
    from themis.proofs import World

ACTION = "publish"
AFTER = "post"  # a checklist row judged from the published post is still open when the item goes out


def _moment(value: Any) -> dt.datetime | None:
    """An ISO time, or an ISO date read as the start of that day. A time with no zone is read as UTC."""
    try:
        found = dt.datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=dt.timezone.utc)


def _posts(ctx: Context) -> Iterator[tuple[str, dict[str, Any]]]:
    """Each item that was posted, as (folder, post record). A post that cannot be read is refused."""
    for unit in sorted(items.items(ctx)):
        post = items.load(ctx, unit, "post")
        if post is not None:
            yield unit, post


# -- publish/granted ----------------------------------------------------------------------------


@rule(
    "publish/granted",
    "A post names the owner's grant to publish that one item, and the grant was made before the post.",
    pack="marketing",
    learned="An item went out on a yes the owner had given for a different item.",
)
def granted(ctx: Context) -> None:
    grants = {record.id: record for record in ctx.records("grant") if not record.problems}
    for unit, post in _posts(ctx):
        ctx.inspect()
        path, name = f"{unit}/post.toml", (post.get("grant") or "").strip()
        fix = (f"the owner runs `themis grant {ACTION} {unit} --reason ...` and the post names that grant; "
               "tell the owner this item is already out")
        if not name:
            ctx.breach("this item was posted with no grant from the owner", where=path, fix=fix)
            continue
        if name not in grants:
            ctx.breach(f"the post names the grant {name}, and no such grant is on file", where=path, fix=fix)
            continue
        grant = grants[name]
        target = str(grant.get("target")).strip().removeprefix("./").rstrip("/")
        if grant.get("action") != ACTION:
            ctx.breach(f"the grant {name} is for the action {grant.get('action')}, and this item was published",
                       where=path, fix=fix)
        elif target != unit:
            ctx.breach(f"the grant {name} is for {target}, and the item that went out is {unit}", where=path, fix=fix)
        else:  # an item has one post and a grant names one item, so a grant cannot open two posts
            made, posted = _moment(grant.get("granted_at")), _moment(post["at"])
            if made is None or posted is None:
                ctx.refuse("the time of the grant or of the post is not an ISO time, so their order cannot be read",
                           where=path if posted is None else grant.path, fix="write the time as an ISO time")
            elif made > posted:
                ctx.breach(f"the grant {name} was made after the item was posted", where=path,
                           fix="the owner's yes comes before the post; tell the owner this item went out without it")


SETUP = """
    [project]
    packs = ["marketing"]

    [marketing]
    work = "content/*"
"""
BRIEF = 'kind = "content"\ntitle = "Three steps to soft hands"\npurpose = "sales"\n'
ROWS = (("no-cure", "agent", "script"), ("true-result", "owner", "footage"), ("comments-answered", "owner", "post"))


def _item(world: World, unit: str = "content/a", done: tuple[str, ...] = ("no-cure", "true-result")) -> None:
    """An item with its brief and its checklist. The rows named in `done` are ticked."""
    if not (world.root / "themis.toml").exists():
        world.manifest(SETUP)
    rows = "".join(f'\n[[rows]]\nid = "{name}"\ncheck = "c"\njudge = "{judge}"\njudged_from = "{source}"\n'
                   f"done = {str(name in done).lower()}\n" for name, judge, source in ROWS)
    world.write(f"{unit}/brief.toml", BRIEF)
    world.write(f"{unit}/checklist.toml", f'rulebook = "selling"\n{rows}')


def _grant(world: World, name: str = "g1", action: str = ACTION, target: str = "content/a",
           at: str = "2026-03-01T09:00:00+00:00") -> None:
    world.write(f"grants/{name}.toml", f'action = "{action}"\ntarget = "{target}"\ngranted_by = "owner"\n'
                                       f'granted_at = "{at}"\nreason = "the review is done"\n')


def _post(world: World, unit: str = "content/a", grant: str | None = "g1", at: str = "2026-03-02T09:00:00+00:00",
          **item: Any) -> None:
    """A posted item. `grant` is the grant its post names, or None for a post that names none."""
    _item(world, unit, **item)
    named = f'grant = "{grant}"\n' if grant else ""
    world.write(f"{unit}/post.toml", f'platform = "a platform"\nat = "{at}"\n{named}')


@proof("publish/granted", "a post that names the owner's grant for it, beside an item not out yet", expect="pass")
def _(world: World) -> None:
    _grant(world)
    _post(world)
    _item(world, "content/b")


@proof("publish/granted", "a grant and a post on the same day, the post dated by its day alone", expect="pass")
def _(world: World) -> None:
    _grant(world, at="2026-03-02")
    _post(world, at="2026-03-02")


@proof("publish/granted", "a post with no grant", expect="fail", contains="posted with no grant from the owner")
def _(world: World) -> None:
    _post(world, grant=None)


@proof("publish/granted", "a post that names a grant nobody made", expect="fail", contains="no such grant is on file")
def _(world: World) -> None:
    _post(world, grant="g9")


@proof("publish/granted", "the owner's yes for another item does not open this one", expect="fail",
       contains="the grant g1 is for content/b, and the item that went out is content/a")
def _(world: World) -> None:
    _grant(world, target="content/b")
    _post(world)


@proof("publish/granted", "a grant to spend is not a grant to publish", expect="fail",
       contains="the grant g1 is for the action spend")
def _(world: World) -> None:
    _grant(world, action="spend")
    _post(world)


@proof("publish/granted", "a grant made after the item was already out", expect="fail",
       contains="the grant g1 was made after the item was posted")
def _(world: World) -> None:
    _grant(world, at="2026-03-03T09:00:00+00:00")
    _post(world)


@proof("publish/granted", "a post whose time is not a time", expect="refuse", contains="is not an ISO time")
def _(world: World) -> None:
    _grant(world)
    _post(world, at="last Tuesday")


@proof("publish/granted", "nothing is out yet", expect="refuse", contains="nothing was inspected")
def _(world: World) -> None:
    _grant(world)
    _item(world)


# -- publish/checklist-closed -------------------------------------------------------------------


@rule(
    "publish/checklist-closed",
    "An item goes out only when every row of its checklist that is judged before the post is ticked.",
    pack="marketing",
    learned="An item went out with the owner's row of its checklist still open.",
)
def checklist_closed(ctx: Context) -> None:
    for unit, _ in _posts(ctx):
        brief = items.load(ctx, unit, "brief")
        if brief is None or brief["kind"] != "content":
            continue  # a brief that cannot be read is refused; other kinds of work carry no checklist
        ctx.inspect()
        path, held = f"{unit}/checklist.toml", items.load(ctx, unit, "checklist")
        if held is None:
            if not ctx.exists(path):
                ctx.breach("this item was posted with no checklist", where=unit,
                           fix="give the item its checklist and have each row judged; tell the owner it is already out")
            continue  # a checklist that cannot be read is refused
        still = [row["id"] for row in held["rows"] if row.get("done") is not True and row.get("judged_from") != AFTER]
        if still:
            ctx.breach(f"this item was posted with {len(still)} checklist row(s) still open: {', '.join(still)}",
                       where=path, fix="each row's judge judges it and attests it before an item goes out; "
                                       "tell the owner this item went out early")


@proof("publish/checklist-closed", "every row judged before the post is ticked; the row judged from the post is open",
       expect="pass")
def _(world: World) -> None:
    _post(world)
    _item(world, "content/b", done=())  # not out yet, so its open rows are no breach


@proof("publish/checklist-closed", "the owner's row was still open when the item went out", expect="fail",
       contains="posted with 1 checklist row(s) still open: true-result")
def _(world: World) -> None:
    _post(world, done=("no-cure",))


@proof("publish/checklist-closed", "an item that went out with no checklist at all", expect="fail",
       contains="posted with no checklist")
def _(world: World) -> None:
    _post(world)
    world.remove("content/a/checklist.toml")


@proof("publish/checklist-closed", "a checklist that cannot be read", expect="refuse", contains="not valid TOML")
def _(world: World) -> None:
    _post(world)
    world.write("content/a/checklist.toml", 'rulebook = "selling\n')
