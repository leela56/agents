import { useEffect, useState } from 'react';
import { getEmailStats } from '../services/api';
import './Sidebar.css';

const CATEGORIES = [
  { key: null, label: 'All Emails', icon: '📬' },
  { key: 'urgent', label: 'Urgent', icon: '🔴', colorVar: '--color-urgent' },
  { key: 'action_required', label: 'Action Required', icon: '🟡', colorVar: '--color-action' },
  { key: 'informational', label: 'Informational', icon: '🔵', colorVar: '--color-info' },
  { key: 'spam', label: 'Spam', icon: '⚪', colorVar: '--color-spam' },
];

export default function Sidebar({ activeCategory, onCategoryChange, refreshKey }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadStats();
  }, [refreshKey]);

  async function loadStats() {
    try {
      const data = await getEmailStats();
      setStats(data);
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  }

  function getCount(key) {
    if (!stats) return 0;
    if (!key) return stats.total_emails;
    const map = {
      urgent: stats.urgent_count,
      action_required: stats.action_required_count,
      informational: stats.informational_count,
      spam: stats.spam_count,
    };
    return map[key] ?? 0;
  }

  return (
    <aside className="sidebar" id="sidebar">
      <div className="sidebar-section">
        <div className="sidebar-label">Categories</div>
        <nav className="sidebar-nav">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.key ?? 'all'}
              className={`sidebar-item ${activeCategory === cat.key ? 'active' : ''}`}
              onClick={() => onCategoryChange(cat.key)}
              id={`sidebar-${cat.key ?? 'all'}`}
            >
              <span className="sidebar-icon">{cat.icon}</span>
              <span className="sidebar-item-label">{cat.label}</span>
              <span className={`sidebar-count ${getCount(cat.key) > 0 ? 'has-count' : ''}`}>
                {loading ? '–' : getCount(cat.key)}
              </span>
            </button>
          ))}
        </nav>
      </div>

      {stats && (
        <div className="sidebar-section sidebar-stats">
          <div className="sidebar-label">Overview</div>
          <div className="stats-grid">
            <div className="stat-card">
              <span className="stat-value">{stats.total_emails}</span>
              <span className="stat-label">Total</span>
            </div>
            <div className="stat-card">
              <span className="stat-value">{stats.processed_emails}</span>
              <span className="stat-label">Processed</span>
            </div>
          </div>
          {stats.total_emails > 0 && (
            <div className="progress-bar-container">
              <div className="progress-label">
                <span>AI Processed</span>
                <span>{Math.round((stats.processed_emails / stats.total_emails) * 100)}%</span>
              </div>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${(stats.processed_emails / stats.total_emails) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      )}

      <div className="sidebar-footer">
        <div className="sidebar-footer-text">
          Powered by Gemini 2.0 Flash
        </div>
      </div>
    </aside>
  );
}
