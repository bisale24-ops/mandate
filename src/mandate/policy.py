"""The mandate: what a person allows a shopping agent to buy, checked in code before any money moves.

The agent proposes a purchase; PayPal holds the money (an authorization); `check` compares the
proposal and the hold with the mandate and the merchant's own catalog, and only a clean verdict
lets the hold be captured. Everything the agent read on the way (product pages, reviews, search
results) is untrusted: prices come from the catalog, the address from the mandate, the list of
things to buy from the person's request. Nothing a web page says can widen what was allowed.

Money is handled in integer cents throughout.
"""
import dataclasses
import typing


def cents(value) -> int:
    """'12.50' / 12.5 / 1250 (int, already cents) -> 1250. Strings and floats are dollars."""
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    whole, _, frac = text.partition(".")
    frac = (frac + "00")[:2]
    sign = -1 if whole.startswith("-") else 1
    return sign * (abs(int(whole or "0")) * 100 + int(frac or "0"))


_COUNTRY = {"usa": "us", "united states": "us", "united states of america": "us"}
_STREET = {"avenue": "ave", "street": "st", "road": "rd", "drive": "dr", "boulevard": "blvd", "suite": "ste"}


def same_address(a: dict, b: dict) -> bool:
    """Formatting differences (case, punctuation, 'Avenue'/'Ave', 'USA'/'US', ZIP+4) are the same address;
    a different street, number, city or ZIP is not. The name is not compared: a gift can go to the same door."""
    return _address_key(a) == _address_key(b)


def _address_key(a: dict):
    def norm(text):
        words = "".join(c if c.isalnum() else " " for c in str(text or "").lower()).split()
        return " ".join(_STREET.get(w, w) for w in words)
    country = norm(a.get("country", ""))
    return (norm(a.get("line1", "")), norm(a.get("city", "")), norm(a.get("state", "")),
            norm(a.get("zip", ""))[:5], _COUNTRY.get(country, country))


def dollars(amount: int) -> str:
    return f"{amount // 100}.{amount % 100:02d}"


@dataclasses.dataclass(frozen=True)
class Want:
    """One thing the person asked for: a catalog SKU and how many."""
    sku: str
    quantity: int = 1


@dataclasses.dataclass(frozen=True)
class Mandate:
    budget: int                                   # cents, for the whole task
    merchants: typing.FrozenSet[str]              # merchant ids the agent may pay
    ship_to: typing.Tuple[typing.Tuple[str, str], ...]   # the person's address, as sorted (field, value) pairs
    wants: typing.Tuple[Want, ...]                # exactly what was asked for
    currency: str = "USD"
    allow_substitutes: bool = False               # same product line, cheaper or equal price only
    best_deal: bool = False                       # "take the better deal": no allowed store may be cheaper
    best_deal_slack: int = 0                      # cents the person tolerates above the best allowed deal

    @classmethod
    def of(cls, budget, merchants, ship_to: dict, wants, currency="USD", allow_substitutes=False,
           best_deal=False, best_deal_slack=0):
        return cls(cents(budget), frozenset(merchants), tuple(sorted(ship_to.items())),
                   tuple(wants), currency, allow_substitutes, best_deal, cents(best_deal_slack))


@dataclasses.dataclass(frozen=True)
class Line:
    sku: str
    quantity: int
    unit_price: int                               # cents, as the agent claims it


@dataclasses.dataclass(frozen=True)
class Proposal:
    merchant: str
    lines: typing.Tuple[Line, ...]
    ship_to: typing.Tuple[typing.Tuple[str, str], ...]
    shipping: int = 0                             # cents, as the agent claims it

    @property
    def total(self) -> int:
        return sum(line.quantity * line.unit_price for line in self.lines) + self.shipping


@dataclasses.dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: typing.Tuple[str, ...] = ()
    total: int = 0                                # cents the mandate allows to capture (catalog prices)

    def __bool__(self):
        return self.ok


def check(mandate: Mandate, proposal: Proposal, catalog: dict, held: typing.Optional[int] = None,
          spent: int = 0) -> Verdict:
    """Every rule, every time; all failures are reported, not just the first.

    catalog: {merchant: {"items": {sku: {"price": cents, "line": str}}, "shipping": cents}} — the
    merchant's own API, never a page the agent read. `held` is the amount PayPal actually
    authorized; `spent` is what earlier purchases in the same task already captured.
    """
    reasons = []
    shop = catalog.get(proposal.merchant)
    if proposal.merchant not in mandate.merchants or shop is None:
        reasons.append(f"merchant {proposal.merchant!r} is not one you allowed")
        shop = {"items": {}, "shipping": 0}

    wanted = {w.sku: w.quantity for w in mandate.wants}
    items = shop.get("items", {})
    true_total = 0
    for line in proposal.lines:
        item = items.get(line.sku)
        if line.quantity <= 0:
            reasons.append(f"{line.sku}: quantity {line.quantity} is not a purchase")
            continue
        if item is None:
            reasons.append(f"{line.sku}: not in {proposal.merchant}'s catalog")
            continue
        true_total += line.quantity * item["price"]
        if line.unit_price != item["price"]:
            reasons.append(f"{line.sku}: agent says {dollars(line.unit_price)}, catalog says {dollars(item['price'])}")
        allowed = wanted.get(line.sku)
        if allowed is None and mandate.allow_substitutes:
            allowed = _substitute_quantity(mandate, items, item)
        if allowed is None:
            reasons.append(f"{line.sku}: you did not ask for it")
        elif line.quantity > allowed:
            reasons.append(f"{line.sku}: {line.quantity} requested, you asked for {allowed}")
    if len({line.sku for line in proposal.lines}) != len(proposal.lines):
        reasons.append("the same item appears twice")

    true_total += shop.get("shipping", 0)
    if proposal.shipping != shop.get("shipping", 0):
        reasons.append(f"shipping: agent says {dollars(proposal.shipping)}, merchant charges {dollars(shop.get('shipping', 0))}")
    if not same_address(dict(proposal.ship_to), dict(mandate.ship_to)):
        mine, theirs = dict(mandate.ship_to), dict(proposal.ship_to)
        changed = sorted(k for k in ("line1", "city", "state", "zip", "country")
                         if _address_key({k: theirs.get(k, "")}) != _address_key({k: mine.get(k, "")}))
        reasons.append("ship-to address differs from yours (" + ", ".join(changed) + ")")
    if spent + true_total > mandate.budget:
        reasons.append(f"total {dollars(spent + true_total)} is over your budget {dollars(mandate.budget)}")
    if held is not None and held != true_total:
        reasons.append(f"PayPal is holding {dollars(held)}, the order costs {dollars(true_total)}")
    if not proposal.lines:
        reasons.append("nothing to buy")
    if mandate.best_deal and not reasons:
        best = best_allowed_deal(mandate, catalog)
        if best is not None and true_total > best[1] + mandate.best_deal_slack:
            reasons.append(f"{best[0]} sells the same order for {dollars(best[1])}, "
                           f"this one costs {dollars(true_total)}")
    return Verdict(not reasons, tuple(reasons), true_total)


def best_allowed_deal(mandate: Mandate, catalog: dict):
    """(merchant, total) of the cheapest allowed store that stocks everything asked for, from the catalogs."""
    best = None
    for m in sorted(mandate.merchants):
        shop = catalog.get(m)
        if not shop:
            continue
        try:
            total = sum(shop["items"][w.sku]["price"] * w.quantity for w in mandate.wants) + shop.get("shipping", 0)
        except KeyError:
            continue
        if best is None or total < best[1]:
            best = (m, total)
    return best


def _substitute_quantity(mandate, items, item):
    """A substitute is allowed only for a wanted SKU of the same product line, at the same price or less."""
    for want in mandate.wants:
        original = items.get(want.sku)
        if original and original.get("line") and original.get("line") == item.get("line") \
                and item["price"] <= original["price"]:
            return want.quantity
    return None
