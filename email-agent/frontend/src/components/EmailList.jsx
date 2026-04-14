import { useState, useEffect } from 'react';
import { listEmails } from '../services/api';
import './EmailList.css';

const CATEGORY_LABELS = {
  urgent: { label: 'Urgent', icon: '🔴' },
  action_required: { label: 'Action', icon: '🟡' },
  informational: { label: 'Info', icon: '🔵' },
  spam: { label: 'Spam', icon: '⚪' },
  uncategorized: { label: 'New', icon: '⬜' },
};

function formatDate(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now - date;
  const hours = diff / (1000 * 60 * 60);
  if (hours < 1) return `${Math.round(diff / 60000)}m ago`;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  if (hours < 48) return 'Yesterday';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function SenderAvatar({ name, sender }) {
  const displayName = name || sender || '?';
  const initial = displayName.charAt(0).toUpperCase();
  // Generate consistent hue from sender string
  let hash = 0;
  for (let i = 0; i < (sender || '').length; i++) {
    hash = sender.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash % 360);
  return (
    <div
      className="sender-avatar"
      style={{ background: `linear-gradient(135deg, hsl(${hue}, 60%, 35%), hsl(${hue + 30}, 50%, 25%))` }}
    >
      {initial}
    </div>
  );
}

export default function EmailList({ category, selectedEmailId, onSelectEmail, refreshKey }) {
  const [emails, setEmails] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const pageSize = 20;

  useEffect(() => {
    setPage(0);
    loadEmails(0);
  }, [category, refreshKey]);

  async function loadEmails(offset = 0) {
    setLoading(true);
    try {
      const result = await listEmails({ category, limit: pageSize, offset });
      setEmails(result.emails);
      setTotal(result.total);
    } catch (err) {
      console.error('Failed to load emails:', err);
      setEmails([]);
    } finally {
      setLoading(false);
    }
  }

  function handleLoadMore() {
    const nextPage = page + 1;
    setPage(nextPage);
    loadEmails(nextPage * pageSize);
  }

  if (loading && emails.length === 0) {
    return (
      <div className="email-list">
        <div className="email-list-header">
          <h2>Inbox</h2>
        </div>
        <div className="email-list-body">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="email-item-skeleton">
              <div className="skeleton" style={{ width: 40, height: 40, borderRadius: '50%' }} />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div className="skeleton" style={{ width: '60%', height: 14 }} />
                <div className="skeleton" style={{ width: '90%', height: 12 }} />
                <div className="skeleton" style={{ width: '40%', height: 10 }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="email-list" id="email-list">
      <div className="email-list-header">
        <h2>
          {category ? CATEGORY_LABELS[category]?.label || category : 'All Emails'}
          <span className="total-count">{total}</span>
        </h2>
      </div>

      <div className="email-list-body">
        {emails.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📭</div>
            <div className="empty-title">No emails found</div>
            <div className="empty-subtitle">
              {category ? 'No emails in this category.' : 'Click "Process Emails" to fetch and analyze your inbox.'}
            </div>
          </div>
        ) : (
          <>
            {emails.map((email, idx) => (
              <button
                key={email.id}
                className={`email-item fade-in ${selectedEmailId === email.id ? 'selected' : ''} ${!email.is_processed ? 'unprocessed' : ''}`}
                style={{ animationDelay: `${idx * 30}ms` }}
                onClick={() => onSelectEmail(email)}
                id={`email-item-${email.id}`}
              >
                <SenderAvatar name={email.sender_name} sender={email.sender} />

                <div className="email-item-content">
                  <div className="email-item-top">
                    <span className="email-sender">{email.sender_name || email.sender}</span>
                    <span className="email-date">{formatDate(email.received_at)}</span>
                  </div>
                  <div className="email-subject">{email.subject}</div>
                  {email.summary && (
                    <div className="email-summary-preview">{email.summary}</div>
                  )}
                  {!email.summary && email.snippet && (
                    <div className="email-snippet">{email.snippet}</div>
                  )}
                </div>

                <div className="email-item-meta">
                  {email.is_processed && (
                    <span className={`badge badge-${email.category}`}>
                      {CATEGORY_LABELS[email.category]?.icon} {CATEGORY_LABELS[email.category]?.label || email.category}
                    </span>
                  )}
                  {email.draft_reply && (
                    <span className="has-draft-indicator" title="AI draft available">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                      </svg>
                    </span>
                  )}
                </div>
              </button>
            ))}

            {emails.length < total && (
              <button className="load-more-btn" onClick={handleLoadMore} id="load-more-btn">
                Load More ({total - emails.length} remaining)
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
