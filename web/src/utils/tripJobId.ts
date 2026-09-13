export function isValidTripJobId(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
    && !['null', 'undefined'].includes(value.trim().toLowerCase());
}
