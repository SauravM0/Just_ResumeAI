/**
 * Global application store using Zustand.
 *
 * Lightweight state for the current active pipeline generation.
 * Master profile data is fetched from the backend profile API and cached only for the active run.
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
  | 'cover-letter';

interface AppState {
  currentStep: AppStep;
  setStep: (step: AppStep) => void;

  generationId: string | null;
  setGenerationId: (id: string) => void;

  parsedJD: ParsedJD | null;
  setParsedJD: (jd: ParsedJD) => void;

  recommendation: ResumeRecommendation | null;
  setRecommendation: (rec: ResumeRecommendation) => void;

  atsScore: ATSScore | null;
  setAtsScore: (score: ATSScore | null) => void;

  alignmentReport: ATSAlignmentReport | null;
  setAlignmentReport: (report: ATSAlignmentReport | null) => void;

  latexSource: string | null;
  setLatexSource: (src: string) => void;

  pipelinePdf: PipelinePdfResult | null;
  setPipelinePdf: (pdf: PipelinePdfResult | null) => void;

  activeProfile: MasterProfile | null;
  setActiveProfile: (profile: MasterProfile | null) => void;

  resetGeneration: () => void;
  resetJobGeneration: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentStep: 'dashboard',
      setStep: (step) => set({ currentStep: step }),

      generationId: null,
      setGenerationId: (id) => set({ generationId: id }),

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

      resetGeneration: () =>
        set({
          generationId: null,
          parsedJD: null,
          recommendation: null,
          atsScore: null,
          alignmentReport: null,
          latexSource: null,
          pipelinePdf: null,
          activeProfile: null,
          currentStep: 'dashboard',
        }),
      resetJobGeneration: () =>
        set({
          generationId: null,
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
      name: 'just-resume-generation',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        currentStep: state.currentStep,
        generationId: state.generationId,
        parsedJD: state.parsedJD,
        recommendation: state.recommendation,
        atsScore: state.atsScore,
        alignmentReport: state.alignmentReport,
        latexSource: state.latexSource,
        pipelinePdf: state.pipelinePdf,
      }),
    },
  ),
);
