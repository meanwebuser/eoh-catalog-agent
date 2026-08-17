# EOH Catalog Agent

![Supplier catalog becomes checked store drafts](docs/hero.svg)

> Turn a messy supplier spreadsheet into a checked Shopify or WooCommerce catalog — without publishing a broken product.

Give the agent a CSV/XLSX. It normalizes product data, quarantines duplicates and broken rows, and produces store-ready draft imports plus an auditable job receipt.

- Shopify and WooCommerce outputs from one source catalog
- automatic aliases for common supplier column names
- duplicate SKU, missing field, price, and stock checks
- non-zero exit for incomplete batches
- revenue, execution cost, and net-profit receipt
- persistent marketplace deal cards with qualification and stop-loss
- deterministic USD wallet with per-step estimate, reservation, actual cost, and remaining balance
- optional Browser Use CAPTCHA/proxy sessions purchased only when affordable

```text
supplier.csv  ->  checked catalog  ->  Shopify / WooCommerce drafts
                         |
                         +---------> issues.csv + receipt.json
```

## Install

```bash
pipx install git+https://github.com/meanwebuser/eoh-catalog-agent.git
```

## Process a paid test batch

```bash
eoh-catalog-agent prepare supplier.csv \
  --out run/client-test \
  --store both \
  --limit 20 \
  --job-id marketplace-job-123 \
  --revenue-usd 20 \
  --expense-usd 0.05
```

Outputs:

- `products.normalized.csv` — clean canonical catalog;
- `shopify_import.csv` — Shopify draft import;
- `woocommerce_import.csv` — WooCommerce unpublished import;
- `issues.csv` — rows that require correction;
- `receipt.json` — batch counts, input hash, targets, and artifact paths.

When revenue and execution expense are supplied, the receipt also records the job's net profit. A batch containing quarantined rows exits non-zero so an automated runner cannot report incomplete work as finished.

Required input columns are `name`, `sku`, and `price`; common supplier aliases such as `Product Name`, `Variant SKU`, `Regular Price`, `Image URL`, and `Vendor` are recognized automatically.

The agent does not publish products or send marketplace proposals. A human reviews the import and explicitly launches publishing.

## Run as a Hermes business operator

Install the complete isolated profile from this repository:

```bash
hermes profile install https://github.com/meanwebuser/eoh-catalog-agent \
  --name catalog-seller --alias -y
export EOH_DEAL_ROOT="$PWD/.eoh/deals"
catalog-seller chat -q "Find one paid catalog test, qualify it, and draft a proposal. Do not send it."
```

The profile combines Hermes search and accessibility-first native browser tools with persistent deal state: discover → qualify → draft → negotiate → deliver → record real economics. Each action gets a machine-calculated estimate before execution and an actual/estimated settlement afterward; the ledger returns the remaining balance without using an LLM for arithmetic.

It expects the established local browser CDP at `http://127.0.0.1:9223`; change `browser.cdp_url` when your shared authenticated browser uses a different endpoint. For protected business pages, configure `BROWSER_USE_API_KEY` through Hermes' secret/config flow. The `paid_browser_start` tool reserves funds first, then creates Browser Use with CAPTCHA solving and a residential proxy; `paid_browser_stop` records provider-reported browser and proxy cost. Set `EOH_MINIMUM_RESERVE_USD` to keep an operating reserve after any purchase. With no key, insufficient balance, or insufficient post-purchase reserve, no paid session is created.

Point the CLI and Hermes profile at the same operational ledger. Initialize it once before first use (or credit verified income with a receipt), then ask for a deterministic quote:

```bash
export EOH_ECONOMY_ROOT="$HOME/.hermes/profiles/catalog-seller/economy"
eoh-catalog-agent wallet --root "$EOH_ECONOMY_ROOT" init --balance-usd 5
eoh-catalog-agent browser --root "$EOH_ECONOMY_ROOT" quote --minutes 10 --proxy-mb 10
eoh-catalog-agent wallet --root "$EOH_ECONOMY_ROOT" status
```

Proposal submission, Connects spending, contracts, and publishing remain explicit human actions.

## Verify from source

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```
