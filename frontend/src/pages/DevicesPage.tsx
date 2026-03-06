import { useEffect, useState } from 'react';
import { api, Device } from '../api';
import { socketClient } from '../socket';
import {
  Smartphone,
  RefreshCw,
  Cpu,
  MonitorSmartphone,
  Signal,
  SignalZero,
  Loader2,
} from 'lucide-react';

const statusConfig: Record<string, { class: string; label: string }> = {
  idle: { class: 'status-idle', label: 'Idle' },
  busy: { class: 'status-busy', label: 'Busy' },
  offline: { class: 'status-offline', label: 'Offline' },
  error: { class: 'status-error', label: 'Error' },
  online: { class: 'status-online', label: 'Online' },
};

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchDevices = async () => {
    try {
      const data = await api.getDevices();
      setDevices(data);
    } catch (err) {
      console.error('Failed to fetch devices:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDevices();

    // Listen for real-time device updates
    const unsub = socketClient.on('device:status_changed', () => {
      fetchDevices();
    });

    const interval = setInterval(fetchDevices, 10000);
    return () => {
      unsub();
      clearInterval(interval);
    };
  }, []);

  const handleRefresh = async () => {
    setLoading(true);
    try {
      await api.refreshDevices();
      await fetchDevices();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-white">Devices</h2>
          <p className="text-sm text-gray-400 mt-1">
            {devices.length} device(s) registered
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg text-sm transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Device Grid */}
      {loading && devices.length === 0 ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-gray-500" />
        </div>
      ) : devices.length === 0 ? (
        <div className="text-center py-20">
          <Smartphone className="w-16 h-16 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-400 mb-2">
            No devices found
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Connect an Android device via USB or start an emulator, then click Refresh.
          </p>
          <code className="text-xs bg-gray-800 text-green-400 px-3 py-1 rounded">
            adb devices
          </code>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {devices.map((device) => (
            <DeviceCard key={device.serial} device={device} />
          ))}
        </div>
      )}
    </div>
  );
}

function DeviceCard({ device }: { device: Device }) {
  const status = statusConfig[device.status] || statusConfig.offline;
  const isEmulator = device.device_type === 'emulator';

  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null);
  const [loadingScreenshot, setLoadingScreenshot] = useState(false);

  const handleScreenshot = async () => {
    setLoadingScreenshot(true);
    try {
      const blob = await api.getScreenshot(device.serial);
      const url = URL.createObjectURL(blob);
      setScreenshotUrl(url);
    } catch {
      setScreenshotUrl(null);
    }
    setLoadingScreenshot(false);
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gray-800 flex items-center justify-center">
            {isEmulator ? (
              <MonitorSmartphone className="w-5 h-5 text-blue-400" />
            ) : (
              <Smartphone className="w-5 h-5 text-green-400" />
            )}
          </div>
          <div>
            <p className="font-medium text-white text-sm">
              {device.model || device.serial}
            </p>
            <p className="text-xs text-gray-500">{device.serial}</p>
          </div>
        </div>
        <span
          className={`px-2 py-0.5 text-xs font-medium rounded-full border ${status.class}`}
        >
          {status.label}
        </span>
      </div>

      {/* Info */}
      <div className="space-y-2 mb-3">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Cpu className="w-3.5 h-3.5" />
          <span>API Level: {device.api_level ?? 'N/A'}</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          {device.status !== 'offline' ? (
            <Signal className="w-3.5 h-3.5 text-green-500" />
          ) : (
            <SignalZero className="w-3.5 h-3.5 text-red-500" />
          )}
          <span>{isEmulator ? 'Emulator' : 'Physical Device'}</span>
        </div>
      </div>

      {/* Screenshot Preview */}
      {screenshotUrl && (
        <div className="mb-3 rounded-lg overflow-hidden bg-black">
          <img
            src={screenshotUrl}
            alt="Device screenshot"
            className="w-full h-40 object-contain"
            onError={() => setScreenshotUrl(null)}
          />
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={handleScreenshot}
          disabled={device.status === 'offline'}
          className="flex-1 text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors disabled:opacity-40"
        >
          {loadingScreenshot ? 'Capturing...' : 'Screenshot'}
        </button>
      </div>
    </div>
  );
}
