/**
 * Global application store using Zustand.
 *
 * Lightweight state for the current active pipeline session.
 * Master profile is NOT stored here — it lives in IndexedDB.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ParsedJD } from '../types/jd';
import type { ATSAlignmentReport } from '../types/alignment';
import type { ResumeRecommendation, ATSScore, PipelinePdfResult } from '../types/resume';
import type { MasterProfile } from '../types/profile';

export type AppStep =
  | 'dashboard'
  | 'profile'
  | 'jd-input'
  | 'jd-analysis'
  | 'resume-review'
  | 'latex-editor'
  | 'cover-letter';

interface AppState {
  // Current step in the pipeline
  currentStep: AppStep;
  setStep: (step: AppStep) => void;

  // Active session
  sessionId: string | null;
  setSessionId: (id: string) => void;

  // Parsed JD (set after analysis)
  parsedJD: ParsedJD | null;
  setParsedJD: (jd: ParsedJD) => void;

  // Resume recommendation (set after AI pipeline)
  recommendation: ResumeRecommendation | null;
  setRecommendation: (rec: ResumeRecommendation) => void;

  // ATS score (set after validation)
  atsScore: ATSScore | null;
  setAtsScore: (score: ATSScore | null) => void;

  alignmentReport: ATSAlignmentReport | null;
  setAlignmentReport: (report: ATSAlignmentReport | null) => void;

  // LaTeX source (set after rendering)
  latexSource: string | null;
  setLatexSource: (src: string) => void;

  // PDF pipeline metadata
  pipelinePdf: PipelinePdfResult | null;
  setPipelinePdf: (pdf: PipelinePdfResult | null) => void;

  // Cached profile ref (loaded from IndexedDB at session start)
  activeProfile: MasterProfile | null;
  setActiveProfile: (profile: MasterProfile | null) => void;

  // Reset for new session
  resetSession: () => void;
  resetJobSession: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentStep: 'dashboard',
      setStep: (step) => set({ currentStep: step }),

      sessionId: null,
      setSessionId: (id) => set({ sessionId: id }),

      parsedJD: null,
      setParsedJD: (jd) => set({ parsedJD: jd }),

      recommendation: null,
      setRecommendation: (rec) => set({ recommendation: rec }),

      atsScore: null,
      setAtsScore: (score) => set({ atsScore: score }),

      alignmentReport: null,
      setAlignmentReport: (report) => set({ alignmentReport: report }),

      latexSource: null,
      setLatexSource: (src) => set({ latexSource: src }),

      pipelinePdf: null,
      setPipelinePdf: (pdf) => set({ pipelinePdf: pdf }),

      activeProfile: null,
      setActiveProfile: (profile) => set({ activeProfile: profile }),

      resetSession: () =>
        set({
          sessionId: null,
          parsedJD: null,
          recommendation: null,
          atsScore: null,
          alignmentReport: null,
          latexSource: null,
          pipelinePdf: null,
          activeProfile: null,
          currentStep: 'dashboard',
        }),
      resetJobSession: () =>
        set({
          sessionId: null,
          parsedJD: null,
          recommendation: null,
          atsScore: null,
          alignmentReport: null,
          latexSource: null,
          pipelinePdf: null,
          currentStep: 'jd-input',
        }),
    }),
    {
      name: 'just-resume-session',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        currentStep: state.currentStep,
        sessionId: state.sessionId,
        parsedJD: state.parsedJD,
        recommendation: state.recommendation,
        atsScore: state.atsScore,
        alignmentReport: state.alignmentReport,
        latexSource: state.latexSource,
        pipelinePdf: state.pipelinePdf,
      }),
    }
  )
);
