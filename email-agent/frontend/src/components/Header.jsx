import { useState, useEffect } from 'react';
import { getAuthStatus, initiateLogin, revokeAuth, processEmails } from '../services/api';
import './Header.css';

export default function Header({ onProcessComplete, isProcessing, setIsProcessing }) {
  const [authStatus, setAuthStatus] = useState(null);
  const [showDropdown, setShowDropdown] = useState(false);

  useEffect(() => {
    checkAuth();
  }, []);

  async function checkAuth() {
    try {
      const status = await getAuthStatus();
      setAuthStatus(status);
    } catch {
      setAuthStatus({ is_authenticated: false });
    }
  }

  async function handleLogin() {
    try {
      const result = await initiateLogin();
      window.open(result.authorization_url, '_blank', 'width=600,height=700');
      // Poll for auth status
      const interval = setInterval(async () => {
        const status = await getAuthStatus();
        if (status.is_authenticated) {
          setAuthStatus(status);
          clearInterval(interval);
        }
      }, 2000);
      setTimeout(() => clearInterval(interval), 120000);
    } catch (err) {
      console.error('Login failed:', err);
    }
  }

  async function handleRevoke() {
    try {
      await revokeAuth();
      setAuthStatus({ is_authenticated: false });
      setShowDropdown(false);
    } catch (err) {
      console.error('Revoke failed:', err);
    }
  }

  async function handleProcess() {
    if (isProcessing) return;
    setIsProcessing(true);
    try {
      const result = await processEmails(20);
      onProcessComplete?.(result);
    } catch (err) {
      console.error('Processing failed:', err);
    } finally {
      setIsProcessing(false);
    }
  }

  const isConnected = authStatus?.is_authenticated;

  return (
    <header className="app-header">
      <div className="header-left">
        <div className="header-logo">
          <div className="logo-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <rect x="2" y="4" width="20" height="16" rx="3" stroke="url(#logoGrad)" strokeWidth="1.5"/>
              <path d="M2 7l10 6 10-6" stroke="url(#logoGrad)" strokeWidth="1.5" strokeLinecap="round"/>
              <defs>
                <linearGradient id="logoGrad" x1="2" y1="4" x2="22" y2="20">
                  <stop stopColor="#4285f4"/>
                  <stop offset="1" stopColor="#a855f7"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <span className="logo-text">AI Email Agent</span>
          <span className="logo-badge">BETA</span>
        </div>
      </div>

      <div className="header-center">
        <button
          className="btn btn-primary process-btn"
          onClick={handleProcess}
          disabled={isProcessing || !isConnected}
          id="process-emails-btn"
        >
          {isProcessing ? (
            <>
              <svg className="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 12a9 9 0 11-6.219-8.56"/>
              </svg>
              Processing…
            </>
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
              </svg>
              Process Emails
            </>
          )}
        </button>
      </div>

      <div className="header-right">
        <div className="connection-status" onClick={() => setShowDropdown(!showDropdown)}>
          <span className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`}/>
          <span className="status-text">{isConnected ? 'Connected' : 'Disconnected'}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 9l6 6 6-6"/>
          </svg>
        </div>

        {showDropdown && (
          <div className="auth-dropdown fade-in" id="auth-dropdown">
            {isConnected ? (
              <>
                <div className="dropdown-info">
                  <span className="status-dot connected"/>
                  <span>Gmail Connected</span>
                </div>
                <button className="dropdown-item danger" onClick={handleRevoke} id="revoke-btn">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18.36 6.64A9 9 0 015.64 18.36M5.64 5.64A9 9 0 0118.36 18.36"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                  Disconnect Gmail
                </button>
              </>
            ) : (
              <button className="dropdown-item" onClick={handleLogin} id="login-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
                  <polyline points="10 17 15 12 10 7"/>
                  <line x1="15" y1="12" x2="3" y2="12"/>
                </svg>
                Connect Gmail
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
