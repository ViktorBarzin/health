"""Principles KB seed contract (ADR-0004).

The seed upserts the versioned, cited exercise-science rules and must be
idempotent — re-running on every boot adds no duplicates, reconciles citations,
and bumps a rule's version only when its substance changes. The authored content
must carry verified citations (a resolvable DOI or PMID) on every Principle.
"""

import re

import pytest
from sqlalchemy import func, select

from app.models.principle import (
    EvidenceGrade,
    ExperienceLevel,
    Principle,
    PrincipleCategory,
    PrincipleCitation,
    TrainingGoal,
)
from app.services.seed_principles import (
    PRINCIPLES,
    CitationSeed,
    PrincipleSeed,
    seed_principles,
)

# A tiny in-memory KB shaped like the real one, for deterministic seed behavior
# without depending on the authored content.
_FIXTURE = (
    PrincipleSeed(
        key="volume-test",
        statement="Do about 10-20 sets per muscle per week.",
        category=PrincipleCategory.volume,
        evidence_grade=EvidenceGrade.A,
        params={"sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"}},
        goals=[TrainingGoal.bulk.value, TrainingGoal.strength.value],
        experience_levels=[],
        citations=(
            CitationSeed(
                authors="Schoenfeld BJ, et al.",
                year=2017,
                title="Dose-response volume meta-analysis",
                journal="Journal of Sports Sciences",
                doi="10.1080/02640414.2016.1210197",
                pmid="27433992",
            ),
        ),
    ),
    PrincipleSeed(
        key="protein-test",
        statement="Aim for 1.6-2.2 g/kg/day protein.",
        category=PrincipleCategory.nutrition,
        evidence_grade=EvidenceGrade.A,
        params={"protein_g_per_kg_per_day": {"min": 1.6, "max": 2.2, "unit": "g/kg/day"}},
        goals=[TrainingGoal.bulk.value],
        experience_levels=[ExperienceLevel.beginner.value],
        citations=(
            CitationSeed(
                authors="Morton RW, et al.",
                year=2018,
                title="Protein supplementation meta-analysis",
                journal="British Journal of Sports Medicine",
                doi="10.1136/bjsports-2017-097608",
                pmid="28698222",
            ),
        ),
    ),
)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seed_inserts_principles_with_citations(db_session) -> None:
    result = await seed_principles(db_session, _FIXTURE)

    assert result.inserted == 2
    assert result.updated == 0
    assert await _count(db_session, Principle) == 2
    assert await _count(db_session, PrincipleCitation) == 2

    volume = (
        await db_session.execute(
            select(Principle).where(Principle.key == "volume-test")
        )
    ).scalar_one()
    assert volume.category == PrincipleCategory.volume
    assert volume.evidence_grade == EvidenceGrade.A
    assert volume.version == 1
    # Structured params are stored as a typed-range dict the generator reads.
    assert volume.params["sets_per_muscle_per_week"] == {
        "min": 10,
        "max": 20,
        "unit": "sets",
    }
    assert volume.goals == ["bulk", "strength"]
    # The citation is attached with a resolvable identifier.
    assert len(volume.citations) == 1
    assert volume.citations[0].pmid == "27433992"
    assert volume.citations[0].resolved_url == "https://doi.org/10.1080/02640414.2016.1210197"


async def test_seed_is_idempotent_no_duplicates(db_session) -> None:
    first = await seed_principles(db_session, _FIXTURE)
    principles_after_first = await _count(db_session, Principle)
    citations_after_first = await _count(db_session, PrincipleCitation)

    second = await seed_principles(db_session, _FIXTURE)

    assert first.inserted == 2
    # Re-run inserts nothing new and only updates the existing rows in place.
    assert second.inserted == 0
    assert second.updated == 2
    assert await _count(db_session, Principle) == principles_after_first == 2
    # Citations are reconciled, not re-appended.
    assert await _count(db_session, PrincipleCitation) == citations_after_first == 2

    # An unchanged re-seed leaves the version untouched.
    volume = (
        await db_session.execute(
            select(Principle).where(Principle.key == "volume-test")
        )
    ).scalar_one()
    assert volume.version == 1


async def test_reseed_updates_changed_fields_and_bumps_version(db_session) -> None:
    await seed_principles(db_session, _FIXTURE)

    # Same keys, but the volume rule's substance changed (range + statement) and
    # its citation gained a URL.
    revised = (
        PrincipleSeed(
            key="volume-test",
            statement="Do about 12-22 sets per muscle per week.",
            category=PrincipleCategory.volume,
            evidence_grade=EvidenceGrade.A,
            params={
                "sets_per_muscle_per_week": {"min": 12, "max": 22, "unit": "sets"}
            },
            goals=[TrainingGoal.bulk.value, TrainingGoal.strength.value],
            experience_levels=[],
            citations=(
                CitationSeed(
                    authors="Schoenfeld BJ, et al.",
                    year=2017,
                    title="Dose-response volume meta-analysis",
                    journal="Journal of Sports Sciences",
                    doi="10.1080/02640414.2016.1210197",
                    pmid="27433992",
                    url="https://example.org/volume",
                ),
            ),
        ),
        _FIXTURE[1],
    )

    result = await seed_principles(db_session, revised)
    assert result.inserted == 0
    assert result.updated == 2

    volume = (
        await db_session.execute(
            select(Principle).where(Principle.key == "volume-test")
        )
    ).scalar_one()
    assert volume.statement.startswith("Do about 12-22")
    assert volume.params["sets_per_muscle_per_week"]["min"] == 12
    # Substance changed -> version bumped (so a consumer can detect the change).
    assert volume.version == 2
    # Citation updated in place, not duplicated.
    assert await _count(db_session, PrincipleCitation) == 2
    assert volume.citations[0].url == "https://example.org/volume"
    assert volume.citations[0].resolved_url == "https://example.org/volume"


async def test_reseed_removes_dropped_citation(db_session) -> None:
    seed_with_two = (
        PrincipleSeed(
            key="overload-test",
            statement="Progress over time.",
            category=PrincipleCategory.progression,
            evidence_grade=EvidenceGrade.B,
            params={"load_increase_percent": {"min": 2, "max": 10, "unit": "%"}},
            citations=(
                CitationSeed(
                    authors="ACSM",
                    year=2009,
                    title="ACSM progression position stand",
                    journal="MSSE",
                    pmid="19204579",
                ),
                CitationSeed(
                    authors="Plotkin D, et al.",
                    year=2022,
                    title="Progressive overload without progressing load",
                    journal="PeerJ",
                    pmid="36199287",
                ),
            ),
        ),
    )
    await seed_principles(db_session, seed_with_two)
    assert await _count(db_session, PrincipleCitation) == 2

    # Drop the second citation on re-seed.
    seed_with_one = (
        PrincipleSeed(
            key="overload-test",
            statement="Progress over time.",
            category=PrincipleCategory.progression,
            evidence_grade=EvidenceGrade.B,
            params={"load_increase_percent": {"min": 2, "max": 10, "unit": "%"}},
            citations=(
                CitationSeed(
                    authors="ACSM",
                    year=2009,
                    title="ACSM progression position stand",
                    journal="MSSE",
                    pmid="19204579",
                ),
            ),
        ),
    )
    await seed_principles(db_session, seed_with_one)
    # Reconciled down to one — not accumulated.
    assert await _count(db_session, PrincipleCitation) == 1


# --------------------------------------------------------------------------- #
# The authored KB content itself — these guard the real PRINCIPLES tuple.
# --------------------------------------------------------------------------- #

_EXPECTED_KEYS = {
    "volume-dose-response",
    "training-frequency",
    "effort-proximity-to-failure",
    "periodization",
    "progressive-overload",
    "protein-intake",
    "rest-intervals",
    "deload",
}

# DOIs/PMIDs verified against PubMed/DOI at authoring time (2026-06-13).
_VERIFIED_PMIDS = {
    "volume-dose-response": "27433992",
    "training-frequency": "27102172",
    "effort-proximity-to-failure": "36334240",
    "periodization": "28497285",
    "protein-intake": "28698222",
    "rest-intervals": "26605807",
    "deload": "36619355",
}


async def test_real_kb_seeds_all_required_principles(db_session) -> None:
    result = await seed_principles(db_session)  # the real PRINCIPLES
    assert result.inserted == len(PRINCIPLES)
    assert result.total == len(PRINCIPLES)

    keys = {
        p.key
        for p in (await db_session.execute(select(Principle))).scalars().all()
    }
    assert keys == _EXPECTED_KEYS

    # Idempotent on the real content too: a second run inserts nothing.
    again = await seed_principles(db_session)
    assert again.inserted == 0
    assert await _count(db_session, Principle) == len(PRINCIPLES)


def test_every_principle_has_a_resolvable_citation() -> None:
    """ADR-0004: every Principle traces to peer-reviewed evidence.

    Each must carry at least one citation with a real DOI or PMID (no fabricated
    or empty references), with the required bibliographic fields populated.
    """
    doi_re = re.compile(r"^10\.\d{4,9}/\S+$")
    pmid_re = re.compile(r"^\d+$")
    for seed in PRINCIPLES:
        assert seed.citations, f"{seed.key} has no citation"
        for c in seed.citations:
            assert c.authors and c.title and c.journal and c.year
            assert c.doi or c.pmid, f"{seed.key} citation lacks DOI/PMID"
            if c.doi:
                assert doi_re.match(c.doi), f"{seed.key} DOI malformed: {c.doi}"
            if c.pmid:
                assert pmid_re.match(c.pmid), f"{seed.key} PMID malformed: {c.pmid}"


def test_verified_pmids_present_on_expected_principles() -> None:
    """The specific verified PMIDs are wired to the right Principle keys."""
    by_key = {s.key: s for s in PRINCIPLES}
    for key, pmid in _VERIFIED_PMIDS.items():
        seed = by_key[key]
        pmids = {c.pmid for c in seed.citations}
        assert pmid in pmids, f"{key} missing verified PMID {pmid}"


def test_every_principle_has_typed_params_and_grade() -> None:
    """The generator reads structured params; every rule carries a grade."""
    for seed in PRINCIPLES:
        assert isinstance(seed.evidence_grade, EvidenceGrade)
        # Every rule the engine needs exposes at least one typed range with a unit.
        assert seed.params, f"{seed.key} has no params"
        for name, rng in seed.params.items():
            assert isinstance(rng, dict)
            assert "unit" in rng
            # At least one of min/max/value bounds the range.
            assert any(k in rng for k in ("min", "max", "value")), name
