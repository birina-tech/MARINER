"""
vessel_spec.py

Physical description of a vessel and the constants the dynamics model derives
from it. Size and weight are linked: displacement always follows from the
hull geometry (L x B x T x Cb x seawater density), so changing draft or
loading condition changes the mass the engine has to move.

IMPORTANT: the numbers in PRESETS are *illustrative*, chosen to be plausible
for each class and to land inside the IMO maneuvering criteria (see
maneuvering.py). They are NOT data for any specific ship. For a paper, replace
them with sourced values (sea trials, builder data) or pass overrides to
make_spec().

Dynamics model summary (implemented in ship.py):
  * Yaw:   nondimensional Nomoto model with a cubic (Norrbin) damping term,
           T' r' + r' + alpha r'^3 = K' delta, where r' = r L / U.
           K' sets the small-rudder response, T' the lag, and `alpha` is
           derived so that the steady turning diameter at full rudder equals
           `turn_diameter_ratio` x L.
  * Surge: m_eff du/dt = Thrust(rpm, u) - Resistance(u) * turn_drag.
           Steady speed is proportional to RPM%: u = (rpm/100) x max speed.
  * Actuators: rate-limited rudder and rate-limited engine order.
"""
import math
from dataclasses import dataclass, fields, replace, asdict

KN_TO_MS = 0.514444
RHO_SEAWATER = 1.025        # t/m^3
ETA_D = 0.65                # quasi-propulsive coefficient (delivered power -> thrust power)
SURGE_ADDED_MASS = 0.10     # added mass in surge, fraction of ship mass
STATIC_THRUST_GAIN = 0.5    # thrust at zero speed = (1 + this) x thrust at max speed
BALLAST_SPEED_GAIN = 1.04   # lighter ship, same power: slightly higher max speed

LOADINGS = ("laden", "ballast")

# Base (laden / design draft) values for each class.
PRESETS = {
    "tug": dict(
        name="Harbor tug",
        length=40.0, beam=12.0, draft=4.0, cb=0.50,
        max_speed_kn=12.0, power_kw=3000.0,
        k_prime=2.2, t_prime=0.9, turn_diameter_ratio=2.3,
        rudder_rate_deg_s=4.0, engine_ramp_pct_s=5.0,
        ballast_draft_factor=0.90,
    ),
    "coastal_cargo": dict(
        name="Coastal cargo ship",
        length=100.0, beam=17.0, draft=6.0, cb=0.75,
        max_speed_kn=12.0, power_kw=2500.0,
        k_prime=1.6, t_prime=1.8, turn_diameter_ratio=3.3,
        rudder_rate_deg_s=2.3, engine_ramp_pct_s=2.5,
        ballast_draft_factor=0.55,
    ),
    "panamax_bulker": dict(
        name="Panamax bulk carrier",
        length=230.0, beam=32.0, draft=12.0, cb=0.80,
        max_speed_kn=14.0, power_kw=9000.0,
        k_prime=1.4, t_prime=2.5, turn_diameter_ratio=4.0,
        rudder_rate_deg_s=2.3, engine_ramp_pct_s=1.5,
        ballast_draft_factor=0.50,
    ),
    "container_large": dict(
        name="Large container ship",
        length=366.0, beam=51.0, draft=14.5, cb=0.65,
        max_speed_kn=22.0, power_kw=45000.0,
        k_prime=1.4, t_prime=2.3, turn_diameter_ratio=3.9,
        rudder_rate_deg_s=2.3, engine_ramp_pct_s=1.0,
        ballast_draft_factor=0.70,
    ),
    "vlcc": dict(
        name="VLCC tanker",
        length=330.0, beam=60.0, draft=21.0, cb=0.83,
        max_speed_kn=15.0, power_kw=25000.0,
        k_prime=1.4, t_prime=3.2, turn_diameter_ratio=4.4,
        rudder_rate_deg_s=2.3, engine_ramp_pct_s=1.0,
        ballast_draft_factor=0.50,
    ),
}

DEFAULT_CLASS = "coastal_cargo"   # closest to the old fixed 100 m x 20 m ship


@dataclass(frozen=True)
class VesselSpec:
    class_id: str
    class_name: str
    loading: str
    length: float                 # L, m
    beam: float                   # B, m
    draft: float                  # T, m
    cb: float                     # block coefficient
    max_speed_kn: float           # steady speed at 100 % RPM
    power_kw: float               # installed (MCR) power
    k_prime: float                # Nomoto K' (small-rudder yaw gain)
    t_prime: float                # Nomoto T' (yaw lag)
    turn_diameter_ratio: float    # steady turning diameter / L at full rudder
    rudder_max_deg: float = 35.0
    rudder_rate_deg_s: float = 2.3
    engine_ramp_pct_s: float = 2.0
    rpm_astern_min: float = -50.0     # RPM% for full astern
    astern_ratio: float = 0.5         # full-astern thrust / static ahead thrust

    # ---- derived: weight ----
    @property
    def displacement_t(self):
        return RHO_SEAWATER * self.cb * self.length * self.beam * self.draft

    @property
    def mass_kg(self):
        return self.displacement_t * 1000.0

    @property
    def m_eff_kg(self):
        return self.mass_kg * (1.0 + SURGE_ADDED_MASS)

    # ---- derived: speed / thrust ----
    @property
    def max_speed_ms(self):
        return self.max_speed_kn * KN_TO_MS

    @property
    def service_speed_kn(self):
        """Default operating speed: 90 % of max, rounded to 0.5 kn."""
        return round(0.9 * self.max_speed_kn * 2.0) / 2.0

    @property
    def r_max_n(self):
        """Resistance (= thrust) at max speed, in newtons."""
        return ETA_D * self.power_kw * 1000.0 / self.max_speed_ms

    def resistance(self, u):
        s = u / self.max_speed_ms
        return self.r_max_n * s * s

    def thrust(self, n, u):
        """n = engine order as a fraction (RPM%/100); negative = astern."""
        a = STATIC_THRUST_GAIN
        if n >= 0.0:
            return self.r_max_n * ((1.0 + a) * n * n - a * n * u / self.max_speed_ms)
        na = n / (self.rpm_astern_min / 100.0)          # 0..1 across the astern range
        return -self.astern_ratio * (1.0 + a) * self.r_max_n * na * na

    def rpm_for_speed(self, speed_ms):
        """RPM% that holds `speed_ms` in steady state."""
        return 100.0 * speed_ms / self.max_speed_ms

    # ---- derived: yaw ----
    @property
    def alpha(self):
        """Cubic damping coefficient so the steady full-rudder turn matches
        turn_diameter_ratio. 0 if K' is too small to reach that rate."""
        r_nd = 2.0 / self.turn_diameter_ratio                   # r' = L / R
        k_delta = self.k_prime * math.radians(self.rudder_max_deg)
        if k_delta <= r_nd:
            return 0.0
        return (k_delta - r_nd) / (r_nd ** 3)

    # ---- serialization ----
    def to_dict(self):
        return asdict(self)

    def describe(self):
        """Compact summary for the UI."""
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "loading": self.loading,
            "length": self.length,
            "beam": self.beam,
            "draft": round(self.draft, 2),
            "displacement_t": round(self.displacement_t),
            "max_speed_kn": round(self.max_speed_kn, 1),
            "service_speed_kn": self.service_speed_kn,
        }


_FIELD_NAMES = {f.name for f in fields(VesselSpec)}


def _validate(spec):
    checks = [
        (10.0 <= spec.length <= 500.0, "length must be 10-500 m"),
        (2.0 <= spec.beam <= 100.0, "beam must be 2-100 m"),
        (1.0 <= spec.draft <= 30.0, "draft must be 1-30 m"),
        (0.3 <= spec.cb <= 1.0, "block coefficient must be 0.3-1.0"),
        (1.0 <= spec.max_speed_kn <= 40.0, "max speed must be 1-40 kn"),
        (spec.power_kw > 0, "power must be positive"),
        (spec.k_prime > 0 and spec.t_prime > 0, "K' and T' must be positive"),
        (spec.turn_diameter_ratio > 0.5, "turning diameter ratio must be > 0.5"),
        (0 < spec.rudder_max_deg <= 45, "max rudder must be in (0, 45] deg"),
        (spec.rudder_rate_deg_s > 0 and spec.engine_ramp_pct_s > 0, "actuator rates must be positive"),
        (-100.0 <= spec.rpm_astern_min < 0.0, "astern RPM limit must be in [-100, 0)"),
    ]
    for ok, message in checks:
        if not ok:
            raise ValueError(message)
    return spec


def make_spec(class_id=DEFAULT_CLASS, loading="laden", **overrides):
    """Build a VesselSpec from a preset, a loading condition and optional
    field overrides (e.g. length=120, max_speed_kn=15)."""
    if class_id not in PRESETS:
        raise ValueError(f"Unknown vessel class: {class_id}")
    if loading not in LOADINGS:
        raise ValueError(f"Unknown loading condition: {loading}")
    unknown = set(overrides) - _FIELD_NAMES
    if unknown:
        raise ValueError(f"Unknown spec field(s): {', '.join(sorted(unknown))}")

    p = dict(PRESETS[class_id])
    ballast_draft_factor = p.pop("ballast_draft_factor")
    params = dict(class_id=class_id, class_name=p.pop("name"), loading=loading, **p)
    if loading == "ballast":
        params["draft"] = params["draft"] * ballast_draft_factor
        params["max_speed_kn"] = params["max_speed_kn"] * BALLAST_SPEED_GAIN
    params.update(overrides)
    return _validate(VesselSpec(**params))


def spec_from_dict(data):
    """Rebuild a spec from a saved dict (scenario files). Missing fields fall
    back to the preset, so older files and partial dicts still load."""
    data = data or {}
    base = make_spec(data.get("class_id", DEFAULT_CLASS), data.get("loading", "laden"))
    known = {k: v for k, v in data.items() if k in _FIELD_NAMES}
    return _validate(replace(base, **known))


def list_classes():
    """Class catalogue for the UI: each class with per-loading summaries."""
    out = []
    for class_id, preset in PRESETS.items():
        entry = {
            "id": class_id,
            "name": preset["name"],
            "length": preset["length"],
            "beam": preset["beam"],
            "loadings": {},
        }
        for loading in LOADINGS:
            entry["loadings"][loading] = make_spec(class_id, loading).describe()
        out.append(entry)
    return out
