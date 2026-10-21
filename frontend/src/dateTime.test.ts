import { describe, expect, it } from 'vitest';
import { fromYerevanDateTimeLocal, toYerevanDateTimeLocal } from './dateTime';

describe('Yerevan task deadlines', () => {
  it('shows stored UTC instants on the Yerevan clock', () => {
    expect(toYerevanDateTimeLocal('2026-10-21T14:00:00Z')).toBe(
      '2026-10-21T18:00',
    );
  });

  it('stores a Yerevan date and time as the matching UTC instant', () => {
    expect(fromYerevanDateTimeLocal('2026-10-22T18:15')).toBe(
      '2026-10-22T14:15:00.000Z',
    );
  });

  it('handles dates that cross midnight when converted to UTC', () => {
    expect(fromYerevanDateTimeLocal('2026-10-22T00:15')).toBe(
      '2026-10-21T20:15:00.000Z',
    );
  });

  it('rejects impossible or malformed local dates', () => {
    expect(() => fromYerevanDateTimeLocal('2026-02-30T12:00')).toThrow(
      RangeError,
    );
    expect(() => fromYerevanDateTimeLocal('tomorrow')).toThrow(RangeError);
  });
});
