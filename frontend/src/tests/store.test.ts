import { beforeEach, describe, expect, it } from 'vitest'
import { useGenerationStore } from '../store/generationStore'

describe('generationStore', () => {
  beforeEach(() => {
    useGenerationStore.getState().reset()
  })

  it('starts from the expected initial state', () => {
    expect(useGenerationStore.getState()).toMatchObject({
      activeGenerationId: null,
      isGenerating: false,
      steps: [],
      currentStepId: null,
      originalScore: null,
      finalScore: null,
      error: null,
      rawEvents: [],
    })
  })

  it('starts a generation and clears previous progress', () => {
    const store = useGenerationStore.getState()

    store.setError('previous error')
    store.addRawEvent('old', { stale: true })
    store.startGeneration('gen-123')

    expect(useGenerationStore.getState()).toMatchObject({
      activeGenerationId: 'gen-123',
      isGenerating: true,
      steps: [],
      error: null,
      rawEvents: [],
    })
  })

  it('marks previous in-progress steps done when adding a new step', () => {
    const store = useGenerationStore.getState()

    store.addStep({ label: 'Parsing job description', status: 'in-progress' })
    store.addStep({ label: 'Scoring resume', status: 'in-progress' })

    const { steps, currentStepId } = useGenerationStore.getState()
    expect(steps).toHaveLength(2)
    expect(steps[0]).toMatchObject({ label: 'Parsing job description', status: 'done' })
    expect(steps[1]).toMatchObject({ label: 'Scoring resume', status: 'in-progress' })
    expect(currentStepId).toBe(steps[1].id)
  })

  it('stores scores, errors, raw events, and resets cleanly', () => {
    const store = useGenerationStore.getState()

    store.startGeneration('gen-456')
    store.setOriginalScore(44)
    store.setFinalScore(91)
    store.addRawEvent('complete', { final_score: 91 })
    store.setError('late failure')

    expect(useGenerationStore.getState()).toMatchObject({
      originalScore: 44,
      finalScore: 91,
      isGenerating: false,
      error: 'late failure',
      rawEvents: [{ event: 'complete', data: { final_score: 91 } }],
    })

    useGenerationStore.getState().reset()
    expect(useGenerationStore.getState()).toMatchObject({
      activeGenerationId: null,
      isGenerating: false,
      steps: [],
      currentStepId: null,
      originalScore: null,
      finalScore: null,
      error: null,
      rawEvents: [],
    })
  })

  it('tracks queued, running, completed, and failed lifecycle states', () => {
    const store = useGenerationStore.getState()

    store.startGeneration('gen-status')
    expect(useGenerationStore.getState()).toMatchObject({
      status: 'queued',
      isGenerating: true,
      activeGenerationId: 'gen-status',
    })

    store.setStatus('running')
    expect(useGenerationStore.getState()).toMatchObject({
      status: 'running',
      isGenerating: true,
    })

    store.setStatus('completed')
    expect(useGenerationStore.getState()).toMatchObject({
      status: 'completed',
      isGenerating: false,
    })

    store.setError('Generation failed')
    expect(useGenerationStore.getState()).toMatchObject({
      status: 'failed',
      isGenerating: false,
      error: 'Generation failed',
    })
  })
})
