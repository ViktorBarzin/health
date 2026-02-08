<script lang="ts">
  import type { ActivityRingData } from '$lib/types';

  interface Props {
    data: ActivityRingData;
    size?: number;
  }

  let {
    data,
    size = 120,
  }: Props = $props();

  const strokeWidth = size * 0.1;
  const center = size / 2;

  const rings = $derived([
    {
      label: 'Move',
      value: data.active_energy,
      goal: data.active_energy_goal,
      color: '#ef4444',
      radius: center - strokeWidth * 0.7,
    },
    {
      label: 'Exercise',
      value: data.exercise_minutes,
      goal: data.exercise_goal,
      color: '#22c55e',
      radius: center - strokeWidth * 2,
    },
    {
      label: 'Stand',
      value: data.stand_hours,
      goal: data.stand_goal,
      color: '#06b6d4',
      radius: center - strokeWidth * 3.3,
    },
  ]);

  function getCircumference(radius: number): number {
    return 2 * Math.PI * radius;
  }

  function getProgress(value: number, goal: number): number {
    if (goal <= 0) return 0;
    return Math.min(value / goal, 1);
  }

  function getDashOffset(radius: number, progress: number): number {
    const circumference = getCircumference(radius);
    return circumference * (1 - progress);
  }
</script>

<div class="flex flex-col items-center gap-2">
  <svg width={size} height={size} class="transform -rotate-90">
    {#each rings as ring}
      <!-- Background ring -->
      <circle
        cx={center}
        cy={center}
        r={ring.radius}
        fill="none"
        stroke={ring.color + '22'}
        stroke-width={strokeWidth}
        stroke-linecap="round"
      />
      <!-- Progress ring -->
      <circle
        cx={center}
        cy={center}
        r={ring.radius}
        fill="none"
        stroke={ring.color}
        stroke-width={strokeWidth}
        stroke-linecap="round"
        stroke-dasharray={getCircumference(ring.radius)}
        stroke-dashoffset={getDashOffset(ring.radius, getProgress(ring.value, ring.goal))}
        class="transition-all duration-700 ease-out"
      />
    {/each}
  </svg>

  <div class="flex gap-3 text-xs">
    {#each rings as ring}
      <div class="flex items-center gap-1">
        <div class="w-2 h-2 rounded-full" style="background-color: {ring.color}"></div>
        <span class="text-surface-400">{ring.label}</span>
        <span class="text-surface-200 font-medium">
          {Math.round((getProgress(ring.value, ring.goal)) * 100)}%
        </span>
      </div>
    {/each}
  </div>
</div>
