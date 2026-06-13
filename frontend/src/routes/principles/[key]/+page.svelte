<script lang="ts">
  import { page } from '$app/stores';
  import { api, ApiError } from '$lib/api';
  import { evidenceGradeColor, evidenceGradeLabel } from '$lib/program';
  import type { Principle } from '$lib/types';

  // The receipts "why this number" deep-link target (#14, ADR-0004): a single
  // Principle in plain English — its statement, the evidence-backed parameter
  // ranges the generator reads, its applicability, and the peer-reviewed
  // citations behind it. Reached by tapping any generated number on a Program or
  // today's workout. Mobile-first.
  let key = $derived($page.params.key);
  let principle = $state<Principle | null>(null);
  let loading = $state(true);
  let error = $state('');
  let notFound = $state(false);

  $effect(() => {
    if (key) load(key);
  });

  async function load(principleKey: string) {
    loading = true;
    error = '';
    notFound = false;
    try {
      principle = await api.get<Principle>(`/api/principles/${principleKey}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        notFound = true;
      } else {
        error = err instanceof Error ? err.message : 'Failed to load principle';
      }
    } finally {
      loading = false;
    }
  }

  function paramLabel(name: string): string {
    return name.replace(/_/g, ' ');
  }

  function paramRange(p: { min: number | null; max: number | null; value: number | null; unit: string | null }): string {
    const unit = p.unit ? ` ${p.unit}` : '';
    if (p.min !== null && p.max !== null) return `${p.min}–${p.max}${unit}`;
    if (p.min !== null) return `≥${p.min}${unit}`;
    if (p.max !== null) return `≤${p.max}${unit}`;
    return `${p.value}${unit}`;
  }

  let params = $derived(Object.entries(principle?.params ?? {}));
</script>

<div class="space-y-5 max-w-2xl mx-auto pb-24">
  <button
    onclick={() => history.back()}
    class="inline-flex items-center gap-1.5 text-sm text-surface-400 hover:text-surface-200 transition-colors"
  >
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
    Back
  </button>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
      <p class="text-sm text-red-400">{error}</p>
    </div>
  {:else if notFound}
    <div class="p-10 text-center bg-surface-800 rounded-xl border border-surface-700">
      <p class="text-surface-300 text-sm font-medium">Principle not found</p>
      <p class="mt-1 text-surface-500 text-xs">This rule isn't in the knowledge base.</p>
    </div>
  {:else if loading}
    <div class="space-y-3">
      {#each Array(4) as _}
        <div class="h-20 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
      {/each}
    </div>
  {:else if principle}
    <!-- Header: category + evidence grade -->
    <div class="space-y-2">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="px-2 py-0.5 rounded-md text-[11px] capitalize bg-surface-800 border border-surface-700 text-surface-300">
          {principle.category}
        </span>
        <span class="px-2 py-0.5 rounded-md text-[11px] border {evidenceGradeColor(principle.evidence_grade)}">
          Grade {principle.evidence_grade} · {evidenceGradeLabel(principle.evidence_grade)}
        </span>
      </div>
      <h1 class="text-lg font-semibold text-surface-100 leading-snug">{principle.statement}</h1>
    </div>

    <!-- Parameter ranges (the evidence window the generator picks from) -->
    {#if params.length > 0}
      <section class="space-y-2">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">Evidence-backed ranges</h2>
        <ul class="space-y-1.5">
          {#each params as [name, p] (name)}
            <li class="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-surface-800/60 border border-surface-700/60">
              <span class="text-xs text-surface-300 capitalize truncate">{paramLabel(name)}</span>
              <span class="shrink-0 text-sm font-semibold text-surface-100 tabular-nums">{paramRange(p)}</span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <!-- Notes / caveats -->
    {#if principle.notes}
      <section class="space-y-1.5">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">The nuance</h2>
        <p class="text-sm text-surface-300 leading-relaxed">{principle.notes}</p>
      </section>
    {/if}

    <!-- Citations -->
    <section class="space-y-2">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">
        Citations ({principle.citations.length})
      </h2>
      <ul class="space-y-2">
        {#each principle.citations as c (c.title)}
          <li class="p-3 rounded-xl bg-surface-800 border border-surface-700">
            <p class="text-sm text-surface-200 leading-snug">{c.title}</p>
            <p class="mt-1 text-xs text-surface-500">{c.authors} · {c.journal} ({c.year})</p>
            {#if c.resolved_url}
              <a
                href={c.resolved_url}
                target="_blank"
                rel="noopener noreferrer"
                class="mt-1.5 inline-flex items-center gap-1 text-[11px] text-primary-400 hover:text-primary-300 underline underline-offset-2"
              >
                {c.doi ? `doi:${c.doi}` : c.pmid ? `PMID ${c.pmid}` : 'Source'}
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                </svg>
              </a>
            {/if}
          </li>
        {/each}
      </ul>
    </section>

    <p class="text-[11px] text-surface-600 text-center pt-2">
      Every training number in your Program and workouts derives from rules like this.
    </p>
  {/if}
</div>
