# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI 学习小书童 (AI Learning Assistant) - A personalized learning assistant for middle and high school students in China. Built with LangGraph agents for intelligent error analysis, OCR-based exam correction, and similarity-based practice recommendations.

**Tech Stack:**
- Backend: FastAPI + Python 3.11+ + LangGraph (for agent orchestration)
- Frontend: React 18 + Vite + TailwindCSS + Zustand (state management)
- Database: SQLite (aiosqlite for async)
- Vector Search: FAISS + BM25 (hybrid search)
- Task Queue: Celery + Redis
- LLM: Gemini 2.5 Flash (via unified LLM API endpoint)

## Essential Commands

### Development
```bash
# Install all dependencies (backend + frontend)
make install

# Start full development environment (ALL modules + frontend + redis)
./deploy/scripts/start.sh all

# Start individual modules (5-module architecture)
./deploy/scripts/start.sh api_rpj      # RPJ module API (port 6001: chinese, english, politics)
./deploy/scripts/start.sh agent_rpj    # RPJ module Agent Worker
./deploy/scripts/start.sh api_tony     # TONY module API (port 6005: history, geography, other)
./deploy/scripts/start.sh agent_tony   # TONY module Agent Worker

# Start all modules of one type
./deploy/scripts/start.sh api_all      # Start all 5 module APIs
./deploy/scripts/start.sh agent_all    # Start all 5 module Agent Workers

# Module management
./deploy/scripts/start.sh stop_rpj     # Stop RPJ module
./deploy/scripts/start.sh stop_all     # Stop all services
./deploy/scripts/start.sh status       # Show all module status

# Frontend only
./deploy/scripts/start.sh frontend     # Frontend only (port 8000)
```

**5-Module Architecture:**

- **rpj** (6001): 语文、英语、政治 (chinese, english, politics)
- **xmx** (6002): 经济学 (economics)
- **wzy** (6003): 数学、物理 (math, physics)
- **wzm** (6004): 化学 (chemistry)
- **tony** (6005): 历史、地理、其他 (history, geography, other)

### Testing
```bash
# Run all tests with coverage
make test

# Run specific test types
make test-unit
make test-integration
```

### Code Quality
```bash
# Lint both backend and frontend
make lint

# Format code with ruff (backend) and prettier (frontend)
make format

# Type checking (mypy)
make type-check
```

### Docker Deployment
```bash
# Standard deployment (all-in-one)
make docker-up
make docker-down

# Microservice deployment (API + Agent Worker separated, scalable)
make docker-split
make docker-split-down
```

### Database
```bash
# Initialize database
make init-db

# Run migrations (if using Alembic)
make migrate
```

## Architecture Deep Dive

### 5-Module Architecture (NEW)

The system has been refactored into **5 independent modules**, each handling specific subjects with their own ports, queues, and vector stores:

```
backend/
├── core/                          # Shared layer (all modules use)
│   ├── base_config.py            # Base configuration class
│   ├── agents/base_agent.py      # Agent base class with subject validation
│   ├── db/, services/, crud/     # Shared database, services, CRUD
│   └── schemas/                  # Shared Pydantic models
│
└── modules/                       # Module layer (independent modules)
    ├── rpj/    (6001) → chinese, english, politics
    ├── xmx/    (6002) → economics
    ├── wzy/    (6003) → math, physics
    ├── wzm/    (6004) → chemistry
    └── tony/   (6005) → history, geography, other

    Each module has:
    ├── config.py          # Module-specific config (inherits BaseAppSettings)
    ├── main.py            # Independent FastAPI app
    ├── celery_app.py      # Module-specific Celery queue
    ├── api/endpoints/     # API endpoints (shared logic + subject validation)
    └── agents/            # Agent instances (inherit BaseAgent)
```

**Module Isolation:**

- **Shared Database**: All modules use same SQLite DB, logical isolation via `subject` field
- **Independent Vector Stores**: Each module has its own FAISS/BM25 indexes in `data/faiss/{module}/`
- **Module-Specific Celery Queues**: `queue_rpj`, `queue_xmx`, `queue_wzy`, `queue_wzm`, `queue_tony`
- **Unified Authentication**: Shared `SECRET_KEY`, users can access all subjects after one login
- **Frontend Smart Routing**: Automatically routes to correct module based on subject

**Benefits:**

- Parallel development by subject teams
- Independent scaling (can run more workers for high-traffic subjects)
- File-level isolation (changes to math module don't affect chemistry)
- Clear responsibility boundaries

**Independent Module Execution:**

The startup scripts support **two execution modes**:

1. **Single Module Mode (Independent)**: Each module runs in its own process with isolated signal handling

   ```bash
   # Terminal 1
   ./deploy/scripts/start.sh api_rpj      # Starts RPJ API
   # Ctrl+C only stops RPJ API

   # Terminal 2 (while Terminal 1 still running)
   ./deploy/scripts/start.sh agent_tony   # Starts TONY Agent
   # Ctrl+C only stops TONY Agent
   ```

   - Uses `start_module.sh` internally (via `exec`)
   - Each module has its own signal handler
   - Modules can run simultaneously without interference
   - PID files: `pids/api_rpj.pid`, `pids/agent_tony.pid`, etc.

2. **Batch Mode (Unified Control)**: Multiple modules controlled together

   ```bash
   ./deploy/scripts/start.sh api_all      # Starts all 5 APIs
   # Ctrl+C stops ALL 5 APIs

   ./deploy/scripts/start.sh all          # Starts everything
   # Ctrl+C stops all services
   ```

   - Uses traditional backgrounding with shared signal handler
   - One Ctrl+C stops all related services
   - Appropriate for "start everything" scenarios

For detailed usage and troubleshooting, see [STARTUP_SCRIPT_OPTIMIZATION_REPORT.md](STARTUP_SCRIPT_OPTIMIZATION_REPORT.md)

### LangGraph Agent System

The core intelligence is built with **LangGraph** state machines. Three main agents (implemented per module):

1. **QuestionIntakeAgent** (`backend/modules/{module}/agents/question_intake_agent.py`)
   - Flow: OCR Processing → Semantic Parsing → Database Storage → Embedding Generation → Error Analysis
   - Uses structured state transitions (see `AgentState` in `backend/core/agents/state.py`)
   - Supports both text input and image OCR
   - Inherits `BaseAgent` with subject validation

2. **OCRAgent** (`backend/modules/{module}/agents/ocr_agent.py`)
   - Gemini 2.5 Flash multimodal analysis
   - Flow: Image Upload → OCR → Question Recognition → Answer Grading → Error Analysis → Save to Database
   - Generates annotated images stored in `data/uploads/{username}/corrections/{subject}/`
   - Module-specific: Only processes subjects assigned to its module

3. **SimilarQuestionAgent** (`backend/modules/{module}/agents/similar_question_agent.py`)
   - RAG-based recommendation using hybrid search
   - Flow: Original Question → FAISS Vector Search (module index) → BM25 Keyword Search → Score Fusion → Similarity Filtering → Guidance Generation
   - Uses module-specific vector store for retrieval

**Key Agent Concepts:**

- All agents extend `BaseAgent` (from `backend/core/agents/base_agent.py`) for subject validation
- State extends `AgentState` (TypedDict) for type-safe state management
- State fields use `Annotated[List, add]` for append-only operations (e.g., error accumulation)
- Agents can access `StudentProfile` for personalization (long-term memory)

### Hybrid Search Architecture

Located in `backend/app/services/hybrid_search_service.py`:

```
Query
  ├─> FAISS Vector Search (semantic similarity, weight=0.6)
  │   └─> Returns top K candidates with cosine similarity
  └─> BM25 Keyword Search (term matching, weight=0.4)
      └─> Returns top K candidates with TF-IDF scores

         ↓ Score Fusion

Weighted merge (configurable weights)
         ↓ Deduplication

Filter by threshold (default 0.55)
         ↓
Final Results
```

**Configuration** (via `.env`):
- `HYBRID_SEARCH_VECTOR_WEIGHT`: FAISS weight (default 0.6)
- `HYBRID_SEARCH_BM25_WEIGHT`: BM25 weight (default 0.4)
- `HYBRID_SEARCH_SIMILARITY_THRESHOLD`: Minimum similarity (default 0.55)
- `HYBRID_SEARCH_TOP_K`: Candidates to retrieve before filtering (default 20)

**Persistence:**
- FAISS index: `data/faiss/`
- BM25 index: `data/bm25/`
- Supports incremental updates without full rebuild

### API Structure

**Module-Based Endpoints** in `backend/modules/{module}/api/endpoints/`:

Each module exposes the same set of endpoints, but only processes its designated subjects:

- `questions.py`: CRUD for error questions (text/OCR submission) + subject validation
- `ocr.py`: Exam upload and batch OCR analysis
- `corrections.py`: Correction history with pagination and statistics
- `learning.py`: Personalized recommendations and study plans
- `guidance.py`: Learning guidance based on error patterns
- `image_files.py`: Serve uploaded images (corrections/questions)
- `users.py`: User authentication and registration (shared across modules)
- `tasks.py`: Task status monitoring
- `feedback.py`: User feedback collection

**Important Patterns:**

- All endpoints use `/api/v1` prefix (each module on its own port)
- **Subject Validation**: Each endpoint validates that the subject belongs to its module
- Async/await throughout (FastAPI + SQLAlchemy async)
- Pydantic schemas in `backend/core/schemas/` for request/response validation (shared)
- CRUD operations abstracted in `backend/core/crud/` (shared)

**Module Access:**

- RPJ module (port 6001): Only accepts chinese, english, politics
- XMX module (port 6002): Only accepts economics
- WZY module (port 6003): Only accepts math, physics
- WZM module (port 6004): Only accepts chemistry
- TONY module (port 6005): Only accepts history, geography, other

Frontend automatically routes requests to the correct module based on subject.

### Frontend Architecture

**Pages** (`frontend/src/pages/`):

- `ExamUpload.jsx`: ⭐ Core feature - upload exam images for AI grading
- `CorrectionHistory.jsx`: View all corrections with week/month/quarter/year stats
- `QuestionSubmit.jsx`: Manual error question entry (text or image)
- `QuestionList.jsx` + `QuestionDetail.jsx`: Browse and analyze errors
- `LearningAdvisor.jsx`: Personalized learning recommendations
- `Dashboard.jsx`: Overview with quick actions

**State Management:**

- Zustand stores in `frontend/src/stores/`
- React Query (@tanstack/react-query) for server state
- Toast notifications with react-hot-toast

**Smart Routing (NEW):**

- **Module Routing Config**: `frontend/src/config/moduleRouting.js`
  - Maps subjects to modules and ports
  - Example: `chinese` → `rpj` module → port 6001
- **Dynamic API Client**: `frontend/src/lib/api.js`
  - `createApiClient(subject)` creates axios instance with correct baseURL
  - All API methods accept `subject` parameter for automatic routing
  - Auth API uses any module (authentication is shared)

**Supported Subjects (10 total):**

- chinese (语文), english (英语), politics (政治) → RPJ module
- economics (经济学) → XMX module
- math (数学), physics (物理) → WZY module
- chemistry (化学) → WZM module
- history (历史), geography (地理), other (其他) → TONY module

**Important:**

- All images support click-to-fullscreen viewer
- Corrections and questions stored under `data/uploads/{username}/{corrections|questions}/{subject}/`
- Frontend automatically routes to correct backend module based on selected subject
- Last selected subject saved in localStorage for convenience

### File Upload Structure

**Data Directory Layout:**
```
data/uploads/{username_email}/
  ├─ corrections/       # AI-graded exam images (with annotations)
  │   ├─ math/
  │   ├─ english/
  │   └─ ...
  └─ questions/         # Individual error question images
      ├─ math/
      ├─ english/
      └─ ...
```

**Key Points:**
- User isolation by `username_email` directory
- Subject-based subdirectories for organization
- Image paths stored in database as relative paths
- API endpoint `/api/v1/images/{subject}/{filename}` for serving

## Configuration Management

**Base Configuration:** `backend/core/base_config.py` (Pydantic BaseSettings)

All module configs inherit from `BaseAppSettings`:

```python
class BaseAppSettings(BaseSettings):
    # Shared configuration (all modules)
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite/app.db"
    SECRET_KEY: str = "..."  # Shared for unified auth

    # Module-specific (overridden by subclasses)
    MODULE_NAME: str = "base"
    PORT: int = 6100
    SUBJECTS: List[str] = []

    # Dynamic properties for module isolation
    @property
    def module_redis_prefix(self) -> str:
        return f"learning_assistant:{self.MODULE_NAME}:"

    @property
    def module_celery_queue(self) -> str:
        return f"queue_{self.MODULE_NAME}"

    @property
    def module_vector_path(self) -> str:
        return f"./data/faiss/{self.MODULE_NAME}"
```

**Module Config Example:** `backend/modules/tony/config.py`

```python
class TONYSettings(BaseAppSettings):
    MODULE_NAME: str = "tony"
    PORT: int = 6005
    SUBJECTS: List[str] = ["history", "geography", "other"]
    LOG_FILE: str = "./logs/tony.log"
```

**LLM Setup:**

- Uses unified `LLM_API_ENDPOINT` + `LLM_API_KEY` for Gemini access
- Falls back to `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` based on `DEFAULT_LLM_PROVIDER`
- Gemini-specific: `GEMINI_MODEL` (default: gemini-2.5-flash), `GEMINI_THINKING_BUDGET`

**Embedding:**

- Default: OpenAI `text-embedding-3-small` (1536 dims)
- Alternative: Local model via `LOCAL_EMBEDDING_MODEL` (e.g., `BAAI/bge-large-zh-v1.5`)

**Database:**

- **Shared**: SQLite with async support: `sqlite+aiosqlite:///./data/sqlite/app.db`
- All modules use the same database, logical isolation via `subject` field
- SQLAlchemy models in `backend/core/db/models/`
- Session management in `backend/core/db/session.py`

**Redis:**

- Broker: `redis://localhost:6379/1` (Celery tasks)
- Backend: `redis://localhost:6379/2` (Celery results)
- Cache: `redis://localhost:6379/0` (general cache)
- Module-specific queues: `queue_rpj`, `queue_xmx`, `queue_wzy`, `queue_wzm`, `queue_tony`

**Vector Stores:**

- **Module-Specific**: Each module has independent FAISS/BM25 indexes
- Paths: `data/faiss/{module}/`, `data/bm25/{module}/`
- Prevents cross-contamination of different subject embeddings

## Development Workflow

### Adding a New Module

1. Copy existing module (e.g., TONY) as template: `cp -r backend/modules/tony backend/modules/new_module`
2. Update `backend/modules/new_module/config.py`:
   - Set `MODULE_NAME`, `PORT`, `SUBJECTS`, `LOG_FILE`
3. Update module name references in all files (use search/replace or automated script)
4. Add module to `deploy/scripts/start.sh` (MODULE_PORTS, MODULE_SUBJECTS arrays)
5. Add subject-to-module mapping in `frontend/src/config/moduleRouting.js`
6. Test: `./deploy/scripts/start.sh api_new_module` and verify health check

### Adding a New Agent (Within a Module)

1. Define state in `backend/core/agents/state.py` (extend `AgentState` if new type needed)
2. Create agent file in `backend/modules/{module}/agents/{agent_name}.py`
3. Inherit from `BaseAgent`: `super().__init__(subjects=settings.SUBJECTS)`
4. Implement LangGraph StateGraph with nodes and edges
5. Add prompts to `backend/core/agents/prompts.py` (subject-specific if needed)
6. Create Celery task in `backend/modules/{module}/agents/tasks.py`
7. Wire up API endpoint in `backend/modules/{module}/api/endpoints/`

### Adding a New Endpoint (To a Module)

1. Create schema in `backend/core/schemas/` if shared, or module-specific if unique
2. Add CRUD operations in `backend/core/crud/` (shared across modules)
3. Implement endpoint in `backend/modules/{module}/api/endpoints/{resource}.py`
4. Add subject validation: Check `subject` against `settings.SUBJECTS`
5. Register router in `backend/modules/{module}/api/router.py`
6. Update frontend API client in `frontend/src/lib/api.js` to accept `subject` parameter
7. Ensure frontend pages pass correct `subject` when calling API

### Adding a New Subject

1. Add to `SubjectEnum` in `backend/core/db/models.py`
2. Add subject-specific prompt in `backend/core/agents/prompts.py`
3. Assign subject to appropriate module in module's `config.py` SUBJECTS list
4. Update `frontend/src/config/moduleRouting.js` SUBJECT_TO_MODULE mapping
5. Update frontend pages' SUBJECTS arrays (ExamUpload.jsx, QuestionSubmit.jsx, etc.)
6. Rebuild vector indexes for the module handling this subject

### Debugging Tips

**Backend Logs:**
- Development: Logs to console + `logs/app.log`
- Celery worker logs: `celery -A backend.app.core.celery_app worker --loglevel=debug`

**Frontend:**
- Vite dev server: Hot reload on save
- React Query DevTools: Add `<ReactQueryDevtools />` to App.jsx for inspection

**Common Issues:**
- CORS errors: Check `CORS_ORIGINS` in `.env` matches frontend URL
- Redis connection: Ensure Redis is running (`redis-cli ping`)
- FAISS dimension mismatch: Clear `data/faiss/` and rebuild with correct `EMBEDDING_DIMENSION`

## Testing Practices

**Backend:**
- Framework: pytest + pytest-asyncio
- Structure: `backend/tests/unit/` and `backend/tests/integration/`
- Coverage: Target >80% for core services and agents
- Run single test: `pytest backend/tests/unit/test_file.py::test_name -v`

**Frontend:**
- (Currently minimal testing setup - ESLint only)
- Potential: Add Vitest for unit tests, Playwright for e2e

## Deployment Notes

**Docker Compose Files:**
- Standard: `docker-compose.yml` (single backend service with API + Celery)
- Split: `deploy/docker/docker-compose.split.yml` (separate API and Agent Worker containers for scaling)

**Environment Variables:**
- Copy `env.example` to `.env` and fill in API keys
- For Docker: Use service names (e.g., `redis:6379` instead of `localhost:6379`)

**Ports:**

- Frontend: 8000
- RPJ Module API: 6001
- XMX Module API: 6002
- WZY Module API: 6003
- WZM Module API: 6004
- TONY Module API: 6005
- Redis: 6379

## Subject Configuration

**10 Supported Subjects** (distributed across 5 modules):

```python
# backend/core/db/models.py - SubjectEnum
MATH = "math"           # → wzy module (6003)
PHYSICS = "physics"     # → wzy module (6003)
CHEMISTRY = "chemistry" # → wzm module (6004)
BIOLOGY = "biology"     # → (legacy, not assigned to module yet)
ENGLISH = "english"     # → rpj module (6001)
CHINESE = "chinese"     # → rpj module (6001)
POLITICS = "politics"   # → rpj module (6001)
ECONOMICS = "economics" # → xmx module (6002)
HISTORY = "history"     # → tony module (6005)
GEOGRAPHY = "geography" # → tony module (6005)
OTHER = "other"         # → tony module (6005)
```

**Module-Subject Mapping:**

```python
# frontend/src/config/moduleRouting.js
{
  rpj:  ["chinese", "english", "politics"],
  xmx:  ["economics"],
  wzy:  ["math", "physics"],
  wzm:  ["chemistry"],
  tony: ["history", "geography", "other"],
}
```

When adding new subjects:

1. Add to `SubjectEnum` in `backend/core/db/models.py`
2. Add subject-specific prompts in `backend/core/agents/prompts.py`
3. Assign to appropriate module in `backend/modules/{module}/config.py` SUBJECTS list
4. Update `SUBJECT_TO_MODULE` mapping in `frontend/src/config/moduleRouting.js`
5. Update frontend pages' SUBJECTS arrays with new subject
6. Ensure frontend UI handles new subject colors/icons (in component logic)

## Important Implementation Details

**Async Everywhere:**
- Database: Use `async with get_db()` pattern for sessions
- HTTP calls: Use `httpx.AsyncClient` (not requests)
- Agent execution: Wrap blocking LLM calls in `asyncio.to_thread()` if needed

**Celery Tasks:**
- Defined in `backend/app/agents/tasks.py`
- Use `@celery_app.task(bind=True)` for instance methods
- Long-running operations (OCR, RAG search) should be async via Celery

**Security:**
- JWT tokens for authentication (see `backend/app/api/v1/endpoints/users.py`)
- `SECRET_KEY` in `.env` must be changed for production
- File uploads validated by extension and size

**Chinese Language Support:**
- All prompts and responses in Chinese
- Use Chinese-optimized embedding models for better semantic search (e.g., `BAAI/bge-large-zh-v1.5`)
- Frontend UI labels and messages in Chinese
