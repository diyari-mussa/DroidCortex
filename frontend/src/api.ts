/**
 * DroidCortex — API client for backend communication.
 */

const BASE_URL = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API Error ${res.status}: ${err}`);
  }
  return res.json();
}

// ── Types ────────────────────────────────────────────────────

export interface Device {
  serial: string;
  name?: string;
  model?: string;
  api_level?: number;
  device_type: string;
  status: 'online' | 'idle' | 'busy' | 'offline' | 'error';
  last_seen?: string;
}

export interface APK {
  id: number;
  filename: string;
  package_name?: string;
  main_activity?: string;
  version_name?: string;
  version_code?: number;
  min_sdk?: number;
  target_sdk?: number;
  file_size?: number;
  uploaded_at: string;
}

export interface TestStep {
  id: number;
  step_number: number;
  action: string;
  params?: Record<string, any>;
  expected?: string;
  actual?: string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'error';
  screenshot_path?: string;
  log_snippet?: string;
  duration_ms?: number;
  ai_reasoning?: string;
  started_at?: string;
  completed_at?: string;
}

export interface DeviceTestRun {
  id: number;
  device_serial: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  summary?: {
    total_steps: number;
    passed: number;
    failed: number;
    skipped: number;
    errors: number;
  };
  steps: TestStep[];
}

export interface TestRun {
  id: number;
  name?: string;
  apk_id: number;
  mode: 'rules' | 'ai';
  status: string;
  config?: Record<string, any>;
  target_devices?: string[];
  created_at: string;
  completed_at?: string;
  device_test_runs: DeviceTestRun[];
}

export interface TestRunSummary {
  id: number;
  name?: string;
  mode: 'rules' | 'ai';
  status: string;
  total_devices: number;
  completed_devices: number;
  created_at: string;
  completed_at?: string;
}

export interface StepDef {
  action: string;
  params: Record<string, any>;
  expected?: string;
  timeout?: number;
}

export interface CreateTestRun {
  name?: string;
  apk_id: number;
  mode: 'rules' | 'ai';
  target_devices: string[];
  steps?: StepDef[];
  ai_config?: {
    provider?: string;
    model?: string;
    goal: string;
    max_steps: number;
    api_key?: string;
  };
}

export interface AppConfig {
  max_parallel_devices: number;
  default_ai_provider: string;
  default_ai_model: string;
  device_poll_interval: number;
  test_step_timeout: number;
  ai_max_steps: number;
  openai_api_key?: string;
  anthropic_api_key?: string;
  google_api_key?: string;
  adb_path?: string;
}

// ── API Functions ────────────────────────────────────────────

export const api = {
  // Devices
  getDevices: () => request<Device[]>('/devices'),
  getDevice: (serial: string) => request<Device>(`/devices/${serial}`),
  refreshDevices: () => request<any>('/devices/refresh', { method: 'POST' }),
  sendCommand: (serial: string, body: { command: string; args?: Record<string, any> }) =>
    request<{ success: boolean; output: string; error?: string }>(
      `/devices/${serial}/command`,
      { method: 'POST', body: JSON.stringify(body) }
    ),
  getScreenshot: async (serial: string): Promise<Blob> => {
    const res = await fetch(`${BASE_URL}/devices/${serial}/screenshot?t=${Date.now()}`);
    if (!res.ok) throw new Error(`Screenshot failed: ${res.status}`);
    return res.blob();
  },
  rebootDevice: (serial: string) =>
    request<any>(`/devices/${serial}/reboot`, { method: 'POST' }),

  // APKs
  getApks: () => request<APK[]>('/apks'),
  getApk: (id: number) => request<APK>(`/apks/${id}`),
  uploadApk: async (file: File): Promise<APK> => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${BASE_URL}/apks/upload`, { method: 'POST', body: form });
    if (!res.ok) throw new Error(`Upload failed: ${await res.text()}`);
    return res.json();
  },
  deleteApk: (id: number) => request<any>(`/apks/${id}`, { method: 'DELETE' }),

  // Test Runs
  getTestRuns: (limit = 50, offset = 0) =>
    request<TestRunSummary[]>(`/test-runs?limit=${limit}&offset=${offset}`),
  getTestRun: (id: number) => request<TestRun>(`/test-runs/${id}`),
  getTestRunSteps: (id: number, serial?: string) =>
    request<TestStep[]>(`/test-runs/${id}/steps${serial ? `?device_serial=${serial}` : ''}`),
  createTestRun: (body: CreateTestRun) =>
    request<{ id: number; status: string }>('/test-runs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  abortTestRun: (id: number) =>
    request<any>(`/test-runs/${id}/abort`, { method: 'POST' }),

  // Config
  getConfig: () => request<AppConfig>('/config'),
  updateConfig: (config: Partial<AppConfig>) =>
    request<AppConfig>('/config', {
      method: 'PATCH',
      body: JSON.stringify(config),
    }),

  // Health
  health: () => request<any>('/health'),
};
