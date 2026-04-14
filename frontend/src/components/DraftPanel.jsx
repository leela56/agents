import { useState } from 'react';
import { redraftEmail } from '../services/api';
import './DraftPanel.css';

const TONES = [
  { key: 'professional', label: 'Professional', icon: '💼' },
  { key: 'friendly', label: 'Friendly', icon: '😊' },
  { key: 'brief', label: 'Brief', icon: '⚡' },
];

export default function DraftPanel({ email, onDraftUpdate }) {
  const [activeTone, setActiveTone] = useState(email?.draft_tone || 'professional');
  const [isRedrafting, setIsRedrafting] = useState(false);
  const [instructions, setInstructions] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [editedDraft, setEditedDraft] = useState(email?.draft_reply || '');

  if (!email?.draft_reply) return null;

  async function handleRedraft(tone) {
    setActiveTone(tone);
    setIsRedrafting(true);
    try {
      const result = await redraftEmail(
        email.id,
        tone,
        instructions || null
      );
      onDraftUpdate?.(result);
      setEditedDraft(result.draft_reply || '');
      setIsEditing(false);
    } catch (err) {
      console.error('Redraft failed:', err);
    } finally {
      setIsRedrafting(false);
    }
  }

  return (
    <div className="draft-panel glass-card fade-in" id="draft-panel">
      <div className="draft-header">
        <div className="draft-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z"/>
            <path d="M20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
          </svg>
          <span>AI Draft Reply</span>
        </div>
        <div className="tone-selector">
          {TONES.map(tone => (
            <button
              key={tone.key}
              className={`tone-btn ${activeTone === tone.key ? 'active' : ''}`}
              onClick={() => handleRedraft(tone.key)}
              disabled={isRedrafting}
              title={tone.label}
              id={`tone-${tone.key}`}
            >
              <span className="tone-icon">{tone.icon}</span>
              <span className="tone-label">{tone.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="draft-body">
        {isRedrafting ? (
          <div className="draft-loading">
            <svg className="spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" strokeWidth="2">
              <path d="M21 12a9 9 0 11-6.219-8.56"/>
            </svg>
            <span>Regenerating draft…</span>
          </div>
        ) : isEditing ? (
          <textarea
            className="draft-editor"
            value={editedDraft}
            onChange={e => setEditedDraft(e.target.value)}
            id="draft-editor"
          />
        ) : (
          <div className="draft-text">{editedDraft || email.draft_reply}</div>
        )}
      </div>

      <div className="draft-footer">
        <div className="draft-instructions">
          <input
            type="text"
            className="instructions-input"
            placeholder="Additional instructions for redraft…"
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleRedraft(activeTone)}
            id="draft-instructions"
          />
        </div>
        <div className="draft-actions">
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setIsEditing(!isEditing);
              if (!isEditing) setEditedDraft(email.draft_reply);
            }}
            id="edit-draft-btn"
          >
            {isEditing ? 'Cancel' : 'Edit'}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => navigator.clipboard.writeText(editedDraft || email.draft_reply)}
            id="copy-draft-btn"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2"/>
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
            </svg>
            Copy
          </button>
        </div>
      </div>
    </div>
  );
}
