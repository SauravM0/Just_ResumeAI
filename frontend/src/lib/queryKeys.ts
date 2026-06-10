/**
 * TanStack Query key constants — single source of truth for cache keys.
 *
 * Usage:
 *   queryClient.invalidateQueries({ queryKey: QUERY_KEYS.generations(userId) })
 *   useQuery({ queryKey: QUERY_KEYS.generation(id), ... })
 *
 * Keys are arrays so `invalidateQueries` with a prefix is straightforward:
 *   queryClient.invalidateQueries({ queryKey: ['generation'] }) // invalidates all single generations
 */

export const QUERY_KEYS = {
  /** Current user's master profile */
  profile: (userId?: string) => ['profile', userId] as const,

  /** Single generation result (completed) */
  generation: (generationId: string) => ['generation', generationId] as const,

  /** Generation history list for a user */
  generations: (userId?: string) => ['generations', userId] as const,

  /** JD analysis results (cached by stable text hash) */
  jdAnalysis: (jdHash?: string) => ['jd-analysis', jdHash] as const,

  /** Cover letter for a specific generation */
  coverLetter: (generationId: string) => ['cover-letter', generationId] as const,

  /** User settings / preferences */
  settings: (userId?: string) => ['settings', userId] as const,
} as const;

/**
 * Cache duration config in milliseconds.
 *
 * principle:
 * - Completed / immutable data → staleTime = Infinity (never refetched automatically)
 * - User-specific data       → staleTime 5 min (refetched on tab focus)
 * - List data                → staleTime 30 s (refetched often)
 * - JD analysis              → staleTime 10 min (same JD pasted twice hits cache)
 */
export const CACHE_CONFIG = {
  /** Master profile — rarely changes */
  profile: { staleTime: 5 * 60 * 1000, gcTime: 30 * 60 * 1000 },

  /** Completed generation result — never changes */
  generation: { staleTime: Infinity, gcTime: 60 * 60 * 1000 },

  /** Generation history list — refreshed on new generation complete */
  generations: { staleTime: 30 * 1000, gcTime: 5 * 60 * 1000 },

  /** JD analysis — cached aggressively */
  jdAnalysis: { staleTime: 10 * 60 * 1000, gcTime: 30 * 60 * 1000 },

  /** Cover letter — changes only when user edits */
  coverLetter: { staleTime: 2 * 60 * 1000, gcTime: 30 * 60 * 1000 },

  /** User settings — rarely changes */
  settings: { staleTime: 10 * 60 * 1000, gcTime: 30 * 60 * 1000 },
} as const;
