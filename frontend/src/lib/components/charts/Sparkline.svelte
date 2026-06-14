<script lang="ts">
  import { Chart, registerables } from 'chart.js';
  import type { ChartConfiguration } from 'chart.js';
  import { DEFAULT_MAX_POINTS, downsample } from '$lib/dashboard';

  Chart.register(...registerables);

  interface Props {
    data: number[];
    color?: string;
    width?: number;
    height?: number;
  }

  let {
    data,
    color = '#10b981',
    width = 120,
    height = 32,
  }: Props = $props();

  let canvas: HTMLCanvasElement;
  let chart: Chart | null = null;

  function buildConfig(): ChartConfiguration {
    // Cap rendered points so a wide window can't freeze the main thread (#51).
    const points = downsample(data, DEFAULT_MAX_POINTS);
    return {
      type: 'line',
      data: {
        labels: points.map((_, i) => String(i)),
        datasets: [
          {
            data: points,
            borderColor: color,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 0,
            fill: false,
            tension: 0.4,
          },
        ],
      },
      options: {
        responsive: false,
        maintainAspectRatio: false,
        events: [],
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        },
        scales: {
          x: { display: false },
          y: { display: false },
        },
        animation: {
          duration: 500,
        },
      },
    };
  }

  $effect(() => {
    if (!canvas) return;

    const _d = data;
    const _c = color;

    if (chart) {
      chart.destroy();
    }

    chart = new Chart(canvas, buildConfig());

    return () => {
      chart?.destroy();
      chart = null;
    };
  });
</script>

<canvas
  bind:this={canvas}
  {width}
  {height}
  style="width: {width}px; height: {height}px;"
></canvas>
