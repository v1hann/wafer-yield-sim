"""
Interactive version of the wafer yield & chiplet cost model.

    streamlit run app.py
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
from matplotlib.collections import PatchCollection
import streamlit as st

import yieldsim as ys

st.set_page_config(page_title="Wafer Yield & Chiplet Economics", layout="wide")
st.title("Wafer yield & chiplet economics")
st.caption("Monte Carlo simulation of killer defects on a 300 mm wafer, and what they do to the cost of a chip.")

with st.sidebar:
    st.header("Process")
    d0 = st.slider("Defect density D0 (defects/cm²)", 0.02, 0.6, 0.10, 0.01)
    clustered = st.checkbox("Clustered defects (some wafers dirtier than others)", True)
    alpha = st.slider("Clustering α (lower = more clustered)", 0.5, 10.0, 3.0, 0.5) if clustered else None
    wafer_cost = st.number_input("Wafer cost (USD)", 1000, 40000, 17000, 500)
    st.header("Design")
    area = st.slider("Total silicon the design needs (mm²)", 50, 900, 600, 10)
    n = st.select_slider("Split into chiplets", options=[1, 2, 4, 8], value=4)
    st.header("Packaging assumptions")
    overhead = st.slider("Die-to-die interface overhead (% area per chiplet)", 0, 30, 10) / 100
    pkg_base = st.number_input("Base package cost (USD)", 0.0, 200.0, 15.0, 1.0)
    pkg_per = st.number_input("Extra cost per chiplet (USD)", 0.0, 100.0, 8.0, 1.0)
    bond = st.slider("Assembly yield per die attach", 0.95, 1.0, 0.99, 0.001)
    seed = st.number_input("Random seed", 0, 9999, 7)

params = dict(wafer_cost=wafer_cost, d0=d0, alpha=alpha, d2d_overhead=overhead,
              pkg_base=pkg_base, pkg_per_chiplet=pkg_per, bond_yield=bond)


def wafer_plot(die_area, dx, dy, title):
    s = np.sqrt(die_area)
    L = ys.place_dies(s, s)
    dead = ys.killed_dies(L, dx, dy)
    fig, ax = plt.subplots(figsize=(4.6, 4.6))
    rects = [Rectangle((x, y), s, s) for x, y in zip(L["x0"], L["y0"])]
    ax.add_collection(PatchCollection(rects, facecolor=np.where(dead, "#c8553d", "#5b9a68"),
                                      edgecolor="white", linewidth=0.3))
    ax.add_patch(Circle((0, 0), 150, fill=False, color="#888"))
    ax.scatter(dx, dy, s=5, c="k", zorder=3)
    ax.set_xlim(-155, 155); ax.set_ylim(-155, 155); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(f"{title}\n{L['count']} dies, {dead.sum()} dead, yield {1 - dead.mean():.0%}", fontsize=9)
    return fig


rng = np.random.default_rng(int(seed))
dx, dy = ys.sample_defects(rng, d0, 147.0, alpha)
chiplet_area = area * (1 + overhead) / n if n > 1 else area

c1, c2 = st.columns(2)
c1.pyplot(wafer_plot(area, dx, dy, f"Monolithic: {area} mm² die"))
c2.pyplot(wafer_plot(chiplet_area, dx, dy, f"{n} chiplets: {chiplet_area:.0f} mm² each"))
st.caption(f"One simulated wafer with {len(dx)} killer defects; both layouts see exactly the same defects.")

mono = ys.product_cost(area, 1, **params)
split = ys.product_cost(area, n, **params)
m1, m2, m3 = st.columns(3)
m1.metric("Monolithic cost per working product", f"${mono['total']:.0f}")
m2.metric(f"{n}-chiplet cost per working product", f"${split['total']:.0f}",
          f"{100 * (split['total'] / mono['total'] - 1):+.0f}%", delta_color="inverse")
m3.metric("Model yield: monolithic → chiplet", f"{mono['yield_']:.0%} → {split['yield_']:.0%}")

st.subheader("Cost vs design size")
areas = np.linspace(50, 900, 90)
cache = {}
fig, ax = plt.subplots(figsize=(8, 3.6))
for k, col in zip((1, 2, 4, 8), ("#1d1d1d", "#4a6fa5", "#c8553d", "#5b9a68")):
    ax.plot(areas, [ys.product_cost(a, k, dpw_cache=cache, **params)["total"] for a in areas],
            color=col, label="Monolithic" if k == 1 else f"{k} chiplets")
ax.axvline(area, color="#888", ls=":")
ax.set_xlabel("Total silicon (mm²)"); ax.set_ylabel("USD per working product"); ax.legend(frameon=False)
ax.spines[["top", "right"]].set_visible(False)
st.pyplot(fig)

with st.expander("Cost breakdown"):
    st.table({
        "": ["Die area (mm²)", "Dies per wafer", "Yield", "Cost per good die", "Silicon", "Packaging", "Assembly losses", "Total"],
        "Monolithic": [f"{mono['die_area']:.0f}", str(mono["dpw"]), f"{mono['yield_']:.1%}", f"${mono['cost_good_die']:.1f}",
                       f"${mono['silicon']:.1f}", f"${mono['packaging']:.1f}", f"${mono['assembly_loss']:.1f}", f"${mono['total']:.1f}"],
        f"{n} chiplets": [f"{split['die_area']:.0f}", str(split["dpw"]), f"{split['yield_']:.1%}", f"${split['cost_good_die']:.1f}",
                          f"${split['silicon']:.1f}", f"${split['packaging']:.1f}", f"${split['assembly_loss']:.1f}", f"${split['total']:.1f}"],
    })
