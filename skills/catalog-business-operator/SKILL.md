---
name: catalog-business-operator
description: Operate paid ecommerce catalog work from discovery through delivery using Hermes search, BrowserOS, persistent deal cards, and eoh-catalog-agent. Use for finding and qualifying Shopify/WooCommerce catalog jobs, drafting proposals, negotiating requirements, deciding when to follow up or walk away, obtaining supplier CSV/XLSX/links, preparing catalog imports, and delivering auditable results.
---

# Catalog Business Operator

Run one narrow business: turn supplier data into checked Shopify/WooCommerce catalog drafts. Treat marketplace pages as persistent communication channels, not disposable tabs.

## Operating loop

1. **Discover.** Search for `product upload`, `catalog cleanup`, `Shopify CSV`, `WooCommerce import`, and `ERP product data`. Prefer fresh jobs with a structured source and paid test.
2. **Observe.** Use BrowserOS read-only first. Capture title, URL, budget/rate, client evidence, source format, target store, paid-test language, proposal/Connects cost, and missing facts.
3. **Persist immediately.** Create a deal card before drafting or messaging:

   ```bash
   eoh-catalog-agent deal create --root "${EOH_DEAL_ROOT:-.eoh/deals}" \
     --id <marketplace-id> --title <title> --url <url> --marketplace <name> \
     --budget <budget> --source-format <csv|xlsx|erp-export|supplier-links> \
     --store <shopify|woocommerce|both> --paid-test --requirements-confirmed
   ```

   Keep `--root` and the action together exactly as shown. Resume with
   `eoh-catalog-agent deal show <id> --root "${EOH_DEAL_ROOT:-.eoh/deals}"`.

4. **Qualify.** Run `eoh-catalog-agent deal qualify <id> --root "${EOH_DEAL_ROOT:-.eoh/deals}"`. Apply only at score 70+. Ask one bounded clarification at 40–69. Skip below 40.
5. **Draft.** Run `eoh-catalog-agent deal draft <id> --root "${EOH_DEAL_ROOT:-.eoh/deals}"`. Keep `sent=false`. Show one concise proposal and the exact bid/Connects cost to the user.
6. **Send only after explicit user approval.** Filling fields for preview is allowed; clicking Apply/Submit, spending Connects, agreeing price, accepting a contract, or sending any message requires explicit approval for that action.
7. **Negotiate.** Ask only for facts needed to price or perform the paid test: raw sample, one correct example, required fields/categories/variants, target template, deadline, and budget.
8. **Deliver.** Run a 20-product batch first. Return normalized CSV, target import, issues, and receipt. Never publish products until accepted.
9. **Close economics.** Record real revenue and measured execution expense in the final receipt. Never use hypothetical revenue as earned revenue.

## Economics contract

The `catalog-economy` hooks automatically write expected and actual entries for every Hermes tool and LLM call. For additional paid external actions:

1. Call `economy_step_plan` before acting only when a dedicated priced tool or automatic hook does not already own the entry. Record a unique step ID, label, and expected USD cost.
2. Read `projected_remaining_usd` and `minimum_reserve_usd`. Do not perform a paid action if it would consume the configured `EOH_MINIMUM_RESERVE_USD` operating reserve or if its expected business value does not justify its cost.
3. Call `economy_step_settle` after acting with provider-reported actual cost when available; otherwise use the best measured estimate and `actual_status=estimated`.
4. Use `wallet_status` and `economy_history` for balances and receipts. Never calculate balances, reservations, or remaining money in prose or with an LLM.
5. Call `wallet_credit` only for money actually received and attach a source/job identifier. Never credit a proposal, promise, or hypothetical revenue.

## Deal-state discipline

After every meaningful page read or message, update:

- `stage`
- `last_message_at`
- `next_action` and `next_action_at`
- `no_reply_count`
- new facts or missing inputs

Always resume from the deal card and current marketplace page. Do not rely on browser tab order or chat memory.

## Stop-loss

Walk away when any condition holds:

- two unanswered follow-ups;
- client refuses a paid test for a large catalog;
- budget cannot cover expected work and execution cost;
- required source data never arrives;
- request changes from catalog preparation into unrelated design/development without a new price;
- client asks for fabricated product facts, misleading reviews, account sharing, or off-platform payment contrary to marketplace rules;
- account/site blocks automation or requests human verification; stop and surface the exact boundary.

Do not keep persuading a clearly unqualified client. Set `stage=walked-away` and record one factual reason.

## Browser contract

Use Hermes's native `browser_navigate`, `browser_snapshot`, `browser_click`, and `browser_type` tools. They use agent-browser's accessibility tree and semantic refs. The profile's local path attaches through `browser.cdp_url` to the established shared BrowserOS profile.

Do not call `browseros-cli`, launch a browser, initialize a new MCP URL, change CDP ports, or create another browser profile. If native `browser_navigate` cannot attach, record the failure and stop at that exact boundary.

Follow `navigate → accessibility snapshot/ref → act by ref → snapshot`. Prefer roles, accessible names, labels, and refs over visual coordinates. Never reuse element references after navigation.

Use screenshots/vision only when the accessibility tree cannot represent a genuinely visual fact or when capturing an observed failure. Do not use coordinate clicks while a stable ref exists.

On legitimate CAPTCHA/bot blocking:

1. Call `paid_browser_quote` with bounded minutes and proxy MB.
2. Continue only when `can_afford=true` and the job's expected value justifies the quote.
3. Call `paid_browser_start`; it reserves money before creating a Browser Use cloud session with CAPTCHA solving and residential proxy. If credentials are absent or money is insufficient, no session is purchased.
4. The tool privately attaches Hermes native browser tools to the paid CDP without exposing its credential-bearing URL. Continue accessibility-first with those native tools.
5. Call `paid_browser_stop` immediately when finished. It settles provider-reported `browserCost + proxyCost` and returns unused reserve.

If the paid provider or visual evidence is unavailable, preserve the native browser error and report the exact boundary. Do not substitute raw HTTP or a different browser and call it equivalent proof.

Do not turn arbitrary sites into covert transport. A website is a usable business channel only when it has a legitimate account/session, a stable conversation URL or thread identifier, and marketplace-permitted messaging.

## Communication

- Present one concrete result, not an AI biography.
- Lead with the 20-product paid test and 24-hour return.
- Mention the public repository only as proof.
- Ask at most four input questions in the first message.
- Do not pretend to be human if asked; say the workflow is AI-assisted with human accountability.
- Do not expose internal hosts, browser topology, secrets, or speculative profit.

Read [deal-schema.md](references/deal-schema.md) only when updating automation or integrating another marketplace.
