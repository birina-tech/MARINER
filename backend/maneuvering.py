"""
maneuvering.py

Standard ship-maneuvering trials, run on the same Ship model the simulator
uses (no separate model to drift out of sync):

  * turning_circle      - advance, transfer, tactical diameter at full rudder
  * crash_stop          - track reach and time from full ahead to dead in water
  * zigzag              - 10/10 zig-zag overshoot angles
  * initial_turning     - distance to change heading 10 deg with 10 deg rudder
  * imo_check           - compares the above with IMO criteria
  * characteristics     - cached summary shown in the UI / usable by autopilot

The IMO limits below are as I recall them from IMO MSC.137(76) (Standards for
ship maneuverability) and should be verified against the standard before being
cited in a paper:
    advance <= 4.5 L, tactical diameter <= 5 L,
    initial turning (10 deg rudder -> 10 deg heading) within 2.5 L,
    crash-stop track reach <= 15 L (the Administration may allow up to 20 L for
    very large ships), 10/10 zig-zag overshoot limits depending on L/V.
Trials are run at the vessel's service speed (the standard uses approach speed
~85 % of engine output), so results are indicative, not certification-grade.
"""
import math
from functools import lru_cache

from ship import Ship


def _ship(spec, speed_ms):
    s = Ship(0.0, 0.0, 0.0, speed_ms, spec=spec, register=False)
    return s


def _default_speed(spec, speed_ms):
    from vessel_spec import KN_TO_MS
    return speed_ms if speed_ms is not None else spec.service_speed_kn * KN_TO_MS


def turning_circle(spec, speed_ms=None, rudder_deg=None, dt=0.5, max_time=7200.0,
                   angles=(30, 45, 60, 90, 120, 150, 180)):
    """Full-rudder turn to starboard from steady straight running.

    Returns advance/transfer (m) at each heading change in `angles`, plus
    'tactical_diameter' (= transfer at 180 deg) and 'advance_90'."""
    speed_ms = _default_speed(spec, speed_ms)
    rudder_deg = spec.rudder_max_deg if rudder_deg is None else rudder_deg
    ship = _ship(spec, speed_ms)
    ship.rudder_cmd = rudder_deg
    sign = 1.0 if rudder_deg >= 0 else -1.0

    targets = sorted(angles)
    out = {}
    turned = 0.0
    prev_psi = ship.psi
    t = 0.0
    idx = 0
    while t < max_time and idx < len(targets):
        ship.update(dt)
        t += dt
        d = ship.psi - prev_psi
        d = math.atan2(math.sin(d), math.cos(d))
        turned += sign * math.degrees(d)
        prev_psi = ship.psi
        while idx < len(targets) and turned >= targets[idx]:
            out[targets[idx]] = {
                'advance': ship.y,
                'transfer': abs(ship.x),
                'time': t,
                'speed': ship.u,
            }
            idx += 1

    result = {'points': out, 'speed_ms': speed_ms}
    if 90 in out:
        result['advance_90'] = out[90]['advance']
    if 180 in out:
        result['tactical_diameter'] = out[180]['transfer']
        result['speed_loss_at_180'] = 1.0 - out[180]['speed'] / speed_ms if speed_ms else 0.0
    return result


def crash_stop(spec, speed_ms=None, dt=0.5, max_time=10800.0):
    """Full ahead -> full astern with rudder amidships, until dead in water."""
    speed_ms = _default_speed(spec, speed_ms)
    ship = _ship(spec, speed_ms)
    ship.rpm_cmd = spec.rpm_astern_min
    t = 0.0
    while t < max_time:
        ship.update(dt)
        t += dt
        if ship.u < 0.05:
            break
    return {'track_reach': ship.y, 'time': t, 'speed_ms': speed_ms,
            'stopped': ship.u < 0.05}


def zigzag(spec, speed_ms=None, rudder_deg=10.0, heading_deg=10.0, dt=0.5, max_time=7200.0):
    """10/10 zig-zag. Returns first and second overshoot angles (deg)."""
    speed_ms = _default_speed(spec, speed_ms)
    ship = _ship(spec, speed_ms)
    ship.rudder_cmd = rudder_deg
    phase = 1                   # 1: rudder to stbd, 2: to port, 3: to stbd again
    max1 = 0.0
    min2 = 0.0
    t = 0.0
    while t < max_time:
        ship.update(dt)
        t += dt
        psi = math.degrees(ship.psi)
        if phase == 1:
            if psi >= heading_deg:
                ship.rudder_cmd = -rudder_deg
                phase = 2
        elif phase == 2:
            max1 = max(max1, psi)
            if psi <= -heading_deg:
                ship.rudder_cmd = rudder_deg
                phase = 3
        elif phase == 3:
            min2 = min(min2, psi)
            if psi >= heading_deg:
                break
    return {'first_overshoot_deg': max(0.0, max1 - heading_deg),
            'second_overshoot_deg': max(0.0, -min2 - heading_deg),
            'completed': phase == 3}


def initial_turning(spec, speed_ms=None, rudder_deg=10.0, heading_deg=10.0, dt=0.5, max_time=3600.0):
    """Distance travelled until the heading has changed by `heading_deg`."""
    speed_ms = _default_speed(spec, speed_ms)
    ship = _ship(spec, speed_ms)
    ship.rudder_cmd = rudder_deg
    dist = 0.0
    t = 0.0
    while t < max_time:
        ship.update(dt)
        t += dt
        dist += ship.u * dt
        if math.degrees(ship.psi) >= heading_deg:
            break
    return {'distance': dist, 'time': t}


def _zigzag_limits(L, V):
    lv = L / V
    if lv < 10.0:
        return 10.0, 25.0
    if lv >= 30.0:
        return 20.0, 40.0
    return 5.0 + 0.5 * lv, 17.5 + 0.75 * lv


def imo_check(spec, speed_ms=None):
    """Run all trials and compare with the IMO criteria. Returns a dict of
    metrics (in metres / ship lengths / degrees) and pass flags."""
    speed_ms = _default_speed(spec, speed_ms)
    L = spec.length
    tc = turning_circle(spec, speed_ms)
    cs = crash_stop(spec, speed_ms)
    zz = zigzag(spec, speed_ms)
    it = initial_turning(spec, speed_ms)
    lim1, lim2 = _zigzag_limits(L, speed_ms)

    m = {
        'speed_kn': speed_ms / 0.514444,
        'advance_L': tc.get('advance_90', float('nan')) / L,
        'tactical_diameter_L': tc.get('tactical_diameter', float('nan')) / L,
        'speed_loss_at_180_pct': 100.0 * tc.get('speed_loss_at_180', float('nan')),
        'initial_turning_L': it['distance'] / L,
        'crash_stop_reach_L': cs['track_reach'] / L,
        'crash_stop_time_s': cs['time'],
        'zigzag_overshoot1_deg': zz['first_overshoot_deg'],
        'zigzag_overshoot1_limit': lim1,
        'zigzag_overshoot2_deg': zz['second_overshoot_deg'],
        'zigzag_overshoot2_limit': lim2,
    }
    m['pass'] = {
        'advance': m['advance_L'] <= 4.5,
        'tactical_diameter': m['tactical_diameter_L'] <= 5.0,
        'initial_turning': m['initial_turning_L'] <= 2.5,
        'crash_stop_15L': m['crash_stop_reach_L'] <= 15.0,
        'crash_stop_20L': m['crash_stop_reach_L'] <= 20.0,
        'zigzag_1': m['zigzag_overshoot1_deg'] <= lim1,
        'zigzag_2': m['zigzag_overshoot2_deg'] <= lim2,
    }
    return m


@lru_cache(maxsize=64)
def characteristics(spec):
    """Cached maneuvering summary for a spec (VesselSpec is hashable)."""
    tc = turning_circle(spec)
    cs = crash_stop(spec)
    return {
        'speed_kn': round(tc['speed_ms'] / 0.514444, 1),
        'tactical_diameter_m': round(tc.get('tactical_diameter', 0.0)),
        'advance_m': round(tc.get('advance_90', 0.0)),
        'stopping_distance_m': round(cs['track_reach']),
        'stopping_time_s': round(cs['time']),
    }


@lru_cache(maxsize=64)
def wheel_over_distances(spec, angles=(30, 45, 60, 90, 120, 180)):
    """Distance before a waypoint at which a full-rudder turn must start to
    end up on the new leg: d = Advance - Transfer * cot(angle).

    For angles >= 150 deg the geometry degenerates (the ship cannot end up on
    a reciprocal track through the waypoint), so the 180 deg entry is taken as
    1.25 x the 120 deg value - a heuristic, only used for U-turn legs."""
    tc = turning_circle(spec, angles=(30, 45, 60, 90, 120))
    pts = tc['points']
    table = {}
    for a in angles:
        if a in pts:
            adv, tr = pts[a]['advance'], pts[a]['transfer']
            cot = 0.0 if a == 90 else 1.0 / math.tan(math.radians(a))
            table[a] = max(adv - tr * cot, 0.5 * spec.length)
    if 180 in angles:
        table[180] = 1.25 * table.get(120, max(table.values()))
    return table
