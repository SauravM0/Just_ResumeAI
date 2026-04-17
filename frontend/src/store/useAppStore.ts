/**
 * Global application store using Zustand.
 *
 * Lightweight state for the current active pipeline session.
 * Master profile is NOT stored here — it lives in IndexedDB.
 */

import { create } from 'zustand';
import type { ParsedJD } from '../types/jd';
import type { ResumeRecommendation, ATSScore } from '../types/resume';
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
  setAtsScore: (score: ATSScore) => void;

  // LaTeX source (set after rendering)
  latexSource: string | null;
  setLatexSource: (src: string) => void;

  // Cached profile ref (loaded from IndexedDB at session start)
  activeProfile: MasterProfile | null;
  setActiveProfile: (profile: MasterProfile | null) => void;

  // Pipeline warnings
  warnings: string[];
  addWarning: (w: string) => void;
  clearWarnings: () => void;

  // Reset for new session
  resetSession: () => void;
}

export const useAppStore = create<AppState>((set) => ({
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

  latexSource: null,
  setLatexSource: (src) => set({ latexSource: src }),

  activeProfile: null,
  setActiveProfile: (profile) => set({ activeProfile: profile }),

  warnings: [],
  addWarning: (w) => set((state) => ({ warnings: [...state.warnings, w] })),
  clearWarnings: () => set({ warnings: [] }),

  resetSession: () =>
    set({
      sessionId: null,
      parsedJD: null,
      recommendation: null,
      atsScore: null,
      latexSource: null,
      warnings: [],
      currentStep: 'dashboard',
    }),
}));
