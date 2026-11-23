"""Deterministic persisted-telemetry fixture shaped like what populate_telemetry stores."""
import math

from api.models import DriverTelemetry

Y, R = 2025, 7
LAP_LEN = 5300.0


def lap_payload(driver_bias=0.0, n=400, with_time=False):
    """One realistic lap: columnar arrays, distance 0..LAP_LEN, speed with corners."""
    dist, speed, thr, brk, gear, rpm, drs, rel, sec, tt = [], [], [], [], [], [], [], [], [], []
    t = 0.0
    prev_d = 0.0
    for i in range(n):
        f = i / (n - 1)
        d = round(f * LAP_LEN, 3)
        v = round(210 + 90 * math.sin(f * 6 * math.pi) + driver_bias * (1 + math.cos(f * 2 * math.pi)) + 20 * f, 2)
        dist.append(d)
        speed.append(v)
        thr.append(round(max(0.0, min(100.0, 50 + 60 * math.sin(f * 6 * math.pi + 0.5))), 1))
        brk.append(bool(math.sin(f * 6 * math.pi + 0.5) < -0.8))
        gear.append(int(2 + round(6 * (v - 120) / 220)))
        rpm.append(int(8000 + 40 * v))
        drs.append(12 if 0.1 < f < 0.2 or 0.7 < f < 0.78 else 0)
        rel.append(round(f, 5))
        sec.append(1 if f < 1 / 3 else 2 if f < 2 / 3 else 3)
        t += (d - prev_d) / (max(v, 5.0) / 3.6)
        prev_d = d
        tt.append(round(t, 4))
    p = {"distance": dist, "speed": speed, "throttle": thr, "brake": brk, "gear": gear,
         "rpm": rpm, "drs": drs, "relative_distance": rel, "sector": sec}
    if with_time:
        p["elapsed_s"] = tt
    return p


def seed(with_time=False, session="R"):
    for code, bias in (("VER", 0.0), ("NOR", 6.0)):
        DriverTelemetry.objects.create(
            year=Y, round_number=R, session=session, driver_code=code,
            payload={"2": lap_payload(bias + 1, with_time=with_time),
                     "3": lap_payload(bias, with_time=with_time)},
        )
