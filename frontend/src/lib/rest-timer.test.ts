import { describe, expect, it } from 'vitest';
import {
  idleTimer,
  restTimerReducer,
  type RestTimerState,
} from './rest-timer';

// The rest timer's STATE is pure and reducer-driven (start when a Set is logged,
// tick down, skip, adjust, complete); the SOUND + VIBRATION side-effects live in
// the component. Testing the reducer here pins the countdown arithmetic, the
// "just completed" edge (fired exactly once), and skip/adjust behaviour.

const t0 = 1_000_000; // an arbitrary epoch-ms "now"

function start(durationSec: number, now = t0): RestTimerState {
  return restTimerReducer(idleTimer(), { type: 'start', durationSec, now });
}

describe('restTimerReducer', () => {
  it('is idle initially (not running, no remaining)', () => {
    const s = idleTimer();
    expect(s.running).toBe(false);
    expect(s.remainingSec).toBe(0);
    expect(s.justCompleted).toBe(false);
  });

  it('starts a countdown for the given duration', () => {
    const s = start(120);
    expect(s.running).toBe(true);
    expect(s.durationSec).toBe(120);
    expect(s.remainingSec).toBe(120);
    expect(s.justCompleted).toBe(false);
  });

  it('counts down on tick based on elapsed wall-clock time', () => {
    let s = start(120, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 5_000 }); // +5s
    expect(s.remainingSec).toBe(115);
    expect(s.running).toBe(true);
  });

  it('uses wall-clock elapsed (robust to missed ticks / backgrounding)', () => {
    let s = start(120, t0);
    // A single tick 30s later must reflect the full elapsed, not one second.
    s = restTimerReducer(s, { type: 'tick', now: t0 + 30_000 });
    expect(s.remainingSec).toBe(90);
  });

  it('fires justCompleted exactly once when it reaches zero', () => {
    let s = start(10, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 10_000 }); // exactly 0
    expect(s.remainingSec).toBe(0);
    expect(s.running).toBe(false);
    expect(s.justCompleted).toBe(true);
    // A subsequent tick must NOT re-fire the completion edge.
    s = restTimerReducer(s, { type: 'tick', now: t0 + 11_000 });
    expect(s.justCompleted).toBe(false);
    expect(s.running).toBe(false);
  });

  it('clamps remaining at zero when ticked past the end', () => {
    let s = start(10, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 25_000 });
    expect(s.remainingSec).toBe(0);
    expect(s.justCompleted).toBe(true);
  });

  it('skip stops the timer without firing completion', () => {
    let s = start(120, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 5_000 });
    s = restTimerReducer(s, { type: 'skip' });
    expect(s.running).toBe(false);
    expect(s.remainingSec).toBe(0);
    expect(s.justCompleted).toBe(false);
  });

  it('adjust adds time to a running timer and keeps it running', () => {
    let s = start(120, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 10_000 }); // 110 left
    s = restTimerReducer(s, { type: 'adjust', deltaSec: 30, now: t0 + 10_000 });
    expect(s.remainingSec).toBe(140);
    expect(s.running).toBe(true);
  });

  it('adjust can subtract time and never goes below zero', () => {
    let s = start(120, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 10_000 }); // 110 left
    s = restTimerReducer(s, { type: 'adjust', deltaSec: -200, now: t0 + 10_000 });
    expect(s.remainingSec).toBe(0);
    // Adjusting a running timer to zero completes it.
    expect(s.running).toBe(false);
    expect(s.justCompleted).toBe(true);
  });

  it('restarts cleanly when a new Set starts mid-countdown', () => {
    let s = start(120, t0);
    s = restTimerReducer(s, { type: 'tick', now: t0 + 60_000 }); // 60 left
    s = restTimerReducer(s, { type: 'start', durationSec: 90, now: t0 + 60_000 });
    expect(s.remainingSec).toBe(90);
    expect(s.running).toBe(true);
    expect(s.justCompleted).toBe(false);
  });

  it('ignores ticks while idle', () => {
    let s = idleTimer();
    s = restTimerReducer(s, { type: 'tick', now: t0 });
    expect(s.running).toBe(false);
    expect(s.remainingSec).toBe(0);
    expect(s.justCompleted).toBe(false);
  });
});
