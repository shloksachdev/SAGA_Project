# Pre-Committed Analysis Plan

<!--
Purpose: Formal pre-registration of statistical hypotheses, comparisons, and testing protocol (§11.1).
Phase: Phase 11
Approval Gate: Must be approved by a human before Phase 10 full experiment run.
-->

## 1. Research Questions and Hypotheses

This analysis plan governs the evaluation of four distributed saga coordination strategies:
- **Path A**: Pure Orchestration (AWS Step Functions Standard Workflows)
- **Path B**: Pure Choreography (AWS EventBridge reverse event chain)
- **Path C**: Static Hybrid (Step Functions core + EventBridge edge with SQS DLQ)
- **Path D**: Dynamic Decentralized Coordination (Choreographed happy path, DynamoDB lease election, dynamic DAG scheduler)

### 1.1 Hypotheses

- **H1 (Parallel Speedup)**: On workloads and failure depths where the compensation DAG has width $k \ge 2$ (`order` failing at Notification; `wide-4`; `wide-6`), Path D's median compensation latency is significantly lower than Path A, Path B, and Path C.
- **H2 (Linear Chain Overhead Bound)**: Where the compensation DAG is a pure chain without concurrency (`order` failing at Payment or Inventory), Path D's median compensation latency is not lower than the baselines; its overhead is bounded by the election duration ($T_{\text{election}} = \text{LEASE\_ACQUIRED.ts} - \text{COMP\_NEEDED.ts}$). The practical equivalence margin is set to $\delta = 20\%$ of the baseline median (differences within $\pm \delta$ are considered "no practical difference").
- **H3 (Ablation: Parallel vs. LIFO)**: Path D parallel makespan is significantly lower than Path D sequential LIFO makespan where DAG width $k \ge 2$, with an expected empirical makespan reduction $\ge 25\%$; and equal within $\delta$ where the DAG is a chain.
- **H4 (Decoupling and Zero Static Binding)**: Path D's steady-state architectural coupling metric equals Path B's, and Path D's orchestrator static-reference count (AST analysis of `common/orchestrator.py`, `common/election.py`, `common/lease.py`, `common/core/dag.py`, `common/core/scheduler.py`) is strictly **0** (enforcing D5).
- **H5 (Recovery Consistency & Fault Resilience)**: Path D's recovery consistency rate (percentage of failed runs satisfying invariants $I_1$–$I_3$ within 60 s) is no lower than Path B's, including under leader-crash faults (`crash_after:1`), with leader takeover time strictly bounded by $T_{\text{takeover}} \le \text{LEASE\_TTL} + \text{WATCH\_JITTER}$.

---

## 2. Primary vs. Exploratory Comparisons

### 2.1 Primary Comparisons (Confirmatory with Holm Correction)

All primary comparisons are tested with a two-sided Mann-Whitney U test, with family-wise error rate controlled at $\alpha = 0.05$ via Holm-Bonferroni step-down adjustment:

1. **D vs. A** on compensation latency for cell `(order, notification_failure)`
2. **D vs. B** on compensation latency for cell `(order, notification_failure)`
3. **D vs. C** on compensation latency for cell `(order, notification_failure)`
4. **D vs. A** on compensation latency for cell `(wide-4, step4_failure)`
5. **D vs. B** on compensation latency for cell `(wide-4, step4_failure)`
6. **D vs. C** on compensation latency for cell `(wide-4, step4_failure)`
7. **D vs. A** on compensation latency for cell `(trainticket, notification_failure)`
8. **D vs. B** on compensation latency for cell `(trainticket, notification_failure)`
9. **D vs. C** on compensation latency for cell `(trainticket, notification_failure)`
10. **D-Parallel vs. D-LIFO** (ablation) on makespan for cell `(wide-4, step4_failure)`
11. **D-Parallel vs. D-LIFO** (ablation) on makespan for cell `(order, notification_failure)`
12. **D-Parallel vs. D-LIFO** (ablation) on makespan for cell `(order, payment_failure)` (equivalence check)

### 2.2 Exploratory Comparisons
All other pairwise comparisons, sensitivity runs (`workScale` $\in \{0, 1, 3\}$), throughput sweeps (2, 5, 10 sagas/s), and component cost breakdowns are strictly designated as **exploratory** in all table and figure captions.

---

## 3. Statistical Testing Protocol

### 3.1 Unit of Analysis
The unit of analysis is one complete saga transaction run.

### 3.2 Descriptive Statistics
For every experimental group, report:
- Sample size $n$
- Median
- Interquartile Range (IQR = $Q_3 - Q_1$)
- 95th Percentile ($p95$)

### 3.3 Confidence Intervals
- 95% Percentile Bootstrap Confidence Interval on the median.
- Resamples: $B = 10,000$, with fixed deterministic seed ($seed = 42$).

### 3.4 Pairwise Significance Testing
- Non-parametric two-sided **Mann-Whitney U** test.
- $p$-values adjusted via the **Holm-Bonferroni** procedure across the 12 primary comparisons at family-wise $\alpha = 0.05$.
- Verdict language in Table T5 is strictly restricted to three categorical terms:
  - **"lower"** (significant decrease, $p_{\text{adj}} < 0.05$ and $\Delta < 0$)
  - **"higher"** (significant increase, $p_{\text{adj}} < 0.05$ and $\Delta > 0$)
  - **"no significant difference"** ($p_{\text{adj}} \ge 0.05$)

### 3.5 Effect Sizes
- **Cliff's Delta** ($\delta$): Non-parametric effect size measuring the probability that a value from group 1 is greater than a value from group 2 minus the reverse probability.
  - $|\delta| < 0.147$: Negligible
  - $0.147 \le |\delta| < 0.33$: Small
  - $0.33 \le |\delta| < 0.474$: Medium
  - $|\delta| \ge 0.474$: Large
- **Hodges-Lehmann Estimator**: Median of all pairwise differences $(x_i - y_j)$ with 95% bootstrap confidence interval.

### 3.6 Censoring and Missing Data
- Runs that do not reach a terminal state within 60 seconds are considered timed-out and **right-censored at 60,000 ms**.
- Censored runs enter the non-parametric rank order at 60,000 ms and are explicitly included in sample size $n$ columns.
- Under no circumstances are timed-out or failed runs silently dropped.

---

## 4. Exclusion Criteria
- **Warm-Up Runs**: Exactly the first 10 runs per path per scenario are flagged `warmup=true` to eliminate container virtualization and JIT cold starts. These are preserved in raw JSONL but excluded from statistical aggregations.
- **No Outlier Removal**: No observations are discarded as outliers. Every valid measurement is included.
- Any anomaly or necessary exclusion requires a formal human-approved entry in `docs/EXPERIMENT_LOG.md`.

---

## 5. Sensitivity Analysis
- Evaluated at `workScale` $\in \{0.0, 1.0, 3.0\}$.
- `workScale = 0.0` isolates raw coordination infrastructure latency (EventBridge delivery, Step Functions state transitions, DynamoDB round trips).
- `workScale = 1.0` represents baseline simulated microservice execution.
- `workScale = 3.0` evaluates performance under high-computation workloads where coordination overhead is amortized.
- **Robustness Claim**: H1, H3, and H4 are hypothesized to hold across all values of `workScale`.
