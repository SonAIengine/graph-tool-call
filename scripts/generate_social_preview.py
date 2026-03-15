"""Generate GitHub social preview image (1280x640)."""

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

# ── Config ──
WIDTH, HEIGHT = 1280, 640
DPI = 100
BG = "#0d1117"
TEXT_COLOR = "#e6edf3"
ACCENT = "#58a6ff"
RED = "#f85149"
GREEN = "#3fb950"
DIM = "#8b949e"

fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 12.8)
ax.set_ylim(0, 6.4)
ax.axis("off")

# ── Title ──
ax.text(
    6.4,
    5.6,
    "graph-tool-call",
    fontsize=42,
    fontweight="bold",
    color=TEXT_COLOR,
    ha="center",
    va="center",
    fontfamily="monospace",
)
ax.text(
    6.4,
    5.0,
    "Graph-based tool retrieval for LLM agents",
    fontsize=18,
    color=DIM,
    ha="center",
    va="center",
)

# ── Benchmark bars ──
bar_y_base = 2.8
bar_height = 0.55
bar_x_start = 2.0
bar_max_width = 8.5

# Data
scenarios = [
    ("248 tools → LLM (baseline)", 12, RED, "12%"),
    ("248 tools → graph-tool-call", 82, GREEN, "82%"),
]

for i, (label, value, color, pct_label) in enumerate(scenarios):
    y = bar_y_base + (1 - i) * 1.2
    w = value / 100 * bar_max_width

    # Bar background
    bg_rect = mpatches.FancyBboxPatch(
        (bar_x_start, y - bar_height / 2),
        bar_max_width,
        bar_height,
        boxstyle="round,pad=0.05",
        facecolor="#161b22",
        edgecolor="none",
    )
    ax.add_patch(bg_rect)

    # Bar fill
    fill_rect = mpatches.FancyBboxPatch(
        (bar_x_start, y - bar_height / 2),
        w,
        bar_height,
        boxstyle="round,pad=0.05",
        facecolor=color,
        edgecolor="none",
        alpha=0.85,
    )
    ax.add_patch(fill_rect)

    # Percentage
    ax.text(
        bar_x_start + w + 0.2,
        y,
        pct_label,
        fontsize=22,
        fontweight="bold",
        color=color,
        ha="left",
        va="center",
    )

    # Label
    ax.text(
        bar_x_start - 0.1,
        y,
        label,
        fontsize=13,
        color=DIM,
        ha="right",
        va="center",
    )

# ── Bottom stats ──
stats = [
    ("79%", "fewer tokens"),
    ("0", "dependencies"),
    ("OpenAPI · MCP · LangChain", "integrations"),
]
stat_xs = [2.5, 6.4, 10.3]

for x, (val, desc) in zip(stat_xs, stats):
    ax.text(x, 1.3, val, fontsize=24, fontweight="bold", color=ACCENT, ha="center", va="center")
    ax.text(x, 0.8, desc, fontsize=12, color=DIM, ha="center", va="center")

# ── Save ──
out = "assets/social_preview.png"
fig.savefig(out, facecolor=BG, dpi=DPI)
plt.close()
print(f"Saved: {out} ({WIDTH}x{HEIGHT})")
