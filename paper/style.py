"""
Purpose: Standardized publication figure styling and colorblind palette (§11.3).
Phase: Phase 11
"""

import matplotlib.pyplot as plt

# Okabe-Ito Colorblind-Safe Palette
PALETTE = {
    "A": "#0072B2",        # Blue
    "B": "#E69F00",        # Orange
    "C": "#009E73",        # Bluish Green
    "D": "#D55E00",        # Vermillion
    "D-LIFO": "#CC79A7",   # Reddish Purple
    "A-par": "#56B4E9",    # Sky Blue (lighter variant)
    "B-fan": "#F0E442",    # Yellow (lighter variant)
}

HATCHES = {
    "D-LIFO": "//",
    "A-par": "..",
    "B-fan": "\\\\",
}

# Standard Dimensions (IEEE / ACM formats)
SINGLE_COL_WIDTH = 3.4  # inches
DOUBLE_COL_WIDTH = 7.0  # inches
DEFAULT_HEIGHT = 2.6    # inches


def apply_publication_style():
    """Configures global matplotlib rcParams for publication-quality figures."""
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif", "Times"],
        "font.size": 8.5,
        "axes.labelsize": 9.0,
        "axes.titlesize": 9.0,
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
        "legend.fontsize": 8.0,
        "figure.titlesize": 9.5,
        "axes.linewidth": 0.8,
        "grid.linewidth": 0.5,
        "grid.alpha": 0.4,
        "lines.linewidth": 1.2,
        "lines.markersize": 4.5,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def get_color(series_name: str) -> str:
    return PALETTE.get(series_name, "#333333")


def get_hatch(series_name: str) -> str:
    return HATCHES.get(series_name, "")
