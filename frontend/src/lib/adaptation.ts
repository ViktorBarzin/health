// Pure Block Review view-logic (ADR-0011) — receipts + adherence rendering.
// No IO (vitest); pages fetch /api/programs/active/{revisions,adherence} and
// feed these.

export interface RevisionChange {
  lever: string;
  muscle?: string | null;
  day_index?: number | null;
  slot_index?: number | null;
  from: unknown;
  to: unknown;
  reason: string;
  principle_key?: string | null;
}

export interface ProgramRevision {
  version: number;
  trigger: string;
  changes: RevisionChange[];
  created_at: string;
}

export interface MuscleAdherenceRead {
  muscle: string;
  prescribed_sets: number;
  performed_sets: number;
  completion: number;
  hard_failures: number;
}

export interface AdherenceWeek {
  week: number;
  current: boolean;
  sessions: number;
  muscles: MuscleAdherenceRead[];
}

/** One-line human description of a change (the receipt's headline). */
export function describeChange(change: RevisionChange): string {
  switch (change.lever) {
    case 'volume':
      return `${title(change.muscle)}: ${change.from} → ${change.to} sets/week`;
    case 'volume_start':
      return `${title(change.muscle)}: new block starts at ${change.to} sets/week`;
    case 'rotation':
      return `${title(change.muscle)}: movement rotated`;
    case 'days_per_week':
      return `Schedule: ${change.from} → ${change.to} days/week`;
    case 'block_succession':
      return 'New training block generated';
    default:
      return change.reason;
  }
}

function title(muscle: string | null | undefined): string {
  if (!muscle) return 'Program';
  return muscle.charAt(0).toUpperCase() + muscle.slice(1);
}

/** Whether a revision is fresh enough for the Today banner (48 h). */
export function isRecentRevision(createdAtISO: string, nowMs: number): boolean {
  const created = Date.parse(createdAtISO);
  if (Number.isNaN(created)) return false;
  return nowMs - created >= 0 && nowMs - created < 48 * 60 * 60 * 1000;
}

/** Trigger → the label the timeline shows. */
export function triggerLabel(trigger: string): string {
  switch (trigger) {
    case 'continuous_review':
      return 'Auto-tune';
    case 'block_review':
      return 'New block';
    case 'proposal':
      return 'Approved proposal';
    default:
      return trigger;
  }
}

/** Completion → a semantic tone the strip colours by. */
export function completionTone(completion: number): 'good' | 'ok' | 'weak' {
  if (completion >= 0.95) return 'good';
  if (completion >= 0.8) return 'ok';
  return 'weak';
}

// --- M5: coach's notes + Proposals ---

export interface AnalysisReportRead {
  id: string;
  week: number;
  narrative: string;
  created_at: string;
}

export interface ProposalRead {
  id: string;
  change: RevisionChange & { requested?: number };
  status: string;
  created_at: string;
}

/** One-line headline for a pending Proposal card. */
export function proposalHeadline(change: {
  lever: string;
  muscle?: string | null;
  to?: unknown;
}): string {
  if (change.lever === 'volume' && change.muscle) {
    const m = change.muscle.charAt(0).toUpperCase() + change.muscle.slice(1);
    return `${m} → ${change.to} sets/week`;
  }
  return 'Program change';
}
