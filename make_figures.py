"""
make_figures.py — runs the full study and saves figures + a results summary.

    python make_figures.py

Outputs go to ./figures/ and ./figures/results.txt
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
from matplotlib.collections import PatchCollection

import yieldsim as ys

OUT = "figures"
os.makedirs(OUT, exist_ok=True)
P = dict(ys.DEFAULTS)
GOOD, DEAD, DEFECT = "#5b9a68", "#c8553d", "#1d1d1d"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
lines = []


def log(s=""):
    print(s)
    lines.append(s)


# ---------------------------------------------------------------------------
# Figure 1: same defects, two die sizes ("the pizza picture")
# ---------------------------------------------------------------------------

def draw_wafer(ax, layout, dead, dx, dy, title):
    rects = [Rectangle((x, y), *layout["die"]) for x, y in zip(layout["x0"], layout["y0"])]
    colors = np.where(dead, DEAD, GOOD)
    ax.add_collection(PatchCollection(rects, facecolor=colors, edgecolor="white", linewidth=0.3))
    ax.add_patch(Circle((0, 0), 150, fill=False, color="#888", lw=1))
    ax.scatter(dx, dy, s=6, c=DEFECT, zorder=3)
    ax.set_xlim(-155, 155); ax.set_ylim(-155, 155); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(title, fontsize=10)


rng = np.random.default_rng(7)
R = 150 - 3
dx, dy = ys.sample_defects(rng, P["d0"], R, alpha=None)
fig, axes = plt.subplots(1, 2, figsize=(10, 5.2))
log("FIGURE 1 — same wafer, same %d defects, two die sizes" % len(dx))
for ax, area in zip(axes, [600, 150]):
    s = np.sqrt(area)
    L = ys.place_dies(s, s)
    dead = ys.killed_dies(L, dx, dy)
    y = 1 - dead.mean()
    draw_wafer(ax, L, dead, dx, dy,
               f"{area} mm² dies: {L['count']} per wafer, {dead.sum()} dead, yield {y:.0%}")
    log(f"  {area} mm^2: {L['count']} dies, {dead.sum()} killed, yield {y:.1%}")
fig.suptitle("Same defects, different die sizes: big dies lose more of the wafer", fontsize=12)
fig.tight_layout()
fig.savefig(f"{OUT}/1_wafer_maps.png", dpi=160)
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 2: Monte Carlo validates the analytic yield models
# ---------------------------------------------------------------------------

log("\nFIGURE 2 — Monte Carlo vs analytic yield (D0 = %.2f /cm^2)" % P["d0"])
areas = np.array([25, 50, 100, 150, 200, 300, 400, 500, 600, 800])
fig, ax = plt.subplots(figsize=(7, 4.5))
grid = np.linspace(10, 850, 200)
ax.plot(grid, ys.poisson_yield(grid, P["d0"]), color="#4a6fa5", label="Poisson model (no clustering)")
ax.plot(grid, ys.neg_binomial_yield(grid, P["d0"], P["alpha"]), color="#c8553d",
        label=f"Negative binomial model (α = {P['alpha']:g})")
worst = 0.0
for alpha, color, lab in [(None, "#4a6fa5", "Monte Carlo, Poisson"),
                          (P["alpha"], "#c8553d", "Monte Carlo, clustered")]:
    mc = [ys.monte_carlo_yield(a, P["d0"], alpha, n_wafers=400, seed=1) for a in areas]
    m = np.array([v[0] for v in mc]); se = np.array([v[1] for v in mc])
    ax.errorbar(areas, m, yerr=2 * se, fmt="o", ms=4, color=color, mfc="white", label=lab)
    ref = ys.model_yield(areas, P["d0"], alpha)
    err = np.abs(m - ref) / ref
    worst = max(worst, err.max())
    log(f"  {lab}: max deviation from analytic = {err.max():.2%}")
ax.set_xlabel("Die area (mm²)"); ax.set_ylabel("Yield (fraction of good dies)")
ax.set_title("Simulated wafers agree with the analytic yield models")
ax.legend(frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig(f"{OUT}/2_yield_validation.png", dpi=160)
plt.close(fig)

# ---------------------------------------------------------------------------
# Figure 3: cost per working product, monolithic vs chiplets
# ---------------------------------------------------------------------------

log("\nFIGURE 3 — cost per working product vs total silicon area")
cache = {}
areas = np.linspace(50, 900, 120)
opts = (1, 2, 4, 8)
cost = {n: np.array([ys.product_cost(a, n, dpw_cache=cache, **P)["total"] for a in areas]) for n in opts}
fig, ax = plt.subplots(figsize=(7, 4.5))
colors = {1: "#1d1d1d", 2: "#4a6fa5", 4: "#c8553d", 8: "#5b9a68"}
for n in opts:
    ax.plot(areas, cost[n], color=colors[n], lw=2 if n == 1 else 1.5,
            label="Monolithic (1 die)" if n == 1 else f"{n} chiplets")
mono_beaten = np.argmax(np.min([cost[n] for n in opts[1:]], axis=0) < cost[1])
a_cross = areas[mono_beaten]
ax.axvline(a_cross, color="#888", ls="--", lw=1)
ax.text(a_cross + 10, ax.get_ylim()[1] * 0.9, f"chiplets win above ~{a_cross:.0f} mm²", color="#555")
ax.set_xlabel("Total silicon the design needs (mm²)"); ax.set_ylabel("Cost per working product (USD)")
ax.set_title(f"When does splitting a chip pay off?  (D0 = {P['d0']}/cm², wafer ${P['wafer_cost']:,.0f})")
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(f"{OUT}/3_cost_monolithic_vs_chiplets.png", dpi=160)
plt.close(fig)
log(f"  crossover: chiplets cheaper above ~{a_cross:.0f} mm^2")
for a in (300, 600, 800):
    n_best, c = ys.best_split(a, **P)
    saving = 1 - c[n_best]["total"] / c[1]["total"]
    log(f"  {a} mm^2: monolithic ${c[1]['total']:.0f} (yield {c[1]['yield_']:.0%}), "
        f"best = {n_best} chiplets ${c[n_best]['total']:.0f}, saving {saving:.0%}")

# ---------------------------------------------------------------------------
# Figure 4: where chiplets win, across die size and process maturity
# ---------------------------------------------------------------------------

log("\nFIGURE 4 — saving from the best chiplet split vs monolithic")
A = np.linspace(50, 900, 60)
D = np.linspace(0.05, 0.5, 46)
S = np.zeros((len(D), len(A)))
for r, d0 in enumerate(D):
    q = dict(P, d0=d0)
    for c_, a in enumerate(A):
        mono = ys.product_cost(a, 1, dpw_cache=cache, **q)["total"]
        best = min(ys.product_cost(a, n, dpw_cache=cache, **q)["total"] for n in (2, 4, 8))
        S[r, c_] = 100 * (1 - best / mono)
fig, ax = plt.subplots(figsize=(7, 4.8))
lim = np.nanmax(np.abs(S))
im = ax.pcolormesh(A, D, S, cmap="RdBu", vmin=-lim, vmax=lim, shading="auto")
cs = ax.contour(A, D, S, levels=[0], colors="k", linewidths=1.5)
ax.clabel(cs, fmt={0: "break-even"}, fontsize=9)
fig.colorbar(im, ax=ax, label="Cost saving of chiplets vs monolithic (%)")
ax.set_xlabel("Total silicon the design needs (mm²)")
ax.set_ylabel("Defect density D0 (defects/cm²)\n← mature process      new process →")
ax.set_title("Chiplets win for big designs, and earlier on immature processes")
fig.tight_layout()
fig.savefig(f"{OUT}/4_chiplet_advantage_map.png", dpi=160)
plt.close(fig)
for d0 in (0.05, 0.1, 0.2, 0.3, 0.5):
    row = S[np.argmin(np.abs(D - d0))]
    above = A[row > 0]
    log(f"  D0={d0:.2f}: chiplets cheaper above ~{above.min():.0f} mm^2" if len(above) else
        f"  D0={d0:.2f}: chiplets never cheaper in range")

with open(f"{OUT}/results.txt", "w") as f:
    f.write("\n".join(lines) + "\n")
print("\nSaved figures to", OUT)
