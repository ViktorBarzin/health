#!/usr/bin/env python3
"""Compare the scraped Fitbod catalog against our seeded Exercise library.

Answers, for the later incorporation step (#-TBD):
  - vocabulary: Fitbod's muscle groups / equipment / level values
  - overlap: which Fitbod exercises already exist in free-exercise-db
    (matched with the SAME normalisation + alias rules as
    backend/app/services/matcher.py, reused by import)
  - gain: how many genuinely new exercises Fitbod would add

Run after `scrape_fitbod.py parse`:  python3 analyze_overlap.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.matcher import (  # noqa: E402  (path bootstrap above)
    ExerciseNameIndex,
    normalize_exercise_name,
)

import uuid  # noqa: E402


def main() -> None:
    scraped = json.loads((HERE / "fitbod_exercises.json").read_text())
    summaries = json.loads((HERE / "fitbod_summaries.json").read_text())
    library = json.loads(
        (BACKEND / "app" / "data" / "free_exercise_db.json").read_text()
    )

    exercises = scraped["exercises"]
    print(f"Fitbod detail records: {len(exercises)}")
    print(f"Fitbod summary-only:   {len(summaries)}")
    print(f"Library (free-exercise-db): {len(library)}")

    # --- vocabulary ---------------------------------------------------------
    muscles = Counter()
    equipment = Counter()
    levels = Counter()
    bodyweight = Counter()
    for ex in exercises.values():
        for m in ex.get("primaryMuscleGroups") or []:
            muscles[m] += 1
        for m in ex.get("secondaryMuscleGroups") or []:
            muscles[m] += 0  # register the label even if only secondary
        levels[ex.get("level")] += 1
        bodyweight[bool(ex.get("isBodyweight"))] += 1
        for eq in ex.get("equipment") or []:
            equipment[eq.get("name")] += 1

    print("\n-- muscle-group vocabulary (primary counts) --")
    for m, n in sorted(muscles.items()):
        print(f"  {m}: {n}")
    print(f"\n-- levels -- {dict(levels)}")
    print(f"-- bodyweight -- {dict(bodyweight)}")
    print(f"\n-- equipment vocabulary ({len(equipment)} kinds, top 25) --")
    for e, n in equipment.most_common(25):
        print(f"  {e}: {n}")

    # --- overlap vs library (matcher's own rules) ---------------------------
    index = ExerciseNameIndex(
        [(uuid.uuid4(), row["name"]) for row in sorted(library, key=lambda r: r["name"])]
    )
    fitbod_names = sorted(ex["name"] for ex in exercises.values())
    resolved, unresolved = index.resolve_all(fitbod_names)

    print(f"\n-- overlap (matcher normalise+alias) --")
    print(f"  matched into library:  {len(resolved)}")
    print(f"  NEW (not in library):  {len(unresolved)}")

    # library exercises Fitbod doesn't have (reverse view, exact-normalised)
    fitbod_norms = {normalize_exercise_name(n) for n in fitbod_names}
    lib_only = [
        row["name"]
        for row in library
        if normalize_exercise_name(row["name"]) not in fitbod_norms
    ]
    print(f"  library-only:          {len(lib_only)}")

    (HERE / "overlap_report.json").write_text(
        json.dumps(
            {
                "fitbod_detail_records": len(exercises),
                "fitbod_summary_only": len(summaries),
                "library_size": len(library),
                "matched": sorted(resolved),
                "new_from_fitbod": unresolved,
                "library_only": sorted(lib_only),
                "muscle_vocabulary": dict(sorted(muscles.items())),
                "equipment_vocabulary": dict(equipment.most_common()),
                "levels": dict(levels),
            },
            indent=1,
            ensure_ascii=False,
        )
    )
    print("\nwrote overlap_report.json")


if __name__ == "__main__":
    main()
