"""
yieldsim.py — Monte Carlo wafer yield and chiplet cost model.

Core idea
---------
A wafer is a 300 mm disc. It gets cut into rectangular dies (chips).
Random killer defects (particles, crystal flaws) land on the wafer.
Any die that a defect lands on is dead. Big dies are more likely to be hit,
so the fraction of good dies (yield) drops quickly as die area grows.

That one fact drives chip economics: the cost of a good die is
    wafer cost / (dies per wafer * yield)
and it rises much faster than linearly with die area. Splitting one big die
into several small "chiplets" raises yield, but adds packaging cost,
die-to-die interface area, and assembly losses. This module finds where
that trade-off flips.

Units: lengths in mm, areas in mm^2, defect density D0 in defects/cm^2.
"""

import numpy as np

MM2_PER_CM2 = 100.0


# ---------------------------------------------------------------------------
# 1. Geometry: how many rectangular dies fit on a round wafer
# ---------------------------------------------------------------------------

def place_dies(die_w, die_h, wafer_d=300.0, edge_excl=3.0, scribe=0.1, n_offsets=8):
    """
    Lay a rectangular grid of dies on the wafer and keep only dies that sit
    completely inside the usable circle (wafer radius minus edge exclusion).

    The grid's position matters: shifting it by a fraction of a die can add or
    lose a row at the edge. So we try n_offsets x n_offsets grid shifts and keep
    the placement with the most complete dies.

    Returns a dict with:
        x0, y0   : lower-left corner of each die (mm), arrays
        i, j     : integer grid index of each die
        ox, oy   : grid offset used
        pitch    : (pitch_x, pitch_y) including scribe lane
        die      : (die_w, die_h)
        R        : usable radius
    """
    R = wafer_d / 2.0 - edge_excl
    px, py = die_w + scribe, die_h + scribe
    nx, ny = int(np.ceil(R / px)) + 2, int(np.ceil(R / py)) + 2
    ii, jj = np.meshgrid(np.arange(-nx, nx + 1), np.arange(-ny, ny + 1))
    ii, jj = ii.ravel(), jj.ravel()

    best = None
    for ox in np.linspace(0.0, px, n_offsets, endpoint=False):
        for oy in np.linspace(0.0, py, n_offsets, endpoint=False):
            x0 = ox + ii * px
            y0 = oy + jj * py
            # farthest corner of the rectangle from the wafer centre
            fx = np.maximum(np.abs(x0), np.abs(x0 + die_w))
            fy = np.maximum(np.abs(y0), np.abs(y0 + die_h))
            inside = fx ** 2 + fy ** 2 <= R ** 2
            if best is None or inside.sum() > best["count"]:
                best = dict(count=int(inside.sum()), x0=x0[inside], y0=y0[inside],
                            i=ii[inside], j=jj[inside], ox=ox, oy=oy)

    best.update(pitch=(px, py), die=(die_w, die_h), R=R)
    return best


def dies_per_wafer_formula(die_area, wafer_d=300.0, edge_excl=3.0):
    """Classic textbook approximation: pi*d^2/(4A) - pi*d/sqrt(2A)."""
    d = wafer_d - 2 * edge_excl
    return np.pi * d ** 2 / (4 * die_area) - np.pi * d / np.sqrt(2 * die_area)


# ---------------------------------------------------------------------------
# 2. Defects: where killer defects land
# ---------------------------------------------------------------------------

def sample_defects(rng, d0, R, alpha=None):
    """
    Drop random killer defects uniformly over the usable wafer area.

    d0    : mean defect density, defects/cm^2
    alpha : clustering parameter. Real fabs don't have the same density on
            every wafer: some wafers are dirtier than others. We model this by
            drawing each wafer's density from a Gamma distribution with mean d0
            and shape alpha. Small alpha = strong clustering. alpha=None means
            every wafer has exactly d0 (pure Poisson, no clustering).

    Returns (x, y) arrays of defect positions in mm.
    """
    area_cm2 = np.pi * R ** 2 / MM2_PER_CM2
    lam = d0 if alpha is None else rng.gamma(alpha, d0 / alpha)
    n = rng.poisson(lam * area_cm2)
    r = R * np.sqrt(rng.random(n))          # sqrt -> uniform over the disc area
    th = 2 * np.pi * rng.random(n)
    return r * np.cos(th), r * np.sin(th)


def killed_dies(layout, dx, dy):
    """
    Boolean mask over the dies in `layout`: True where at least one defect
    landed inside the die (defects landing in scribe lanes do no harm).
    """
    px, py = layout["pitch"]
    w, h = layout["die"]
    gi = np.floor((dx - layout["ox"]) / px).astype(np.int64)
    gj = np.floor((dy - layout["oy"]) / py).astype(np.int64)
    in_die = ((dx - layout["ox"] - gi * px) < w) & ((dy - layout["oy"] - gj * py) < h)
    key = lambda a, b: a * 1_000_003 + b
    hit_keys = np.unique(key(gi[in_die], gj[in_die]))
    return np.isin(key(layout["i"], layout["j"]), hit_keys)


# ---------------------------------------------------------------------------
# 3. Yield: Monte Carlo and the analytic models it should agree with
# ---------------------------------------------------------------------------

def monte_carlo_yield(die_area, d0, alpha=None, n_wafers=200, seed=0, **geom):
    """
    Simulate n_wafers wafers of square dies with the given area.
    Returns (mean yield, standard error, dies per wafer).
    """
    rng = np.random.default_rng(seed)
    side = np.sqrt(die_area)
    layout = place_dies(side, side, **geom)
    yields = np.empty(n_wafers)
    for k in range(n_wafers):
        dx, dy = sample_defects(rng, d0, layout["R"], alpha)
        yields[k] = 1.0 - killed_dies(layout, dx, dy).mean()
    return yields.mean(), yields.std(ddof=1) / np.sqrt(n_wafers), layout["count"]


def poisson_yield(die_area, d0):
    """Y = exp(-A*D0): every die sees the same average defect density."""
    return np.exp(-die_area / MM2_PER_CM2 * d0)


def neg_binomial_yield(die_area, d0, alpha):
    """
    Y = (1 + A*D0/alpha)^(-alpha): Poisson averaged over a Gamma-distributed
    density. This is the industry-standard model; clustering makes big dies
    yield better than plain Poisson predicts.
    """
    return (1.0 + die_area / MM2_PER_CM2 * d0 / alpha) ** (-alpha)


def model_yield(die_area, d0, alpha=None):
    return poisson_yield(die_area, d0) if alpha is None else neg_binomial_yield(die_area, d0, alpha)


# ---------------------------------------------------------------------------
# 4. Cost: monolithic die vs N chiplets
# ---------------------------------------------------------------------------

DEFAULTS = dict(
    wafer_cost=17000.0,      # USD per leading-edge 300 mm wafer (assumption; reported estimates vary)
    d0=0.10,                 # killer defects per cm^2 (assumption, mature leading-edge process)
    alpha=3.0,               # clustering parameter (assumption; 2-3 is commonly used)
    d2d_overhead=0.10,       # extra silicon each chiplet spends on die-to-die links (fraction)
    pkg_base=15.0,           # USD, basic package for any product
    pkg_per_chiplet=8.0,     # USD, extra substrate/test/handling per chiplet
    bond_yield=0.99,         # probability that attaching one die to the package succeeds
)


def product_cost(total_area, n_chiplets, wafer_cost, d0, alpha, d2d_overhead,
                 pkg_base, pkg_per_chiplet, bond_yield, dpw_cache=None):
    """
    Cost of one working product whose logic needs `total_area` mm^2 of silicon.

    n_chiplets = 1 : one monolithic die.
    n_chiplets > 1 : the design is split into n equal chiplets. Each chiplet
                     carries d2d_overhead extra area for the links between them.
                     Chiplets are tested before assembly (known-good-die), so we
                     only pay for good ones, but each attach can fail and a
                     failed assembly throws away every good die in it.

    Returns a dict with the cost breakdown (USD).
    """
    if n_chiplets == 1:
        die_area = total_area
    else:
        die_area = total_area * (1.0 + d2d_overhead) / n_chiplets

    side = np.sqrt(die_area)
    if dpw_cache is not None and round(die_area, 3) in dpw_cache:
        dpw = dpw_cache[round(die_area, 3)]
    else:
        dpw = place_dies(side, side, n_offsets=4)["count"]
        if dpw_cache is not None:
            dpw_cache[round(die_area, 3)] = dpw

    y = model_yield(die_area, d0, alpha)
    if dpw == 0 or y <= 0:
        return dict(total=np.inf)

    cost_good_die = wafer_cost / (dpw * y)
    silicon = n_chiplets * cost_good_die
    packaging = pkg_base + pkg_per_chiplet * (n_chiplets if n_chiplets > 1 else 0)
    assembly_yield = bond_yield ** n_chiplets
    total = (silicon + packaging) / assembly_yield
    return dict(total=total, silicon=silicon, packaging=packaging,
                assembly_loss=total - silicon - packaging,
                die_area=die_area, dpw=dpw, yield_=y, cost_good_die=cost_good_die)


def best_split(total_area, options=(1, 2, 4, 8), **params):
    """Return (best n, cost dict for each n)."""
    costs = {n: product_cost(total_area, n, **params) for n in options}
    n_best = min(costs, key=lambda n: costs[n]["total"])
    return n_best, costs
