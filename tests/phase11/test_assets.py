"""
Purpose: Acceptance tests for publication asset generation, tables, figures, numbers, and SHA256 (§11.6).
Phase: Phase 11
"""

import csv
import hashlib
import json
import os
import re
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAPER_DIR = os.path.join(PROJECT_ROOT, "paper")
FIGURES_DIR = os.path.join(PAPER_DIR, "figures")
DATA_DIR = os.path.join(FIGURES_DIR, "data")
TABLES_DIR = os.path.join(PAPER_DIR, "tables")
ARTIFACT_DIR = os.path.join(PAPER_DIR, "artifact")


def test_figures_f1_through_f12_exist():
    """Assert F1 through F12 exist with .pdf, .png, .csv, and .caption.md (§11.6)."""
    for i in range(1, 13):
        fig_id = f"F{i}"
        pdf_path = os.path.join(FIGURES_DIR, f"{fig_id}.pdf")
        png_path = os.path.join(FIGURES_DIR, f"{fig_id}.png")
        csv_path = os.path.join(DATA_DIR, f"{fig_id}.csv")
        cap_path = os.path.join(FIGURES_DIR, f"{fig_id}.caption.md")

        assert os.path.exists(pdf_path), f"Missing PDF for {fig_id}"
        assert os.path.exists(png_path), f"Missing PNG for {fig_id}"
        assert os.path.exists(csv_path), f"Missing data CSV for {fig_id}"
        assert os.path.exists(cap_path), f"Missing caption for {fig_id}"


def test_figure_csv_row_count_matches_caption_n():
    """
    Assert for every figure, the number of data rows in CSV equals the n stated in its caption (§11.6).
    """
    for i in range(1, 13):
        fig_id = f"F{i}"
        csv_path = os.path.join(DATA_DIR, f"{fig_id}.csv")
        cap_path = os.path.join(FIGURES_DIR, f"{fig_id}.caption.md")

        # Read CSV row count (excluding header)
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            data_rows = list(reader)
            row_count = len(data_rows)

        # Read stated n from caption
        with open(cap_path, "r", encoding="utf-8") as f:
            cap_text = f.read()

        match = re.search(r"\(n\)\*:\s*(\d+)", cap_text)
        assert match is not None, f"Caption for {fig_id} does not state n in standard format: {cap_text}"
        stated_n = int(match.group(1))

        assert row_count == stated_n, f"For {fig_id}: CSV row count ({row_count}) != stated n ({stated_n}) in caption"


def test_tables_t1_through_t10_exist():
    """Assert T1 through T10 exist as both .csv and LaTeX booktabs .tex (§11.6)."""
    for i in range(1, 11):
        tbl_id = f"T{i}"
        csv_path = os.path.join(TABLES_DIR, f"{tbl_id}.csv")
        tex_path = os.path.join(TABLES_DIR, f"{tbl_id}.tex")

        assert os.path.exists(csv_path), f"Missing CSV for {tbl_id}"
        assert os.path.exists(tex_path), f"Missing TeX for {tbl_id}"


def test_t5_matches_analysis_plan():
    """
    Assert that the primary-comparison list in Table T5 is exactly the list in ANALYSIS_PLAN.md (§11.6).
    """
    analysis_plan_path = os.path.join(PROJECT_ROOT, "docs", "ANALYSIS_PLAN.md")
    t5_csv_path = os.path.join(TABLES_DIR, "T5.csv")

    assert os.path.exists(analysis_plan_path), "Missing docs/ANALYSIS_PLAN.md"
    assert os.path.exists(t5_csv_path), "Missing paper/tables/T5.csv"

    # Extract primary comparisons from ANALYSIS_PLAN.md
    plan_comparisons = []
    with open(analysis_plan_path, "r", encoding="utf-8") as f:
        in_primary = False
        for line in f:
            if "2.1 Primary Comparisons" in line:
                in_primary = True
                continue
            if in_primary and "2.2 Exploratory Comparisons" in line:
                break
            if in_primary:
                # Matches numbered items: 1. **D vs. A** on compensation latency for cell `(order, notification_failure)`
                m = re.search(r"\d+\.\s+\*\*(.+?)\*\*.*?cell\s+`(.+?)`", line)
                if m:
                    comp_name = m.group(1).strip()
                    cell = m.group(2).strip()
                    plan_comparisons.append((comp_name, cell))

    assert len(plan_comparisons) == 12, f"Expected 12 primary comparisons in ANALYSIS_PLAN.md, found {len(plan_comparisons)}"

    # Read T5.csv comparisons
    t5_comparisons = []
    with open(t5_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t5_comparisons.append((row["Comparison"].strip(), row["Scenario / Cell"].strip()))

    assert len(t5_comparisons) == len(plan_comparisons), (
        f"Mismatch in count: T5 has {len(t5_comparisons)} comparisons, ANALYSIS_PLAN has {len(plan_comparisons)}"
    )

    for idx, (p_comp, p_cell) in enumerate(plan_comparisons):
        t_comp, t_cell = t5_comparisons[idx]
        assert p_comp.replace(" ", "") == t_comp.replace(" ", ""), (
            f"Comparison {idx+1} mismatch: plan '{p_comp}' vs T5 '{t_comp}'"
        )
        assert p_cell == t_cell, f"Cell {idx+1} mismatch: plan '{p_cell}' vs T5 '{t_cell}'"


def test_numbers_json_matches_tex():
    """
    Assert for every number macro in numbers.json, numbers.tex equals numbers.json (§11.6).
    """
    json_path = os.path.join(PAPER_DIR, "numbers.json")
    tex_path = os.path.join(PAPER_DIR, "numbers.tex")

    assert os.path.exists(json_path)
    assert os.path.exists(tex_path)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(tex_path, "r", encoding="utf-8") as f:
        tex_content = f.read()

    for key, item in data.items():
        val = item.get("value")
        if isinstance(val, float):
            val_str = f"{val:.2f}" if abs(val) < 100 else f"{val:.1f}"
        else:
            val_str = str(val)

        macro_def = f"\\newcommand{{\\{key}}}{{{val_str}}}"
        assert macro_def in tex_content, f"Macro for {key} missing or value mismatched in numbers.tex: expected '{macro_def}'"


def test_artifact_bundle_and_sha256_verifies():
    """
    Assert paper/artifact/SHA256SUMS exists and every listed file matches its hash (§11.6).
    """
    sha_file = os.path.join(ARTIFACT_DIR, "SHA256SUMS")
    assert os.path.exists(sha_file), "Missing paper/artifact/SHA256SUMS"

    verified_count = 0
    with open(sha_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            parts = line.strip().split()
            expected_hash = parts[0]
            filename = parts[1]

            target_file = os.path.join(ARTIFACT_DIR, filename)
            assert os.path.exists(target_file), f"File {filename} listed in SHA256SUMS does not exist in {ARTIFACT_DIR}"

            hasher = hashlib.sha256()
            with open(target_file, "rb") as f_in:
                hasher.update(f_in.read())
            actual_hash = hasher.hexdigest()

            assert actual_hash == expected_hash, f"Hash mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
            verified_count += 1

    assert verified_count >= 4, f"Expected at least 4 bundle files verified, got {verified_count}"
