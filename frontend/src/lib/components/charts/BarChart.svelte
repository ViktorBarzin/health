<script lang="ts">
  import { Chart, registerables } from 'chart.js';
  import type { ChartConfiguration } from 'chart.js';

  Chart.register(...registerables);

  interface DataPoint {
    time: string;
    value: number;
  }

  interface Props {
    data: DataPoint[];
    label: string;
    color: string;
    showGrid?: boolean;
  }

  let {
    data,
    label,
    color,
    showGrid = true,
  }: Props = $props();

  let canvas: HTMLCanvasElement;
  let chart: Chart | null = null;

  function aggregateDaily(points: DataPoint[]): { labels: string[]; values: number[] } {
    const map = new Map<string, number>();
    for (const p of points) {
      const day = p.time.slice(0, 10);
      map.set(day, (map.get(day) ?? 0) + p.value);
    }
    const sorted = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    return {
      labels: sorted.map(([d]) => d),
      values: sorted.map(([, v]) => v),
    };
  }

  function buildConfig(): ChartConfiguration {
    const { labels, values } = aggregateDaily(data);

    return {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label,
            data: values,
            backgroundColor: color + '99',
            borderColor: color,
            borderWidth: 1,
            borderRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1e293b',
            titleColor: '#f1f5f9',
            bodyColor: '#94a3b8',
            borderColor: '#334155',
            borderWidth: 1,
            padding: 10,
            callbacks: {
              title(items) {
                if (!items.length) return '';
                const raw = items[0].label;
                const d = new Date(raw + 'T00:00:00');
                return isNaN(d.getTime()) ? raw : d.toLocaleDateString('en-US', {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                });
              },
            },
          },
        },
        scales: {
          x: {
            grid: {
              display: showGrid,
              color: '#47556922',
            },
            ticks: {
              color: '#64748b',
              maxTicksLimit: 8,
              callback(value) {
                const raw = this.getLabelForValue(value as number);
                const d = new Date(raw + 'T00:00:00');
                if (isNaN(d.getTime())) return raw;
                return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
              },
            },
            border: { color: '#334155' },
          },
          y: {
            grid: {
              display: showGrid,
              color: '#47556922',
            },
            ticks: { color: '#64748b' },
            border: { color: '#334155' },
          },
        },
      },
    };
  }

  $effect(() => {
    if (!canvas) return;

    const _d = data;
    const _l = label;
    const _c = color;
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
