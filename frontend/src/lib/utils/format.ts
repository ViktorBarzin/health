/**
 * Format a number with locale-aware separators and decimal places.
 */
export function formatNumber(n: number, decimals: number = 0): string {
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Format a date string or Date object.
 */
export function formatDate(d: string | Date, style: 'short' | 'long' = 'short'): string {
  const date = typeof d === 'string' ? new Date(d) : d;

  if (style === 'long') {
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  }

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * Format a time string or Date object as a short time (e.g., "3:45 PM").
 */
export function formatTime(d: string | Date): string {
  const date = typeof d === 'string' ? new Date(d) : d;
  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * Format a duration in seconds as "Xh Ym" or "Ym Zs".
 */
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  }
  return `${secs}s`;
}

/**
 * Format a distance in meters to km or miles.
 */
export function formatDistance(meters: number): string {
  const km = meters / 1000;
  if (km >= 1) {
    return `${km.toFixed(1)} km`;
  }
  return `${Math.round(meters)} m`;
}

/**
 * Format an energy value in kilojoules as human-readable kilocalories.
 */
export function formatEnergy(kj: number): string {
  const kcal = Math.round(kj / 4.184);
  return `${kcal} kcal`;
}

/**
 * Smart-format a metric value based on its unit.
 */
export function formatMetricValue(value: number, unit: string): string {
  switch (unit) {
    case 'count':
    case 'count/min':
      return formatNumber(Math.round(value));
    case 'bpm':
      return `${Math.round(value)} bpm`;
    case 'ms':
      return `${Math.round(value)} ms`;
    case '%':
      return `${value.toFixed(1)}%`;
    case 'kcal':
    case 'kJ':
      return formatNumber(Math.round(value));
    case 'kg':
      return `${value.toFixed(1)} kg`;
    case 'lb':
      return `${value.toFixed(1)} lb`;
    case 'cm':
      return `${value.toFixed(1)} cm`;
    case 'm':
      return formatDistance(value);
    case 'min':
      return `${Math.round(value)} min`;
    case 'hr':
    case 'hours':
      return `${value.toFixed(1)} hr`;
    case 'degC':
      return `${value.toFixed(1)} C`;
    case 'dBASPL':
      return `${Math.round(value)} dB`;
    default:
      return value % 1 === 0 ? formatNumber(value) : value.toFixed(1);
  }
}
