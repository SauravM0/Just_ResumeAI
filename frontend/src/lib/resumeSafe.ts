export function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

export function objectArray<T extends object>(value: unknown): T[] {
  return Array.isArray(value) ? (value.filter((item): item is T => Boolean(item) && typeof item === 'object') as T[]) : [];
}

export function joinedStrings(value: unknown, separator = ', '): string {
  return stringArray(value).filter(Boolean).join(separator);
}
