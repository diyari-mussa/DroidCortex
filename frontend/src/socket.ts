/**
 * DroidCortex — Socket.IO client for real-time events.
 */

import { io, Socket } from 'socket.io-client';

class SocketClient {
  private socket: Socket | null = null;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();

  connect() {
    if (this.socket?.connected) return;

    this.socket = io(window.location.origin, {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
    });

    this.socket.on('connect', () => {
      console.log('[DroidCortex] WebSocket connected');
    });

    this.socket.on('disconnect', () => {
      console.log('[DroidCortex] WebSocket disconnected');
    });

    this.socket.on('server:hello', (data: any) => {
      console.log('[DroidCortex]', data.message);
    });

    // Forward all known events to registered listeners
    const events = [
      'device:status_changed',
      'device:list',
      'test:run_started',
      'test:run_completed',
      'test:device_started',
      'test:device_completed',
      'test:step_completed',
      'test:log_line',
      'test:screenshot',
      'ai:agent_thought',
      'command:result',
      'command:error',
    ];

    events.forEach(event => {
      this.socket!.on(event, (data: any) => {
        const handlers = this.listeners.get(event);
        if (handlers) {
          handlers.forEach(handler => handler(data));
        }
      });
    });
  }

  disconnect() {
    this.socket?.disconnect();
    this.socket = null;
  }

  on(event: string, handler: (data: any) => void): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler);

    // Return an unsubscribe function
    return () => {
      this.listeners.get(event)?.delete(handler);
    };
  }

  emit(event: string, data?: any) {
    this.socket?.emit(event, data);
  }

  requestDevices() {
    this.socket?.emit('client:request_devices');
  }

  sendCommand(serial: string, command: string) {
    this.socket?.emit('client:send_command', { serial, command });
  }

  get connected() {
    return this.socket?.connected ?? false;
  }
}

export const socketClient = new SocketClient();
