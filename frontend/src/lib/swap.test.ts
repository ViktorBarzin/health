// Pure Swap view-logic (CONTEXT.md "Swap") — the mid-Session replace plan.
//
// A Swap replaces one exercise block's Sets with the incoming alternative's,
// expressed in existing op-queue verbs (delete + add + reorder) so it works
// offline on prefetched data. These tests pin:
// - the incoming Sets: one per outgoing Set (the slot's set COUNT is the
//   muscle's volume, so it stays), each at the alternative's OWN prescription,
//   preserving the outgoing set_type (a planned warmup stays a warmup);
// - the final order: the new ids take the outgoing ids' positions exactly.

import { describe, expect, it } from 'vitest';
import { incomingSets, swappedOrder, type SwapAlternative } from './swap';
import type { TrainingSet } from './types';

function set(id: string, exerciseId: string, type = 'normal'): TrainingSet {
  return {
    id,
    exercise_id: exerciseId,
    order_index: 0,
    weight_kg: 60,
    reps: 8,
    set_type: type as TrainingSet['set_type'],
    effort_rir: null,
    superset_group: null,
    exercise_name: null,
  };
}

const ALT: SwapAlternative = {
  exercise_id: 'alt-ex',
  name: 'Dumbbell Bench Press',
  equipment: 'dumbbell',
  target_reps: 10,
  target_weight_kg: 26,
  is_starting_point: false,
  has_history: true,
  primary_muscles: ['chest'],
  secondary_muscles: [],
  shared_muscles: ['chest'],
};

describe('incomingSets', () => {
  it('creates one Set per outgoing Set at the alternative’s own prescription', () => {
    const outgoing = [set('a', 'bench'), set('b', 'bench'), set('c', 'bench')];
    const adds = incomingSets(outgoing, ALT);
    expect(adds).toHaveLength(3);
    for (const add of adds) {
      expect(add.exercise_id).toBe('alt-ex');
      expect(add.weight_kg).toBe(26);
      expect(add.reps).toBe(10);
    }
  });

  it('preserves each outgoing set_type (planned warmups stay warmups)', () => {
    const outgoing = [set('a', 'bench', 'warmup'), set('b', 'bench')];
    const adds = incomingSets(outgoing, ALT);
    expect(adds.map((a) => a.set_type)).toEqual(['warmup', 'normal']);
  });
});

describe('swappedOrder', () => {
  it('puts the new ids exactly where the outgoing ids were (middle block)', () => {
    const all = ['s1', 's2', 'b1', 'b2', 'b3', 's3'];
    expect(swappedOrder(all, ['b1', 'b2', 'b3'], ['n1', 'n2', 'n3'])).toEqual([
      's1',
      's2',
      'n1',
      'n2',
      'n3',
      's3',
    ]);
  });

  it('handles head and tail blocks', () => {
    expect(swappedOrder(['b1', 's1'], ['b1'], ['n1'])).toEqual(['n1', 's1']);
    expect(swappedOrder(['s1', 'b1'], ['b1'], ['n1'])).toEqual(['s1', 'n1']);
  });

  it('handles a different incoming count than outgoing', () => {
    expect(swappedOrder(['s1', 'b1', 'b2', 's2'], ['b1', 'b2'], ['n1'])).toEqual([
      's1',
      'n1',
      's2',
    ]);
  });

  it('collapses a non-consecutive outgoing run to its first position', () => {
    expect(
      swappedOrder(['b1', 's1', 'b2', 's2'], ['b1', 'b2'], ['n1', 'n2']),
    ).toEqual(['n1', 'n2', 's1', 's2']);
  });
});
