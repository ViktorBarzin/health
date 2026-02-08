export type Resolution = 'raw' | 'day' | 'week' | 'month';
export type Preset = '7d' | '30d' | '90d' | '1y' | 'all';

function createDateRangeStore() {
  const now = new Date();
  const thirtyDaysAgo = new Date(now);
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

  let start = $state<Date>(thirtyDaysAgo);
  let end = $state<Date>(now);
  let resolution = $state<Resolution>('day');
  let activePreset = $state<Preset | null>('30d');

  function setRange(newStart: Date, newEnd: Date) {
    start = newStart;
    end = newEnd;
    activePreset = null;
  }

  function setResolution(res: Resolution) {
    resolution = res;
  }

  function setPreset(preset: Preset) {
    const today = new Date();
    let newStart: Date;

    switch (preset) {
      case '7d':
        newStart = new Date(today);
        newStart.setDate(today.getDate() - 7);
        break;
      case '30d':
        newStart = new Date(today);
        newStart.setDate(today.getDate() - 30);
        break;
      case '90d':
        newStart = new Date(today);
        newStart.setDate(today.getDate() - 90);
        break;
      case '1y':
        newStart = new Date(today);
        newStart.setFullYear(today.getFullYear() - 1);
        break;
      case 'all':
        newStart = new Date(2015, 0, 1);
        break;
    }

    start = newStart;
    end = today;
    activePreset = preset;
  }

  return {
    get start() { return start; },
    get end() { return end; },
    get resolution() { return resolution; },
    get activePreset() { return activePreset; },
    get startISO() { return start.toISOString().slice(0, 10); },
    get endISO() { return end.toISOString().slice(0, 10); },
    get queryParams() {
      return `start=${start.toISOString()}&end=${end.toISOString()}&resolution=${resolution}`;
    },
    setRange,
    setResolution,
    setPreset,
  };
}

export const dateRange = createDateRangeStore();
