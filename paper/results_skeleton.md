# Results Skeleton

<!--
Purpose: Factual, purely descriptive results section outline with macro placeholders filled (§11.5).
No interpretive claims or subjective adjectives.
-->

## 1. Experimental Setup
The evaluation executed across four coordination paths (A, B, C, D) using LocalStack 3.8.0 on an 8-core host (Table T10). A total of 360 runs were evaluated under seeded randomization, excluding the first 10 warm-up runs per series.

## 2. Primary Hypothesis Comparisons (H1–H5)
- **H1 (Parallel Speedup)**: For the wide-fan workload (`wide-4`), Path D achieved a median compensation makespan of 1868 ms (95% CI [1750, 1980], n=20), which was statistically lower than Path A (Table T5, Comparison 4, p_adj < 0.001, Cliff's delta = -0.92, verdict: lower).
- **H2 (Linear Chain Bound)**: On the chain workload (`order` failing at Payment), the difference between Path D and sequential rollback was -18 ms (95% CI [-70, +35], Table T5, Comparison 12, p_adj = 1.000, verdict: no significant difference).
- **H3 (Ablation: Parallel vs. LIFO)**: On `wide-4`, Path D parallel makespan (1868 ms) reduced makespan by 46.75% (95% CI [41.2%, 52.1%], Table T4) compared to sequential LIFO (3508 ms; Table T5, Comparison 10, verdict: lower).
- **H4 (Architectural Coupling)**: Path D required 5 EventBridge rules, while Path B required 7 rules. Path D dynamic orchestrator modules contained 0 static service references (Table T6).
- **H5 (Recovery Consistency)**: Under failure injection, Path D achieved a recovery consistency rate of 100.0% (Table T8).

## 3. Cost Analysis
Evaluated under AWS list pricing (Table T7), cost per 1,000 transactions was $0.1547 for Path A, $0.0112 for Path B, $0.1375 for Path C, and $0.0251 for Path D (Figure F9).
