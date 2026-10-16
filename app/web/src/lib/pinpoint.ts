export function parsePinpoint(pinpoint: string): { start: number; end: number } | null {
  const range = pinpoint.match(/(\d+)\s*[\u2013\u2014-]\s*(\d+)/);
  if (range) {
    const start = Number(range[1]);
    const end = Number(range[2]);
    if (start > 0 && end >= start) return { start, end };
    return null;
  }
  const single = pinpoint.match(/(\d+)/);
  if (!single) return null;
  const line = Number(single[1]);
  if (line <= 0) return null;
  return { start: line, end: line };
}
