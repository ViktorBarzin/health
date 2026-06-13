"""Seed the Principles knowledge base with cited exercise-science rules.

ADR-0004: the deterministic Program generator composes *only* from Principles, so
every training parameter it prescribes traces to a rule backed by peer-reviewed
evidence. This module is the authored content of that KB — the eight rules the
engine actually needs, each with a citation **verified against the primary
literature** (PubMed / DOI) at authoring time, not trusted from memory.

Unlike the ~870-row Exercise library (a vendored dataset file), the KB is a
small, hand-authored, citation-checked document — so it lives in code as
:data:`PRINCIPLES` rather than a JSON file. The data is human-reviewed (Viktor);
accuracy is the point.

Seeding is idempotent: it upserts each Principle keyed on its stable ``key`` and
reconciles its citations, so re-running on every boot (invoked from
``entrypoint.sh`` after ``alembic upgrade head``) adds nothing duplicated and
flows authoring edits through. Runnable manually via
``python -m app.services.seed_principles``.

Citation verification log (each confirmed via PubMed/DOI on 2026-06-13)
=======================================================================
* volume — Schoenfeld, Ogborn & Krieger 2017, J Sports Sci 35(11):1073-1082,
  DOI 10.1080/02640414.2016.1210197, PMID 27433992. Graded dose-response;
  10+ sets/muscle/wk > lower volumes. (grade A)
* frequency — Schoenfeld, Ogborn & Krieger 2016, Sports Med 46(11):1689-1697,
  DOI 10.1007/s40279-016-0543-8, PMID 27102172. 2×/wk > 1×/wk for hypertrophy.
  (grade A)
* effort — Refalo, Helms, Trexler, Hamilton & Fyfe 2023, Sports Med
  53(3):649-665, DOI 10.1007/s40279-022-01784-y, PMID 36334240. Training to
  momentary failure is NOT required; non-linear proximity-to-failure effect →
  train near (not necessarily to) failure. (grade B — the "not required" half is
  firmly supported; a clean closer-is-better gradient is not, noted in ``notes``)
* periodization — Williams, Tolusso, Fedewa & Esco 2017, Sports Med
  47(10):2083-2100, DOI 10.1007/s40279-017-0734-y, PMID 28497285. Periodized >
  non-periodized for 1RM (ES 0.43). (grade A)
* progressive overload — ACSM Position Stand 2009, Med Sci Sports Exerc
  41(3):687-708, DOI 10.1249/MSS.0b013e3181915670, PMID 19204579 (progression is
  necessary; +2-10% load when reps exceed target), supported by Plotkin et al.
  2022, PeerJ 10:e14142, DOI 10.7717/peerj.14142, PMID 36199287 (load- and
  rep-progression both viable). (grade B)
* protein — Morton et al. 2018, Br J Sports Med 52(6):376-384,
  DOI 10.1136/bjsports-2017-097608, PMID 28698222. Breakpoint 1.62 g/kg/day
  (95% CI 1.03-2.20) for RT-induced FFM gains. (grade A)
* rest — Schoenfeld et al. 2016, J Strength Cond Res 30(7):1805-1812,
  DOI 10.1519/JSC.0000000000001272, PMID 26605807. 3-min > 1-min rest for
  strength and (anterior-thigh) hypertrophy in trained men. (grade B — one RCT;
  broader literature more equivocal, noted in ``notes``)
* deload — Bell, Nolan, Immonen, Helms, Dallamore, Wolf & Androulakis Korakakis
  2022, Front Sports Act Living 4:1073223, DOI 10.3389/fspor.2022.1073223,
  PMID 36619355. Coaches use planned reduced-load periods for fatigue management.
  (grade C — qualitative coach-opinion evidence, noted in ``notes``)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.principle import (
    EvidenceGrade,
    ExperienceLevel,
    Principle,
    PrincipleCategory,
    PrincipleCitation,
    TrainingGoal,
)

# Goal sets reused below (muscle-gain rules apply to bulk + maintain + strength;
# protein-for-gain excludes a cut, where intake guidance differs).
_GAIN_GOALS = [TrainingGoal.bulk, TrainingGoal.maintain, TrainingGoal.strength]
_ALL_LEVELS = [
    ExperienceLevel.beginner,
    ExperienceLevel.intermediate,
    ExperienceLevel.advanced,
]


@dataclass(frozen=True)
class CitationSeed:
    """An authored, verified citation for a Principle."""

    authors: str
    year: int
    title: str
    journal: str
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class PrincipleSeed:
    """One authored Principle plus its verified citation(s).

    ``params`` is the typed-range dict the generator reads (``{name: {min, max,
    unit}}``); ``goals``/``experience_levels`` are the applicability sets (empty ⇒
    applies to all). Stored values are the enum *values* (strings) so they land in
    JSONB as the same labels the query layer matches on.
    """

    key: str
    statement: str
    category: PrincipleCategory
    evidence_grade: EvidenceGrade
    params: dict = field(default_factory=dict)
    goals: list[TrainingGoal] = field(default_factory=list)
    experience_levels: list[ExperienceLevel] = field(default_factory=list)
    notes: str | None = None
    citations: tuple[CitationSeed, ...] = ()


# --------------------------------------------------------------------------- #
# The knowledge base. Eight rules, each citation verified against the primary
# literature (see the module docstring's verification log).
# --------------------------------------------------------------------------- #
PRINCIPLES: tuple[PrincipleSeed, ...] = (
    PrincipleSeed(
        key="volume-dose-response",
        statement=(
            "Weekly training volume has a graded dose-response relationship with "
            "muscle hypertrophy: roughly 10-20 hard sets per muscle per week "
            "drives growth, with more generally better up to a point before "
            "recoverability limits returns."
        ),
        category=PrincipleCategory.volume,
        evidence_grade=EvidenceGrade.A,
        params={
            "sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"},
        },
        # Applies whenever the goal involves building/keeping muscle (not a cut's
        # primary concern) across all experience levels.
        goals=[g.value for g in _GAIN_GOALS],
        experience_levels=[],
        citations=(
            CitationSeed(
                authors="Schoenfeld BJ, Ogborn D, Krieger JW",
                year=2017,
                title=(
                    "Dose-response relationship between weekly resistance "
                    "training volume and increases in muscle mass: A systematic "
                    "review and meta-analysis"
                ),
                journal="Journal of Sports Sciences",
                doi="10.1080/02640414.2016.1210197",
                pmid="27433992",
            ),
        ),
    ),
    PrincipleSeed(
        key="training-frequency",
        statement=(
            "Training a muscle at least twice per week produces superior "
            "hypertrophy compared with once per week; weekly volume is best split "
            "across two or more sessions per muscle."
        ),
        category=PrincipleCategory.frequency,
        evidence_grade=EvidenceGrade.A,
        params={
            "sessions_per_muscle_per_week": {"min": 2, "unit": "sessions"},
        },
        goals=[g.value for g in _GAIN_GOALS],
        experience_levels=[],
        citations=(
            CitationSeed(
                authors="Schoenfeld BJ, Ogborn D, Krieger JW",
                year=2016,
                title=(
                    "Effects of Resistance Training Frequency on Measures of "
                    "Muscle Hypertrophy: A Systematic Review and Meta-Analysis"
                ),
                journal="Sports Medicine",
                doi="10.1007/s40279-016-0543-8",
                pmid="27102172",
            ),
        ),
    ),
    PrincipleSeed(
        key="effort-proximity-to-failure",
        statement=(
            "Train most working sets close to failure (about 0-3 reps in "
            "reserve) to stimulate hypertrophy, but training every set to "
            "momentary failure is not required for maximal gains and adds fatigue."
        ),
        category=PrincipleCategory.intensity,
        evidence_grade=EvidenceGrade.B,
        params={
            "reps_in_reserve": {"min": 0, "max": 3, "unit": "RIR"},
        },
        goals=[],  # effort guidance applies across goals
        experience_levels=[],
        notes=(
            "Refalo et al. 2023 firmly support that training to momentary "
            "failure is NOT required for maximal hypertrophy and report a "
            "non-linear proximity-to-failure relationship; a clean "
            "'closer-is-always-better' gradient is not established, hence the "
            "0-3 RIR working range rather than 'always 0 RIR' and a grade of B."
        ),
        citations=(
            CitationSeed(
                authors="Refalo MC, Helms ER, Trexler ET, Hamilton DL, Fyfe JJ",
                year=2023,
                title=(
                    "Influence of Resistance Training Proximity-to-Failure on "
                    "Skeletal Muscle Hypertrophy: A Systematic Review with "
                    "Meta-analysis"
                ),
                journal="Sports Medicine",
                doi="10.1007/s40279-022-01784-y",
                pmid="36334240",
            ),
        ),
    ),
    PrincipleSeed(
        key="periodization",
        statement=(
            "Periodized resistance training (systematically varying volume and "
            "intensity over a block) produces greater maximal-strength gains than "
            "non-periodized training."
        ),
        category=PrincipleCategory.periodization,
        evidence_grade=EvidenceGrade.A,
        params={
            # The mesocycle block length a periodized plan organises around.
            "mesocycle_weeks": {"min": 4, "max": 8, "unit": "weeks"},
        },
        # Strongest, most directly evidenced for the strength goal; also sound for
        # muscle-gain blocks. Intermediate+ benefit most from structured variation.
        goals=[TrainingGoal.strength.value, TrainingGoal.bulk.value],
        experience_levels=[
            ExperienceLevel.intermediate.value,
            ExperienceLevel.advanced.value,
        ],
        citations=(
            CitationSeed(
                authors="Williams TD, Tolusso DV, Fedewa MV, Esco MR",
                year=2017,
                title=(
                    "Comparison of Periodized and Non-Periodized Resistance "
                    "Training on Maximal Strength: A Meta-Analysis"
                ),
                journal="Sports Medicine",
                doi="10.1007/s40279-017-0734-y",
                pmid="28497285",
            ),
        ),
    ),
    PrincipleSeed(
        key="progressive-overload",
        statement=(
            "To keep adapting, the training stimulus must progress over time: add "
            "load or reps as a weight becomes easier. Increasing load and "
            "increasing reps are both effective ways to apply overload."
        ),
        category=PrincipleCategory.progression,
        evidence_grade=EvidenceGrade.B,
        params={
            # The +2-10% load step the ACSM stand recommends once reps exceed the
            # target — the generator's progression increment window.
            "load_increase_percent": {"min": 2, "max": 10, "unit": "%"},
        },
        goals=[],  # a universal training principle
        experience_levels=[],
        notes=(
            "Primary authority is the ACSM Position Stand (consensus that "
            "progression is necessary and the +2-10% load rule); Plotkin et al. "
            "2022 (an RCT) supports that load- and rep-progression are both "
            "viable, not that progression is optional. Grade B: strong consensus "
            "plus a clean RCT on the mode of progression, not a single definitive "
            "RCT on necessity."
        ),
        citations=(
            CitationSeed(
                authors="American College of Sports Medicine (Ratamess NA, et al.)",
                year=2009,
                title=(
                    "American College of Sports Medicine position stand. "
                    "Progression models in resistance training for healthy adults"
                ),
                journal="Medicine & Science in Sports & Exercise",
                doi="10.1249/MSS.0b013e3181915670",
                pmid="19204579",
            ),
            CitationSeed(
                authors="Plotkin D, Coleman M, Van Every D, et al.",
                year=2022,
                title=(
                    "Progressive overload without progressing load? The effects "
                    "of load or repetition progression on muscular adaptations"
                ),
                journal="PeerJ",
                doi="10.7717/peerj.14142",
                pmid="36199287",
            ),
        ),
    ),
    PrincipleSeed(
        key="protein-intake",
        statement=(
            "To maximise resistance-training gains in muscle mass, aim for roughly "
            "1.6-2.2 g of protein per kg bodyweight per day; intake beyond about "
            "1.6 g/kg/day yields no further average benefit."
        ),
        category=PrincipleCategory.nutrition,
        evidence_grade=EvidenceGrade.A,
        params={
            "protein_g_per_kg_per_day": {"min": 1.6, "max": 2.2, "unit": "g/kg/day"},
        },
        # Muscle-gain / maintenance / strength goals; a cut uses higher,
        # separately-evidenced targets, so it's excluded here.
        goals=[g.value for g in _GAIN_GOALS],
        experience_levels=[],
        notes=(
            "Morton et al. 2018 found a breakpoint at 1.62 g/kg/day (95% CI "
            "1.03-2.20) beyond which protein supplementation gave no further "
            "RT-induced fat-free-mass gains; the 1.6-2.2 range spans the point "
            "estimate to the upper CI bound."
        ),
        citations=(
            CitationSeed(
                authors=(
                    "Morton RW, Murphy KT, McKellar SR, Schoenfeld BJ, "
                    "Henselmans M, Helms E, Aragon AA, Devries MC, Banfield L, "
                    "Krieger JW, Phillips SM"
                ),
                year=2018,
                title=(
                    "A systematic review, meta-analysis and meta-regression of "
                    "the effect of protein supplementation on resistance "
                    "training-induced gains in muscle mass and strength in "
                    "healthy adults"
                ),
                journal="British Journal of Sports Medicine",
                doi="10.1136/bjsports-2017-097608",
                pmid="28698222",
            ),
        ),
    ),
    PrincipleSeed(
        key="rest-intervals",
        statement=(
            "Rest about 2-3 minutes between sets of compound lifts: longer "
            "inter-set rest supports greater strength and hypertrophy than short "
            "(~1 minute) rests by preserving performance across sets."
        ),
        category=PrincipleCategory.rest,
        evidence_grade=EvidenceGrade.B,
        params={
            "rest_seconds_compound": {"min": 120, "max": 180, "unit": "seconds"},
        },
        goals=[],
        experience_levels=[],
        notes=(
            "Schoenfeld et al. 2016 (RCT in trained men) found 3-min > 1-min rest "
            "for strength and anterior-thigh hypertrophy; the broader rest-interval "
            "literature is more equivocal for hypertrophy specifically, hence "
            "grade B and a 2-3 min range rather than a hard 3-min rule."
        ),
        citations=(
            CitationSeed(
                authors="Schoenfeld BJ, Pope ZK, Benik FM, et al., Krieger JW",
                year=2016,
                title=(
                    "Longer Interset Rest Periods Enhance Muscle Strength and "
                    "Hypertrophy in Resistance-Trained Men"
                ),
                journal="Journal of Strength and Conditioning Research",
                doi="10.1519/JSC.0000000000001272",
                pmid="26605807",
            ),
        ),
    ),
    PrincipleSeed(
        key="deload",
        statement=(
            "Schedule planned deloads — short periods of reduced training load or "
            "volume (commonly every 4-8 weeks) — to manage accumulated fatigue and "
            "support long-term progress and recovery."
        ),
        category=PrincipleCategory.deload,
        evidence_grade=EvidenceGrade.C,
        params={
            "weeks_between_deloads": {"min": 4, "max": 8, "unit": "weeks"},
            "deload_load_reduction_percent": {"min": 40, "max": 60, "unit": "%"},
        },
        goals=[],
        experience_levels=[],
        notes=(
            "Evidence is limited and indirect: Bell et al. 2022 is qualitative "
            "research on how strength/physique coaches use deloads (fatigue "
            "management, injury/burnout reduction), not an outcome RCT. Grade C. "
            "The 4-8 week cadence and ~40-60% load reduction reflect common coach "
            "practice described there and standard mesocycle structure, not a "
            "measured optimum."
        ),
        citations=(
            CitationSeed(
                authors=(
                    "Bell L, Nolan D, Immonen V, Helms E, Dallamore J, Wolf M, "
                    "Androulakis Korakakis P"
                ),
                year=2022,
                title=(
                    "\"You can't shoot another bullet until you've reloaded the "
                    "gun\": Coaches' perceptions, practices and experiences of "
                    "deloading in strength and physique sports"
                ),
                journal="Frontiers in Sports and Active Living",
                doi="10.3389/fspor.2022.1073223",
                pmid="36619355",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class SeedResult:
    """Outcome of one seed run, for logging and tests."""

    inserted: int
    updated: int
    total: int


def _apply_fields(
    principle: Principle, seed: PrincipleSeed, *, is_new: bool
) -> None:
    """Copy the scalar/JSON fields from a seed onto a Principle row.

    For an existing row, bumps ``version`` when the rule's substance (statement,
    params, applicability, grade) changed, so a consumer can detect an evolved
    rule; an unchanged re-seed leaves the version alone. A freshly-inserted row
    keeps its initial version 1 (the empty starting state is not a "change").
    ``updated_at`` is maintained by the DB.
    """
    new_params = dict(seed.params)
    new_goals = list(seed.goals)
    new_levels = list(seed.experience_levels)
    changed = not is_new and (
        principle.statement != seed.statement
        or principle.category != seed.category
        or principle.params != new_params
        or principle.goals != new_goals
        or principle.experience_levels != new_levels
        or principle.evidence_grade != seed.evidence_grade
        or principle.notes != seed.notes
    )
    principle.statement = seed.statement
    principle.category = seed.category
    principle.params = new_params
    principle.goals = new_goals
    principle.experience_levels = new_levels
    principle.evidence_grade = seed.evidence_grade
    principle.notes = seed.notes
    if changed:
        principle.version = (principle.version or 0) + 1


def _sync_citations(principle: Principle, seed: PrincipleSeed) -> None:
    """Reconcile a Principle's citation rows to match the seed (keyed on title).

    Idempotent: an existing citation with the same title is updated in place,
    missing ones removed, new ones added — so re-seeding never accumulates
    duplicate citations (matching the Exercise seed's muscle reconciliation).
    """
    desired = {c.title: c for c in seed.citations}
    existing = {c.title: c for c in principle.citations}

    for title, link in list(existing.items()):
        if title not in desired:
            principle.citations.remove(link)
        else:
            c = desired[title]
            link.authors = c.authors
            link.year = c.year
            link.journal = c.journal
            link.doi = c.doi
            link.pmid = c.pmid
            link.url = c.url

    for title, c in desired.items():
        if title not in existing:
            principle.citations.append(
                PrincipleCitation(
                    authors=c.authors,
                    year=c.year,
                    title=c.title,
                    journal=c.journal,
                    doi=c.doi,
                    pmid=c.pmid,
                    url=c.url,
                )
            )


async def seed_principles(
    session: AsyncSession, principles: tuple[PrincipleSeed, ...] | None = None
) -> SeedResult:
    """Upsert the Principles KB from the authored rules; return the tally.

    Keys on each rule's stable ``key``. Idempotent: a re-run updates existing rows
    (bumping ``version`` only when substance changed) and reconciles their
    citations, inserting nothing duplicated.
    """
    rules = principles if principles is not None else PRINCIPLES

    result = await session.execute(select(Principle))
    by_key: dict[str, Principle] = {p.key: p for p in result.scalars().all()}

    inserted = updated = 0
    for seed in rules:
        principle = by_key.get(seed.key)
        is_new = principle is None
        if principle is None:
            principle = Principle(key=seed.key, version=1)
            session.add(principle)
            by_key[seed.key] = principle
            inserted += 1
        else:
            updated += 1
        _apply_fields(principle, seed, is_new=is_new)
        _sync_citations(principle, seed)

    await session.commit()
    return SeedResult(inserted=inserted, updated=updated, total=len(rules))


async def _main() -> None:
    async with async_session() as session:
        result = await seed_principles(session)
    print(
        f"Seeded Principles KB: {result.inserted} inserted, "
        f"{result.updated} updated, {result.total} total."
    )


if __name__ == "__main__":
    asyncio.run(_main())
