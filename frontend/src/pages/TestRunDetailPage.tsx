import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api, TestRun, DeviceTestRun, TestStep } from '../api';
import { socketClient } from '../socket';
import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  AlertTriangle,
  SkipForward,
  ChevronDown,
  ChevronRight,
  Brain,
  Smartphone,
  StopCircle,
  Image,
} from 'lucide-react';

const stepStatusConfig: Record<string, { icon: any; color: string; bg: string }> = {
  passed: { icon: CheckCircle2, color: 'text-green-400', bg: 'step-passed' },
  failed: { icon: XCircle, color: 'text-red-400', bg: 'step-failed' },
  running: { icon: Loader2, color: 'text-blue-400', bg: 'step-running' },
  skipped: { icon: SkipForward, color: 'text-gray-400', bg: 'step-skipped' },
  error: { icon: AlertTriangle, color: 'text-orange-400', bg: 'step-error' },
  pending: { icon: Clock, color: 'text-gray-500', bg: 'step-pending' },
};

export default function TestRunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [testRun, setTestRun] = useState<TestRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedDevice, setSelectedDevice] = useState<string | null>(null);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  const fetchTestRun = async () => {
    if (!id) return;
    try {
      const data = await api.getTestRun(parseInt(id));
      setTestRun(data);
      if (!selectedDevice && data.device_test_runs.length > 0) {
        setSelectedDevice(data.device_test_runs[0].device_serial);
      }
    } catch (err) {
      console.error('Failed to fetch test run:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTestRun();

    const unsub1 = socketClient.on('test:step_completed', fetchTestRun);
    const unsub2 = socketClient.on('test:device_completed', fetchTestRun);
    const unsub3 = socketClient.on('test:run_completed', fetchTestRun);
    const unsub4 = socketClient.on('ai:agent_thought', fetchTestRun);

    const interval = setInterval(() => {
      if (testRun?.status === 'running') fetchTestRun();
    }, 3000);

    return () => { unsub1(); unsub2(); unsub3(); unsub4(); clearInterval(interval); };
  }, [id]);

  const handleAbort = async () => {
    if (!id) return;
    try {
      await api.abortTestRun(parseInt(id));
      fetchTestRun();
    } catch (err) {
      console.error('Abort failed:', err);
    }
  };

  const toggleStep = (stepId: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-gray-500" />
      </div>
    );
  }

  if (!testRun) {
    return (
      <div className="p-6 text-center text-gray-400">Test run not found</div>
    );
  }

  const currentDTR = testRun.device_test_runs.find(
    (d) => d.device_serial === selectedDevice
  );

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white">
            {testRun.name || `Test Run #${testRun.id}`}
          </h2>
          <div className="flex items-center gap-3 mt-1">
            <span
              className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                testRun.mode === 'ai'
                  ? 'bg-purple-500/20 text-purple-400'
                  : 'bg-blue-500/20 text-blue-400'
              }`}
            >
              {testRun.mode === 'ai' ? 'AI Agent' : 'Rule-Based'}
            </span>
            <span
              className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                testRun.status === 'completed'
                  ? 'bg-green-500/20 text-green-400'
                  : testRun.status === 'failed'
                  ? 'bg-red-500/20 text-red-400'
                  : testRun.status === 'running'
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'bg-gray-500/20 text-gray-400'
              }`}
            >
              {testRun.status.toUpperCase()}
            </span>
            <span className="text-xs text-gray-500">
              {new Date(testRun.created_at).toLocaleString()}
            </span>
          </div>
        </div>
        {testRun.status === 'running' && (
          <button
            onClick={handleAbort}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium"
          >
            <StopCircle className="w-4 h-4" />
            Abort
          </button>
        )}
      </div>

      {/* Device Tabs */}
      <div className="flex gap-2 mb-4 border-b border-gray-800 pb-2 overflow-x-auto">
        {testRun.device_test_runs.map((dtr) => {
          const isSelected = dtr.device_serial === selectedDevice;
          return (
            <button
              key={dtr.device_serial}
              onClick={() => setSelectedDevice(dtr.device_serial)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm whitespace-nowrap transition-colors ${
                isSelected
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'
              }`}
            >
              <Smartphone className="w-4 h-4" />
              {dtr.device_serial}
              {dtr.summary && (
                <span className="text-xs text-gray-500">
                  ({dtr.summary.passed}/{dtr.summary.total_steps})
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Steps for selected device */}
      {currentDTR ? (
        <div className="space-y-2">
          {/* DTR Header */}
          {currentDTR.error_message && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4">
              <p className="text-sm text-red-400">{currentDTR.error_message}</p>
            </div>
          )}

          {currentDTR.summary && (
            <div className="grid grid-cols-4 gap-3 mb-4">
              {[
                { label: 'Total', value: currentDTR.summary.total_steps, color: 'text-gray-300' },
                { label: 'Passed', value: currentDTR.summary.passed, color: 'text-green-400' },
                { label: 'Failed', value: currentDTR.summary.failed, color: 'text-red-400' },
                { label: 'Skipped', value: currentDTR.summary.skipped, color: 'text-gray-400' },
              ].map((stat) => (
                <div key={stat.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3 text-center">
                  <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
                  <p className="text-xs text-gray-500 mt-1">{stat.label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Step List */}
          {currentDTR.steps.map((step) => {
            const config = stepStatusConfig[step.status] || stepStatusConfig.pending;
            const StatusIcon = config.icon;
            const expanded = expandedSteps.has(step.id);

            return (
              <div
                key={step.id}
                className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden"
              >
                <button
                  onClick={() => toggleStep(step.id)}
                  className="w-full flex items-center gap-3 p-3 text-left hover:bg-gray-800/50 transition-colors"
                >
                  <StatusIcon
                    className={`w-5 h-5 flex-shrink-0 ${config.color} ${
                      step.status === 'running' ? 'animate-spin' : ''
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">
                        Step {step.step_number}
                      </span>
                      <span className={`px-1.5 py-0.5 text-xs rounded ${config.bg}`}>
                        {step.action}
                      </span>
                      {step.ai_reasoning && (
                        <Brain className="w-3.5 h-3.5 text-purple-400" />
                      )}
                    </div>
                    {step.actual && (
                      <p className="text-xs text-gray-500 mt-0.5 truncate">
                        {step.actual}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {step.duration_ms != null && (
                      <span className="text-xs text-gray-500">
                        {step.duration_ms}ms
                      </span>
                    )}
                    {step.screenshot_path && (
                      <Image className="w-3.5 h-3.5 text-gray-500" />
                    )}
                    {expanded ? (
                      <ChevronDown className="w-4 h-4 text-gray-500" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-gray-500" />
                    )}
                  </div>
                </button>

                {/* Expanded details */}
                {expanded && (
                  <div className="border-t border-gray-800 p-4 space-y-3">
                    {step.params && Object.keys(step.params).length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-gray-400 mb-1">Parameters</p>
                        <pre className="text-xs bg-gray-800 rounded p-2 text-gray-300 overflow-x-auto">
                          {JSON.stringify(step.params, null, 2)}
                        </pre>
                      </div>
                    )}
                    {step.expected && (
                      <div>
                        <p className="text-xs font-medium text-gray-400 mb-1">Expected</p>
                        <p className="text-xs text-gray-300">{step.expected}</p>
                      </div>
                    )}
                    {step.actual && (
                      <div>
                        <p className="text-xs font-medium text-gray-400 mb-1">Actual</p>
                        <p className="text-xs text-gray-300">{step.actual}</p>
                      </div>
                    )}
                    {step.ai_reasoning && (
                      <div>
                        <p className="text-xs font-medium text-purple-400 mb-1 flex items-center gap-1">
                          <Brain className="w-3 h-3" /> AI Reasoning
                        </p>
                        <p className="text-xs text-gray-300 italic">{step.ai_reasoning}</p>
                      </div>
                    )}
                    {step.log_snippet && (
                      <div>
                        <p className="text-xs font-medium text-gray-400 mb-1">Log</p>
                        <pre className="text-xs bg-gray-800 rounded p-2 text-gray-400 overflow-x-auto max-h-40">
                          {step.log_snippet}
                        </pre>
                      </div>
                    )}
                    {step.screenshot_path && (
                      <div>
                        <p className="text-xs font-medium text-gray-400 mb-1">Screenshot</p>
                        <img
                          src={`/screenshots/${step.screenshot_path.split(/[/\\]/).pop()}`}
                          alt={`Step ${step.step_number} screenshot`}
                          className="max-w-sm rounded-lg border border-gray-700"
                          onError={(e) => (e.currentTarget.style.display = 'none')}
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {currentDTR.steps.length === 0 && currentDTR.status === 'running' && (
            <div className="text-center py-10">
              <Loader2 className="w-8 h-8 animate-spin text-blue-400 mx-auto mb-3" />
              <p className="text-sm text-gray-400">Executing test steps...</p>
            </div>
          )}
        </div>
      ) : (
        <p className="text-gray-400">Select a device to see results.</p>
      )}
    </div>
  );
}
