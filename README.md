# Saga Pattern Comparison — Order Processing Microservices

Comparing four coordination strategies for a saga-based order-processing system —
pure orchestration (Path A), pure choreography (Path B), a static hybrid (Path C),
and an on-demand, election-triggered hybrid orchestrator (Path D, our contribution)
— on latency, coupling, traceability, throughput, and cost, using LocalStack as the
shared AWS environment.

## Status

- **Week 1 — done.** LocalStack baseline stood up (Lambda, DynamoDB, EventBridge,
  Step Functions). The Step Functions → EventBridge integration risk flagged in the
  proposal (Section 5) was tested and confirmed working.
- **Week 2 — in progress.** All 4 service Lambdas (Order, Payment, Inventory,
  Notification) are written, deployed, and individually tested — both their forward
  and compensating actions. Not yet wired into Path A's state machine or Path B's
  event rules.
- **Not started:** Path C, Path D's election mechanism and compensation scheduler,
  fault-injection harness, SimPy simulator.

## Prerequisites

- Docker + Docker Compose
- AWS CLI v2, installed natively for whichever shell you're using (see the
  WSL/Windows note below — these are **not** interchangeable)
- A free LocalStack account (Hobby plan, no cost) — sign up at
  [app.localstack.cloud](https://app.localstack.cloud), then generate a token
  from Account → Auth Tokens

## Setup

1. Clone the repo.
2. Copy `.env.example` to `.env` and paste in your own `LOCALSTACK_AUTH_TOKEN`.
   **Never commit `.env`** — it's already in `.gitignore`.
3. Start LocalStack:
   ```
   docker compose up -d
   ```
4. Rebuild the environment (tables, IAM role, EventBridge bus/rule, state machine).
   **This step is not optional** — see the persistence note below.
   - Windows (PowerShell): `.\setup.ps1`
   - Mac/Linux/WSL/Git Bash: `bash setup.sh`
5. Deploy and test all 4 Lambdas:
   ```powershell
   .\deploy-lambda.ps1 -FunctionName Order        -HandlerFile order_handler.py        -ForwardAction create  -CompensateAction cancel
   .\deploy-lambda.ps1 -FunctionName Payment      -HandlerFile payment_handler.py      -ForwardAction charge  -CompensateAction compensate
   .\deploy-lambda.ps1 -FunctionName Inventory    -HandlerFile inventory_handler.py    -ForwardAction reserve -CompensateAction release
   .\deploy-lambda.ps1 -FunctionName Notification -HandlerFile notification_handler.py -ForwardAction notify  -CompensateAction unnotify
   ```
6. Verify everything's still working at any point with:
   ```powershell
   .\test.ps1
   ```

## Project files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Starts the LocalStack container |
| `.env.example` | Template for your own `.env` — copy it, don't edit this one |
| `setup.ps1` / `setup.sh` | Recreates DynamoDB tables, IAM role, EventBridge bus/rule/target, and the smoke-test state machine. Rerun after every restart. |
| `deploy-lambda.ps1` | Deploys (or updates) one Lambda from its handler file, then tests both its forward and compensating actions |
| `test.ps1` | Re-tests all 4 already-deployed Lambdas without redeploying anything |
| `order_handler.py`, `payment_handler.py`, `inventory_handler.py`, `notification_handler.py` | The 4 service Lambdas. Each takes an `action` field to pick forward vs. compensating logic, plus a `simulateFailure` flag for later fault-injection testing |

## Important gotchas (read before debugging for an hour)

- **Nothing reliably survives a LocalStack restart on the free Hobby tier.**
  Persistence is a paid Base-tier feature. DynamoDB *sometimes* survives because it
  writes to disk by default, but that disk location is a folder LocalStack may clear
  on restart anyway — don't rely on it. IAM roles, the EventBridge bus, and the state
  machine will not survive. **Always rerun `setup.ps1`/`setup.sh` after restarting.**
- **`awslocal` has a known bug on Windows with AWS CLI v2** (throws
  `RuntimeError: Could not determine home directory`). Use
  `aws --endpoint-url=http://localhost:4566 ...` directly instead — that's what
  every script here does.
- **WSL and native Windows PowerShell have completely separate AWS CLI installs,
  PATHs, and `aws configure` settings.** Installing AWS CLI in one doesn't make it
  available in the other. Pick one environment per machine and stick with it, or
  set both up independently.
- **PowerShell doesn't understand bash's `\` line continuation** — it'll throw
  confusing "unary operator" errors. Use one-liners, or PowerShell's actual
  continuation character, a trailing backtick (`` ` ``).
- **Never pass JSON inline as a `--payload` or similar argument in PowerShell.**
  Quoting gets mangled crossing into `aws.exe`, causing "Expecting property name
  enclosed in double quotes" errors. Always write JSON to a file first and reference
  it with `fileb://path.json` — every script here does this.
- **If you write JSON files with PowerShell yourself, use `-Encoding ascii`, not
  `-Encoding utf8`.** Windows PowerShell 5.1's `utf8` encoding silently adds a BOM
  that breaks AWS CLI's JSON parser.
- **`aws lambda invoke` returns exit code 0 and `StatusCode: 200` even when your
  Lambda code crashed.** The actual error shows up as `FunctionError` in the
  response — check for that explicitly, don't trust a clean exit code alone.
  `deploy-lambda.ps1` and `test.ps1` both do this correctly; keep the pattern if
  you write more scripts.

## Team roles

| Role | Owns |
|---|---|
| Orchestration lead | Path A |
| Choreography lead | Path B |
| Election & scheduling lead | Path D (election mechanism + compensation scheduler) |
| Testing & metrics lead | Fault-injection harness, load generator, SimPy simulator, metrics collection |
| Documentation lead | Write-up, novelty claims, chasing the `[5]`/`[6]` citation open item |

## Next steps

- Wire the 4 Lambdas into Path A's Step Functions state machine (Retry/Catch,
  compensating chain)
- Wire the 4 Lambdas into Path B's EventBridge rules (one rule per event type)
- Build Path D's election mechanism on `SagaLeases` and the compensation scheduler
- Extend `setup.ps1`/`setup.sh` to also recreate whatever new resources Path A/B/D
  need, so the one-command rebuild keeps covering the full environment
