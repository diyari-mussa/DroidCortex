# DroidCortex

**Android APK Test Orchestration Platform** — Install, run, and test APKs across multiple Android devices with AI-driven or rule-based testing, all controlled from a real-time dashboard.

---

## Features

- **Multi-Device Testing** — Run tests across multiple physical devices and emulators simultaneously
- **Two Testing Modes**:
  - **Rule-Based** — Define step-by-step test scripts in YAML/JSON (tap, swipe, input, assertions, etc.)
  - **AI Agent** — Let an LLM autonomously explore and test your app (supports OpenAI, Anthropic, Google)
- **Real-Time Dashboard** — Monitor device status, test progress, and results via WebSocket
- **Command Console** — Execute ADB shell commands directly from the browser
- **Screenshot Capture** — Automatic screenshots at each test step for visual evidence
- **Device Pool Management** — Auto-detect devices, acquire/release for tests, track status

---

## Architecture

```
┌─────────────────────────────┐
│     React Dashboard         │
│  (Vite + TypeScript + TW)   │
└──────────┬──────────────────┘
           │ REST + Socket.IO
┌──────────▼──────────────────┐
│     FastAPI Backend         │
│  ┌────────────────────────┐ │
│  │     Orchestrator       │ │
│  │  ┌──────┐  ┌────────┐ │ │
│  │  │ Rule │  │   AI   │ │ │
│  │  │Exec. │  │ Exec.  │ │ │
│  │  └──┬───┘  └───┬────┘ │ │
│  │     └────┬─────┘      │ │
│  │          │             │ │
│  │   ┌──────▼───────┐    │ │
│  │   │  ADB Service │    │ │
│  │   └──────┬───────┘    │ │
│  └──────────┼────────────┘ │
│      Device Pool Manager   │
└──────────┬─────────────────┘
           │ ADB
    ┌──────▼──────┐
    │   Android   │
    │   Devices   │
    └─────────────┘
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and **npm**
- **Android SDK** with `adb` in PATH (or set `ADB_PATH` in `.env`)
- **Redis** (optional, for task queue — can run without it)

---

## Quick Start

### 1. Clone & Setup Environment

```bash
cd DroidCortex

# Copy environment config
cp .env.example .env
# Edit .env — set your AI API keys if using AI mode
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/macOS)
source .venv/bin/activate

# Install dependencies
pip install -e "backend/[dev]"
# Or install directly:
pip install fastapi uvicorn sqlalchemy aiosqlite python-socketio pydantic-settings \
  structlog pyyaml aiofiles python-multipart openai anthropic google-generativeai
```

### 3. Frontend Setup

```bash
cd frontend
npm install
cd ..
```

### 4. Start Redis (optional)

```bash
docker compose up -d
```

### 5. Run the Application

**Terminal 1 — Backend:**
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Usage

### Connect Devices

1. Connect Android devices via USB with **USB debugging enabled**
2. Or start Android emulator(s): `emulator -avd <name>`
3. DroidCortex auto-detects devices via `adb devices` polling
4. View connected devices on the **Devices** page

### Rule-Based Testing

1. Go to **New Test Run**
2. Upload or select an APK
3. Select target device(s)
4. Choose **Rule-Based** mode
5. Add test steps using the visual editor or paste JSON:

```json
[
  { "action": "install", "params": {}, "expected": "success" },
  { "action": "launch", "params": {}, "expected": "app_running" },
  { "action": "wait", "params": { "seconds": 3 } },
  { "action": "tap", "params": { "x": 540, "y": 960 }, "expected": "" },
  { "action": "assert_text_visible", "params": { "text": "Welcome" }, "expected": "true" },
  { "action": "screenshot", "params": {} }
]
```

6. Click **Launch Test Run**

### Available Test Actions

| Action | Params | Description |
|--------|--------|-------------|
| `install` | — | Install the APK on device |
| `launch` | — | Launch the app |
| `check_running` | — | Verify app is running |
| `tap` | `x`, `y` | Tap screen coordinates |
| `input_text` | `text` | Type text |
| `swipe` | `x1`, `y1`, `x2`, `y2`, `duration_ms` | Swipe gesture |
| `press_key` | `key` | Press keycode (e.g., KEYCODE_ENTER) |
| `press_back` | — | Press back button |
| `press_home` | — | Press home button |
| `send_broadcast` | `action`, `extras` | Send broadcast intent |
| `send_intent` | `action`, `component`, `extras` | Send explicit intent |
| `shell` | `command` | Run arbitrary shell command |
| `wait` | `seconds` | Wait N seconds |
| `screenshot` | — | Capture screenshot |
| `assert_text_visible` | `text` | Assert text visible in UI |
| `assert_activity` | `activity` | Assert current activity |
| `logcat` | `lines`, `filter` | Capture logcat |
| `force_stop` | — | Force stop the app |
| `clear_data` | — | Clear app data |
| `uninstall` | — | Uninstall the app |

### AI Agent Testing

1. Go to **New Test Run**
2. Upload or select an APK
3. Select target device(s)
4. Choose **AI Agent** mode
5. Select provider (OpenAI / Anthropic / Google)
6. Set testing goal (e.g., "Test the login flow and verify error handling")
7. Set max steps (default: 30)
8. Launch — the AI will autonomously explore and test

### Command Console

The **Console** page provides direct ADB shell access:
- Select a device from the dropdown
- Run any ADB shell command
- Use preset buttons for common tasks
- View real-time output

---

## Test Scripts

Pre-built test scripts are in `test_scripts/`:

- `smoke_test.yaml` — Basic smoke test (install, launch, verify)
- `login_test.json` — Login flow test
- `ai_exploratory.yaml` — AI agent exploration config

---

## Configuration

All settings can be configured via `.env` file or the **Settings** page in the dashboard:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/droidcortex.db` | Database connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis URL for task queue |
| `ADB_PATH` | `adb` | Path to ADB executable |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `GOOGLE_API_KEY` | — | Google AI API key |
| `DEFAULT_AI_PROVIDER` | `openai` | Default AI provider |
| `DEFAULT_AI_MODEL` | `gpt-4o` | Default AI model |
| `MAX_PARALLEL_DEVICES` | `2` | Max simultaneous device tests |
| `DEVICE_POLL_INTERVAL` | `5` | Device detection interval (sec) |

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/devices` | List all devices |
| `POST` | `/api/devices/refresh` | Force device refresh |
| `POST` | `/api/devices/{serial}/command` | Send command to device |
| `GET` | `/api/devices/{serial}/screenshot` | Get device screenshot |
| `POST` | `/api/apks/upload` | Upload APK file |
| `GET` | `/api/apks` | List uploaded APKs |
| `POST` | `/api/test-runs` | Create & start test run |
| `GET` | `/api/test-runs` | List test runs |
| `GET` | `/api/test-runs/{id}` | Get test run details |
| `POST` | `/api/test-runs/{id}/abort` | Abort running test |
| `GET` | `/api/config` | Get configuration |
| `PATCH` | `/api/config` | Update configuration |
| `GET` | `/health` | Health check |

API docs available at **http://localhost:8000/docs** (Swagger UI).

---

## Project Structure

```
DroidCortex/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entrypoint
│   ├── config.py             # Configuration (pydantic-settings)
│   ├── pyproject.toml        # Python dependencies
│   ├── models/
│   │   ├── database.py       # SQLAlchemy ORM models
│   │   └── schemas.py        # Pydantic request/response schemas
│   ├── services/
│   │   ├── adb_service.py    # ADB CLI wrapper
│   │   ├── device_manager.py # Device pool management
│   │   └── llm_service.py    # Multi-provider LLM abstraction
│   ├── engine/
│   │   ├── rule_executor.py  # Rule-based test execution
│   │   ├── ai_executor.py    # AI agent test execution
│   │   └── orchestrator.py   # Test run coordinator
│   └── api/
│       ├── devices.py        # Device endpoints
│       ├── test_runs.py      # Test run endpoints
│       ├── apks.py           # APK management endpoints
│       ├── config.py         # Config endpoints
│       └── websocket.py      # Socket.IO events
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/
│       ├── main.tsx
│       ├── App.tsx           # Layout + routing
│       ├── api.ts            # REST API client
│       ├── socket.ts         # Socket.IO client
│       └── pages/
│           ├── DevicesPage.tsx
│           ├── TestRunsPage.tsx
│           ├── TestRunDetailPage.tsx
│           ├── NewTestRunPage.tsx
│           ├── CommandConsolePage.tsx
│           └── SettingsPage.tsx
├── test_scripts/             # Sample test scripts
├── docker-compose.yml        # Redis service
├── .env.example
└── .gitignore
```

---

## License

MIT
