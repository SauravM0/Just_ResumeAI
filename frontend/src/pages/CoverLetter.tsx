import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getMyProfile } from '../lib/profileApi';
import { generateCoverLetter, getCoverLetter, updateCoverLetter } from '../lib/api';
import { useAppStore } from '../store/useAppStore';
import PageHeader from '../components/ui/PageHeader';
import AppCard from '../components/ui/AppCard';
import PrimaryActionBar from '../components/ui/PrimaryActionBar';
import LoadingState from '../components/ui/LoadingState';
import EmptyState from '../components/ui/EmptyState';

export default function CoverLetterPage() {
  const { generationId } = useParams<{ generationId: string }>();
  const navigate = useNavigate();
  const { activeProfile, setActiveProfile, setGenerationId } = useAppStore();

  const [coverLetter, setCoverLetter] = useState<string | null>(null);
  const [editedText, setEditedText] = useState('');
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!generationId) return;
    setGenerationId(generationId);
    setLoading(true);
    getCoverLetter(generationId)
      .then((data) => {
        if (data.cover_letter_text) {
          setCoverLetter(data.cover_letter_text);
          setEditedText(data.cover_letter_text);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [generationId, setGenerationId]);

  const handleGenerate = async () => {
    if (!generationId) return;
    if (coverLetter && !window.confirm('Regenerate cover letter? Any unsaved edits will be lost.')) return;
    setGenerating(true);
    setError(null);
    try {
      let profile = activeProfile;
      if (!profile) {
        const response = await getMyProfile();
        profile = response.profile_json;
        if (!profile) {
          throw new Error('No profile found. Please save your profile first.');
        }
        setActiveProfile(profile);
      }
      const data = await generateCoverLetter(generationId, { profile });
      setCoverLetter(data.cover_letter_text);
      setEditedText(data.cover_letter_text);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate cover letter');
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    if (!generationId) return;
    setSaving(true);
    try {
      await updateCoverLetter(generationId, editedText);
      setCoverLetter(editedText);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <LoadingState text="Loading cover letter..." />;
  }

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Cover Letter"
        subtitle="Generate and edit a tailored cover letter."
      />

      {error && (
        <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-md)' }}>
          <span>{error}</span>
        </div>
      )}

      {!coverLetter && !generating && (
        <EmptyState
          icon="✉"
          title="No cover letter yet"
          description="Generate a tailored cover letter from your profile and job description."
          action={
            <button className="btn btn-primary" onClick={handleGenerate}>
              Generate Cover Letter
            </button>
          }
        />
      )}

      {generating && (
        <LoadingState text="Generating your cover letter..." />
      )}

      {coverLetter && (
        <AppCard>
          <textarea
            className="form-textarea cover-letter-content"
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            style={{ minHeight: '350px', fontFamily: 'var(--font-sans)' }}
          />
          <PrimaryActionBar>
            <button className="btn btn-ghost" onClick={() => navigate(`/review/${generationId}`)}>
              ← Back to Resume
            </button>
            <button className="btn btn-ghost" onClick={() => navigate(`/history/${generationId}`)}>
              View Generation
            </button>
            <button className="btn btn-secondary" onClick={handleGenerate} disabled={generating} style={{ marginLeft: 'auto' }}>
              {generating ? <span className="spinner" /> : 'Regenerate'}
            </button>
            <button className="btn btn-primary" onClick={handleSave} disabled={saving || generating}>
              {saving ? <span className="spinner" /> : saved ? '✓ Saved' : 'Save Edits'}
            </button>
          </PrimaryActionBar>
        </AppCard>
      )}
    </div>
  );
}
