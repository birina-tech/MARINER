"""
tools/validate_dynamics.py

Runs the standard maneuvering trials on every vessel class and loading
condition and prints the results next to the IMO criteria (as recalled in
backend/maneuvering.py: verify the limits against IMO MSC.137(76) before
citing them). Exit code 1 if any class fails a criterion.

Run from the repository root:
    python tools/validate_dynamics.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from vessel_spec import make_spec, PRESETS, LOADINGS  # noqa: E402
from maneuvering import imo_check                      # noqa: E402

HEADER = (f"{'class':16s} {'loading':8s} {'tons':>8s} {'kn':>5s} {'adv/L':>6s} {'TD/L':>6s} "
          f"{'init/L':>7s} {'stop/L':>7s} {'stop min':>8s} {'zz1':>11s} {'zz2':>11s}  result")


def main():
    print(HEADER)
    all_ok = True
    for class_id in PRESETS:
        for loading in LOADINGS:
            spec = make_spec(class_id, loading)
            m = imo_check(spec)
            # crash stop is judged against 15 L (up to 20 L may be accepted for very large ships)
            ok = all(v for k, v in m['pass'].items() if k != 'crash_stop_20L')
            all_ok &= ok
            print(f"{class_id:16s} {loading:8s} {spec.displacement_t:8.0f} {m['speed_kn']:5.1f} "
                  f"{m['advance_L']:6.2f} {m['tactical_diameter_L']:6.2f} {m['initial_turning_L']:7.2f} "
                  f"{m['crash_stop_reach_L']:7.1f} {m['crash_stop_time_s'] / 60:8.1f} "
                  f"{m['zigzag_overshoot1_deg']:5.1f}/{m['zigzag_overshoot1_limit']:4.1f} "
                  f"{m['zigzag_overshoot2_deg']:5.1f}/{m['zigzag_overshoot2_limit']:4.1f}  "
                  f"{'PASS' if ok else 'FAIL'}")
    print("\nAll classes within criteria." if all_ok else "\nSome classes outside criteria.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
