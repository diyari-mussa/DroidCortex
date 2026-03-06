import { useEffect, useState, useRef } from 'react';
import { api, Device } from '../api';
import { socketClient } from '../socket';
import {
  Terminal,
  Send,
  Smartphone,
  Loader2,
  Trash2,
  Camera,
  Play,
  Square,
  X,
  Power,
} from 'lucide-react';

interface LogEntry {
  id: number;
  type: 'command' | 'result' | 'error' | 'info';
  text: string;
  timestamp: Date;
}

const presetCommands = [
  { label: 'List Packages', cmd: 'pm list packages -3', icon: Terminal },
  { label: 'Screenshot', cmd: '__screenshot__', icon: Camera },
  { label: 'Get Activity', cmd: 'dumpsys activity activities | grep mResumedActivity', icon: Play },
  { label: 'Memory Info', cmd: 'dumpsys meminfo', icon: Terminal },
  { label: 'Battery', cmd: 'dumpsys battery', icon: Power },
  { label: 'Screen Size', cmd: 'wm size', icon: Smartphone },
];

export default function CommandConsolePage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [command, setCommand] = useState('');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  let nextId = useRef(1);

  useEffect(() => {
    api.getDevices().then(setDevices);
    const unsub = socketClient.on('devices:update', (data: Device[]) => setDevices(data));
    return unsub;
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const addLog = (type: LogEntry['type'], text: string) => {
    setLogs((prev) => [...prev, { id: nextId.current++, type, text, timestamp: new Date() }]);
  };

  const executeCommand = async (cmd: string) => {
    if (!selectedDevice) {
      addLog('error', 'No device selected');
      return;
    }
    if (!cmd.trim()) return;

    // Handle special commands
    if (cmd === '__screenshot__') {
      addLog('command', '> Take Screenshot');
      setRunning(true);
      try {
        const blob: Blob = await api.getScreenshot(selectedDevice);
        const url = URL.createObjectURL(blob);
        setScreenshotUrl(url);
        addLog('info', 'Screenshot captured (see preview)');
      } catch (err: any) {
        addLog('error', `Screenshot failed: ${err.message}`);
      }
      setRunning(false);
      return;
    }

    addLog('command', `> ${cmd}`);
    setRunning(true);
    try {
      const result = await api.sendCommand(selectedDevice, {
        command: 'shell',
        args: { command: cmd },
      });
      if (result.success) {
        addLog('result', result.output || '(no output)');
      } else {
        addLog('error', result.error || 'Command failed');
      }
    } catch (err: any) {
      addLog('error', `Error: ${err.message}`);
    }
    setRunning(false);
    inputRef.current?.focus();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (running) return;
    executeCommand(command);
    setCommand('');
  };

  const handleInstall = async () => {
    if (!selectedDevice) { addLog('error', 'No device selected'); return; }
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.apk';
    fileInput.onchange = async (e: any) => {
      const file = e.target.files?.[0];
      if (!file) return;
      addLog('info', `Uploading & installing ${file.name}...`);
      setRunning(true);
      try {
        const apk = await api.uploadApk(file);
        const result = await api.sendCommand(selectedDevice, {
          command: 'install',
          args: { apk_path: apk.filename },
        });
        addLog(result.success ? 'result' : 'error', result.output || result.error || '');
      } catch (err: any) {
        addLog('error', err.message);
      }
      setRunning(false);
    };
    fileInput.click();
  };

  const handleForceStop = async () => {
    if (!selectedDevice) return;
    const pkg = prompt('Enter package name:');
    if (!pkg) return;
    addLog('command', `> force-stop ${pkg}`);
    setRunning(true);
    try {
      const result = await api.sendCommand(selectedDevice, {
        command: 'force_stop',
        args: { package_name: pkg },
      });
      addLog(result.success ? 'result' : 'error', result.output || result.error || 'Done');
    } catch (err: any) {
      addLog('error', err.message);
    }
    setRunning(false);
  };

  const handleReboot = async () => {
    if (!selectedDevice) return;
    if (!confirm('Reboot device?')) return;
    addLog('command', '> Rebooting device...');
    try {
      await api.rebootDevice(selectedDevice);
      addLog('info', 'Reboot signal sent');
    } catch (err: any) {
      addLog('error', err.message);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)]">
      {/* Top bar */}
      <div className="flex items-center gap-3 p-4 border-b border-gray-800">
        <Terminal className="w-5 h-5 text-cortex-400" />
        <h2 className="text-lg font-bold text-white">Command Console</h2>

        <select
          value={selectedDevice}
          onChange={(e) => setSelectedDevice(e.target.value)}
          className="ml-4 bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white"
        >
          <option value="">Select device...</option>
          {devices.map((d) => (
            <option key={d.serial} value={d.serial}>
              {d.model || d.serial} ({d.status})
            </option>
          ))}
        </select>

        <div className="ml-auto flex gap-2">
          <button onClick={handleInstall} className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg">
            Install APK
          </button>
          <button onClick={handleForceStop} className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg flex items-center gap-1">
            <Square className="w-3 h-3" /> Force Stop
          </button>
          <button onClick={handleReboot} className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 text-orange-400 rounded-lg flex items-center gap-1">
            <Power className="w-3 h-3" /> Reboot
          </button>
        </div>
      </div>

      {/* Preset buttons */}
      <div className="flex gap-2 p-3 border-b border-gray-800 overflow-x-auto">
        {presetCommands.map((pc) => (
          <button
            key={pc.label}
            onClick={() => executeCommand(pc.cmd)}
            disabled={running || !selectedDevice}
            className="flex items-center gap-1 px-3 py-1 text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-300 rounded-lg whitespace-nowrap"
          >
            <pc.icon className="w-3 h-3" /> {pc.label}
          </button>
        ))}
      </div>

      {/* Output area */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1 custom-scrollbar">
        {logs.length === 0 && (
          <p className="text-gray-600 text-center py-10">
            Select a device and run a command to get started.
          </p>
        )}
        {logs.map((entry) => (
          <div key={entry.id} className="flex gap-2">
            <span className="text-gray-600 flex-shrink-0">
              {entry.timestamp.toLocaleTimeString()}
            </span>
            <span
              className={`whitespace-pre-wrap break-all ${
                entry.type === 'command'
                  ? 'text-cortex-400 font-bold'
                  : entry.type === 'error'
                  ? 'text-red-400'
                  : entry.type === 'info'
                  ? 'text-blue-400'
                  : 'text-gray-300'
              }`}
            >
              {entry.text}
            </span>
          </div>
        ))}
        <div ref={logEndRef} />
      </div>

      {/* Screenshot preview */}
      {screenshotUrl && (
        <div className="border-t border-gray-800 p-3">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-gray-400">Screenshot Preview</p>
            <button onClick={() => setScreenshotUrl(null)} className="text-gray-500 hover:text-white">
              <X className="w-4 h-4" />
            </button>
          </div>
          <img src={screenshotUrl} alt="Device screenshot" className="max-h-48 rounded border border-gray-700" />
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex items-center gap-2 p-3 border-t border-gray-800">
        <span className="text-cortex-400 text-sm font-mono">$</span>
        <input
          ref={inputRef}
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder={selectedDevice ? 'Enter ADB shell command...' : 'Select a device first'}
          disabled={!selectedDevice || running}
          className="flex-1 bg-transparent text-sm text-white placeholder-gray-600 focus:outline-none font-mono"
          autoFocus
        />
        <button
          type="submit"
          disabled={!selectedDevice || running || !command.trim()}
          className="p-2 text-cortex-400 hover:text-cortex-300 disabled:opacity-30"
        >
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
        </button>
        {logs.length > 0 && (
          <button
            type="button"
            onClick={() => setLogs([])}
            className="p-2 text-gray-500 hover:text-gray-300"
            title="Clear console"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </form>
    </div>
  );
}
