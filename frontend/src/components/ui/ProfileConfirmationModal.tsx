import { useEffect, useMemo, useState } from 'react';
import type { ExtractionConfidenceField, ExtractionConfidenceReport, MasterProfile } from '../../types/profile';

interface Props {
  isOpen: boolean;
  confidenceReport?: ExtractionConfidenceReport | null;
  profile: MasterProfile;
  onConfirm: (correctedProfile: MasterProfile) => void;
  onSkip: () => void;
}

type EditableField = ExtractionConfidenceField & {
  normalizedPath: Array<string | number>;
};

export default function ProfileConfirmationModal({
  isOpen,
  confidenceReport,
  profile,
  onConfirm,
  onSkip,
}: Props) {
  const fields = useMemo<EditableField[]>(
    () => (confidenceReport?.fields || [])
      .filter((field) => field.needs_confirmation || field.confidence < 0.7)
      .map((field) => ({ ...field, normalizedPath: parseFieldPath(field.field_path) })),
    [confidenceReport],
  );
  const hasLowConfidenceFields = fields.length > 0;
  const [draft, setDraft] = useState<MasterProfile>(profile);

  useEffect(() => {
    if (isOpen) setDraft(profile);
  }, [isOpen, profile]);

  if (!isOpen) return null;

  const updateField = (field: EditableField, value: string) => {
    setDraft((current) => setByPath(current, field.normalizedPath, value));
  };

  return (
    <div className="profile-confirmation-backdrop" role="presentation">
      <section
        className="profile-confirmation-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-confirmation-title"
      >
        <header className="profile-confirmation-header">
          <div>
            <h2 id="profile-confirmation-title">Review extracted information</h2>
            <p>We detected some fields that may need your attention.</p>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onSkip} aria-label="Close review">
            x
          </button>
        </header>

        <div className="profile-confirmation-body">
          {!hasLowConfidenceFields ? (
            <div className="profile-confirmation-empty">
              <div className="profile-confirmation-empty-icon" aria-hidden="true">✓</div>
              <h3>Everything looks good!</h3>
              <p>No low-confidence fields were detected in this upload.</p>
            </div>
          ) : (
            fields.map((field) => {
              const value = getByPath(draft, field.normalizedPath);
              return (
                <article className="profile-confirmation-field" key={field.field_path}>
                  <div className="profile-confirmation-field-head">
                    <label className="form-label" htmlFor={`confirm-${field.field_path}`}>
                      {field.label || field.field_path}
                    </label>
                    <span className="badge badge-warning" title={field.reason || 'Low extraction confidence'}>
                      Please verify
                    </span>
                  </div>
                  <input
                    id={`confirm-${field.field_path}`}
                    className="form-input"
                    value={stringifyValue(value ?? field.value)}
                    onChange={(event) => updateField(field, event.target.value)}
                  />
                  <p className="profile-confirmation-reason">
                    {field.reason || `Confidence ${Math.round(field.confidence * 100)}%. Please confirm this value.`}
                  </p>
                </article>
              );
            })
          )}
        </div>

        <footer className="profile-confirmation-footer">
          {hasLowConfidenceFields && (
            <button className="btn btn-ghost btn-sm" onClick={onSkip}>Skip verification</button>
          )}
          <button className="btn btn-primary" onClick={() => onConfirm(draft)}>
            {hasLowConfidenceFields ? 'Confirm & Continue' : 'Looks good'}
          </button>
        </footer>
      </section>
    </div>
  );
}

function parseFieldPath(path: string): Array<string | number> {
  return path
    .replace(/\[(\d+)\]/g, '.$1')
    .split('.')
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part))
    .filter((part) => part !== '');
}

function getByPath(source: unknown, path: Array<string | number>): unknown {
  return path.reduce<unknown>((current, segment) => {
    if (current == null) return undefined;
    return (current as Record<string | number, unknown>)[segment];
  }, source);
}

function setByPath<T>(source: T, path: Array<string | number>, value: string): T {
  if (path.length === 0) return source;
  const clone = structuredClone(source);
  let cursor: Record<string | number, unknown> = clone as Record<string | number, unknown>;
  path.slice(0, -1).forEach((segment) => {
    const next = cursor[segment];
    if (next == null || typeof next !== 'object') {
      cursor[segment] = typeof segment === 'number' ? [] : {};
    }
    cursor = cursor[segment] as Record<string | number, unknown>;
  });
  cursor[path[path.length - 1]] = value;
  return clone;
}

function stringifyValue(value: unknown): string {
  if (value == null) return '';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}
