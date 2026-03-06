import { useEffect, useState } from 'react';
import { api, AppConfig } from '../api';
import { Settings, Save, Loader2, CheckCircle2, Eye, EyeOff } from 'lucide-react';

export default function SettingsPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showKeys, setShowKeys] = useState(false);

  // Editable fields
  const [openaiKey, setOpenaiKey] = useState('');
  const [anthropicKey, setAnthropicKey] = useState('');
  const [googleKey, setGoogleKey] = useState('');
  const [defaultProvider, setDefaultProvider] = useState('openai');
  const [defaultModel, setDefaultModel] = useState('gpt-4o');
  const [maxParallel, setMaxParallel] = useState(2);
  const [pollingInterval, setPollingInterval] = useState(5);
  const [adbPath, setAdbPath] = useState('adb');

  useEffect(() => {
    api.getConfig().then((cfg) => {
      setConfig(cfg);
      setOpenaiKey(cfg.openai_api_key || '');
      setAnthropicKey(cfg.anthropic_api_key || '');
      setGoogleKey(cfg.google_api_key || '');
      setDefaultProvider(cfg.default_ai_provider || 'openai');
      setDefaultModel(cfg.default_ai_model || 'gpt-4o');
      setMaxParallel(cfg.max_parallel_devices ?? 2);
      setPollingInterval(cfg.device_poll_interval ?? 5);
      setAdbPath(cfg.adb_path || 'adb');
      setLoading(false);
    });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const updated = await api.updateConfig({
        openai_api_key: openaiKey || undefined,
        anthropic_api_key: anthropicKey || undefined,
        google_api_key: googleKey || undefined,
        default_ai_provider: defaultProvider,
        default_ai_model: defaultModel,
        max_parallel_devices: maxParallel,
        device_poll_interval: pollingInterval,
        adb_path: adbPath,
      });
      setConfig(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      console.error('Save failed:', err);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-gray-500" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Settings className="w-6 h-6 text-cortex-400" />
        <h2 className="text-2xl font-bold text-white">Settings</h2>
      </div>

      <div className="space-y-8">
        {/* AI Provider Section */}
        <section>
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            AI Provider Configuration
          </h3>
          <div className="space-y-4 bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-gray-400">Default Provider</label>
                <select
                  value={defaultProvider}
                  onChange={(e) => setDefaultProvider(e.target.value)}
                  className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="google">Google (Gemini)</option>
                </select>
              </div>
              <div>
                <label className="text-sm text-gray-400">Default Model</label>
                <input
                  value={defaultModel}
                  onChange={(e) => setDefaultModel(e.target.value)}
                  className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                  placeholder="gpt-4o"
                />
              </div>
            </div>

            <div className="flex items-center gap-2 pt-2 border-t border-gray-800">
              <button
                onClick={() => setShowKeys(!showKeys)}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-300"
              >
                {showKeys ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                {showKeys ? 'Hide' : 'Show'} API Keys
              </button>
            </div>

            <div>
              <label className="text-sm text-gray-400">OpenAI API Key</label>
              <input
                type={showKeys ? 'text' : 'password'}
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                placeholder="sk-..."
                className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono"
              />
            </div>
            <div>
              <label className="text-sm text-gray-400">Anthropic API Key</label>
              <input
                type={showKeys ? 'text' : 'password'}
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
                placeholder="sk-ant-..."
                className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono"
              />
            </div>
            <div>
              <label className="text-sm text-gray-400">Google AI API Key</label>
              <input
                type={showKeys ? 'text' : 'password'}
                value={googleKey}
                onChange={(e) => setGoogleKey(e.target.value)}
                placeholder="AIza..."
                className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono"
              />
            </div>
          </div>
        </section>

        {/* Execution Section */}
        <section>
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            Execution Settings
          </h3>
          <div className="space-y-4 bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-gray-400">Max Parallel Devices</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={maxParallel}
                  onChange={(e) => setMaxParallel(parseInt(e.target.value) || 1)}
                  className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                />
                <p className="text-xs text-gray-600 mt-1">
                  How many devices can run tests simultaneously
                </p>
              </div>
              <div>
                <label className="text-sm text-gray-400">Device Poll Interval (sec)</label>
                <input
                  type="number"
                  min="1"
                  max="60"
                  value={pollingInterval}
                  onChange={(e) => setPollingInterval(parseInt(e.target.value) || 5)}
                  className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                />
                <p className="text-xs text-gray-600 mt-1">
                  How often to scan for connected devices
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ADB Section */}
        <section>
          <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
            ADB Configuration
          </h3>
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div>
              <label className="text-sm text-gray-400">ADB Executable Path</label>
              <input
                value={adbPath}
                onChange={(e) => setAdbPath(e.target.value)}
                placeholder="adb"
                className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono"
              />
              <p className="text-xs text-gray-600 mt-1">
                Leave as "adb" if it's in your PATH, or set the full path
              </p>
            </div>
          </div>
        </section>
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3 mt-8 pt-4 border-t border-gray-800">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-6 py-2 bg-cortex-600 hover:bg-cortex-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
        >
          {saving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          Save Settings
        </button>
        {saved && (
          <span className="flex items-center gap-1 text-sm text-green-400">
            <CheckCircle2 className="w-4 h-4" /> Saved
          </span>
        )}
        <p className="text-xs text-gray-600 ml-auto">
          Note: API key changes apply to new test runs only. Some settings require a restart.
        </p>
      </div>
    </div>
  );
}
