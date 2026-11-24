"""Circuit identity for chaos: seed file (curated) + CircuitProfile rows + trackmap geometry (derived). Idempotent.

Matching a stored schedule race to a circuit (CircuitIndex.match): the schedule row's `location` first, then its event
`name` (with and without "Grand Prix"), then a whole-word alias inside either. Texts are normalised (case, accents,
punctuation), and an alias that two circuits share never matches. An unmatched race is logged loudly (history.race_meta).
"""
import logging
import re
import unicodedata
from pathlib import Path

import yaml

from .models import CircuitProfile

logger = logging.getLogger(__name__)
SEED = Path(__file__).parent / "data" / "circuits.yaml"
PROFILE_FIELDS = ("name", "locations", "circuit_type", "circuit_key", "length_m", "corners", "wall_proximity",
                  "overtaking_index", "elevation_range_m")
MIN_CONTAINED_ALIAS = 5  # shorter aliases (e.g. "spa") only match exactly


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _strip_gp(n: str) -> str:
    return re.sub(r"\s*\bgrand prix\b\s*", " ", n).strip()


def load_seed(path=SEED) -> list[dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["circuits"]


class CircuitIndex:
    """profiles: {slug: dict(slug, name, locations, circuit_type, ...)}."""

    def __init__(self, profiles: dict):
        self.profiles = profiles
        owners = {}
        for slug, p in profiles.items():
            for a in [*p.get("locations", []), p.get("name", ""), slug.replace("-", " ")]:
                if norm(a):
                    owners.setdefault(norm(a), set()).add(slug)
        self.alias = {a: next(iter(s)) for a, s in owners.items() if len(s) == 1}  # shared aliases never match
        self.alias_gp = {_strip_gp(a): s for a, s in self.alias.items() if _strip_gp(a)}

    def match(self, location=None, name=None):
        """-> (profile dict, how) or (None, None). `how` says which text matched, for the log."""
        loc, nm = norm(location), norm(name)
        for label, text in (("location", loc), ("event name", nm)):
            if text and text in self.alias:
                return self.profiles[self.alias[text]], label
        if nm and _strip_gp(nm) in self.alias_gp:
            return self.profiles[self.alias_gp[_strip_gp(nm)]], "event name"
        for label, text in (("location", loc), ("event name", nm)):
            hits = {s for a, s in self.alias.items() if len(a) >= MIN_CONTAINED_ALIAS and text and re.search(rf"\b{re.escape(a)}\b", text)}
            if len(hits) == 1:
                return self.profiles[next(iter(hits))], f"{label} contains alias"
        return None, None


def load_index() -> CircuitIndex:
    """Seed file overlaid with CircuitProfile rows (a non-null DB value wins; aliases are unioned)."""
    profiles = {c["slug"]: {**c, "locations": list(c.get("locations", []))} for c in load_seed()}
    for row in CircuitProfile.objects.all():
        p = profiles.setdefault(row.slug, {"slug": row.slug, "locations": []})
        for f in PROFILE_FIELDS:
            v = getattr(row, f)
            if f == "locations":
                p["locations"] = list(dict.fromkeys([*p.get("locations", []), *(v or [])]))
            elif v is not None and v != "":
                p[f] = v
    return CircuitIndex(profiles)


def geometry_fields(circuit_key) -> dict:
    """Length (m) and corner count from the newest TrackGeometry for this key; {} when there is none."""
    from api.trackmap.models import TrackGeometry  # read-only use of the trackmap app

    g = TrackGeometry.objects.filter(circuit_key=circuit_key).order_by("-year", "-id").first()
    if g is None:
        return {}
    dist = (g.points or {}).get("distance") or []
    return {"length_m": round(dist[-1], 1) if dist else None, "corners": len(g.corners or []) or None}


def populate_circuit_profiles(seed=None) -> int:
    n = 0
    for c in seed if seed is not None else load_seed():
        fields = {k: c[k] for k in ("name", "locations", "circuit_type", "circuit_key", "wall_proximity",
                                    "overtaking_index", "elevation_range_m", "sources") if k in c}
        if c.get("circuit_key") is not None:
            fields.update(geometry_fields(c["circuit_key"]))
        CircuitProfile.objects.update_or_create(slug=c["slug"], defaults=fields)
        n += 1
    return n


# ---- linking circuit_key ---------------------------------------------------------------------------------------------

def _schedule_race(year, rnd) -> dict:
    from api.models import SeasonSchedule

    sched = SeasonSchedule.objects.filter(year=year).first()
    return next((r for r in (sched.payload.get("races", []) if sched else []) if r.get("round") == rnd), {})


def _link(slug, circuit_key) -> bool:
    """Set circuit_key (and length/corners) on the profile for slug, creating it from the seed if needed. Never overwrites a
    different existing key (logged). True when something changed."""
    index = load_index()
    seed = index.profiles.get(slug)
    if seed is None:
        return False
    prof, _ = CircuitProfile.objects.get_or_create(
        slug=slug, defaults={"name": seed.get("name", slug), "locations": seed.get("locations", []), "circuit_type": seed.get("circuit_type")})
    if prof.circuit_key is not None and prof.circuit_key != circuit_key:
        logger.warning("[chaos] circuit %s already linked to key %s, geometry says %s: left unchanged", slug, prof.circuit_key, circuit_key)
        return False
    changed = prof.circuit_key is None
    prof.circuit_key = circuit_key
    for k, v in geometry_fields(circuit_key).items():
        if v is not None and getattr(prof, k) != v:
            setattr(prof, k, v)
            changed = True
    if changed:
        prof.save()
    return changed


def link_geometry(geom) -> bool:
    """TrackGeometry -> CircuitProfile. trackmap records which race built a geometry in `source` ("<year> R<round> <session> ..."),
    so the schedule row of that race names the circuit. Called from the post_save signal and by link_circuit_keys."""
    m = re.match(r"\s*(\d{4}) R(\d+)", geom.source or "")
    if not m:
        return False
    race = _schedule_race(int(m[1]), int(m[2]))
    prof, how = load_index().match(race.get("location"), race.get("name"))
    if prof is None:
        logger.warning("[chaos] UNMATCHED CIRCUIT for track geometry %s (%s R%s: location=%r name=%r): add an alias to data/circuits.yaml",
                       geom.circuit_key, m[1], m[2], race.get("location"), race.get("name"))
        return False
    return _link(prof["slug"], geom.circuit_key)


def link_circuit_keys(year=None) -> int:
    """Backfill: link every stored TrackGeometry (and, for `year`, the trackmap cache pointer of each of its rounds) to its
    profile. Idempotent; returns the number of profiles changed."""
    from django.core.cache import caches

    from api.models import SeasonSchedule
    from api.trackmap.models import TrackGeometry
    from api.trackmap.service import built_key

    n = 0
    index = load_index()
    cache = caches["telemetry_cache"]
    years = [year] if year else list(SeasonSchedule.objects.values_list("year", flat=True))
    for y in years:
        for race in _schedule_race_list(y):
            ptr = cache.get(built_key(y, race.get("round")))
            prof, _ = index.match(race.get("location"), race.get("name")) if ptr else (None, None)
            if prof is not None:
                n += _link(prof["slug"], ptr[0])
    qs = TrackGeometry.objects.all() if not year else TrackGeometry.objects.filter(source__startswith=f"{year} ")
    for g in qs:
        n += link_geometry(g)
    return n


def _schedule_race_list(year) -> list:
    from api.models import SeasonSchedule

    sched = SeasonSchedule.objects.filter(year=year).first()
    return list(sched.payload.get("races", [])) if sched else []
