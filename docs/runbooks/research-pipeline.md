# Research pipeline — growing the Principles KB (ADR-0011 M6)

The knowledge base only grows through **researched, cited, human-reviewed** additions —
never runtime LLM writes (ADR-0004's every-citation-verified guarantee is non-negotiable).

## When to run it (gap-driven)

- The generator raises `MissingPrincipleError` for a parameter a new feature needs.
- The Block Review wants to bound a lever no Principle covers (e.g. a future
  rep-placement rule needing a cited fatigue-proximity range).
- Viktor asks a programming question the KB can't answer ("should I train to failure?").

## The loop

1. **Draft the question** precisely: the parameter, its units, the population
   (trained/untrained), the Goal contexts it applies to.
2. **Deep research** (Claude via the `deep-research` skill, or claude-agent-service for
   agentic search): gather primary sources — meta-analyses and systematic reviews first,
   then key RCTs. Capture DOI/PMID for every claim.
3. **Verify every citation** against PubMed/DOI directly (title, authors, year, and that
   the abstract actually supports the parameter range). A citation that can't be verified
   is dropped, not paraphrased.
4. **Author the Principle** in `backend/app/services/seed_principles.py`: `key`,
   `statement`, typed `params` ranges, `goals`/`experience_levels` applicability,
   honest `evidence_grade`, citations with resolved URLs — and append the verification
   log entry in the module docstring (the existing convention).
5. **Viktor reviews the diff** before it lands (a normal commit review; the seed is
   idempotent and bumps `version` only when substance changes).
6. Ship: the seed runs at deploy; the generator/Block Review can now cite it.

## Non-goals

- No auto-merge of LLM-researched rules (a hallucinated study steering training is the
  exact failure mode this process exists to prevent).
- No scraping copyrighted programs — the KB stores principles and parameters, not
  someone's product.
