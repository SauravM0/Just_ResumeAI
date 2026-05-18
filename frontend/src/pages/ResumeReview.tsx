import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import ATSCompactScoreCard from '../components/ATSCompactScoreCard';
import ResumeVisualEditor from '../components/resume-editor/ResumeVisualEditor';
import { validateResume, getGeneration, exportPdf, exportDocx } from '../lib/api';

import { getMyProfile } from '../lib/profileApi';
import { sanitizeProfile } from '../lib/profile';
import {
  recommendationToPlainText,
} from '../lib/resumeText';
import { useAppStore } from '../store/useAppStore';
import type {
  ExportFileResponse,
} from '../types/resume';
import type { MasterProfile } from '../types/profile';

const logger = console;

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

function downloadExport(file: ExportFileResponse) {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function ResumeReview() {
   const navigate = useNavigate();
   const { generationId } = useParams<{ generationId: string }>();
   const {
    generationId: activeGenerationId,
    parsedJD,
    recommendation,
    setRecommendation,
    atsScore,
    setAtsScore,
    alignmentReport,
    setPipelinePdf,
    setStep,
    activeProfile,
    setActiveProfile,
    setAlignmentReport,
    resetJobGeneration,
    setGenerationId,
    setParsedJD,
  } = useAppStore();

  const [, setResolvedProfile] = useState<MasterProfile | null>(activeProfile);
  const [isCheckingProfile, setIsCheckingProfile] = useState(false);
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [exportedPdf, setExportedPdf] = useState<ExportFileResponse | null>(null);
  const [exportedDocx, setExportedDocx] = useState<ExportFileResponse | null>(null);

  const currentGenerationId = generationId || activeGenerationId;

  useEffect(() => {
    let cancelled = false;

    async function loadGeneration(): Promise<boolean> {
      if (generationId) {
        try {
          const genData = await getGeneration(generationId);
          if (cancelled) return false;
          if (genData.parsed_jd_json) setParsedJD(genData.parsed_jd_json as any);
          if (genData.resume_json) setRecommendation(genData.resume_json as any);
          if (genData.ats_score_json) setAtsScore(genData.ats_score_json as any);
          if (genData.alignment_report_json) setAlignmentReport(genData.alignment_report_json as any);
          setGenerationId(generationId);
          return Boolean(genData.parsed_jd_json);
        } catch (e) {
          if (!cancelled) {
            logger.error("Failed to load generation:", e);
            setBlockingError('Generation not found or unavailable. Please open it from history again.');
          }
        }
      }
      return false;
    }

    async function resolveProfile() {
      const loadedParsedJD = generationId ? await loadGeneration() : false;

      if (!currentGenerationId) {
        setResolvedProfile(null);
        setBlockingError('Missing generation. Please generate a resume again.');
        return;
      }

      if (!parsedJD && !loadedParsedJD) {
        setResolvedProfile(null);
        setBlockingError('Missing parsed JD. Please analyze the JD again.');
        return;
      }

      if (activeProfile) {
        setResolvedProfile(activeProfile);
        return;
      }

      setIsCheckingProfile(true);
      setBlockingError(null);

      try {
        const savedProfile = (await getMyProfile()).profile_json;
        if (cancelled) return;

        if (!hasSavedProfile(savedProfile)) {
          setResolvedProfile(null);
          setActiveProfile(null);
          setBlockingError('No saved master profile found. Please save your profile before analyzing a job description.');
          return;
        }

        const normalizedProfile = sanitizeProfile(savedProfile);
        setResolvedProfile(normalizedProfile);
        setActiveProfile(normalizedProfile);
      } finally {
        if (!cancelled) setIsCheckingProfile(false);
      }
    }

    void resolveProfile();

    return () => {
      cancelled = true;
    };
  }, [generationId, activeGenerationId, activeProfile, parsedJD, setActiveProfile, setParsedJD, setRecommendation, setAtsScore, setAlignmentReport, setGenerationId]);

  const validateMutation = useMutation({
    mutationFn: validateResume,
    onSuccess: (data) => setAtsScore(data.ats_score),
  });

  const pdfExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportPdf,
    onSuccess: (data) => {
      setExportedPdf(data);
      downloadExport(data);
      setCopyStatus('PDF ready');
      window.setTimeout(() => setCopyStatus(null), 2000);
    },
    onError: (error) => {
      setRenderError(error instanceof Error ? error.message : 'PDF export failed.');
    },
  });

  const docxExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportDocx,
    onSuccess: (data) => {
      setExportedDocx(data);
      downloadExport(data);
      setCopyStatus('DOCX ready');
      window.setTimeout(() => setCopyStatus(null), 2000);
    },
    onError: (error) => {
      setRenderError(error instanceof Error ? error.message : 'DOCX export failed.');
    },
  });

  const handleCopyResume = () => {
    if (!recommendation) return;
    navigator.clipboard.writeText(recommendationToPlainText(recommendation));
    setCopyStatus('Copied!');
    window.setTimeout(() => setCopyStatus(null), 2000);
  };

  const handleStorageExportPdf = () => {
    if (!currentGenerationId) return;
    setRenderError(null);
    pdfExportMutation.mutate(currentGenerationId);
  };

  const handleStorageExportDocx = () => {
    if (!currentGenerationId) return;
    setRenderError(null);
    docxExportMutation.mutate(currentGenerationId);
  };

  const handleVisualEditorSave = (updatedRecommendation: typeof recommendation) => {
    if (!updatedRecommendation || !currentGenerationId) return;
    setRecommendation(updatedRecommendation);
    setAtsScore(null);
    setPipelinePdf(null);
    setRenderError(null);
  };

  const handleNextJD = () => {
    resetJobGeneration();
    setStep('jd-input');
    navigate('/jd');
  };

  if (blockingError) {
    return (
      <div className="empty-state">
        <div className="empty-icon">!</div>
        <div className="empty-title">Cannot open resume</div>
        <div className="empty-description">{blockingError}</div>
        <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-md)' }}>
          <button className="btn btn-secondary" onClick={() => navigate('/profile')}>Go to Profile</button>
          <button className="btn btn-primary" onClick={handleNextJD}>Go to JD Input</button>
        </div>
      </div>
    );
  }

  if (isCheckingProfile) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
        <div className="loading-text">Loading your saved master profile...</div>
      </div>
    );
  }

  if (!recommendation) {
    return (
      <div className="empty-state">
        <div className="empty-icon">Resume</div>
        <div className="empty-title">No resume available</div>
        <div className="empty-description">
          Paste a job description to generate a fast ATS resume output.
        </div>
        <button className="btn btn-primary" onClick={handleNextJD}>Go to JD Input</button>
      </div>
    );
  }

  return (
    <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <h1 className="page-title">Resume Editor</h1>
        <p className="page-subtitle">Edit your resume visually, then export as PDF or DOCX.</p>
      </div>

      <div
        className="action-bar"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-md)',
          flexWrap: 'wrap',
          padding: 'var(--space-md)',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <ATSCompactScoreCard
          atsScore={atsScore}
          alignmentReport={alignmentReport}
          compact
        />

        <div className="action-bar-actions">
          {copyStatus && <span style={{ color: 'var(--status-success)', fontSize: '0.85rem' }}>{copyStatus}</span>}
          <button className="btn btn-ghost btn-sm" onClick={handleCopyResume}>Copy Text</button>

          {exportedDocx ? (
            <button className="btn btn-primary btn-sm" onClick={() => downloadExport(exportedDocx)}>
              Download DOCX
            </button>
          ) : (
            <button className="btn btn-secondary btn-sm" onClick={handleStorageExportDocx} disabled={docxExportMutation.isPending}>
              {docxExportMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
              {docxExportMutation.isPending ? 'Exporting...' : 'Export DOCX'}
            </button>
          )}

          {exportedPdf ? (
            <button className="btn btn-primary btn-sm" onClick={() => downloadExport(exportedPdf)}>
              Download PDF
            </button>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={handleStorageExportPdf} disabled={pdfExportMutation.isPending}>
              {pdfExportMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
              {pdfExportMutation.isPending ? 'Exporting...' : 'Export PDF'}
            </button>
          )}

          <button className="btn btn-ghost btn-sm" onClick={() => currentGenerationId && navigate(`/cover-letter/${currentGenerationId}`)}>
            Cover Letter
          </button>

          <button className="btn btn-ghost btn-sm" onClick={handleNextJD}>
            New JD
          </button>

          {recommendation && currentGenerationId && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => validateMutation.mutate({ generation_id: currentGenerationId, recommendation })}
              disabled={validateMutation.isPending}
            >
              {validateMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
              Refresh ATS
            </button>
          )}
        </div>
      </div>

      {renderError && (
        <div className="warning-banner warning-error">
          <span>{renderError}</span>
        </div>
      )}

      {recommendation && currentGenerationId && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <ResumeVisualEditor
            recommendation={recommendation}
            generationId={currentGenerationId}
            onSave={handleVisualEditorSave}
          />
        </div>
      )}
    </div>
  );
}
