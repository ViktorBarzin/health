import { describe, it, expect } from 'vitest';
import { looksLikeFitbodCsv } from './fitbod';

describe('looksLikeFitbodCsv', () => {
  it('accepts the real Fitbod export header', () => {
    const header =
      'Date,Exercise,Reps,Weight(kg),Duration(s),Distance(m),Incline,Resistance,isWarmup,Note,multiplier';
    expect(looksLikeFitbodCsv(header + '\n2021-12-27 10:00:00 +0000,Squat,5,100,...')).toBe(true);
  });

  it('accepts a reordered header (matched by name, not position)', () => {
    expect(looksLikeFitbodCsv('Note,Exercise,Weight(kg),Reps,isWarmup,Date\n')).toBe(true);
  });

  it('is case- and whitespace-insensitive', () => {
    expect(looksLikeFitbodCsv(' DATE , Exercise , REPS , Weight(kg) \n')).toBe(true);
  });

  it('accepts "Exercise Name" as the exercise column', () => {
    expect(looksLikeFitbodCsv('Date,Exercise Name,Reps,Weight\n')).toBe(true);
  });

  it('rejects a file missing the Reps column', () => {
    expect(looksLikeFitbodCsv('Date,Exercise,Weight(kg)\n')).toBe(false);
  });

  it('rejects an Apple Health / unrelated CSV', () => {
    expect(looksLikeFitbodCsv('startDate,endDate,type,value,unit\n')).toBe(false);
  });

  it('rejects empty input', () => {
    expect(looksLikeFitbodCsv('')).toBe(false);
    expect(looksLikeFitbodCsv('\n\n')).toBe(false);
  });
});
