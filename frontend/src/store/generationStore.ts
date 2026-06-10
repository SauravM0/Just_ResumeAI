/**
 * Generation progress store — tracks the active SSE streaming generation.
 *
 * Separated from useAppStore so components that only need progress state
 * (GenerationProgress, cancel button, etc.) don't subscribe to the entire
 * generation result data.
 */

import { create } from 'zustand';

export interface GenerationStep {
  id: string;
  label: string;
  detail?: string;
  status: 'pending' | 'in-progress' | 'done' | 'error';
  timestamp?: number;
  /** Score value shown inline (e.g. repair pass score) */
  score?: number;
}

export interface GenerationState {
  /** Backend lifecycle status for the active generation */
  status: 'idle' | 'draft' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  /** ID of the active/in-progress generation */
  activeGenerationId: string | null;
  /** Whether a generation is currently running */
  isGenerating: boolean;
  /** Ordered list of steps with status */
  steps: GenerationStep[];
  /** ID of the currently active step */
  currentStepId: string | null;
  /** Original resume ATS score before optimisation */
  originalScore: number | null;
  /** Final ATS score after optimisation */
  finalScore: number | null;
  /** Error message if generation failed */
  error: string | null;
  /** Raw SSE events for backward compatibility with GenerationProgress */
  rawEvents: Array<{ event: string; data: Record<string, unknown> }>;

  // ── Actions ────────────────────────────────────────────
  startGeneration: (generationId: string) => void;
  addStep: (step: Omit<GenerationStep, 'id' | 'timestamp'>) => void;
  updateStep: (stepId: string, updates: Partial<GenerationStep>) => void;
  setOriginalScore: (score: number) => void;
  setFinalScore: (score: number) => void;
  setError: (error: string) => void;
  setActiveMessage: (message: string, status?: 'draft' | 'queued' | 'running') => void;
  setStatus: (status: GenerationState['status']) => void;
  /** Append a raw SSE event for backward compat with GenerationProgress */
  addRawEvent: (event: string, data: Record<string, unknown>) => void;
  /** Reset to initial state (called on cancel, error, or completion after navigating away) */
  reset: () => void;
}

const initialState = {
  status: 'idle' as const,
  activeGenerationId: null,
  isGenerating: false,
  steps: [],
  currentStepId: null,
  originalScore: null,
  finalScore: null,
  error: null,
  rawEvents: [],
};

let stepCounter = 0;

export const useGenerationStore = create<GenerationState>()((set) => ({
  ...initialState,

  startGeneration: (generationId) =>
    set({
      activeGenerationId: generationId,
      status: 'queued',
      isGenerating: true,
      steps: [],
      currentStepId: null,
      originalScore: null,
      finalScore: null,
      error: null,
      rawEvents: [],
    }),

  addStep: (step) =>
    set((state) => {
      const newStep: GenerationStep = {
        ...step,
        id: `gstep-${++stepCounter}`,
        timestamp: Date.now(),
      };
      // Mark previous in-progress step as done
      const updatedSteps = state.steps.map((s) =>
        s.status === 'in-progress' ? { ...s, status: 'done' as const } : s,
      );
      return { steps: [...updatedSteps, newStep], currentStepId: newStep.id };
    }),

  updateStep: (stepId, updates) =>
    set((state) => ({
      steps: state.steps.map((s) =>
        s.id === stepId ? { ...s, ...updates } : s,
      ),
    })),

  setOriginalScore: (score) => set({ originalScore: score }),

  setFinalScore: (score) => set({ finalScore: score, status: 'completed', isGenerating: false }),

  setError: (error) => set({ error, status: 'failed', isGenerating: false }),

  setActiveMessage: (message, status = 'running') =>
    set({
      error: message,
      status,
      isGenerating: true,
    }),

  setStatus: (status) =>
    set({
      status,
      isGenerating: status === 'draft' || status === 'queued' || status === 'running',
    }),

  addRawEvent: (event, data) =>
    set((state) => ({
      rawEvents: [...state.rawEvents, { event, data }],
    })),

  reset: () => set(initialState),
}));
