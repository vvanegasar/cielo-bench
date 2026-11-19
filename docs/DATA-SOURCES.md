# Data sources, terms and credits

Checked on 2026-10-20. Re-verify the terms before each public release.

| Source | Used for | Access | Limits and terms | Credit required |
|---|---|---|---|---|
| **JPL Horizons API** — `https://ssd.jpl.nasa.gov/api/horizons.api` | Ephemerides: positions, rise and set, Moon | No key | **JPL SSD Fair Use Policy:** one request at a time (no parallel requests); cache results; send a User-Agent with app name, version and contact; no browser embedding (CORS); no availability guarantee | NASA/JPL Solar System Dynamics |
| **SIMBAD TAP (CDS)** — `https://simbad.cds.unistra.fr/simbad/sim-tap/sync` | Object facts | No key | About 10 queries/s per IP; bursts above that are temporarily blocked; max 50,000 objects per query | "This research has made use of the SIMBAD database, CDS, Strasbourg, France" |

## Considered and excluded from v0

| Source | Reason |
|---|---|
| api.nasa.gov (APOD, DONKI, …) | Several endpoints failed on 2026-10-20 (500, 503 and 404). Not reliable enough for ground truth |
| NASA Exoplanet Archive (TAP) | Returned HTTP 526 twice on 2026-10-20. Reconsider for v1 |
| ESA Gaia Archive | License is CC BY-NC 3.0 IGO (non-commercial). Excluded to keep the project license-clean |
| Minor Planet Center API | Uses GET with a JSON body, which `fetch` does not support. Revisit later |

## Our obligations
- An honest User-Agent. Since v1 it is `cielo-bench/<version> (non-commercial research benchmark)`, without personal data (ADR-0005 §8). Once the repository is public its URL may be added; a personal email is not.
- A queue for JPL requests (concurrency of 1) plus a cache keyed by normalized query.
- Credits in the README and in every report.
- No claim or suggestion of endorsement by NASA, JPL, CDS or ESA. No agency logos.
