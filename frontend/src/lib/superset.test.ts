import { describe, expect, it } from 'vitest';
import {
  groupSessionSets,
  nextSupersetExerciseId,
  type SetLike,
} from './superset';

// Supersets group Exercises within a Session, logged in ALTERNATION. The model:
// each Set carries a nullable `superset_group` integer; Sets sharing a group id
// (in order) are one Superset. These pure helpers build the display grouping
// (standalone exercise blocks vs. superset blocks) and decide which Exercise the
// logger should auto-advance to next within a Superset.

function s(
  id: string,
  exercise_id: string,
  order_index: number,
  superset_group: number | null = null,
): SetLike {
  return { id, exercise_id, order_index, superset_group };
}

describe('groupSessionSets', () => {
  it('groups consecutive same-exercise standalone sets into one block', () => {
    const sets = [
      s('1', 'squat', 0),
      s('2', 'squat', 1),
      s('3', 'bench', 2),
    ];
    const blocks = groupSessionSets(sets);
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ kind: 'single', exerciseId: 'squat' });
    expect(blocks[0].sets.map((x) => x.id)).toEqual(['1', '2']);
    expect(blocks[1]).toMatchObject({ kind: 'single', exerciseId: 'bench' });
  });

  it('groups all sets of one superset group into a single superset block', () => {
    // A↔B superset logged in alternation: bench, row, bench, row.
    const sets = [
      s('1', 'bench', 0, 1),
      s('2', 'row', 1, 1),
      s('3', 'bench', 2, 1),
      s('4', 'row', 3, 1),
    ];
    const blocks = groupSessionSets(sets);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].kind).toBe('superset');
    expect(blocks[0].group).toBe(1);
    expect(blocks[0].exerciseIds).toEqual(['bench', 'row']);
    expect(blocks[0].sets.map((x) => x.id)).toEqual(['1', '2', '3', '4']);
  });

  it('keeps two different superset groups as separate blocks', () => {
    const sets = [
      s('1', 'bench', 0, 1),
      s('2', 'row', 1, 1),
      s('3', 'curl', 2, 2),
      s('4', 'pushdown', 3, 2),
    ];
    const blocks = groupSessionSets(sets);
    expect(blocks).toHaveLength(2);
    expect(blocks[0].group).toBe(1);
    expect(blocks[1].group).toBe(2);
  });

  it('interleaves standalone blocks and superset blocks in order', () => {
    const sets = [
      s('1', 'squat', 0),
      s('2', 'bench', 1, 5),
      s('3', 'row', 2, 5),
      s('4', 'curl', 3),
    ];
    const blocks = groupSessionSets(sets);
    expect(blocks.map((b) => b.kind)).toEqual(['single', 'superset', 'single']);
    expect(blocks[1].exerciseIds).toEqual(['bench', 'row']);
  });

  it('preserves distinct exercises within a superset in first-seen order', () => {
    const sets = [
      s('1', 'a', 0, 7),
      s('2', 'b', 1, 7),
      s('3', 'c', 2, 7),
      s('4', 'a', 3, 7),
    ];
    const blocks = groupSessionSets(sets);
    expect(blocks[0].exerciseIds).toEqual(['a', 'b', 'c']);
  });

  it('collapses a NON-contiguous superset group into one block (no fractured/duplicate blocks)', () => {
    // A freshly-added superset set lands at the end of the session, or grouping
    // tags scattered sets — so a group's members may not be adjacent in order.
    // They must still render as ONE block (one unique group id), not several.
    const sets = [
      s('1', 'bench', 0, 1),
      s('2', 'row', 1, 1),
      s('3', 'squat', 2), // a standalone set interrupts the group's order
      s('4', 'bench', 3, 1), // another set of group 1, after the interruption
    ];
    const blocks = groupSessionSets(sets);
    // Exactly one superset block for group 1 (anchored at first appearance),
    // plus the standalone squat — NOT two superset blocks sharing group 1.
    const supersets = blocks.filter((b) => b.kind === 'superset');
    expect(supersets).toHaveLength(1);
    expect(supersets[0].group).toBe(1);
    expect(supersets[0].sets.map((x) => x.id)).toEqual(['1', '2', '4']);
    expect(supersets[0].exerciseIds).toEqual(['bench', 'row']);
    // group ids are unique across all blocks → keyed-each can't collide
    const groupIds = supersets.map((b) => b.group);
    expect(new Set(groupIds).size).toBe(groupIds.length);
  });

  it('keeps two scattered groups distinct even when interleaved', () => {
    const sets = [
      s('1', 'a', 0, 1),
      s('2', 'c', 1, 2),
      s('3', 'b', 2, 1),
      s('4', 'd', 3, 2),
    ];
    const blocks = groupSessionSets(sets);
    expect(blocks).toHaveLength(2);
    expect(blocks[0].group).toBe(1); // anchored where group 1 first appeared
    expect(blocks[0].sets.map((x) => x.id)).toEqual(['1', '3']);
    expect(blocks[1].group).toBe(2);
    expect(blocks[1].sets.map((x) => x.id)).toEqual(['2', '4']);
  });

  it('returns no blocks for an empty session', () => {
    expect(groupSessionSets([])).toEqual([]);
  });
});

describe('nextSupersetExerciseId', () => {
  it('advances to the next exercise in the superset rotation', () => {
    // Superset [bench, row]; the last logged set was bench → next is row.
    const sets = [s('1', 'bench', 0, 1), s('2', 'row', 1, 1), s('3', 'bench', 2, 1)];
    expect(nextSupersetExerciseId(sets, '3')).toBe('row');
  });

  it('wraps around from the last exercise back to the first', () => {
    const sets = [s('1', 'bench', 0, 1), s('2', 'row', 1, 1)];
    expect(nextSupersetExerciseId(sets, '2')).toBe('bench');
  });

  it('rotates through three exercises in order', () => {
    const sets = [s('1', 'a', 0, 1), s('2', 'b', 1, 1), s('3', 'c', 2, 1)];
    expect(nextSupersetExerciseId(sets, '1')).toBe('b');
    expect(nextSupersetExerciseId(sets, '2')).toBe('c');
    expect(nextSupersetExerciseId(sets, '3')).toBe('a');
  });

  it('returns null for a standalone (non-superset) set', () => {
    const sets = [s('1', 'squat', 0, null)];
    expect(nextSupersetExerciseId(sets, '1')).toBeNull();
  });

  it('returns null when the set id is unknown', () => {
    const sets = [s('1', 'bench', 0, 1), s('2', 'row', 1, 1)];
    expect(nextSupersetExerciseId(sets, 'nope')).toBeNull();
  });

  it('returns null for a single-exercise superset (nothing to alternate with)', () => {
    const sets = [s('1', 'bench', 0, 1), s('2', 'bench', 1, 1)];
    expect(nextSupersetExerciseId(sets, '2')).toBeNull();
  });
});
