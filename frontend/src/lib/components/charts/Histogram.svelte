<script lang="ts">
  import { Chart, registerables } from 'chart.js';
  import type { ChartConfiguration } from 'chart.js';

  Chart.register(...registerables);

  interface Props {
    values: number[];
    label?: string;
    color?: string;
    bins?: number;
    unit?: string;
  }

  let {
    values,
    label = 'Distribution',
    color = '#10b981',
    bins = 20,
    unit = '',
  }: Props = $props();

  let canvas: HTMLCanvasElement;
  let chart: Chart | null = null;

  function computeBins(vals: number[], numBins: number): { labels: string[]; counts: number[] } {
    if (vals.length === 0) return { labels: [], counts: [] };

    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const binWidth = range / numBins;

    const counts = new Array(numBins).fill(0);
    const labels: string[] = [];

    for (let i = 0; i < numBins; i++) {
      const lo = min + i * binWidth;
      labels.push(`${lo.toFixed(1)}${unit ? ' ' + unit : ''}`);
    }

    for (const v of vals) {
      let idx = Math.floor((v - min) / binWidth);
      if (idx >= numBins) idx = numBins - 1;
      counts[idx]++;
    }

    return { labels, counts };
  }

  function buildConfig(): ChartConfiguration {
    const { labels, counts } = computeBins(values, bins);

    return {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label,
            data: counts,
            backgroundColor: color + '99',
            borderColor: color,
            borderWidth: 1,
            borderRadius: 2,
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
                return items[0].label ?? '';
              },
              label(item) {
                return `Count: ${item.raw}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#64748b',
              maxTicksLimit: 8,
              maxRotation: 0,
            },
            border: { color: '#334155' },
          },
          y: {
            grid: { color: '#47556922' },
            ticks: { color: '#64748b' },
            border: { color: '#334155' },
            title: {
              display: true,
              text: 'Frequency',
              color: '#64748b',
            },
          },
        },
      },
    };
  }

  $effect(() => {
    if (!canvas) return;

    const _v = values;
    const _l = label;
    const _c = color;
    const _b = bins;

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
