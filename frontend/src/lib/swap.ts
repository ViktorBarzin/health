// Pure Swap view-logic (CONTEXT.md "Swap") — the mid-Session replace plan.
//
// The SwapSheet picks a ranked alternative (prefetched from
// GET /api/exercises/{id}/alternatives so it survives a signal drop); these
// helpers turn that pick into existing op-queue verbs — delete the outgoing
// block's Sets, add the incoming ones, reorder them into the block's place —
// so a Swap is fully offline-capable and replays idempotently like any other
// queued op (ADR-0005).

import type { SetCreate, TrainingSet } from './types';

/** One ranked Swap equivalent, as served by /api/exercises/{id}/alternatives. */
export interface SwapAlternative {
  exercise_id: string;
  name: string;
  equipment: string | null;
  target_reps: number;
  target_weight_kg: number;
  is_starting_point: boolean;
  has_history: boolean;
  primary_muscles: string[];
  secondary_muscles: string[];
  shared_muscles: string[];
}

/** The IndexedDB kv key alternatives are prefetched under, per Exercise. */
export function alternativesKvKey(exerciseId: string): string {
  return `alts:${exerciseId}`;
}

/**
 * The Sets that replace an outgoing block: one per outgoing Set (the slot's
 * set COUNT belongs to the muscle's volume, so it stays), each at the
 * alternative's OWN prescription — never the outgoing Exercise's numbers —
 * preserving the outgoing set_type so a planned warmup stays a warmup.
 */
export function incomingSets(
  outgoing: TrainingSet[],
  alternative: SwapAlternative,
): SetCreate[] {
  return outgoing.map((s) => ({
    exercise_id: alternative.exercise_id,
    weight_kg: alternative.target_weight_kg,
    reps: alternative.target_reps,
    set_type: s.set_type,
  }));
}

/**
 * The full Session set-id order after a Swap: the new ids take the outgoing
 * ids' positions (a non-consecutive outgoing run collapses to its first
 * position — blocks are consecutive by construction, this is just safety).
 */
export function swappedOrder(
  allIds: string[],
  outgoingIds: string[],
  newIds: string[],
): string[] {
  const outgoing = new Set(outgoingIds);
  const out: string[] = [];
  let inserted = false;
  for (const id of allIds) {
    if (outgoing.has(id)) {
      if (!inserted) {
        out.push(...newIds);
        inserted = true;
      }
      continue;
    }
    out.push(id);
  }
  if (!inserted) out.push(...newIds);
  return out;
}
