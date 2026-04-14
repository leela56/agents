/**
 * Backend API client for the AI Email Agent.
 *
 * All calls go to the FastAPI backend at localhost:8000.
 */

const API_BASE = 'http://localhost:8000';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const config = {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: response.statusText }));
    throw new Error(error.message || `API Error: ${response.status}`);
  }

  return response.json();
}

// ---- Auth ----
export async function getAuthStatus() {
  return request('/auth/status');
}

export async function initiateLogin() {
  return request('/auth/login');
}

export async function revokeAuth() {
  return request('/auth/revoke', { method: 'POST' });
}

// ---- Emails ----
export async function listEmails({ category, isProcessed, limit = 20, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (isProcessed !== undefined) params.set('is_processed', isProcessed);
  params.set('limit', limit);
  params.set('offset', offset);
  return request(`/emails?${params}`);
}

export async function getEmail(emailId) {
  return request(`/emails/${emailId}`);
}

export async function processEmails(maxEmails = 20, forceReprocess = false) {
  return request('/emails/process', {
    method: 'POST',
    body: JSON.stringify({ max_emails: maxEmails, force_reprocess: forceReprocess }),
  });
}

export async function redraftEmail(emailId, tone = 'professional', additionalInstructions = null) {
  return request(`/emails/${emailId}/redraft`, {
    method: 'POST',
    body: JSON.stringify({ tone, additional_instructions: additionalInstructions }),
  });
}

export async function getEmailStats() {
  return request('/emails/stats');
}

// ---- Health ----
export async function getHealth() {
  return request('/health');
}

export async function getReadiness() {
  return request('/health/ready');
}
