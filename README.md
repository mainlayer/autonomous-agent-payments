# Autonomous Agent Payments

A fully autonomous agent that **earns and spends** money via [Mainlayer](https://mainlayer.fr) — the payment infrastructure API for AI agents.

The agent registers itself as a paid service, accepts payments from other agents, and autonomously decides which external services to purchase based on its current balance — all without any human intervention.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Autonomous Agent                            │
│                                                                 │
│  ┌──────────┐   earn()    ┌─────────────────┐                  │
│  │  Buyer   │────────────▶│  AutonomousAgent │                  │
│  │  Agents  │             │                 │                  │
│  └──────────┘             │  budget: $X.XX  │                  │
│                           │  limit:  $10.00 │                  │
│                           └────────┬────────┘                  │
│                                    │ spend()                   │
│                       ┌────────────▼────────────┐              │
│                       │   Mainlayer Payment API  │              │
│                       │  api.mainlayer.fr       │              │
│                       └──┬──────────┬────────────┘              │
│                          │          │          │                │
│               ┌──────────▼─┐  ┌────▼────┐  ┌─▼─────────┐     │
│               │ DataService │  │Research │  │ Storage   │     │
│               │ $0.02/call  │  │$0.10/rpt│  │$0.01/slot │     │
│               └────────────┘  └─────────┘  └───────────┘     │
└─────────────────────────────────────────────────────────────────┘

   Earn cycle:  Buyer pays → balance increases
   Spend cycle: Agent evaluates balance → buys services it needs
   Budget guard: total spend never exceeds configured limit
```

---

## Quickstart

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

```bash
export MAINLAYER_API_KEY=your_mainlayer_api_key
```

### 3. Run the demo

```bash
python -m src.main
```

This launches a live Rich dashboard showing the agent earning from simulated buyers and making autonomous spending decisions cycle by cycle.

### 4. Run with Docker

```bash
docker compose up agent
```

---

## How It Works

### Earning

The agent registers its **text summarization service** as a Mainlayer resource. Any other agent or system can pay for this service:

```python
agent = AutonomousAgent(name="Summarizer", api_key="...", budget_limit=10.0)
await agent.setup()                        # registers service → gets resource_id
await agent.earn(buyer_wallet="buyer-001") # accepts payment, balance increases
```

### Spending

After each earning cycle the agent evaluates its balance and purchases external services it needs:

| Service | Resource ID | Price | Trigger |
|---|---|---|---|
| Market data feed | `market-data-mainlayer` | $0.02 | Balance >= min threshold |
| Research report | `research-reports-mainlayer` | $0.10 | Balance >= 3× price |
| Storage slot | `storage-mainlayer` | $0.01 | Balance >= min threshold |

```python
await agent.spend("market-data-mainlayer", "Real-time data for strategy")
```

### Budget Management

The agent never exceeds its `budget_limit`:

- Hard cap: `total_spent` is tracked and compared against `budget_limit` on every purchase
- Soft threshold: `min_balance_to_spend` prevents spending when balance is too low
- Tiered logic: expensive services only purchased when well-funded

### Autonomous Loop

```python
await agent.run_forever(interval_seconds=60)
# Runs until cancelled — check balance, earn, spend, repeat
```

---

## Examples

### Minimal agent (30 lines)

```bash
python examples/simple_agent.py
```

### Profit-maximizing agent

Dynamically adjusts service price based on observed buyer demand:

```bash
python examples/profit_maximizer.py
```

### Multi-agent swarm

Three agents trading with each other, creating a self-sustaining micro-economy:

```bash
python examples/multi_agent_swarm.py
```

```
  Summarizer  sells summaries → buys research reports
  Researcher  sells reports   → buys data feeds
  DataBroker  sells data      → buys summaries
```

---

## Configuration

All settings are read from environment variables:

| Variable | Default | Description |
|---|---|---|
| `MAINLAYER_API_KEY` | — | **Required.** Your Mainlayer Bearer token |
| `AGENT_NAME` | `SummarizerAgent` | Agent display name |
| `BUDGET_LIMIT` | `10.0` | Lifetime spend cap in USD |
| `SERVICE_PRICE` | `0.05` | Price charged per service call |
| `MIN_BALANCE_TO_SPEND` | `0.50` | Don't spend below this balance |
| `CYCLE_INTERVAL_SECONDS` | `60` | Seconds between autonomous cycles |
| `DEMO_CYCLES` | `8` | Number of cycles in demo mode |

---

## Tests

```bash
pytest tests/ -v
```

The test suite includes 30+ tests with fully mocked HTTP — no real API key required:

- `tests/test_agent.py` — earn, spend, setup, balance, HTTP error paths
- `tests/test_budget.py` — lifetime limits, thresholds, tiered logic, float safety

---

## Project Structure

```
autonomous-agent-payments/
├── src/
│   ├── agent.py              # AutonomousAgent — core earn/spend logic
│   ├── config.py             # AgentConfig + ServicePrices dataclasses
│   ├── main.py               # Rich dashboard entry point
│   └── services/
│       ├── data_service.py       # Purchases market data
│       ├── research_service.py   # Purchases research reports
│       └── storage_service.py    # Purchases storage slots
├── tests/
│   ├── test_agent.py         # 25+ agent unit tests
│   └── test_budget.py        # Budget management tests
├── examples/
│   ├── simple_agent.py           # Minimal 30-line agent
│   ├── profit_maximizer.py       # Dynamic pricing strategy
│   └── multi_agent_swarm.py      # 3-agent trading economy
├── .github/workflows/ci.yml  # CI: test + lint + Docker build
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## API Reference

### `AutonomousAgent`

```python
agent = AutonomousAgent(name, api_key, budget_limit=10.0)

await agent.setup()                    # → str: resource_id
await agent.earn(buyer_wallet)         # → dict: payment response
await agent.spend(resource_id, purpose)# → bool: True if purchased
await agent.check_balance()            # → float: current revenue
await agent.run_cycle()                # → dict: summary snapshot
await agent.run_forever(interval_seconds=60)
agent.summary()                        # → dict: financial snapshot
agent.net_profit()                     # → float
await agent.close()
```

---

## Mainlayer API

Base URL: `https://api.mainlayer.fr`

Authentication: `Authorization: Bearer <api_key>`

| Endpoint | Method | Purpose |
|---|---|---|
| `/resources` | POST | Register a payable service |
| `/payments` | POST | Send or receive a payment |
| `/analytics/revenue` | GET | Query revenue for a resource |
| `/resources/{id}/deliver` | GET | Retrieve purchased resource payload |
