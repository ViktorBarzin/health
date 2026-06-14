<script lang="ts">
  // Today — the action-first home (ADR-0008). Answers "what do I do now":
  // start/resume the day's Session, what's left in the Budget, how recovered
  // you are. The health-metrics dashboard moved to Progress.
  import { goto } from '$app/navigation';
  import { api, ApiError } from '$lib/api';
  import { haptic } from '$lib/ui/haptics';
  import type {
    DiaryDay,
    MacroTotals,
    SessionDetail,
    SessionSummary,
    TodayRecommendationResponse,
  } from '$lib/types';
  import Card from '$lib/components/ui/Card.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import NumberReadout from '$lib/components/ui/NumberReadout.svelte';
  import ReadinessCard from '$lib/components/dashboard/ReadinessCard.svelte';
  import BudgetCard from '$lib/components/nutrition/BudgetCard.svelte';

  const ZERO: MacroTotals = { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 };

  let sessions = $state<SessionSummary[] | null>(null);
  let today = $state<TodayRecommendationResponse | null>(null);
  let logged = $state<MacroTotals>(ZERO);
  let recsLoading = $state(true);
  let sessionsLoading = $state(true);
  let starting = $state(false);
  let startError = $state<string | null>(null);

  const active = $derived(sessions?.find((s) => s.is_active && !s.ended_at) ?? null);
  const recent = $derived((sessions ?? []).filter((s) => !s.is_active).slice(0, 4));

  $effect(() => {
    void load();
  });

  async function load() {
    api
      .get<SessionSummary[]>('/api/sessions')
      .then((r) => (sessions = r))
      .catch(() => (sessions = []))
      .finally(() => (sessionsLoading = false));
    api
      .get<TodayRecommendationResponse>('/api/recommendations/today')
      .then((r) => (today = r))
      .catch(() => (today = null))
      .finally(() => (recsLoading = false));
    api
      .get<DiaryDay>('/api/nutrition/diary')
      .then((d) => (logged = d.total))
      .catch(() => (logged = ZERO));
  }

  async function startToday() {
    starting = true;
    startError = null;
    try {
      const session = await api.post<SessionDetail>('/api/recommendations/today/start');
      haptic('success');
      await goto(`/sessions/${session.id}`);
    } catch (e) {
      startError = e instanceof ApiError ? e.message : 'Could not start the session';
      starting = false;
    }
  }

  function greeting(): string {
    const h = new Date().getHours();
    if (h < 5) return 'Late night';
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }

  const todayLabel = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

  function planTitle(t: TodayRecommendationResponse): string {
    return t.source === 'program' && t.program ? t.program.day_name : 'Freestyle session';
  }
</script>

<div class="mx-auto max-w-2xl space-y-5">
  <header class="pt-1">
    <p class="text-sm text-ink-3">{todayLabel}</p>
    <h1 class="text-2xl font-semibold tracking-tight text-ink">{greeting()}</h1>
  </header>

  <!-- Primary action: resume an in-progress Session, else start today's. -->
  {#if sessionsLoading}
    <Card class="h-40 animate-pulse" padded={false}><span class="sr-only">Loading</span></Card>
  {:else if active}
    <Card class="border-accent/40 bg-gradient-to-br from-accent-soft to-transparent">
      <div class="flex items-start justify-between gap-4">
        <div>
          <span
            class="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-[0.7rem] font-semibold uppercase tracking-wider text-accent-ink"
          >
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"></span> In progress
          </span>
          <div class="mt-3 flex items-end gap-6">
            <NumberReadout value={active.set_count} label="Sets" size="lg" />
            <NumberReadout value={Math.round(active.total_volume_kg)} unit="kg" label="Volume" size="lg" />
          </div>
        </div>
      </div>
      <Button href={`/sessions/${active.id}`} variant="accent" size="lg" full feedback="select">
        Resume session
      </Button>
    </Card>
  {:else}
    <Card>
      <div class="mb-4 flex items-center justify-between gap-3">
        <div class="min-w-0">
          <p class="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-ink-3">
            Today's session
          </p>
          {#if recsLoading}
            <div class="mt-1 h-7 w-40 animate-pulse rounded bg-panel-2"></div>
          {:else if today}
            <h2 class="truncate text-xl font-semibold text-ink">{planTitle(today)}</h2>
            <p class="mt-0.5 text-sm text-ink-2">
              {today.exercises.length} exercise{today.exercises.length === 1 ? '' : 's'}
              {#if today.source === 'program' && today.program}
                · Week {today.program.week}/{today.program.total_weeks}{today.program.is_deload
                  ? ' · deload'
                  : ''}
              {/if}
            </p>
          {:else}
            <h2 class="text-xl font-semibold text-ink">Start training</h2>
            <p class="mt-0.5 text-sm text-ink-2">Log a fresh session.</p>
          {/if}
        </div>
        <span class="grid h-12 w-12 flex-shrink-0 place-items-center rounded-2xl bg-accent text-on-accent">
          <svg class="h-6 w-6" viewBox="0 0 24 24" fill="currentColor">
            <path d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
          </svg>
        </span>
      </div>

      {#if today && today.exercises.length}
        <ul class="mb-4 space-y-1.5">
          {#each today.exercises.slice(0, 4) as ex (ex.exercise_id)}
            <li class="flex items-center justify-between gap-3 text-sm">
              <span class="truncate text-ink-2">{ex.name}</span>
              <span class="readout flex-shrink-0 text-xs text-ink-3"
                >{ex.target_sets}×{ex.target_reps}{#if ex.target_weight_kg}
                  · {Math.round(ex.target_weight_kg)}kg{/if}</span
              >
            </li>
          {/each}
          {#if today.exercises.length > 4}
            <li class="text-xs text-ink-3">+{today.exercises.length - 4} more</li>
          {/if}
        </ul>
      {/if}

      {#if startError}
        <p class="mb-3 text-sm text-danger">{startError}</p>
      {/if}

      <div class="flex gap-2">
        <Button onclick={startToday} variant="accent" size="lg" full disabled={starting} feedback={null}>
          {starting ? 'Starting…' : 'Start training'}
        </Button>
        <Button href="/sessions" variant="outline" size="lg">All</Button>
      </div>
    </Card>
  {/if}

  <!-- Recovery + fuel at a glance. -->
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    <ReadinessCard />
    <BudgetCard {logged} />
  </div>

  <!-- Recent sessions. -->
  <section>
    <div class="mb-2 flex items-center justify-between px-1">
      <h2 class="text-sm font-semibold text-ink">Recent sessions</h2>
      <a href="/sessions" class="text-xs font-medium text-accent-ink">View all</a>
    </div>
    {#if sessionsLoading}
      <Card class="h-20 animate-pulse" padded={false}></Card>
    {:else if recent.length === 0}
      <Card class="text-center">
        <p class="text-sm text-ink-3">No sessions yet. Start your first above.</p>
      </Card>
    {:else}
      <div class="space-y-2">
        {#each recent as s (s.id)}
          <Card href={`/sessions/${s.id}`} class="flex items-center justify-between gap-3 py-3">
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-ink">
                {new Date(s.started_at).toLocaleDateString('en-US', {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </p>
              <p class="text-xs text-ink-3">{s.set_count} sets</p>
            </div>
            <span class="readout flex-shrink-0 text-sm text-ink-2">{Math.round(s.total_volume_kg)} kg</span>
          </Card>
        {/each}
      </div>
    {/if}
  </section>
</div>
