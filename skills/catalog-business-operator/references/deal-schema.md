# Deal schema

| Field | Meaning |
| --- | --- |
| `id` | Stable marketplace job/thread identifier |
| `url` | Canonical job or conversation URL |
| `stage` | discovered, qualified, drafted, applied, negotiating, won, delivering, completed, lost, walked-away |
| `fit_score` | 0–100 deterministic qualification score |
| `connects_cost` | Proposal/application cost before submission |
| `required_phrase` | Listing-specific phrase, used only for this deal's draft |
| `source_format` | csv, xlsx, erp-export, supplier-links, unknown |
| `store` | shopify, woocommerce, both, unknown |
| `paid_test` | Whether the client explicitly offers a paid sample |
| `requirements_confirmed` | Whether the listing or client confirms enough inputs to execute |
| `missing` | Facts required before pricing or execution |
| `last_message_at` | Last verified inbound/outbound timestamp |
| `next_action_at` | Follow-up or delivery deadline |
| `no_reply_count` | Count of bounded unanswered follow-ups |
| `walk_away_reason` | One factual terminal reason |

The JSON file is operational state. Do not store credentials, private product exports, message bodies, or personal data in it. Store customer files in a job-scoped private workspace and only retain artifact paths or hashes in receipts.
