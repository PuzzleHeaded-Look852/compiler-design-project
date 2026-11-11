"""The heart of Lumen: dimensions, units and the unit table.

DIMENSION  = the kind of quantity (length, time, speed, ...).
             Stored as a sorted tuple of (base_unit, exponent) pairs with
             non-zero exponents, e.g. speed = (("m", 1), ("s", -1)).
             The empty tuple () means "dimensionless" (a plain number).
UNIT       = a dimension plus a SCALE FACTOR to the base units.
             km = length with scale 1000, h = time with scale 3600.
             Scales are exact Fractions so conversions never drift.

Dimension algebra (this is what the checker uses on every expression):
    a * b   -> add the exponents          m * m    = m^2
    a / b   -> subtract the exponents     m / s    = m s^-1
    a ^ n   -> multiply exponents by n    s ^ -1   = s^-1
    a + b   -> exponents must be equal    m + s    -> error

Base units are m (length), kg (mass), s (time) and bit (data). A program can
declare more with `unit INR;`. Because two different base units have
different dimensions, INR and USD can never be added or converted by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

Dim = tuple  # tuple[tuple[str, int], ...]

ZERO: Dim = ()


# ---------------------------------------------------------------- dimension algebra
def _norm(d: dict) -> Dim:
    return tuple(sorted((k, v) for k, v in d.items() if v != 0))


def dim_mul(a: Dim, b: Dim) -> Dim:
    out = dict(a)
    for k, v in b:
        out[k] = out.get(k, 0) + v
    return _norm(out)


def dim_div(a: Dim, b: Dim) -> Dim:
    out = dict(a)
    for k, v in b:
        out[k] = out.get(k, 0) - v
    return _norm(out)


def dim_pow(a: Dim, n: int) -> Dim:
    return _norm({k: v * n for k, v in a})


def D(**kw: int) -> Dim:
    return _norm(kw)


# Names for common dimensions, used in error messages and suggestions.
BASE_DIM_NAMES = {"m": "length", "kg": "mass", "s": "time", "bit": "data"}

NAMED_DIMS: dict[Dim, str] = {
    D(m=1): "length", D(kg=1): "mass", D(s=1): "time", D(bit=1): "data",
    D(m=2): "area", D(m=3): "volume",
    D(m=1, s=-1): "speed", D(m=1, s=-2): "acceleration", D(s=-1): "rate per time",
    D(m=1, kg=1, s=-2): "force", D(m=1, kg=1, s=-1): "impulse",
    D(m=2, kg=1, s=-2): "energy", D(m=2, kg=1, s=-3): "power",
    D(m=-1, kg=1, s=-2): "pressure", D(m=-3, kg=1): "density",
    D(bit=1, s=-1): "data rate", D(m=3, s=-1): "volume flow rate",
    D(kg=1, s=-1): "mass flow rate",
}


# ---------------------------------------------------------------- units
@dataclass(frozen=True)
class Unit:
    name: str
    dim: Dim
    scale: Fraction          # how many base units one of this unit is
    kind: str = "user"       # "base", "builtin" or "user"


PREFIXES = {
    "n": Fraction(1, 10**9), "u": Fraction(1, 10**6), "m": Fraction(1, 1000),
    "c": Fraction(1, 100), "k": Fraction(1000), "M": Fraction(10**6),
    "G": Fraction(10**9),
}
PREFIXABLE = ("m", "s", "g", "bit")   # prefixes may attach to these names


class UnitTable:
    """All units known to the program: built-ins, SI prefixes, user declarations."""

    def __init__(self):
        self.units: dict[str, Unit] = {}
        self.order: list[str] = []                       # declaration order
        self.base_names: dict[str, str] = dict(BASE_DIM_NAMES)
        for sym in ("m", "kg", "s", "bit"):
            self._put(Unit(sym, D(**{sym: 1}), Fraction(1), "base"))
        self._put(Unit("g", D(kg=1), Fraction(1, 1000), "builtin"))

    def _put(self, u: Unit):
        self.units[u.name] = u
        self.order.append(u.name)

    # -- lookup
    def lookup(self, name: str) -> Unit | None:
        """Exact name first; otherwise try SI prefix + prefixable unit (km, ms, mg)."""
        if name in self.units:
            return self.units[name]
        if len(name) >= 2 and name[0] in PREFIXES:
            rest = name[1:]
            if rest in PREFIXABLE and rest in self.units:
                base = self.units[rest]
                return Unit(name, base.dim, PREFIXES[name[0]] * base.scale, "builtin")
        return None

    def declare(self, u: Unit):
        self._put(u)

    def declare_base(self, name: str):
        """`unit INR;` creates a brand-new base dimension."""
        self.base_names[name] = name
        self._put(Unit(name, D(**{name: 1}), Fraction(1), "base"))

    # -- naming things for messages
    def dim_name(self, dim: Dim) -> str:
        if dim == ZERO:
            return "plain number"
        if dim in NAMED_DIMS:
            return NAMED_DIMS[dim]
        if len(dim) == 1 and dim[0][1] == 1 and dim[0][0] in self.base_names:
            return self.base_names[dim[0][0]]
        pos = [self._pow_name(k, v) for k, v in dim if v > 0]
        neg = [self._pow_name(k, -v) for k, v in dim if v < 0]
        top = "*".join(pos) if pos else "1"
        return top + ("/" + "*".join(neg) if neg else "")

    def _pow_name(self, k: str, e: int) -> str:
        n = self.base_names.get(k, k)
        return n if e == 1 else f"{n}^{e}"

    def label_for(self, dim: Dim, scale: Fraction) -> str | None:
        """A unit name with exactly this dimension and scale, if any exists."""
        if dim == ZERO:
            return None
        for name in self.order:                      # declared units first
            u = self.units[name]
            if u.dim == dim and u.scale == scale and u.kind != "base":
                return name
        for name in self.order:
            u = self.units[name]
            if u.dim == dim and u.scale == scale:
                return name
        if len(dim) == 1 and dim[0][1] == 1:         # km, ms, ... from prefixes
            for sym in PREFIXABLE:
                base = self.units.get(sym)
                if base and base.dim == dim:
                    for p, f in PREFIXES.items():
                        if f * base.scale == scale:
                            return p + sym
        return None

    def si_label(self, dim: Dim) -> str:
        """Composite label in base units, e.g. kg*m/s^2."""
        def fmt(k, e):
            return k if e == 1 else f"{k}^{e}"
        pos = [fmt(k, v) for k, v in sorted(dim, key=lambda kv: _order_key(kv[0])) if v > 0]
        neg = [fmt(k, -v) for k, v in sorted(dim, key=lambda kv: _order_key(kv[0])) if v < 0]
        top = "*".join(pos) if pos else "1"
        if not neg:
            return top
        den = "*".join(neg)
        return f"{top}/{den}" if len(neg) == 1 else f"{top}/({den})"

    def display(self, dim: Dim, scale: Fraction) -> str:
        """Best printable unit for a quantity, or '' if it needs conversion."""
        return self.label_for(dim, scale) or ""

    def all_names(self) -> list[str]:
        names = list(self.units)
        for sym in PREFIXABLE:
            for p in PREFIXES:
                names.append(p + sym)
        return names


def _order_key(sym: str):
    order = ["kg", "m", "s", "bit"]
    return (order.index(sym), sym) if sym in order else (len(order), sym)


# ---------------------------------------------------------------- "did you mean?"
def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def closest(name: str, candidates) -> str | None:
    """The most similar candidate name, if it is close enough to be a typo."""
    best, best_d = None, 99
    for c in candidates:
        if c == name:
            continue
        d = edit_distance(name.lower(), c.lower())
        if d < best_d:
            best, best_d = c, d
    limit = 1 if len(name) <= 2 else 2
    return best if best is not None and best_d <= limit else None
