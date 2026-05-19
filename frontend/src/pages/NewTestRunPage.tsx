import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, APK, Device, StepDef, CreateTestRun } from '../api';
import {
  Upload,
  Play,
  Plus,
  Trash2,
  Smartphone,
  Brain,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Loader2,
  AlertTriangle,
} from 'lucide-react';

type Mode = 'rules' | 'ai';
type WizardStep = 'apk' | 'devices' | 'mode' | 'review';

const defaultAIConfig = {
  provider: 'openai',
  model: 'gpt-4o',
  goal: 'Explore the application, test core features, and report any crashes or UI issues.',
  max_steps: 30,
  api_key: '',
};

const defaultSteps: StepDef[] = [
  { action: 'install', params: {}, expected: 'success' },
  { action: 'launch', params: {}, expected: 'app_running' },
  { action: 'check_running', params: {}, expected: 'true' },
  { action: 'wait', params: { seconds: 2 }, expected: '' },
  { action: 'screenshot', params: {}, expected: '' },
];

type ActionDoc = {
  params: Record<string, unknown>;
  expected: string;
  paramsExample: string;
  paramsHelp: string;
  expectedHelp: string;
};

const ACTION_OPTIONS = [
  'install', 'launch', 'check_running', 'wait', 'screenshot',
  'tap', 'input_text', 'swipe', 'press_key', 'press_back',
  'press_home', 'send_broadcast', 'send_intent', 'shell',
  'assert_text_visible', 'assert_activity', 'force_stop',
  'clear_data', 'logcat', 'uninstall',
];

const ACTION_DOCS: Record<string, ActionDoc> = {
  install: {
    params: {},
    expected: 'success',
    paramsExample: '{}',
    paramsHelp: 'Installs the selected APK. Optionally set apk_path to override the file path.',
    expectedHelp: 'Optional. Success is already checked automatically.',
  },
  launch: {
    params: {},
    expected: 'app_running',
    paramsExample: '{"package":"com.example.app","activity":".MainActivity"}',
    paramsHelp: 'Usually leave empty. package and activity are optional overrides.',
    expectedHelp: 'Optional. Launch already checks that the app is running.',
  },
  check_running: {
    params: {},
    expected: 'true',
    paramsExample: '{"package":"com.example.app"}',
    paramsHelp: 'Usually leave empty. package is optional if you want to check a different app.',
    expectedHelp: 'Use true, false, yes, or running.',
  },
  wait: {
    params: { seconds: 2 },
    expected: '',
    paramsExample: '{"seconds":2}',
    paramsHelp: 'Pauses the test. duration also works as an alias for seconds.',
    expectedHelp: 'Leave empty.',
  },
  screenshot: {
    params: {},
    expected: '',
    paramsExample: '{}',
    paramsHelp: 'Captures a screenshot from the current device screen.',
    expectedHelp: 'Leave empty.',
  },
  tap: {
    params: { x: 540, y: 960 },
    expected: '',
    paramsExample: '{"x":540,"y":960}',
    paramsHelp: 'Screen coordinates are required. wait_after is optional.',
    expectedHelp: 'Leave empty.',
  },
  input_text: {
    params: { text: 'hello world' },
    expected: '',
    paramsExample: '{"text":"hello world"}',
    paramsHelp: 'Types text into the focused input field.',
    expectedHelp: 'Leave empty.',
  },
  swipe: {
    params: { x1: 540, y1: 1600, x2: 540, y2: 600, duration_ms: 300 },
    expected: '',
    paramsExample: '{"x1":540,"y1":1600,"x2":540,"y2":600,"duration_ms":300}',
    paramsHelp: 'Start and end coordinates are required. duration_ms and wait_after are optional.',
    expectedHelp: 'Leave empty.',
  },
  press_key: {
    params: { keycode: 'KEYCODE_ENTER' },
    expected: '',
    paramsExample: '{"keycode":"KEYCODE_ENTER"}',
    paramsHelp: 'Use keycode or key. Android names like KEYCODE_ENTER and numeric codes both work.',
    expectedHelp: 'Leave empty.',
  },
  press_back: {
    params: {},
    expected: '',
    paramsExample: '{}',
    paramsHelp: 'Presses the Android Back button.',
    expectedHelp: 'Leave empty.',
  },
  press_home: {
    params: {},
    expected: '',
    paramsExample: '{}',
    paramsHelp: 'Presses the Android Home button.',
    expectedHelp: 'Leave empty.',
  },
  send_broadcast: {
    params: { action: 'com.example.SYNC', extras: { userId: '42' } },
    expected: '',
    paramsExample: '{"action":"com.example.SYNC","extras":{"userId":"42"}}',
    paramsHelp: 'action is the broadcast action. extras is optional. package can be used to scope the broadcast.',
    expectedHelp: 'Optional substring that must appear in the adb output.',
  },
  send_intent: {
    params: { action: 'android.intent.action.VIEW', data_uri: 'https://example.com' },
    expected: '',
    paramsExample: '{"action":"android.intent.action.VIEW","data_uri":"https://example.com"}',
    paramsHelp: 'action defaults to android.intent.action.VIEW. Use data_uri or uri, plus optional extras.',
    expectedHelp: 'Optional. Pass or fail is based on adb success.',
  },
  shell: {
    params: { command: 'pm list packages' },
    expected: '',
    paramsExample: '{"command":"pm list packages"}',
    paramsHelp: 'Runs an adb shell command on the device.',
    expectedHelp: 'Optional substring that must appear in the shell output.',
  },
  assert_text_visible: {
    params: { text: 'Welcome' },
    expected: 'Welcome',
    paramsExample: '{"text":"Welcome"}',
    paramsHelp: 'Checks the UI hierarchy for text. text can also be provided through expected.',
    expectedHelp: 'Optional fallback text to search for.',
  },
  assert_activity: {
    params: { activity: '.MainActivity' },
    expected: '.MainActivity',
    paramsExample: '{"activity":".MainActivity"}',
    paramsHelp: 'Checks the currently focused activity. activity can also be provided through expected.',
    expectedHelp: 'Optional fallback activity name to match.',
  },
  force_stop: {
    params: {},
    expected: '',
    paramsExample: '{"package":"com.example.app"}',
    paramsHelp: 'Usually leave empty. package is optional if you want to stop a different app.',
    expectedHelp: 'Leave empty.',
  },
  clear_data: {
    params: {},
    expected: '',
    paramsExample: '{"package":"com.example.app"}',
    paramsHelp: 'Usually leave empty. package is optional if you want to clear a different app.',
    expectedHelp: 'Leave empty.',
  },
  logcat: {
    params: { lines: 50, tag: 'MyApp' },
    expected: '',
    paramsExample: '{"lines":50,"tag":"MyApp"}',
    paramsHelp: 'Reads recent logcat lines. tag is optional.',
    expectedHelp: 'Optional substring that must appear in the captured logs.',
  },
  uninstall: {
    params: {},
    expected: '',
    paramsExample: '{"package":"com.example.app"}',
    paramsHelp: 'Usually leave empty. package is optional if you want to uninstall a different app.',
    expectedHelp: 'Leave empty.',
  },
};

const FALLBACK_ACTION_DOC: ActionDoc = {
  params: {},
  expected: '',
  paramsExample: '{}',
  paramsHelp: 'Enter a valid JSON object for the action parameters.',
  expectedHelp: 'Optional expected value.',
};

const getActionDoc = (action: string): ActionDoc => ACTION_DOCS[action] ?? FALLBACK_ACTION_DOC;

const cloneParams = (params: Record<string, unknown>): Record<string, unknown> =>
  JSON.parse(JSON.stringify(params));

export default function NewTestRunPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<WizardStep>('apk');
  const [apks, setApks] = useState<APK[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [selectedApk, setSelectedApk] = useState<number | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>('rules');
  const [testName, setTestName] = useState('');
  const [steps, setSteps] = useState<StepDef[]>(defaultSteps);
  const [aiConfig, setAiConfig] = useState(defaultAIConfig);
  const [scriptText, setScriptText] = useState('');
  const [useScriptEditor, setUseScriptEditor] = useState(false);

  useEffect(() => {
    Promise.all([api.getApks(), api.getDevices()])
      .then(([a, d]) => {
        setApks(a);
        setDevices(d);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleUpload = async () => {
    if (!uploadFile) return;
    setUploading(true);
    try {
      const apk = await api.uploadApk(uploadFile);
      setApks((prev) => [apk, ...prev]);
      setSelectedApk(apk.id);
      setUploadFile(null);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const toggleDevice = (serial: string) => {
    setSelectedDevices((prev) =>
      prev.includes(serial) ? prev.filter((s) => s !== serial) : [...prev, serial]
    );
  };

  const selectAllDevices = () => {
    const idle = devices.filter((d) => d.status === 'idle').map((d) => d.serial);
    setSelectedDevices(idle);
  };

  const addStep = () => {
    const actionDoc = getActionDoc('tap');
    setSteps((prev) => [
      ...prev,
      { action: 'tap', params: cloneParams(actionDoc.params), expected: actionDoc.expected },
    ]);
  };

  const removeStep = (index: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== index));
  };

  const updateStep = (index: number, field: keyof StepDef, value: any) => {
    setSteps((prev) =>
      prev.map((s, i) => (i === index ? { ...s, [field]: value } : s))
    );
  };

  const updateStepAction = (index: number, action: string) => {
    const actionDoc = getActionDoc(action);
    setSteps((prev) =>
      prev.map((s, i) => (
        i === index
          ? {
              ...s,
              action,
              params: cloneParams(actionDoc.params),
              expected: actionDoc.expected,
            }
          : s
      ))
    );
  };

  const wizardSteps: WizardStep[] = ['apk', 'devices', 'mode', 'review'];
  const currentIndex = wizardSteps.indexOf(step);

  const canNext = () => {
    switch (step) {
      case 'apk': return selectedApk !== null;
      case 'devices': return selectedDevices.length > 0;
      case 'mode': return true;
      case 'review': return true;
    }
  };

  const handleSubmit = async () => {
    if (!selectedApk) return;
    setSubmitting(true);
    setError(null);

    let finalSteps = steps;
    if (mode === 'rules' && useScriptEditor && scriptText.trim()) {
      try {
        finalSteps = JSON.parse(scriptText);
        if (!Array.isArray(finalSteps)) {
          setError('Script editor content must be a JSON array of steps.');
          setSubmitting(false);
          return;
        }
      } catch {
        try {
          // Attempt basic YAML-like parsing (simplified)
          setError('Invalid JSON in script editor. Please use valid JSON format.');
          setSubmitting(false);
          return;
        } catch { /* no-op */ }
      }
    }

    if (mode === 'rules') {
      const invalidParamsIndex = finalSteps.findIndex(
        (ruleStep) => !ruleStep.params || typeof ruleStep.params !== 'object' || Array.isArray(ruleStep.params)
      );
      if (invalidParamsIndex !== -1) {
        setError(`Step ${invalidParamsIndex + 1} params must be a valid JSON object.`);
        setSubmitting(false);
        return;
      }
    }

    const payload: CreateTestRun = {
      apk_id: selectedApk,
      mode,
      target_devices: selectedDevices,
      name: testName || undefined,
      steps: mode === 'rules' ? finalSteps : undefined,
      ai_config: mode === 'ai' ? aiConfig : undefined,
    };

    try {
      const run = await api.createTestRun(payload);
      navigate(`/test-runs/${run.id}`);
    } catch (err: any) {
      setError(err.message || 'Failed to create test run');
      setSubmitting(false);
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
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold text-white mb-6">New Test Run</h2>

      {/* Wizard Progress */}
      <div className="flex items-center gap-2 mb-8">
        {wizardSteps.map((ws, i) => (
          <div key={ws} className="flex items-center gap-2">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                i < currentIndex
                  ? 'bg-cortex-500 text-white'
                  : i === currentIndex
                  ? 'bg-cortex-500 text-white ring-2 ring-cortex-400'
                  : 'bg-gray-800 text-gray-500'
              }`}
            >
              {i + 1}
            </div>
            <span
              className={`text-sm capitalize ${
                i === currentIndex ? 'text-white font-medium' : 'text-gray-500'
              }`}
            >
              {ws}
            </span>
            {i < wizardSteps.length - 1 && (
              <div className={`w-8 h-0.5 ${i < currentIndex ? 'bg-cortex-500' : 'bg-gray-800'}`} />
            )}
          </div>
        ))}
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* Step: APK */}
      {step === 'apk' && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold text-white">Select or Upload APK</h3>

          {/* Upload */}
          <div className="border-2 border-dashed border-gray-700 rounded-lg p-6 text-center">
            <input
              type="file"
              accept=".apk"
              id="apk-upload"
              className="hidden"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
            />
            <label htmlFor="apk-upload" className="cursor-pointer">
              <Upload className="w-8 h-8 text-gray-500 mx-auto mb-2" />
              <p className="text-sm text-gray-400">
                {uploadFile ? uploadFile.name : 'Click to select an APK file'}
              </p>
            </label>
            {uploadFile && (
              <button
                onClick={handleUpload}
                disabled={uploading}
                className="mt-3 px-4 py-2 bg-cortex-600 hover:bg-cortex-700 disabled:opacity-50 text-white rounded-lg text-sm"
              >
                {uploading ? 'Uploading...' : 'Upload'}
              </button>
            )}
          </div>

          {/* Existing APKs */}
          <div className="space-y-2">
            <p className="text-sm text-gray-400">Or choose an existing APK:</p>
            {apks.length === 0 ? (
              <p className="text-sm text-gray-500">No APKs uploaded yet.</p>
            ) : (
              apks.map((apk) => (
                <button
                  key={apk.id}
                  onClick={() => setSelectedApk(apk.id)}
                  className={`w-full text-left p-3 rounded-lg border transition-colors ${
                    selectedApk === apk.id
                      ? 'border-cortex-500 bg-cortex-500/10'
                      : 'border-gray-800 bg-gray-900 hover:border-gray-700'
                  }`}
                >
                  <p className="text-sm font-medium text-white">{apk.package_name || apk.filename}</p>
                  <p className="text-xs text-gray-500">{apk.filename} &bull; v{apk.version_name || '?'}</p>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Step: Devices */}
      {step === 'devices' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-white">Select Devices</h3>
            <button onClick={selectAllDevices} className="text-xs text-cortex-400 hover:text-cortex-300">
              Select all idle
            </button>
          </div>

          {devices.length === 0 ? (
            <p className="text-sm text-gray-500">No devices detected. Connect a device or start an emulator.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {devices.map((d) => {
                const selected = selectedDevices.includes(d.serial);
                const available = d.status === 'idle';
                return (
                  <button
                    key={d.serial}
                    onClick={() => available && toggleDevice(d.serial)}
                    disabled={!available}
                    className={`text-left p-3 rounded-lg border transition-colors ${
                      selected
                        ? 'border-cortex-500 bg-cortex-500/10'
                        : available
                        ? 'border-gray-800 bg-gray-900 hover:border-gray-700'
                        : 'border-gray-800 bg-gray-900 opacity-50 cursor-not-allowed'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Smartphone className="w-4 h-4 text-gray-400" />
                      <span className="text-sm font-medium text-white">{d.model || d.serial}</span>
                      <span className={`ml-auto text-xs status-${d.status}`}>{d.status}</span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">{d.serial}</p>
                  </button>
                );
              })}
            </div>
          )}
          <p className="text-xs text-gray-500">{selectedDevices.length} device(s) selected</p>

          <div>
            <label className="text-sm text-gray-400">Test Run Name (optional)</label>
            <input
              value={testName}
              onChange={(e) => setTestName(e.target.value)}
              placeholder="e.g. Login flow v2.1"
              className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-cortex-500"
            />
          </div>
        </div>
      )}

      {/* Step: Mode */}
      {step === 'mode' && (
        <div className="space-y-6">
          <h3 className="text-lg font-semibold text-white">Testing Mode</h3>

          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => setMode('rules')}
              className={`p-4 rounded-lg border text-left transition-colors ${
                mode === 'rules'
                  ? 'border-cortex-500 bg-cortex-500/10'
                  : 'border-gray-800 bg-gray-900 hover:border-gray-700'
              }`}
            >
              <BookOpen className="w-6 h-6 text-blue-400 mb-2" />
              <p className="font-medium text-white">Rule-Based</p>
              <p className="text-xs text-gray-400 mt-1">
                Define step-by-step test commands with expected outcomes.
              </p>
            </button>
            <button
              onClick={() => setMode('ai')}
              className={`p-4 rounded-lg border text-left transition-colors ${
                mode === 'ai'
                  ? 'border-cortex-500 bg-cortex-500/10'
                  : 'border-gray-800 bg-gray-900 hover:border-gray-700'
              }`}
            >
              <Brain className="w-6 h-6 text-purple-400 mb-2" />
              <p className="font-medium text-white">AI Agent</p>
              <p className="text-xs text-gray-400 mt-1">
                Let an AI explore and test the app autonomously.
              </p>
            </button>
          </div>

          {mode === 'rules' && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <h4 className="text-sm font-medium text-gray-300">Test Steps</h4>
                <label className="flex items-center gap-1 text-xs text-gray-500">
                  <input
                    type="checkbox"
                    checked={useScriptEditor}
                    onChange={(e) => setUseScriptEditor(e.target.checked)}
                    className="rounded"
                  />
                  JSON editor
                </label>
              </div>

              {useScriptEditor ? (
                <textarea
                  value={scriptText || JSON.stringify(steps, null, 2)}
                  onChange={(e) => setScriptText(e.target.value)}
                  rows={15}
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300 font-mono focus:outline-none focus:border-cortex-500"
                  placeholder="Paste JSON array of steps..."
                />
              ) : (
                <div className="space-y-2">
                  {steps.map((s, i) => {
                    const actionDoc = getActionDoc(s.action);
                    const paramsInvalid = typeof s.params === 'string';

                    return (
                      <div key={i} className="bg-gray-900 border border-gray-800 rounded-lg p-2 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-500 w-6">{i + 1}.</span>
                          <select
                            value={s.action}
                            onChange={(e) => updateStepAction(i, e.target.value)}
                            className="bg-gray-800 text-sm text-white rounded px-2 py-1 border border-gray-700"
                          >
                            {ACTION_OPTIONS.map((a) => (
                              <option key={a} value={a}>{a}</option>
                            ))}
                          </select>
                          <input
                            value={typeof s.params === 'string' ? s.params : JSON.stringify(s.params)}
                            onChange={(e) => {
                              try { updateStep(i, 'params', JSON.parse(e.target.value)); }
                              catch { updateStep(i, 'params', e.target.value); }
                            }}
                            placeholder={actionDoc.paramsExample}
                            title={actionDoc.paramsHelp}
                            className={`flex-1 bg-gray-800 text-xs rounded px-2 py-1 border font-mono ${
                              paramsInvalid ? 'border-red-500 text-red-200' : 'border-gray-700 text-gray-300'
                            }`}
                          />
                          <input
                            value={s.expected || ''}
                            onChange={(e) => updateStep(i, 'expected', e.target.value)}
                            placeholder={actionDoc.expected || 'optional'}
                            title={actionDoc.expectedHelp}
                            className="w-28 bg-gray-800 text-xs text-gray-300 rounded px-2 py-1 border border-gray-700"
                          />
                          <button onClick={() => removeStep(i)} className="text-gray-500 hover:text-red-400">
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                        <div className="pl-8 text-[11px] leading-5 text-gray-500">
                          <span className="text-gray-400">Example:</span>{' '}
                          <span className="font-mono text-gray-300">{actionDoc.paramsExample}</span>
                          <span>{' '}· {actionDoc.paramsHelp}</span>
                          <span>{' '}· <span className="text-gray-400">Expected:</span> {actionDoc.expectedHelp}</span>
                          {paramsInvalid && (
                            <span className="text-red-400">{' '}· Invalid JSON. Use a JSON object like {actionDoc.paramsExample}</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  <button
                    onClick={addStep}
                    className="flex items-center gap-1 text-xs text-cortex-400 hover:text-cortex-300"
                  >
                    <Plus className="w-3 h-3" /> Add step
                  </button>
                </div>
              )}
            </div>
          )}

          {mode === 'ai' && (
            <div className="space-y-3">
              <div>
                <label className="text-sm text-gray-400">AI Provider</label>
                <select
                  value={aiConfig.provider}
                  onChange={(e) => setAiConfig({ ...aiConfig, provider: e.target.value })}
                  className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="google">Google (Gemini)</option>
                </select>
              </div>
              <div>
                <label className="text-sm text-gray-400">Model</label>
                <input
                  value={aiConfig.model}
                  onChange={(e) => setAiConfig({ ...aiConfig, model: e.target.value })}
                  className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400">API Key (if not set in settings)</label>
                <input
                  type="password"
                  value={aiConfig.api_key}
                  onChange={(e) => setAiConfig({ ...aiConfig, api_key: e.target.value })}
                  placeholder="sk-..."
                  className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400">Testing Goal</label>
                <textarea
                  value={aiConfig.goal}
                  onChange={(e) => setAiConfig({ ...aiConfig, goal: e.target.value })}
                  rows={3}
                  className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                />
              </div>
              <div>
                <label className="text-sm text-gray-400">Max Steps</label>
                <input
                  type="number"
                  value={aiConfig.max_steps}
                  onChange={(e) => setAiConfig({ ...aiConfig, max_steps: parseInt(e.target.value) || 30 })}
                  className="mt-1 w-28 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white"
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Step: Review */}
      {step === 'review' && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold text-white">Review & Launch</h3>
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-3">
            <div>
              <p className="text-xs text-gray-500">APK</p>
              <p className="text-sm text-white">{apks.find((a) => a.id === selectedApk)?.filename || '—'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Devices ({selectedDevices.length})</p>
              <p className="text-sm text-white">{selectedDevices.join(', ')}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Mode</p>
              <p className="text-sm text-white">{mode === 'ai' ? 'AI Agent' : 'Rule-Based'}</p>
            </div>
            {mode === 'rules' && (
              <div>
                <p className="text-xs text-gray-500">Steps</p>
                <p className="text-sm text-white">{steps.length} step(s)</p>
              </div>
            )}
            {mode === 'ai' && (
              <div>
                <p className="text-xs text-gray-500">AI Goal</p>
                <p className="text-sm text-white">{aiConfig.goal}</p>
              </div>
            )}
            {testName && (
              <div>
                <p className="text-xs text-gray-500">Name</p>
                <p className="text-sm text-white">{testName}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between mt-8 pt-4 border-t border-gray-800">
        <button
          onClick={() => setStep(wizardSteps[currentIndex - 1])}
          disabled={currentIndex === 0}
          className="flex items-center gap-1 px-4 py-2 text-sm text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="w-4 h-4" /> Back
        </button>
        {step === 'review' ? (
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex items-center gap-2 px-6 py-2 bg-cortex-600 hover:bg-cortex-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
          >
            {submitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            Launch Test Run
          </button>
        ) : (
          <button
            onClick={() => setStep(wizardSteps[currentIndex + 1])}
            disabled={!canNext()}
            className="flex items-center gap-1 px-4 py-2 bg-cortex-600 hover:bg-cortex-700 disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium"
          >
            Next <ChevronRight className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
