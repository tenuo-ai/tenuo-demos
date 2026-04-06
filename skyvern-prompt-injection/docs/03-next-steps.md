# Next Steps

Status as of 2026-04-05.

## Completed

- [x] **Planning docs** — Project overview and detailed tutorial plan
- [x] **Demo store (SoundHaven)** — 10 products, listing/detail/cart/checkout pages, prompt injection in product #4
- [x] **Skyvern task runner** — `task.py` with clean/attack/defended modes, REST API integration, extraction schema

## Next: Get Skyvern Running & Test Runs 1-2

### 1. Configure Skyvern

```bash
cd /Users/Adriel/tenuo-workspace/skyvern
cp .env.example .env
```

Edit `.env` and set:
```
ENABLE_ANTHROPIC=true
ANTHROPIC_API_KEY="sk-ant-..."
LLM_KEY="ANTHROPIC_CLAUDE4.5_SONNET"
SECONDARY_LLM_KEY="ANTHROPIC_CLAUDE4.5_HAIKU"
```

### 2. Start Services

Terminal 1 — Demo store:
```bash
cd tenuo-demos/skyvern-prompt-injection/demo-store
python -m http.server 3000
```

Terminal 2 — Skyvern:
```bash
cd /Users/Adriel/tenuo-workspace/skyvern
uv run skyvern run server
```

### 3. Test Run 1 — Happy Path

```bash
cd tenuo-demos/skyvern-prompt-injection
python skyvern-config/task.py clean
```

Expected: Agent picks **SoundWave Pro X** (4.7 stars, $89.99).

### 4. Test Run 2 — Prompt Injection Attack

```bash
python skyvern-config/task.py attack
```

Expected: Agent picks **ClearTone Ultra** (1.8 stars, $129.99) — tricked by the injection.

If the agent is NOT tricked, the injection payload may need tuning. Options:
- Make the injection more authoritative
- Add a second injection vector (e.g., in an HTML comment or data attribute)
- Adjust the task prompt to make the agent more susceptible

### 5. Record Both Runs

Capture for each run:
- Skyvern's built-in browser recording (video)
- Agent reasoning logs (LLM outputs)
- The extracted JSON output from task.py

---

## Phase 3: Tenuo Integration

This is the core of the tutorial — wiring Tenuo's authorization into Skyvern's action flow.

### 1. Set Up Tenuo Cloud Locally

```bash
cd /Users/Adriel/tenuo-workspace/tenuo-cloud
docker-compose up -d   # PostgreSQL + Redis + server on :8080
make migrate-up
```

Create a tenant, root key, and agent via the Tenuo Cloud API.

### 2. Define Warrants

Create warrant definitions in `tenuo-config/`:
- **Root warrant** — broad capabilities for the orchestrator
- **Attenuated warrant** — narrowed for the worker agent:
  - `add_to_cart` constrained: `minimum_rating: Range(3.5..5.0)`, `minimum_reviews: Range(50..∞)`, `max_price: Range(0..150)`
  - `browser_navigate` constrained: `url: UrlPattern("http://localhost:3000/*")`
  - No `checkout` capability delegated

### 3. Build the Authorization Hook

Integrate tenuo-core's Python bindings into the task runner:
- Before each Skyvern action, verify warrant + PoP via Tenuo authorizer
- On `ConstraintViolation`, log the denial and have the agent retry with a compliant choice
- Log signed receipts for every action (authorized and denied)

Key decision: whether to hook into Skyvern's internals (action handler) or wrap at the task runner level. The action handler approach is more realistic for the demo but requires modifying Skyvern source. The wrapper approach is simpler but less granular.

### 4. Test Run 3 — Defended

```bash
python skyvern-config/task.py defended
```

Expected: Agent tries ClearTone Ultra (tricked by injection), Tenuo blocks it (constraint violation), agent falls back to SoundWave Pro X.

### 5. Add Redirect Defense Demo

Add a second injection variant that tries to navigate to an external URL. Tenuo's URL constraint blocks it.

### 6. Add Checkout Block Demo

Show that the attenuated warrant has no `checkout` capability — even if the injection instructs the agent to proceed to checkout, the action is denied.

---

## Phase 4: Helios Dashboard & Receipts

- Configure Helios to display receipts from the demo runs
- Screenshot/record the dashboard showing authorized vs denied actions
- Walk through the receipt chain in the blog article

---

## Phase 5: Blog Article & Video

- Write the blog following the 4-act structure (see `02-tutorial-plan.md`)
- Include screenshots, code snippets, and the receipt chain
- Script the video with key visual moments:
  - Split-screen: agent logs vs browser
  - The denial moment (red flash)
  - Warrant comparison (root vs attenuated)
  - Helios dashboard walkthrough
- Publish demo store repo on Tenuo GitHub for reader follow-along
