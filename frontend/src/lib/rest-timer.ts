// Rest-timer state — a PURE, reducer-driven countdown.
//
// The timer auto-starts when a Set is logged and counts down a per-Exercise
// default rest duration; the user can skip or adjust it. Keeping the STATE pure
// (and wall-clock based, so a missed tick or a backgrounded tab still lands on
// the right remaining time) lets it be unit-tested in isolation, while the
// component owns the side-effects: a tick interval, plus a sound + vibration on
// the `justCompleted` edge.

export interface RestTimerState {
  /** Whether a countdown is currently running. */
  running: boolean;
  /** The configured duration of the current/last countdown (seconds). */
  durationSec: number;
  /** Whole seconds left; 0 when idle or finished. */
  remainingSec: number;
  /** Epoch-ms the current countdown ends at (null when idle). */
  endsAt: number | null;
  /**
   * True for the single reducer step in which the countdown hit zero — the
   * component reads this to fire the completion sound/vibration exactly once,
   * and it clears on the next action.
   */
  justCompleted: boolean;
}

export type RestTimerAction =
  | { type: 'start'; durationSec: number; now: number }
  | { type: 'tick'; now: number }
  | { type: 'skip' }
  | { type: 'adjust'; deltaSec: number; now: number };

/** The initial (idle) timer state. */
export function idleTimer(): RestTimerState {
  return {
    running: false,
    durationSec: 0,
    remainingSec: 0,
    endsAt: null,
    justCompleted: false,
  };
}

/**
 * Advance the rest-timer state. Pure: `now` (epoch-ms) is always supplied by the
 * caller so the reducer never reads the clock itself.
 */
export function restTimerReducer(
  state: RestTimerState,
  action: RestTimerAction,
): RestTimerState {
  switch (action.type) {
    case 'start': {
      const duration = Math.max(0, Math.round(action.durationSec));
      return {
        running: duration > 0,
        durationSec: duration,
        remainingSec: duration,
        endsAt: action.now + duration * 1000,
        justCompleted: false,
      };
    }

    case 'tick': {
      if (!state.running || state.endsAt === null) {
        // Idle/finished: clear any stale completion edge, change nothing else.
        return state.justCompleted ? { ...state, justCompleted: false } : state;
      }
      return settle(state, state.endsAt - action.now);
    }

    case 'adjust': {
      if (!state.running || state.endsAt === null) return state;
      const endsAt = state.endsAt + Math.round(action.deltaSec) * 1000;
      return settle({ ...state, endsAt }, endsAt - action.now);
    }

    case 'skip':
      return {
        ...idleTimer(),
        durationSec: state.durationSec,
      };
  }
}

/**
 * Resolve a running timer given the milliseconds left until `endsAt`: still
 * counting down, or just hit zero (fire the completion edge once).
 */
function settle(state: RestTimerState, msLeft: number): RestTimerState {
  if (msLeft <= 0) {
    return {
      ...state,
      running: false,
      remainingSec: 0,
      endsAt: null,
      justCompleted: true,
    };
  }
  return {
    ...state,
    running: true,
    remainingSec: Math.ceil(msLeft / 1000),
    justCompleted: false,
  };
}
