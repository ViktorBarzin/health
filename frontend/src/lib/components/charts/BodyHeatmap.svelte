<script lang="ts">
  // SVG body-map heatmap — front + back human figure with the major muscle
  // regions coloured by a per-muscle value. The one analytics view every
  // competitor app ships (Fitbod/Hevy/Boostcamp). Mobile-first: the two figures
  // sit in a responsive grid (side by side on phones, they scale to width).
  //
  // Regions are deliberately stylised (clean rounded blocks over a simple
  // silhouette), not anatomically exact — each maps to one of the 17 backend
  // muscle enum values so the colour is a direct lookup. Paired muscles
  // (biceps, quads, …) render as a mirrored L/R pair sharing one value.
  //
  // `mode` picks the colour scale: 'recovery' (red→green freshness) or 'volume'
  // (opacity ramp keyed to the busiest muscle). The component is presentational
  // — the caller supplies the value map; tooltips read it straight back.

  import {
    muscleLabel,
    recoveryColor,
    volumeColor,
    volumeIntensity,
  } from '$lib/muscle-heat';

  interface Props {
    /** muscle enum value → score. Recovery: 0–100. Volume: raw volume-load. */
    values: Map<string, number>;
    mode?: 'recovery' | 'volume';
    /** Accent colour for the volume opacity ramp. */
    volumeAccent?: string;
  }

  let { values, mode = 'recovery', volumeAccent = '#10b981' }: Props = $props();

  // The busiest muscle sets the volume scale; only meaningful in volume mode (in
  // recovery mode the values are 0–100 scores and this is unused).
  let maxVolume = $derived(
    mode === 'volume' ? Math.max(0, ...values.values()) : 0,
  );

  let tooltip = $state<{ x: number; y: number; label: string; text: string } | null>(
    null,
  );

  // A region: the muscle it represents and one or more SVG path `d` strings
  // (a left/right pair for bilateral muscles). Coordinates live in a 100×220
  // viewBox per figure.
  interface Region {
    muscle: string;
    paths: string[];
  }

  // --- FRONT figure regions (viewBox 0 0 100 220) ------------------------- //
  const frontRegions: Region[] = [
    { muscle: 'neck', paths: ['M44 26 h12 v8 h-12 z'] },
    { muscle: 'shoulders', paths: ['M30 36 h10 v12 h-12 q0 -8 2 -12 z', 'M70 36 h-10 v12 h12 q0 -8 -2 -12 z'] },
    { muscle: 'chest', paths: ['M40 37 h9 v15 h-13 v-8 q0 -5 4 -7 z', 'M60 37 h-9 v15 h13 v-8 q0 -5 -4 -7 z'] },
    { muscle: 'biceps', paths: ['M28 50 h8 v18 h-9 v-14 q0 -3 1 -4 z', 'M72 50 h-8 v18 h9 v-14 q0 -3 -1 -4 z'] },
    { muscle: 'abdominals', paths: ['M42 54 h16 v26 h-16 z'] },
    { muscle: 'forearms', paths: ['M25 70 h8 v22 h-9 v-18 q0 -3 1 -4 z', 'M75 70 h-8 v22 h9 v-18 q0 -3 -1 -4 z'] },
    { muscle: 'adductors', paths: ['M44 82 h5 v24 h-6 v-20 q0 -3 1 -4 z', 'M56 82 h-5 v24 h6 v-20 q0 -3 -1 -4 z'] },
    { muscle: 'quadriceps', paths: ['M36 84 h7 v34 h-9 v-28 q0 -4 2 -6 z', 'M64 84 h-7 v34 h9 v-28 q0 -4 -2 -6 z'] },
    { muscle: 'abductors', paths: ['M33 84 h3 v18 h-5 v-13 q0 -4 2 -5 z', 'M67 84 h-3 v18 h5 v-13 q0 -4 -2 -5 z'] },
    { muscle: 'calves', paths: ['M37 124 h6 v36 h-7 v-31 q0 -3 1 -5 z', 'M63 124 h-6 v36 h7 v-31 q0 -3 -1 -5 z'] },
  ];

  // --- BACK figure regions (viewBox 0 0 100 220) -------------------------- //
  const backRegions: Region[] = [
    { muscle: 'traps', paths: ['M40 34 h20 v12 l-10 4 l-10 -4 z'] },
    { muscle: 'shoulders', paths: ['M28 36 h11 v11 h-13 q0 -7 2 -11 z', 'M72 36 h-11 v11 h13 q0 -7 -2 -11 z'] },
    { muscle: 'triceps', paths: ['M27 49 h8 v18 h-9 v-14 q0 -3 1 -4 z', 'M73 49 h-8 v18 h9 v-14 q0 -3 -1 -4 z'] },
    { muscle: 'lats', paths: ['M38 47 h11 v18 l-13 -3 v-9 q0 -4 2 -6 z', 'M62 47 h-11 v18 l13 -3 v-9 q0 -4 -2 -6 z'] },
    { muscle: 'middle back', paths: ['M42 47 h16 v14 h-16 z'] },
    { muscle: 'lower back', paths: ['M43 62 h14 v16 h-14 z'] },
    { muscle: 'forearms', paths: ['M24 69 h8 v22 h-9 v-18 q0 -3 1 -4 z', 'M76 69 h-8 v22 h9 v-18 q0 -3 -1 -4 z'] },
    { muscle: 'glutes', paths: ['M40 80 h9 v16 h-11 v-11 q0 -3 2 -5 z', 'M60 80 h-9 v16 h11 v-11 q0 -3 -2 -5 z'] },
    { muscle: 'hamstrings', paths: ['M37 98 h10 v26 h-12 v-20 q0 -4 2 -6 z', 'M63 98 h-10 v26 h12 v-20 q0 -4 -2 -6 z'] },
    { muscle: 'calves', paths: ['M37 126 h7 v34 h-8 v-29 q0 -3 1 -5 z', 'M63 126 h-7 v34 h8 v-29 q0 -3 -1 -5 z'] },
  ];

  // A faint humanoid silhouette behind the regions so unmapped areas (head,
  // hands, feet, joints) still read as a body.
  const silhouette =
    'M50 6 q9 0 9 11 q0 8 -5 11 l8 3 q11 3 11 14 v20 q0 6 -4 22 l-3 18 ' +
    'q4 18 4 40 l-2 44 q0 5 -5 5 q-5 0 -5 -6 l-3 -42 l-3 42 q0 6 -5 6 ' +
    'q-5 0 -5 -5 l-2 -44 q0 -22 4 -40 l-3 -18 q-4 -16 -4 -22 v-20 ' +
    'q0 -11 11 -14 l8 -3 q-5 -3 -5 -11 q0 -11 9 -11 z';

  function fillFor(muscle: string): string {
    const v = values.get(muscle);
    if (mode === 'recovery') {
      // Untrained muscles arrive at 100 from the API; default fresh if absent.
      return recoveryColor(v ?? 100);
    }
    return volumeColor(volumeIntensity(v ?? 0, maxVolume), volumeAccent);
  }

  function tooltipText(muscle: string): string {
    const v = values.get(muscle);
    if (mode === 'recovery') {
      return `${Math.round(v ?? 100)}% recovered`;
    }
    return v && v > 0 ? `${Math.round(v).toLocaleString()} kg·reps` : 'No volume';
  }

  function showTip(e: MouseEvent | FocusEvent, muscle: string) {
    const target = e.currentTarget as SVGElement;
    // Position the tooltip relative to the card wrapper. Bail out gracefully if
    // the expected ancestor is missing (e.g. the component reused in another
    // layout) rather than dereferencing null.
    const card = target.closest('.body-heatmap-card');
    if (!card) return;
    const cardRect = card.getBoundingClientRect();
    const r = target.getBoundingClientRect();
    tooltip = {
      x: r.left - cardRect.left + r.width / 2,
      y: r.top - cardRect.top - 6,
      label: muscleLabel(muscle),
      text: tooltipText(muscle),
    };
  }

  function hideTip() {
    tooltip = null;
  }
</script>

<div class="body-heatmap-card relative">
  <div class="grid grid-cols-2 gap-3">
    {#each [{ title: 'Front', regions: frontRegions }, { title: 'Back', regions: backRegions }] as figure}
      <div class="flex flex-col items-center">
        <svg
          viewBox="0 0 100 220"
          class="w-full max-w-[180px] h-auto"
          role="img"
          aria-label={`${figure.title} muscle map`}
        >
          <!-- Body silhouette backdrop -->
          <path d={silhouette} fill="#0f172a" stroke="#334155" stroke-width="1" />

          {#each figure.regions as region}
            {#each region.paths as d}
              <path
                {d}
                fill={fillFor(region.muscle)}
                stroke="#0f172a"
                stroke-width="0.8"
                class="cursor-pointer transition-[fill] duration-300"
                role="button"
                tabindex="0"
                aria-label={`${muscleLabel(region.muscle)}: ${tooltipText(region.muscle)}`}
                onmouseenter={(e) => showTip(e, region.muscle)}
                onmouseleave={hideTip}
                onfocus={(e) => showTip(e, region.muscle)}
                onblur={hideTip}
              />
            {/each}
          {/each}
        </svg>
        <span class="mt-1 text-xs text-surface-500">{figure.title}</span>
      </div>
    {/each}
  </div>

  {#if tooltip}
    <div
      class="absolute pointer-events-none z-10 px-2 py-1 rounded text-xs bg-surface-700 text-surface-100
             border border-surface-600 shadow-lg whitespace-nowrap"
      style="left: {tooltip.x}px; top: {tooltip.y}px; transform: translate(-50%, -100%);"
    >
      <span class="font-medium">{tooltip.label}</span>
      <span class="text-surface-400"> · {tooltip.text}</span>
    </div>
  {/if}
</div>
