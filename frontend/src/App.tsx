import { Routes, Route, NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import {
  Smartphone,
  Play,
  Upload,
  Terminal,
  Settings,
  Activity,
  Bot,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { socketClient } from './socket';
import DevicesPage from './pages/DevicesPage';
import TestRunsPage from './pages/TestRunsPage';
import TestRunDetailPage from './pages/TestRunDetailPage';
import NewTestRunPage from './pages/NewTestRunPage';
import CommandConsolePage from './pages/CommandConsolePage';
import SettingsPage from './pages/SettingsPage';

function App() {
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    socketClient.connect();

    const checkConnection = setInterval(() => {
      setWsConnected(socketClient.connected);
    }, 1000);

    return () => {
      clearInterval(checkConnection);
    };
  }, []);

  const navItems = [
    { to: '/', icon: Smartphone, label: 'Devices' },
    { to: '/test-runs', icon: Play, label: 'Test Runs' },
    { to: '/new-test', icon: Bot, label: 'New Test' },
    { to: '/console', icon: Terminal, label: 'Console' },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="flex h-screen bg-gray-950">
      {/* Sidebar */}
      <aside className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
        {/* Logo */}
        <div className="p-4 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-green-600 flex items-center justify-center">
              <Activity className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">DroidCortex</h1>
              <p className="text-xs text-gray-400">Test Orchestration</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-green-600/20 text-green-400'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* WebSocket Status */}
        <div className="p-4 border-t border-gray-800">
          <div className="flex items-center gap-2 text-xs">
            {wsConnected ? (
              <>
                <Wifi className="w-3.5 h-3.5 text-green-400" />
                <span className="text-green-400">Live Connected</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3.5 h-3.5 text-red-400" />
                <span className="text-red-400">Disconnected</span>
              </>
            )}
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<DevicesPage />} />
          <Route path="/test-runs" element={<TestRunsPage />} />
          <Route path="/test-runs/:id" element={<TestRunDetailPage />} />
          <Route path="/new-test" element={<NewTestRunPage />} />
          <Route path="/console" element={<CommandConsolePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
