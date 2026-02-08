<script lang="ts">
  import { Chart, registerables } from 'chart.js';
  import type { ChartConfiguration } from 'chart.js';

  Chart.register(...registerables);

  interface Props {
    xValues: number[];
    yValues: number[];
    xLabel?: string;
    yLabel?: string;
    color?: string;
    xUnit?: string;
    yUnit?: string;
  }

  let {
    xValues,
    yValues,
    xLabel = 'X',
    yLabel = 'Y',
    color = '#10b981',
    xUnit = '',
    yUnit = '',
  }: Props = $props();

  let canvas: HTMLCanvasElement;
  let chart: Chart | null = null;

  function buildConfig(): ChartConfiguration {
    const points = xValues.map((x, i) => ({ x, y: yValues[i] ?? 0 }));

    return {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: `${xLabel} vs ${yLabel}`,
            data: points,
            backgroundColor: color + '66',
            borderColor: color,
            borderWidth: 1,
            pointRadius: 3,
            pointHoverRadius: 5,
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
              label(context) {
                const p = context.raw as { x: number; y: number };
                return `${xLabel}: ${p.x.toFixed(1)}${xUnit ? ' ' + xUnit : ''}, ${yLabel}: ${p.y.toFixed(1)}${yUnit ? ' ' + yUnit : ''}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: '#47556922' },
            ticks: { color: '#64748b' },
            border: { color: '#334155' },
            title: {
              display: true,
              text: xLabel + (xUnit ? ` (${xUnit})` : ''),
              color: '#64748b',
            },
          },
          y: {
            grid: { color: '#47556922' },
            ticks: { color: '#64748b' },
            border: { color: '#334155' },
            title: {
              display: true,
              text: yLabel + (yUnit ? ` (${yUnit})` : ''),
              color: '#64748b',
            },
          },
        },
      },
    };
  }

  $effect(() => {
    if (!canvas) return;

    const _x = xValues;
    const _y = yValues;
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

<div class="w-full h-full min-h-[200px] rounded-lg bg-surface-800 p-4">
  <canvas bind:this={canvas}></canvas>
</div>
