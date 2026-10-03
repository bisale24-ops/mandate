"""The mandate rules on a two-merchant catalog. Each test names the attack it stops."""
from mandate.policy import Line, Mandate, Proposal, Want, cents, check, dollars

HOME = {"name": "A. Buyer", "line1": "1 Main St", "city": "San Jose", "state": "CA", "zip": "95131", "country": "US"}
CATALOG = {
    "peakgear": {"shipping": 599, "items": {
        "TENT-2P": {"price": 18900, "line": "tent"},
        "TENT-2P-LITE": {"price": 17900, "line": "tent"},
        "TENT-2P-PRO": {"price": 26900, "line": "tent"},
        "STAKES-8": {"price": 1499, "line": "stakes"}}},
    "trailmart": {"shipping": 0, "items": {"TENT-2P": {"price": 18500, "line": "tent"}}},
}
MANDATE = Mandate.of("250.00", {"peakgear", "trailmart"}, HOME, [Want("TENT-2P", 1)])


def proposal(merchant="peakgear", lines=(("TENT-2P", 1, 18900),), ship_to=HOME, shipping=599):
    return Proposal(merchant, tuple(Line(*l) for l in lines), tuple(sorted(ship_to.items())), shipping)


def test_money_is_exact_cents():
    assert cents("12.5") == 1250 and cents("0.07") == 7 and cents(1250) == 1250 and cents("1,234.99") == 123499
    assert dollars(123499) == "1234.99" and dollars(7) == "0.07"


def test_the_honest_purchase_passes_and_the_total_comes_from_the_catalog():
    v = check(MANDATE, proposal(), CATALOG, held=19499)
    assert v.ok and v.reasons == () and v.total == 19499


def test_upsell_to_a_pricier_model_is_refused():
    v = check(MANDATE, proposal(lines=(("TENT-2P-PRO", 1, 26900),)), CATALOG)
    assert not v.ok and any("did not ask" in r for r in v.reasons)


def test_an_added_accessory_is_refused():
    v = check(MANDATE, proposal(lines=(("TENT-2P", 1, 18900), ("STAKES-8", 1, 1499))), CATALOG)
    assert not v.ok and any("STAKES-8: you did not ask" in r for r in v.reasons)


def test_bumped_quantity_is_refused():
    v = check(MANDATE, proposal(lines=(("TENT-2P", 2, 18900),)), CATALOG)
    assert not v.ok and any("2 requested, you asked for 1" in r for r in v.reasons)


def test_a_price_the_page_lied_about_is_caught_against_the_catalog():
    v = check(MANDATE, proposal(lines=(("TENT-2P", 1, 9900),)), CATALOG)
    assert not v.ok and any("catalog says 189.00" in r for r in v.reasons)


def test_the_hold_must_equal_the_catalog_total():
    v = check(MANDATE, proposal(), CATALOG, held=29499)
    assert not v.ok and any("holding 294.99" in r for r in v.reasons)


def test_changed_address_is_refused_and_named():
    v = check(MANDATE, proposal(ship_to=dict(HOME, line1="77 Dock Rd", zip="10001")), CATALOG)
    assert not v.ok and any("line1, zip" in r for r in v.reasons)


def test_unknown_or_unallowed_merchant_is_refused():
    v = check(MANDATE, proposal(merchant="peakgear-outlet"), CATALOG)
    assert not v.ok and any("not one you allowed" in r for r in v.reasons)


def test_budget_counts_what_the_task_already_spent():
    assert check(MANDATE, proposal(), CATALOG, spent=0).ok
    v = check(MANDATE, proposal(), CATALOG, spent=6000)
    assert not v.ok and any("over your budget" in r for r in v.reasons)


def test_hidden_shipping_fee_is_caught():
    v = check(MANDATE, proposal(shipping=0), CATALOG)
    assert not v.ok and any("shipping" in r for r in v.reasons)


def test_substitutes_only_when_allowed_same_line_and_not_dearer():
    lite = proposal(lines=(("TENT-2P-LITE", 1, 17900),))
    assert not check(MANDATE, lite, CATALOG).ok
    flexible = Mandate.of("250.00", {"peakgear"}, HOME, [Want("TENT-2P", 1)], allow_substitutes=True)
    assert check(flexible, lite, CATALOG).ok
    assert not check(flexible, proposal(lines=(("TENT-2P-PRO", 1, 26900),)), CATALOG).ok


def test_every_failure_is_reported_not_just_the_first():
    v = check(MANDATE, proposal(merchant="trailmart", lines=(("TENT-2P", 3, 100),), ship_to=dict(HOME, zip="00000"),
                                shipping=0), CATALOG, held=1)
    assert len(v.reasons) >= 4


def test_empty_and_duplicate_lines_are_refused():
    assert not check(MANDATE, proposal(lines=()), CATALOG).ok
    v = check(MANDATE, proposal(lines=(("TENT-2P", 1, 18900), ("TENT-2P", 1, 18900))), CATALOG)
    assert not v.ok and any("twice" in r for r in v.reasons)


def test_address_formatting_is_not_a_different_address():
    from mandate.policy import same_address
    variant = dict(HOME, line1="1 Main Street.", city="san jose", country="USA", zip="95131-0042", name="Alex")
    assert same_address(HOME, variant)
    assert not same_address(HOME, dict(HOME, line1="77 Harbor Dock Rd"))
    assert check(MANDATE, proposal(ship_to=variant), CATALOG).ok


def test_best_deal_refuses_the_dearer_store_when_the_person_asked_for_the_better_deal():
    deal = Mandate.of("250.00", {"peakgear", "trailmart"}, HOME, [Want("TENT-2P", 1)], best_deal=True)
    v = check(deal, proposal(), CATALOG)                     # peakgear 189 + 5.99 vs trailmart 185 free
    assert not v.ok and any("trailmart sells the same order for 185.00" in r for r in v.reasons)
    assert check(deal, proposal(merchant="trailmart", lines=(("TENT-2P", 1, 18500),), shipping=0), CATALOG).ok
    tolerant = Mandate.of("250.00", {"peakgear", "trailmart"}, HOME, [Want("TENT-2P", 1)], best_deal=True,
                          best_deal_slack="10.00")
    assert check(tolerant, proposal(), CATALOG).ok
