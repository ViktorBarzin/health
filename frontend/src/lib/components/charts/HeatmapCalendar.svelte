<script lang="ts">
  interface Props {
    data: Map<string, number>;
    color?: string;
  }

  let {
    data,
    color = '#10b981',
  }: Props = $props();

  let tooltip = $state<{ x: number; y: number; date: string; value: number } | null>(null);

  const cellSize = 13;
  const cellGap = 3;
  const totalCell = cellSize + cellGap;
  const weeksToShow = 52;
  const leftPadding = 30;
  const topPadding = 20;

  const dayLabels = ['Mon', '', 'Wed', '', 'Fri', '', 'Sun'];

  interface CellData {
    x: number;
    y: number;
    date: string;
    value: number;
    intensity: number;
  }

  let cells = $derived.by(() => {
    const result: CellData[] = [];
    const today = new Date();
    const maxVal = Math.max(1, ...data.values());

    // Find the start: go back weeksToShow * 7 days from end of this week
    const endOfWeek = new Date(today);
    // Adjust to end of week (Sunday)
    const dayOfWeek = endOfWeek.getDay();
    endOfWeek.setDate(endOfWeek.getDate() + (6 - dayOfWeek));

    const startDate = new Date(endOfWeek);
    startDate.setDate(startDate.getDate() - (weeksToShow * 7 - 1));

    const current = new Date(startDate);
    let weekIdx = 0;
    let dayIdx = current.getDay();

    // Adjust dayIdx for Monday-start (0=Mon, 6=Sun)
    function toMondayStart(jsDay: number): number {
      return jsDay === 0 ? 6 : jsDay - 1;
    }

    while (current <= endOfWeek) {
      const dateStr = current.toISOString().slice(0, 10);
      const monDay = toMondayStart(current.getDay());
      const value = data.get(dateStr) ?? 0;
      const intensity = maxVal > 0 ? value / maxVal : 0;

      result.push({
        x: leftPadding + weekIdx * totalCell,
        y: topPadding + monDay * totalCell,
        date: dateStr,
        value,
        intensity,
      });

      current.setDate(current.getDate() + 1);

      // If we moved to Monday, advance the week
      if (current.getDay() === 1) {
        weekIdx++;
      }
    }

    return result;
  });

  let monthLabels = $derived.by(() => {
    const labels: { x: number; label: string }[] = [];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    let lastMonth = -1;

    for (const cell of cells) {
      const d = new Date(cell.date + 'T00:00:00');
      const dayInMonth = d.getDate();
      const month = d.getMonth();
      if (month !== lastMonth && dayInMonth <= 7) {
        labels.push({ x: cell.x, label: months[month] });
        lastMonth = month;
      }
    }

    return labels;
  });

  function getCellColor(intensity: number): string {
    if (intensity === 0) return '#1e293b';
    // Parse the hex color
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);
    // Scale alpha between 0.2 and 1.0
    const alpha = 0.2 + intensity * 0.8;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function handleMouseEnter(e: MouseEvent, cell: CellData) {
    const target = e.currentTarget as SVGRectElement;
    const rect = target.closest('svg')!.getBoundingClientRect();
    const cellRect = target.getBoundingClientRect();
    tooltip = {
      x: cellRect.left - rect.left + cellSize / 2,
      y: cellRect.top - rect.top - 8,
      date: cell.date,
      value: cell.value,
    };
  }

  function handleMouseLeave() {
    tooltip = null;
  }

  const svgWidth = leftPadding + weeksToShow * totalCell + 10;
  const svgHeight = topPadding + 7 * totalCell + 10;
</script>

<div class="relative w-full overflow-x-auto rounded-lg bg-surface-800 p-4">
  <svg width={svgWidth} height={svgHeight} class="block">
    <!-- Month labels -->
    {#each monthLabels as m}
      <text
        x={m.x}
        y={12}
        fill="#64748b"
        font-size="10"
        font-family="sans-serif"
      >
        {m.label}
      </text>
    {/each}

    <!-- Day-of-week labels -->
    {#each dayLabels as day, i}
      {#if day}
        <text
          x={0}
          y={topPadding + i * totalCell + cellSize - 2}
          fill="#64748b"
          font-size="9"
          font-family="sans-serif"
        >
          {day}
        </text>
      {/if}
    {/each}

    <!-- Cells -->
    {#each cells as cell}
      <rect
        x={cell.x}
        y={cell.y}
        width={cellSize}
        height={cellSize}
        rx="2"
        fill={getCellColor(cell.intensity)}
        class="cursor-pointer transition-colors duration-100"
        onmouseenter={(e) => handleMouseEnter(e, cell)}
        onmouseleave={handleMouseLeave}
      />
    {/each}
  </svg>

  <!-- Tooltip -->
  {#if tooltip}
    <div
      class="absolute pointer-events-none z-10 px-2 py-1 rounded text-xs bg-surface-700 text-surface-200 border border-surface-600 shadow-lg whitespace-nowrap"
      style="left: {tooltip.x}px; top: {tooltip.y}px; transform: translate(-50%, -100%);"
    >
      <span class="font-medium">{tooltip.date}</span>: {tooltip.value.toLocaleString()}
    </div>
  {/if}
</div>
