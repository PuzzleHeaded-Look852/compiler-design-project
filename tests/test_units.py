from fractions import Fraction

from lumen.units import D, UnitTable, closest, dim_div, dim_mul, dim_pow, edit_distance


def test_dimension_algebra():
    speed = dim_div(D(m=1), D(s=1))
    assert speed == D(m=1, s=-1)
    assert dim_mul(speed, D(s=1)) == D(m=1)
    assert dim_pow(D(s=1), -2) == D(s=-2)
    assert dim_div(D(m=1), D(m=1)) == ()


def test_force_dimension():
    force = dim_mul(D(kg=1), dim_div(D(m=1), dim_pow(D(s=1), 2)))
    assert force == D(m=1, kg=1, s=-2)


def test_prefixes():
    t = UnitTable()
    assert t.lookup("km").scale == 1000 and t.lookup("km").dim == D(m=1)
    assert t.lookup("mg").scale == Fraction(1, 10**6)       # 1e-3 g = 1e-6 kg
    assert t.lookup("ms").scale == Fraction(1, 1000)
    assert t.lookup("ug").scale == Fraction(1, 10**9)
    assert t.lookup("Mbit").scale == 10**6
    assert t.lookup("furlong") is None


def test_no_prefix_on_arbitrary_units():
    t = UnitTable()
    assert t.lookup("mh") is None


def test_new_base_unit_is_its_own_dimension():
    t = UnitTable()
    t.declare_base("INR")
    t.declare_base("USD")
    assert t.lookup("INR").dim != t.lookup("USD").dim


def test_dim_names():
    t = UnitTable()
    assert t.dim_name(D(m=1, s=-1)) == "speed"
    assert t.dim_name(D(m=2)) == "area"
    assert t.dim_name(()) == "plain number"


def test_edit_distance_and_closest():
    assert edit_distance("kitten", "sitting") == 3
    assert closest("mtr", ["m", "kg", "s"]) == "m"
    assert closest("qqqq", ["m", "kg"]) is None
