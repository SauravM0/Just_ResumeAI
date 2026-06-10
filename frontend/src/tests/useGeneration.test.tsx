import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGeneration } from '../hooks/useGeneration'
import { useGenerationStore } from '../store/generationStore'

const apiMocks = vi.hoisted(() => ({
  startGeneration: vi.fn(),
  connectGenerationStream: vi.fn(),
  getGenerationResult: vi.fn(),
}))

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    startGeneration: apiMocks.startGeneration,
    connectGenerationStream: apiMocks.connectGenerationStream,
    getGenerationResult: apiMocks.getGenerationResult,
  }
})

const minimalProfile = {
  id: 'profile-1',
  user_id: 'user-1',
  contact: { full_name: 'Ada Lovelace', email: 'ada@example.com' },
  experience: [],
  education: [],
  skills: [],
  projects: [],
  certifications: [],
  achievements: [],
  awards: [],
  custom_sections: [],
}

function wrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return function TestWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('useGeneration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useGenerationStore.getState().reset()
  })

  it('starts generation, consumes SSE events, and reports completion', async () => {
    const cleanup = vi.fn()
    const onComplete = vi.fn()

    apiMocks.startGeneration.mockResolvedValue({ generation_id: 'gen-1', status: 'started' })
    apiMocks.getGenerationResult.mockResolvedValue({ generation_id: 'gen-1' })
    apiMocks.connectGenerationStream.mockImplementation(async (_id, onEvent) => {
      onEvent({ event: 'started', data: {} })
      onEvent({ event: 'original_scored', data: { original_score: 47 } })
      onEvent({ event: 'complete', data: { final_score: 92 } })
      return cleanup
    })

    const { result } = renderHook(() => useGeneration({ onComplete }), { wrapper: wrapper() })

    await act(async () => {
      await result.current.generate({
        profile: minimalProfile as never,
        raw_jd_text: 'Senior engineer role with React and Python.',
      })
    })

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({
      generationId: 'gen-1',
      originalScore: 47,
      finalScore: 92,
    }))

    expect(apiMocks.connectGenerationStream).toHaveBeenCalledWith(
      'gen-1',
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    )
    expect(useGenerationStore.getState()).toMatchObject({
      activeGenerationId: 'gen-1',
      isGenerating: false,
      originalScore: 47,
      finalScore: 92,
    })
    expect(useGenerationStore.getState().steps.at(-1)).toMatchObject({
      label: 'Resume ready!',
      status: 'done',
    })
  })

  it('sets store error and calls onError when start fails', async () => {
    const onError = vi.fn()
    const error = Object.assign(new Error('Unable to queue generation'), { code: 'PIPELINE_ERROR' })
    apiMocks.startGeneration.mockRejectedValue(error)

    const { result } = renderHook(() => useGeneration({ onError }), { wrapper: wrapper() })

    await act(async () => {
      await result.current.generate({
        profile: minimalProfile as never,
        raw_jd_text: 'not enough detail',
      })
    })

    expect(onError).toHaveBeenCalledWith('PIPELINE_ERROR', 'Unable to queue generation')
    expect(useGenerationStore.getState()).toMatchObject({
      isGenerating: false,
      error: 'Unable to queue generation',
    })
  })

  it('cancels the active stream and resets progress', async () => {
    const cleanup = vi.fn()
    apiMocks.startGeneration.mockResolvedValue({ generation_id: 'gen-cancel', status: 'started' })
    apiMocks.connectGenerationStream.mockResolvedValue(cleanup)

    const { result } = renderHook(() => useGeneration(), { wrapper: wrapper() })

    await act(async () => {
      await result.current.generate({
        profile: minimalProfile as never,
        raw_jd_text: 'A role that can be cancelled.',
      })
    })

    act(() => {
      result.current.cancel()
    })

    expect(cleanup).toHaveBeenCalledTimes(1)
    expect(useGenerationStore.getState()).toMatchObject({
      activeGenerationId: null,
      isGenerating: false,
      steps: [],
    })
  })

  it('polls generation result and completes when SSE disconnects after backend completion', async () => {
    const onComplete = vi.fn()
    apiMocks.startGeneration.mockResolvedValue({ generation_id: 'gen-fallback', status: 'queued' })
    apiMocks.getGenerationResult.mockResolvedValue({
      generation_id: 'gen-fallback',
      status: 'completed',
      resume_json: { summary: 'Done' },
      ats_score_json: { overall_score: 89 },
    })
    apiMocks.connectGenerationStream.mockImplementation(async (_id, _onEvent, _onComplete, onError) => {
      onError?.(new Error('stream disconnected'))
      return vi.fn()
    })

    const { result } = renderHook(() => useGeneration({ onComplete }), { wrapper: wrapper() })

    await act(async () => {
      await result.current.generate({
        profile: minimalProfile as never,
        raw_jd_text: 'Senior engineer role with durable SSE fallback.',
      })
    })

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({
      generationId: 'gen-fallback',
      originalScore: undefined,
      finalScore: 89,
    }))

    expect(apiMocks.getGenerationResult).toHaveBeenCalledWith('gen-fallback')
    expect(useGenerationStore.getState()).toMatchObject({
      status: 'completed',
      isGenerating: false,
      finalScore: 89,
    })
  })
})
