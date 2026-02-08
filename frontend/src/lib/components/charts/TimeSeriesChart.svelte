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
    const labels = data.map((d) => d.time);
    const values = data.map((d) => d.value);

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
            pointRadius: data.length > 60 ? 0 : 3,
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
              color: '#47556922',
            },
            ticks: {
              color: '#64748b',
              maxTicksLimit: 8,
              callback(value) {
                const raw = this.getLabelForValue(value as number);
                const d = new Date(raw);
                if (isNaN(d.getTime())) return raw;
                return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
              },
            },
            border: {
              color: '#334155',
            },
          },
          y: {
            display: true,
            grid: {
              display: showGrid,
              color: '#47556922',
            },
            ticks: {
              color: '#64748b',
            },
            border: {
              color: '#334155',
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
