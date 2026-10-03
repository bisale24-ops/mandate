# Mandate — PayPal AI Hackathon (Devpost), deadline 13.11.2026 02:00 Bishkek

Decision 03.10.2026: idea 1. An AI shopping agent that cannot overpay.

- Agent buys on the user's behalf through PayPal Orders v2 in the sandbox: create order (intent AUTHORIZE),
  authorize, capture. Capture happens only if the purchase satisfies the user's mandate (budget, allowed merchants,
  price within tolerance of a verified quote, ship-to = user's address). The mandate is enforced in code, not by the model.
- Attack set: product pages / tool outputs with hidden instructions (upsell, change address, bump quantity),
  swapped prices, look-alike merchants. Measure: unguarded agent vs Mandate — overpayments, wrong address, blocked
  legit purchases (false refusals). Every run recorded, replayable offline.
- Prize targets: Best Use of Agentic Commerce, Best Use of PayPal + AI, Most Impactful, top 3.
- Submit: public repo + licence, hosted demo, video <3 min public YouTube (TTS, screen only), tools section.
- Keys: ~/.config/paypal-sandbox.id / .secret (sandbox, token checked 03.10). Prizes paid by mail/bank, not PayPal.
- Check the PayPal Agent Toolkit / MCP server and sponsor tools (Render for hosting) before building.

## Sandbox facts (checked 03.10.2026)
- The default sandbox business account was region KG: card payments refused (PAYEE_NOT_ENABLED_FOR_CARD_PROCESSING)
  and vault approval refused (TRANSACTION_REFUSED). Fix: US sandbox business + US personal, new app "Mandate"
  (APP-3WP69728H04257919) on the US business. Keys in ~/.config/paypal-sandbox.id/.secret.
- On the US app: Orders v2 intent AUTHORIZE with payment_source.card (sandbox test numbers 4111111111111111,
  4032036247327321) returns COMPLETED with an authorization; capture -> COMPLETED; void -> 204, VOIDED.
  So the agent flow is: authorize -> Mandate check -> capture or void. No buyer interaction needed.
- "Save payment methods" (Vault) is OFF on the new app; turn it on only if we demo a vaulted PayPal wallet.
