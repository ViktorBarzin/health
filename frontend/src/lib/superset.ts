// Superset grouping — PURE display + alternation logic.
//
// A Superset is two or more Exercises within a Session logged in alternation
// (CONTEXT.md). The model: each Set carries a nullable `superset_group` integer;
// Sets sharing a group id form one Superset, NULL means standalone. These
// helpers turn the flat, order_index-ordered Set list into display blocks
// (standalone exercise blocks vs. superset blocks) and decide which Exercise the
// logger auto-advances to after a Set in a Superset.

/** The minimal Set shape these helpers need (a subset of TrainingSet). */
export interface SetLike {
  id: string;
  exercise_id: string;
  order_index: number;
  superset_group: number | null;
}

/** A run of standalone sets of one Exercise. */
export interface SingleBlock<T extends SetLike> {
  kind: 'single';
  exerciseId: string;
  sets: T[];
}

/** A Superset: its group id, the distinct Exercises in it, and all its sets. */
export interface SupersetBlock<T extends SetLike> {
  kind: 'superset';
  group: number;
  exerciseIds: string[];
  sets: T[];
}

export type SessionBlock<T extends SetLike> = SingleBlock<T> | SupersetBlock<T>;

/**
 * Group a Session's ordered Sets into display blocks.
 *
 * Walks the Sets in their given order. Each ``superset_group`` collapses into a
 * SINGLE block anchored where the group first appears — even if its members are
 * NOT contiguous in ``order_index`` (a freshly-added superset set lands at the
 * end of the Session, and grouping can tag scattered sets). Collecting a group
 * into one block keeps every group id unique across blocks, so the rendering
 * keyed-each never collides; the group's sets keep their relative order.
 * Standalone Sets coalesce into single-exercise blocks for consecutive runs.
 */
export function groupSessionSets<T extends SetLike>(sets: T[]): SessionBlock<T>[] {
  const blocks: SessionBlock<T>[] = [];
  const supersetBlocks = new Map<number, SupersetBlock<T>>();
  for (const set of sets) {
    if (set.superset_group !== null) {
      const existing = supersetBlocks.get(set.superset_group);
      if (existing) {
        existing.sets.push(set);
        if (!existing.exerciseIds.includes(set.exercise_id)) {
          existing.exerciseIds.push(set.exercise_id);
        }
      } else {
        // First appearance of this group: anchor a new block in place.
        const block: SupersetBlock<T> = {
          kind: 'superset',
          group: set.superset_group,
          exerciseIds: [set.exercise_id],
          sets: [set],
        };
        supersetBlocks.set(set.superset_group, block);
        blocks.push(block);
      }
      continue;
    }
    const last = blocks[blocks.length - 1];
    if (last && last.kind === 'single' && last.exerciseId === set.exercise_id) {
      last.sets.push(set);
    } else {
      blocks.push({ kind: 'single', exerciseId: set.exercise_id, sets: [set] });
    }
  }
  return blocks;
}

/**
 * The Exercise the logger should auto-advance to after the Set `afterSetId`,
 * when that Set belongs to a Superset — the next distinct Exercise in the
 * group's rotation, wrapping around. Returns null when the Set is standalone,
 * unknown, or the only Exercise in its group (nothing to alternate with).
 */
export function nextSupersetExerciseId<T extends SetLike>(
  sets: T[],
  afterSetId: string,
): string | null {
  const set = sets.find((x) => x.id === afterSetId);
  if (!set || set.superset_group === null) return null;

  // Distinct Exercises in this group, in first-seen order.
  const rotation: string[] = [];
  for (const x of sets) {
    if (x.superset_group === set.superset_group && !rotation.includes(x.exercise_id)) {
      rotation.push(x.exercise_id);
    }
  }
  if (rotation.length < 2) return null; // need at least two to alternate

  const i = rotation.indexOf(set.exercise_id);
  return rotation[(i + 1) % rotation.length];
}

/**
 * The next free Superset group id for a Session: max existing group + 1, or 0
 * when there are none. Mirrors the server's assignment so a Superset created
 * offline (expressed as `superset_group` patches; ADR-0005) lands on the same
 * id the server would have chosen.
 */
export function nextGroupId(sets: SetLike[]): number {
  let max = -1;
  for (const s of sets) {
    if (s.superset_group !== null && s.superset_group > max) max = s.superset_group;
  }
  return max + 1;
}
