# Synthetic Slack dialogue (copy into a real channel)

Use **two people** (or two test accounts) in a channel whose name **starts with your opportunity prefix**.

Example: if `opportunities.opportunity_id` is `oid1023`, the prefix is **`oid1023`** (letters and digits only, lowercased).  
Create a channel like **`oid1023-saas-discovery`**, invite your bot, then paste or improvise from the script below.

Themes align loosely with studio CSV batches (cloud architecture, security, pricing, integration, sales methodology).

---

**Alex (Champion):** Jordan — kicking off discovery for our SaaS evaluation. Can you explain multi-tenant vs single-tenant in plain terms? We're comparing two vendors.

**Jordan (SE):** Multi-tenant: one shared stack serves many customers with logical isolation. Single-tenant: dedicated instance or cluster for one customer — stronger isolation, usually higher cost. For regulated workloads some buyers mandate single-tenant or dedicated cells.

**Alex:** Our CISO asked about SOC 2 — what's the real difference between Type I and Type II for us?

**Jordan:** Type I is point-in-time: controls are *designed* appropriately. Type II covers a period and says controls operated *effectively*. Procurement usually wants Type II for production vendors.

**Alex:** Finance wants TCO, not just per-seat price. What should we include beyond licence fees?

**Jordan:** Add implementation/SI, SSO/SCIM, sandbox, premium support, data egress, backup add-ons, API overage, training, and annual uplift. Model a 3-year cash flow with seat ramp — that's the CFO conversation.

**Alex:** IT asked about iPaaS vs native CRM integration — when do we push an integration hub?

**Jordan:** Native fits standard objects. Use iPaaS for many endpoints, heavy transforms, or central governance. If they run 14 SaaS tools with custom spaghetti, hub-and-spoke or iPaaS is usually the right answer.

**Alex:** Should we qualify this deal with BANT or MEDDIC? Multi-stakeholder, roughly $400k ARR.

**Jordan:** BANT is a fast filter. MEDDIC helps for complex enterprise: metrics, economic buyer, criteria, decision process, identify pain, champion. I'd multithread champion, economic buyer, and security, and tie a PoC to mutual success criteria.

---

## Second channel (optional)

Create **`oid1023-security-thread`** and add a shorter security-only thread (encryption at rest, MFA, RBAC vs ABAC) using the same two personas so the sync pulls **multiple** `slack_messages.json` files under different channel IDs.

---

## Static JSON sample (upload to GCS without Slack API)

For offline tests, see:

- `data/test/synthetic_slack_export_sample/slack_metadata.json`
- `data/test/synthetic_slack_export_sample/C0SYNTHSAAS01/slack_messages.json`

Upload to your bucket as:

- `{opportunity_id}/raw/slack/slack_metadata.json`
- `{opportunity_id}/raw/slack/C0SYNTHSAAS01/slack_messages.json`

Use your real **Slack channel ID** (starts with `C`) in the folder name if you want to mirror production naming; the sample ID `C0SYNTHSAAS01` is fictional.
