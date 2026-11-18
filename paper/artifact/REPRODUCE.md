# Artifact Reproducibility Guide

To reproduce every figure, table, statistic, and reported number from scratch:

1. **Prerequisites & Setup**:
   ```bash
   pip install -r requirements.txt
   powershell.exe -ExecutionPolicy Bypass -File .\setup.ps1
   ```

2. **Run Smoke Test or Full Evaluation**:
   ```bash
   python harness/run_experiment.py --config experiments/configs/smoke.json --runTag smoke-reproduce
   ```

3. **Rebuild Paper Assets**:
   ```bash
   python paper/build_assets.py --runTag smoke-reproduce --bundle
   ```
