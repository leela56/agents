import { useState, useEffect } from 'react';
import { getEmail } from '../services/api';
import DraftPanel from './DraftPanel';
import './EmailDetail.css';

const CATEGORY_CONFIG = {
  urgent: { label: 'Urgent', icon: '🔴', className: 'badge-urgent' },
  action_required: { label: 'Action Required', icon: '🟡', className: 'badge-action_required' },
  informational: { label: 'Informational', icon: '🔵', className: 'badge-informational' },
  spam: { label: 'Spam', icon: '⚪', className: 'badge-spam' },
  uncategorized: { label: 'Uncategorized', icon: '⬜', className: 'badge-uncategorized' },
};

const SENTIMENT_CONFIG = {
  positive: { icon: '😊', color: 'var(--color-positive)' },
  negative: { icon: '😟', color: 'var(--color-negative)' },
  neutral: { icon: '😐', color: 'var(--color-neutral)' },
  mixed: { icon: '🤔', color: 'var(--color-mixed)' },
};

function formatFullDate(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

export default function EmailDetail({ emailId, onClose }) {
  const [email, setEmail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showBody, setShowBody] = useState(false);

  useEffect(() => {
    if (emailId) {
      loadEmail();
    }
  }, [emailId]);

  async function loadEmail() {
    setLoading(true);
    try {
      const data = await getEmail(emailId);
      setEmail(data);
    } catch (err) {
      console.error('Failed to load email:', err);
    } finally {
      setLoading(false);
    }
  }

  if (!emailId) {
    return (
      <div className="email-detail email-detail-empty" id="email-detail">
        <div className="empty-state">
          <div className="empty-icon">✉️</div>
          <div className="empty-title">Select an email</div>
          <div className="empty-subtitle">Choose an email from the list to view its AI analysis.</div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="email-detail" id="email-detail">
        <div className="detail-loading">
          <svg className="spin" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent-blue)" strokeWidth="2">
            <path d="M21 12a9 9 0 11-6.219-8.56"/>
          </svg>
          <span>Loading email…</span>
        </div>
      </div>
    );
  }

  if (!email) return null;

  const catConfig = CATEGORY_CONFIG[email.category] || CATEGORY_CONFIG.uncategorized;
  const sentimentConfig = SENTIMENT_CONFIG[email.sentiment] || SENTIMENT_CONFIG.neutral;

  return (
    <div className="email-detail" id="email-detail">
      <div className="detail-scroll">
        {/* Top bar */}
        <div className="detail-topbar">
          <button className="btn-icon" onClick={onClose} title="Back to list" id="close-detail-btn">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7"/>
            </svg>
          </button>
          <div className="detail-topbar-meta">
            {email.is_processed && (
              <span className={`badge ${catConfig.className}`}>
                {catConfig.icon} {catConfig.label}
                {email.category_confidence != null && (
                  <span className="confidence">{Math.round(email.category_confidence * 100)}%</span>
                )}
              </span>
            )}
          </div>
        </div>

        {/* Header */}
        <div className="detail-header">
          <h1 className="detail-subject">{email.subject}</h1>
          <div className="detail-sender-row">
            <div className="detail-from">
              <span className="from-label">From</span>
              <span className="from-value">
                {email.sender_name ? `${email.sender_name} <${email.sender}>` : email.sender}
              </span>
            </div>
            <span className="detail-date">{formatFullDate(email.received_at)}</span>
          </div>
        </div>

        {/* AI Analysis Section */}
        {email.is_processed && (
          <div className="ai-analysis fade-in">
            <div className="analysis-header">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-purple)" strokeWidth="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
              </svg>
              <span>AI Analysis</span>
              <span className="analysis-sentiment" style={{ color: sentimentConfig.color }}>
                {sentimentConfig.icon} {email.sentiment}
              </span>
            </div>

            {/* Summary */}
            {email.summary && (
              <div className="analysis-card">
                <div className="analysis-card-label">Summary</div>
                <p className="analysis-card-content">{email.summary}</p>
              </div>
            )}

            {/* Key Points */}
            {email.key_points?.length > 0 && (
              <div className="analysis-card">
                <div className="analysis-card-label">Key Points</div>
                <ul className="analysis-list">
                  {email.key_points.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Action Items */}
            {email.action_items?.length > 0 && (
              <div className="analysis-card action-items">
                <div className="analysis-card-label">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--color-action)" strokeWidth="2">
                    <path d="M9 11l3 3L22 4"/>
                    <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
                  </svg>
                  Action Items
                </div>
                <ul className="analysis-list action-list">
                  {email.action_items.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Draft Reply */}
        <DraftPanel email={email} onDraftUpdate={updated => setEmail(updated)} />

        {/* Original Email Body (collapsible) */}
        <div className="original-email">
          <button
            className="original-toggle"
            onClick={() => setShowBody(!showBody)}
            id="toggle-body-btn"
          >
            <svg
              width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              style={{ transform: showBody ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s' }}
            >
              <path d="M9 18l6-6-6-6"/>
            </svg>
            Original Email
          </button>
          {showBody && (
            <div className="original-body fade-in">
              {email.body_text || email.snippet || '(no content)'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
