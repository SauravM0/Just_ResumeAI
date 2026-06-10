/**
 * useGeneration — React hook for SSE-driven resume generation.
 *
 * Combines:
 * 1. Zustand generationStore for local progress state
 * 2. @microsoft/fetch-event-source for SSE streaming with auth headers
 * 3. TanStack Query invalidation so history refetches on completion
 *
 * The hook uses `useGenerationStore.getState()` inside the SSE callback
 * to avoid unnecessary re-renders / stale dependencies.
 */
import { useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useGenerationStore } from '../store/generationStore';
import { ApiError, startGeneration, connectGenerationStream, getGenerationResult } from '../lib/api';
import { QUERY_KEYS } from '../lib/queryKeys';
import type { SSEProgressEvent } from '../lib/api';
import type { MasterProfile } from '../types/profile';

const STILL_RUNNING_MESSAGE = 'Resume generation is still running. You can find it in History when it finishes.';

export interface UseGenerationOptions {
  onComplete?: (result: {
    generationId: string;
    originalScore?: number;
    finalScore?: number;
  }) => void;
  /** Called when generation errors. `code` is the backend error code (e.g. 'JD_INVALID'), `message` is the human-readable description. */
  onError?: (code: string, message: string) => void;
}

export function useGeneration(options?: UseGenerationOptions) {
  const store = useGenerationStore();
  const queryClient = useQueryClient();
  const cleanupSseRef = useRef<(() => void) | null>(null);
  const activeGenIdRef = useRef<string | null>(null);
  const startingRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // Stable callback: uses getState() to read the store rather than closing over it
  const handleSSEEvent = useCallback(
    (event: SSEProgressEvent) => {
      const s = useGenerationStore.getState();
      const opts = optionsRef.current;
      const data = event.data as Record<string, unknown>;

      // Always push raw events for GenerationProgress backward compatibility
      s.addRawEvent(event.event, data);

      switch (event.event) {
        case 'status': {
          const status = (data as { status?: string }).status;
          if (status === 'draft' || status === 'queued' || status === 'running' || status === 'completed' || status === 'failed' || status === 'cancelled') {
            s.setStatus(status);
          }
          break;
        }

        case 'started':
          s.setStatus('running');
          s.addStep({ label: 'Starting generation', status: 'in-progress' });
          break;

        case 'jd_parsing':
          s.addStep({ label: 'Parsing job description', status: 'in-progress' });
          break;

        case 'jd_parsed': {
          const keywords = (data as { keywords_found?: number }).keywords_found;
          const title = (data as { job_title?: string }).job_title;
          s.updateStep(s.currentStepId || '', {
            label: 'Job description analysed',
            status: 'done',
            detail: `${title ? `${title} — ` : ''}${typeof keywords === 'number' ? keywords : 0} keywords detected`,
          });
          s.addStep({ label: 'Scoring your current resume', status: 'in-progress' });
          break;
        }

        case 'scoring_original':
          s.updateStep(s.currentStepId || '', {
            label: 'Scoring your current resume',
            status: 'in-progress',
          });
          break;

        case 'original_scored': {
          const originalScore = (data as { original_score?: number }).original_score;
          if (originalScore !== undefined) {
            s.setOriginalScore(originalScore);
          }
          s.updateStep(s.currentStepId || '', {
            status: 'done',
            detail: `Score: ${originalScore !== undefined ? Math.round(originalScore) : '?'}`,
          });
          s.addStep({ label: 'Matching experience to requirements', status: 'in-progress' });
          break;
        }

        case 'building_evidence':
          s.updateStep(s.currentStepId || '', {
            label: 'Matching experience to requirements',
            status: 'in-progress',
          });
          break;

        case 'composing':
          s.updateStep(s.currentStepId || '', {
            status: 'done',
          });
          s.addStep({ label: 'Writing your resume', status: 'in-progress' });
          break;

        case 'repair_pass': {
          const attempt = (data as { attempt?: number }).attempt;
          const score = (data as { score?: number }).score;
          s.updateStep(s.currentStepId || '', {
            label: 'Optimising for ATS',
            status: 'in-progress',
            detail: `Pass ${attempt ?? '?'} — ATS score: ${score !== undefined ? Math.round(score) : '...'}`,
          });
          break;
        }

        case 'pdf_compile': {
          s.updateStep(s.currentStepId || '', {
            status: 'done',
          });
          s.addStep({ label: 'Building your PDF', status: 'in-progress' });
          break;
        }

        case 'complete': {
          const finalScore = (data as { final_score?: number }).final_score;
          // Mark all current steps done
          const steps = s.steps;
          steps.forEach((step) => {
            if (step.status === 'in-progress') {
              s.updateStep(step.id, { status: 'done' });
            }
          });
          s.addStep({ label: 'Resume ready!', status: 'done' });

          if (finalScore !== undefined) {
            s.setFinalScore(finalScore);
          } else {
            s.setFinalScore(s.originalScore ?? 0);
          }

          // Invalidate history so the new generation appears
          queryClient.invalidateQueries({ queryKey: ['generations'] });

          // Prefetch the new generation result
          const genId = s.activeGenerationId;
          if (genId) {
            queryClient.prefetchQuery({
              queryKey: QUERY_KEYS.generation(genId),
              queryFn: () => getGenerationResult(genId),
              staleTime: Infinity,
            });
          }

          opts?.onComplete?.({
            generationId: genId || '',
            originalScore: s.originalScore ?? undefined,
            finalScore: finalScore ?? s.originalScore ?? undefined,
          });
          break;
        }

        case 'error': {
          const errData = data as { code?: string; message?: string };
          const code = errData.code || 'PIPELINE_ERROR';
          const message = errData.message || 'Generation failed';
          s.setError(message);
          opts?.onError?.(code, message);
          break;
        }
      }
    },
    [queryClient], // options via ref — stable
  );

  const handleStreamInterruption = useCallback(async (_error: Error) => {
    const genId = activeGenIdRef.current;
    if (!genId) return;

    try {
      const result = await getGenerationResult(genId);
      const status = typeof result?.status === 'string' ? result.status : undefined;
      const s = useGenerationStore.getState();

      if (status === 'completed' || result?.resume_json) {
        const finalScore = typeof result?.ats_score_json?.overall_score === 'number'
          ? result.ats_score_json.overall_score
          : s.finalScore ?? s.originalScore ?? 0;
        s.setFinalScore(finalScore);
        optionsRef.current?.onComplete?.({
          generationId: genId,
          originalScore: s.originalScore ?? undefined,
          finalScore,
        });
        return;
      }

      if (status === 'draft' || status === 'queued' || status === 'running') {
        s.setStatus(status);
        const message = STILL_RUNNING_MESSAGE;
        s.setActiveMessage(message, status);
        optionsRef.current?.onError?.('GENERATION_STILL_RUNNING', message);
        return;
      }

      if (status === 'failed' || status === 'cancelled') {
        const message = result?.message || `Generation ${status}.`;
        s.setError(message);
        optionsRef.current?.onError?.(status === 'cancelled' ? 'GENERATION_CANCELLED' : 'PIPELINE_ERROR', message);
        return;
      }
    } catch (pollError) {
      const requestId = pollError instanceof ApiError && pollError.request_id ? ` Request ID: ${pollError.request_id}` : '';
      const message = `${STILL_RUNNING_MESSAGE}${requestId}`;
      useGenerationStore.getState().setActiveMessage(message);
      optionsRef.current?.onError?.('GENERATION_STILL_RUNNING', message);
    }
  }, []);

  const generate = useCallback(
    async (params: {
      profile: MasterProfile;
      raw_jd_text: string;
      target_pages?: number;
      allow_two_pages_for_senior?: boolean;
      generate_pdf?: boolean;
      additional_alignment_text?: string;
      ats_optimization_mode?: 'realistic' | 'aggressive';
      target_ats_score?: number;
      max_repair_attempts?: number;
    }) => {
      if (startingRef.current || useGenerationStore.getState().isGenerating) {
        return cleanupSseRef.current ?? undefined;
      }
      startingRef.current = true;

      // Cancel any existing stream first
      cleanupSseRef.current?.();
      cleanupSseRef.current = null;
      activeGenIdRef.current = null;

      try {
        // Step 1: POST /pipeline/generate/start → get generation_id
        const { generation_id: generationId } = await startGeneration(params);
        activeGenIdRef.current = generationId;
        useGenerationStore.getState().startGeneration(generationId);

        // Step 2: Open SSE stream for real-time progress
        const cleanup = await connectGenerationStream(
          generationId,
          handleSSEEvent,
          () => {
            void handleStreamInterruption(new Error('Generation stream closed before a terminal event.'));
          },
          (error) => {
            void handleStreamInterruption(error);
          },
        );
        cleanupSseRef.current = cleanup;

        // Return cleanup function in case the caller wants to cancel early
        return () => {
          cleanupSseRef.current?.();
          cleanupSseRef.current = null;
          activeGenIdRef.current = null;
        };
      } catch (error) {
        const code = error && typeof error === 'object' && 'code' in error
          ? (error as { code: string }).code
          : 'PIPELINE_ERROR';
        const message = error instanceof Error ? error.message : 'Unable to start generation.';
        useGenerationStore.getState().setError(message);
        optionsRef.current?.onError?.(code, message);
        return undefined;
      } finally {
        startingRef.current = false;
      }
    },
    [handleSSEEvent, handleStreamInterruption], // options via ref - stable
  );

  const cancel = useCallback(() => {
    cleanupSseRef.current?.();
    cleanupSseRef.current = null;
    activeGenIdRef.current = null;
    startingRef.current = false;
    useGenerationStore.getState().reset();
  }, []);

  return {
    /** Start a new generation and connect to SSE stream. Returns a cleanup function. */
    generate,
    /** Cancel the active generation and reset state */
    cancel,
    /** Whether a generation is currently running */
    isGenerating: store.isGenerating,
    /** Current generation ID */
    activeGenerationId: store.activeGenerationId,
    /** Ordered step list with status */
    steps: store.steps,
    /** Currently active step ID */
    currentStepId: store.currentStepId,
    /** Original score */
    originalScore: store.originalScore,
    /** Final score */
    finalScore: store.finalScore,
    /** Error message (null if no error) */
    error: store.error,
    /** Raw SSE events for backward-compatible progress display */
    rawEvents: store.rawEvents,
  };
}
