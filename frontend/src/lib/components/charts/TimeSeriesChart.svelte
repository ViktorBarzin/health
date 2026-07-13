<script lang="ts">
  import { Chart, registerables } from 'chart.js';
  import type { ChartConfiguration } from 'chart.js';
  import { DEFAULT_MAX_POINTS, downsampleSeries } from '$lib/dashboard';
  import { chartTheme } from '$lib/ui/chart-theme';

  Chart.register(...registerables);

  interface DataPoint {
    time: string;
    value: number;
  }

  interface Props {
    data: DataPoint[];
    label: string;
    color: string;
    type?: 'line' | 'bar';
    fill?: boolean;
    showGrid?: boolean;
  }

  let {
    data,
    label,
    color,
    type = 'line',
    fill = false,
    showGrid = true,
  }: Props = $props();

  let canvas: HTMLCanvasElement;
  let chart: Chart | null = null;

  function buildConfig(): ChartConfiguration {
    // Cap rendered points so a wide window can't freeze the main thread (#51).
    const points = downsampleSeries(data, DEFAULT_MAX_POINTS);
    const labels = points.map((d) => d.time);
    const values = points.map((d) => d.value);
    const t = chartTheme();

    return {
      type,
      data: {
        labels,
        datasets: [
          {
            label,
            data: values,
            borderColor: color,
            backgroundColor: fill ? color + '33' : color + '22',
            borderWidth: 2,
            fill,
            pointRadius: points.length > 60 ? 0 : 3,
            pointHoverRadius: 5,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            backgroundColor: t.tooltipBg,
            titleColor: t.tooltipTitle,
            bodyColor: t.tooltipBody,
            borderColor: t.border,
            borderWidth: 1,
            padding: 10,
            callbacks: {
              title(items) {
                if (!items.length) return '';
                const raw = items[0].label;
                const d = new Date(raw);
                return isNaN(d.getTime()) ? raw : d.toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                });
              },
            },
          },
        },
        scales: {
          x: {
            display: true,
            grid: {
              display: showGrid,
              color: t.grid,
            },
            ticks: {
              color: t.tick,
              maxTicksLimit: 8,
              callback(value) {
                const raw = this.getLabelForValue(value as number);
                const d = new Date(raw);
                if (isNaN(d.getTime())) return raw;
                return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
              },
            },
            border: {
              color: t.border,
            },
          },
          y: {
            display: true,
            grid: {
              display: showGrid,
              color: t.grid,
            },
            ticks: {
              color: t.tick,
            },
            border: {
              color: t.border,
            },
          },
        },
      },
    };
  }

  $effect(() => {
    if (!canvas) return;

    // Reference reactive data to track changes
    const _d = data;
    const _l = label;
    const _c = color;
    const _t = type;
    const _f = fill;
    const _g = showGrid;

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

<div class="w-full h-full min-h-[200px] rounded-lg bg-surface-800 p-4">
  <canvas bind:this={canvas}></canvas>
</div>
