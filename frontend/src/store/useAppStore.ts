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
import type { ResumeRecommendation, ATSScore, PipelinePdfResult, ValidationStatus, RecruiterReview } from '../types/resume';
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
  pipelineWarnings: string[];
  setPipelineWarnings: (warnings: string[]) => void;

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

  validationStatus: ValidationStatus | null;
  setValidationStatus: (status: ValidationStatus | null) => void;

  recruiterReview: RecruiterReview | null;
  setRecruiterReview: (review: RecruiterReview | null) => void;

  scoreHistory: number[];
  setScoreHistory: (history: number[]) => void;

  strategyHistory: string[];
  setStrategyHistory: (history: string[]) => void;

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
      pipelineWarnings: [],
      setPipelineWarnings: (pipelineWarnings) => set({ pipelineWarnings }),

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

      validationStatus: null,
      setValidationStatus: (status) => set({ validationStatus: status }),

      recruiterReview: null,
      setRecruiterReview: (review) => set({ recruiterReview: review }),

      scoreHistory: [],
      setScoreHistory: (scoreHistory) => set({ scoreHistory }),

      strategyHistory: [],
      setStrategyHistory: (strategyHistory) => set({ strategyHistory }),

      activeProfile: null,
      setActiveProfile: (profile) => set({ activeProfile: profile }),

      resetGeneration: () =>
        set({
          generationId: null,
          parsedJD: null,
          pipelineWarnings: [],
          recommendation: null,
          atsScore: null,
          alignmentReport: null,
          latexSource: null,
          pipelinePdf: null,
          validationStatus: null,
          recruiterReview: null,
          scoreHistory: [],
          strategyHistory: [],
          activeProfile: null,
          currentStep: 'dashboard',
        }),
      resetJobGeneration: () =>
        set({
          generationId: null,
          parsedJD: null,
          pipelineWarnings: [],
          recommendation: null,
          atsScore: null,
          alignmentReport: null,
          latexSource: null,
          pipelinePdf: null,
          validationStatus: null,
          recruiterReview: null,
          scoreHistory: [],
          strategyHistory: [],
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
        pipelineWarnings: state.pipelineWarnings,
        recommendation: state.recommendation,
        atsScore: state.atsScore,
        alignmentReport: state.alignmentReport,
        latexSource: state.latexSource,
        pipelinePdf: state.pipelinePdf,
        recruiterReview: state.recruiterReview,
        scoreHistory: state.scoreHistory,
        strategyHistory: state.strategyHistory,
      }),
    },
  ),
);
