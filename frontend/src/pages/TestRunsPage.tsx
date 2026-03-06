import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, TestRunSummary } from '../api';
import { socketClient } from '../socket';
import {
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  AlertTriangle,
  Bot,
  FileCode,
  ChevronRight,
} from 'lucide-react';

const statusIcons: Record<string, any> = {
  pending: Clock,
  running: Loader2,
  completed: CheckCircle2,
  failed: XCircle,
  aborted: AlertTriangle,
};

const statusColors: Record<string, string> = {
  pending: 'text-gray-400',
  running: 'text-blue-400',
  completed: 'text-green-400',
  failed: 'text-red-400',
  aborted: 'text-yellow-400',
};

export default function TestRunsPage() {
  const [runs, setRuns] = useState<TestRunSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchRuns = async () => {
    try {
      const data = await api.getTestRuns();
      setRuns(data);
    } catch (err) {
      console.error('Failed to fetch test runs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();

    const unsub1 = socketClient.on('test:run_started', fetchRuns);
    const unsub2 = socketClient.on('test:run_completed', fetchRuns);
    const unsub3 = socketClient.on('test:device_completed', fetchRuns);

    return () => { unsub1(); unsub2(); unsub3(); };
  }, []);

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white">Test Runs</h2>
          <p className="text-sm text-gray-400 mt-1">{runs.length} test run(s)</p>
        </div>
        <Link
          to="/new-test"
          className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          <Play className="w-4 h-4" />
          New Test Run
        </Link>
      </div>

      {/* List */}
      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-gray-500" />
        </div>
      ) : runs.length === 0 ? (
        <div className="text-center py-20">
          <Play className="w-16 h-16 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-400 mb-2">
            No test runs yet
          </h3>
          <p className="text-sm text-gray-500">
            Start a new test to see results here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map((run) => {
            const StatusIcon = statusIcons[run.status] || Clock;
            const statusColor = statusColors[run.status] || 'text-gray-400';
            return (
              <Link
                key={run.id}
                to={`/test-runs/${run.id}`}
                className="block bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <StatusIcon
                      className={`w-5 h-5 ${statusColor} ${
                        run.status === 'running' ? 'animate-spin' : ''
                      }`}
                    />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-white">
                          {run.name || `Test Run #${run.id}`}
                        </span>
                        <span
                          className={`px-2 py-0.5 text-xs rounded-full ${
                            run.mode === 'ai'
                              ? 'bg-purple-500/20 text-purple-400'
                              : 'bg-blue-500/20 text-blue-400'
                          }`}
                        >
                          {run.mode === 'ai' ? (
                            <span className="flex items-center gap-1">
                              <Bot className="w-3 h-3" /> AI
                            </span>
                          ) : (
                            <span className="flex items-center gap-1">
                              <FileCode className="w-3 h-3" /> Rules
                            </span>
                          )}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {new Date(run.created_at).toLocaleString()} ·{' '}
                        {run.completed_devices}/{run.total_devices} devices
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {/* Progress bar */}
                    {run.total_devices > 0 && (
                      <div className="w-24 h-2 bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${
                            run.status === 'completed'
                              ? 'bg-green-500'
                              : run.status === 'failed'
                              ? 'bg-red-500'
                              : 'bg-blue-500'
                          }`}
                          style={{
                            width: `${(run.completed_devices / run.total_devices) * 100}%`,
                          }}
                        />
                      </div>
                    )}
                    <ChevronRight className="w-4 h-4 text-gray-600" />
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
