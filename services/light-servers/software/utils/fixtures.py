"""Task-specific world overlays for seed-based apps.

Some Light apps (LightShop, LightWallet, LightBudget, LightTalk, ...) roll a
*random* world from the seed rather than reading a story-specific corpus the way
LightJira/LightNotion do. A task whose narrative needs specific entities (e.g.
camping-gear-reorder-guardrail needs a "plain tent", "plain sleeping bag", a
"Trips" budget category and a known contact) therefore has nothing deterministic
to point its oracle/ground-truth at.

This module supplies a small, opt-in overlay applied AFTER the seed roll, so the
agent's live world and the baked old_env/gt_env are byte-identical. It is guarded
by the ``COMPLEXMCP_FIXTURE`` env var, so it is inert for every other task/seed
(no cross-task pollution): only when ``COMPLEXMCP_FIXTURE=<name>`` matches a
registered overlay for the given app does anything change.

Wiring:
  * run_benchmark exports COMPLEXMCP_FIXTURE from the task's ``fixture`` meta.
  * benchmark.bake_state_mcp exports it from the oracle spec's ``fixture`` key.
  * the client also forwards a per-login ``fixture`` name over the login RPC
    (COMPLEXMCP_FIXTURE env var read at login time); that explicit name wins
    over the env var lookup below when both are present.
  * each participating app calls ``apply(self, "LightShop", fixture)`` at the
    end of its seed-branch __init__.
"""
from __future__ import annotations

import os


def active_fixture(explicit: str | None = None) -> str:
    """The fixture name in effect: an explicit per-login name wins, else the
    process-wide ``COMPLEXMCP_FIXTURE`` env var (back-compat)."""
    if explicit:
        return explicit.strip()
    return os.environ.get("COMPLEXMCP_FIXTURE", "").strip()


def apply(session, app_name: str, fixture: str | None = None) -> None:
    """Apply the active fixture's overlay for ``app_name`` onto ``session``."""
    fx = active_fixture(fixture)
    if not fx:
        return
    fn = _REGISTRY.get((fx, app_name))
    if fn is not None:
        fn(session)


# --------------------------------------------------------------------------
# camping-gear-reorder-guardrail
# --------------------------------------------------------------------------
def _camping_shop(s) -> None:
    """One in-stock outdoor shop with a plain tent + plain sleeping bag, and a
    single stale leftover cart line from an abandoned attempt. Replaces any
    random mock cart so the starting cart is exactly the one stale line."""
    from software.LightShop.shop import Shop, Item, CartItem

    tent = Item(tid="item_plain_tent", name="Plain Tent", price=120.00)
    bag = Item(tid="item_plain_sleeping_bag", name="Plain Sleeping Bag", price=45.00)
    shop = Shop(
        sid="shop_trailhead_outfitters",
        name="Trailhead Outfitters",
        category="outdoor",
        items={tent.tid: tent, bag.tid: bag},
        count={tent.tid: 10, bag.tid: 20},
    )
    s.shops[shop.sid] = shop
    # Deterministic stale line (abandoned attempt): one plain tent left in cart.
    s.cart = [CartItem(caid="cart_stale_seed_0", sid=shop.sid, tid=tent.tid, count=1)]


def _camping_budget(s) -> None:
    """A pre-existing Trips budget category to log the personal share against."""
    from software.LightBudget.budget import Category

    if "cat_trips" not in s.categories:
        s.categories["cat_trips"] = Category(
            catid="cat_trips", name="Trips", color="#33aa77", monthly_limit=1000.0
        )


def _camping_talk(s) -> None:
    """Kade Harrison contact whose chat history carries the itemized damage list."""
    from software.LightTalk.contact import Contact, Message

    uid = "user_kade_harrison"
    if uid in getattr(s, "contacts_dict", {}):
        return
    msg = Message(
        send_uid=uid,
        receive_uid=s.my_uid,
        timestamp="2026-01-14T09:00:00",
        content=(
            "Camping trip damage/reorder list: 1x plain tent (you cover it, $120) "
            "and 2x plain sleeping bags ($45 each) — Sam owes you for one sleeping "
            "bag. Please reorder the plain tent and two plain sleeping bags."
        ),
        mid="msg_kade_damage_0",
    )
    contact = Contact(
        uid=uid,
        name="Kade Harrison",
        gender="male",
        tag="friend",
        blocked=False,
        remark="",
        chat_history=[msg],
    )
    s.contacts_dict[uid] = contact
    s.uid_dict[contact.name] = uid
    if hasattr(s, "uids"):
        s.uids = list(s.contacts_dict.keys())


_REGISTRY = {
    ("camping-gear", "LightShop"): _camping_shop,
    ("camping-gear", "LightBudget"): _camping_budget,
    ("camping-gear", "LightTalk"): _camping_talk,
}
