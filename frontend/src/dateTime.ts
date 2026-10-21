export const TASK_TIME_ZONE = 'Asia/Yerevan';

const dateTimeFormatter = new Intl.DateTimeFormat(
  'en-GB-u-ca-iso8601-nu-latn',
  {
    timeZone: TASK_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  },
);

function partsAtYerevan(date: Date) {
  const parts = dateTimeFormatter.formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value);
  return {
    year: part('year'),
    month: part('month'),
    day: part('day'),
    hour: part('hour'),
    minute: part('minute'),
  };
}

export function toYerevanDateTimeLocal(value: string | null | undefined) {
  if (!value) return '';
  const { year, month, day, hour, minute } = partsAtYerevan(new Date(value));
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

export function fromYerevanDateTimeLocal(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new RangeError('Enter a valid Yerevan date and time');

  const target = match.slice(1).map(Number);
  const [year, month, day, hour, minute] = target;
  const localAsUtc = Date.UTC(year, month - 1, day, hour, minute);
  const normalized = new Date(localAsUtc);
  if (
    normalized.getUTCFullYear() !== year ||
    normalized.getUTCMonth() + 1 !== month ||
    normalized.getUTCDate() !== day ||
    normalized.getUTCHours() !== hour ||
    normalized.getUTCMinutes() !== minute
  ) {
    throw new RangeError('Enter a valid Yerevan date and time');
  }

  let timestamp = localAsUtc;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const actual = partsAtYerevan(new Date(timestamp));
    const offset =
      Date.UTC(
        actual.year,
        actual.month - 1,
        actual.day,
        actual.hour,
        actual.minute,
      ) - timestamp;
    const adjusted = localAsUtc - offset;
    if (adjusted === timestamp) break;
    timestamp = adjusted;
  }

  const actual = partsAtYerevan(new Date(timestamp));
  if (
    actual.year !== year ||
    actual.month !== month ||
    actual.day !== day ||
    actual.hour !== hour ||
    actual.minute !== minute
  ) {
    throw new RangeError('This local time does not exist in Yerevan');
  }
  return new Date(timestamp).toISOString();
}
