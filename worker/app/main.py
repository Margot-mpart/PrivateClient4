"""
PCC Platform - Worker Service

This is the main entry point for the PCC Platform Worker service.
It handles background tasks, AI processing, and scheduled jobs.
"""
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import structlog
from celery import Celery
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import AnyUrl, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Configure structured logging
logger = structlog.get_logger()

# =====================================================
# Settings Configuration
# =====================================================
class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Core settings
    app_env: str = Field("production", env="APP_ENV")
    debug: bool = Field(False, env="DEBUG")
    
    # MongoDB settings
    mongodb_uri: AnyUrl = Field(..., env="MONGODB_URI")
    mongodb_db_name: str = Field("pcc", env="MONGODB_DB_NAME")
    mongodb_max_pool_size: int = Field(10, env="MONGODB_MAX_POOL_SIZE")
    
    # API settings
    api_title: str = "PCC Platform Worker"
    api_description: str = "Worker service for PCC Platform - handles background tasks and AI processing"
    api_version: str = "1.0.0"
    
    # Security settings
    jwt_secret: str = Field(..., env="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", env="JWT_ALGORITHM")
    
    # CORS settings
    cors_origins: List[str] = Field(["*"], env="CORS_ORIGINS")
    
    # Celery settings
    celery_broker_url: str = Field("memory://", env="CELERY_BROKER_URL")
    celery_result_backend: str = Field("memory://", env="CELERY_RESULT_BACKEND")
    celery_task_serializer: str = Field("json", env="CELERY_TASK_SERIALIZER")
    celery_result_serializer: str = Field("json", env="CELERY_RESULT_SERIALIZER")
    celery_accept_content: List[str] = Field(["json"], env="CELERY_ACCEPT_CONTENT")
    celery_task_acks_late: bool = Field(True, env="CELERY_TASK_ACKS_LATE")
    celery_worker_prefetch_multiplier: int = Field(1, env="CELERY_WORKER_PREFETCH_MULTIPLIER")
    celery_worker_concurrency: int = Field(2, env="CONCURRENCY")
    celery_worker_max_tasks_per_child: int = Field(100, env="MAX_TASKS_PER_CHILD")
    
    # OpenAI settings
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4", env="OPENAI_MODEL")
    
    # Worker mode
    worker_mode: str = Field("api", env="WORKER_MODE")  # "api" or "worker"
    
    # Model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    @property
    def is_development(self) -> bool:
        """Check if the application is running in development mode."""
        return self.app_env.lower() == "development"
    
    @property
    def is_production(self) -> bool:
        """Check if the application is running in production mode."""
        return self.app_env.lower() == "production"
    
    def get_cors_origins(self) -> List[str]:
        """Get the CORS origins as a list."""
        if isinstance(self.cors_origins, str):
            return [origin.strip() for origin in self.cors_origins.split(",")]
        return self.cors_origins


# Create global settings instance
settings = Settings()

# =====================================================
# Database Connection
# =====================================================
class Database:
    """Database connection manager."""
    
    client: Optional[AsyncIOMotorClient] = None
    db = None
    
    @classmethod
    async def connect(cls):
        """Connect to MongoDB."""
        logger.info("Connecting to MongoDB", uri=settings.mongodb_uri)
        cls.client = AsyncIOMotorClient(
            str(settings.mongodb_uri),
            maxPoolSize=settings.mongodb_max_pool_size,
        )
        cls.db = cls.client[settings.mongodb_db_name]
        logger.info("Connected to MongoDB", database=settings.mongodb_db_name)
    
    @classmethod
    async def disconnect(cls):
        """Disconnect from MongoDB."""
        if cls.client:
            logger.info("Disconnecting from MongoDB")
            cls.client.close()
            cls.client = None
            cls.db = None


# =====================================================
# Celery Configuration
# =====================================================
celery_app = Celery(
    "pcc_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    accept_content=settings.celery_accept_content,
    task_acks_late=settings.celery_task_acks_late,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
)

# =====================================================
# Application Startup and Shutdown
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting worker application", 
                environment=settings.app_env,
                mode=settings.worker_mode)
    
    # Connect to database
    await Database.connect()
    
    # Initialize OpenAI if API key is provided
    if settings.openai_api_key:
        import openai
        openai.api_key = settings.openai_api_key
        logger.info("OpenAI API initialized", model=settings.openai_model)
    
    # Yield control to FastAPI
    yield
    
    # Shutdown
    logger.info("Shutting down worker application")
    await Database.disconnect()


# =====================================================
# Application Instance
# =====================================================
app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    debug=settings.debug,
    lifespan=lifespan,
)

# =====================================================
# Middleware Configuration
# =====================================================
# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID middleware
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    """Add request ID to each request for tracing."""
    request_id = request.headers.get("X-Request-ID", f"req-{time.time()}")
    request.state.request_id = request_id
    
    # Add request ID to structlog context
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

# Logging middleware
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Log request and response information."""
    start_time = time.time()
    
    # Extract client info
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "unknown")
    
    # Log request
    logger.info(
        "Request started",
        method=request.method,
        url=str(request.url),
        client_host=client_host,
        user_agent=user_agent,
    )
    
    # Process request
    try:
        response = await call_next(request)
        
        # Calculate processing time
        process_time = time.time() - start_time
        
        # Log response
        logger.info(
            "Request completed",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            process_time_ms=round(process_time * 1000, 2),
        )
        
        # Add processing time header
        response.headers["X-Process-Time"] = str(process_time)
        return response
    except Exception as e:
        # Log exception
        logger.exception(
            "Request failed",
            method=request.method,
            url=str(request.url),
            error=str(e),
            error_type=type(e).__name__,
        )
        raise

# =====================================================
# Health Check Endpoint
# =====================================================
class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    version: str
    environment: str
    mode: str
    database_connected: bool
    celery_ready: bool
    ai_enabled: bool
    timestamp: float
    system_stats: Dict[str, Any]


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint for monitoring and Cloud Run.
    Returns the status of the worker service and its dependencies.
    """
    # Check database connection
    database_connected = Database.client is not None
    
    # Check if OpenAI is configured
    ai_enabled = settings.openai_api_key is not None
    
    # Check Celery connection
    celery_ready = True
    try:
        # Simple ping to check if broker is reachable
        if settings.celery_broker_url != "memory://":
            celery_app.control.ping()
    except Exception:
        celery_ready = False
    
    # Get system stats
    try:
        import psutil
        system_stats = {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        }
    except ImportError:
        system_stats = {"status": "psutil not available"}
    
    return HealthResponse(
        status="ok",
        version=settings.api_version,
        environment=settings.app_env,
        mode=settings.worker_mode,
        database_connected=database_connected,
        celery_ready=celery_ready,
        ai_enabled=ai_enabled,
        timestamp=time.time(),
        system_stats=system_stats,
    )


# =====================================================
# Root Endpoint
# =====================================================
@app.get("/", tags=["System"])
async def root():
    """Root endpoint with basic worker information."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "environment": settings.app_env,
        "mode": settings.worker_mode,
        "docs": "/docs" if not settings.is_production else None,
    }


# =====================================================
# Task Status Endpoints
# =====================================================
@app.get("/tasks/{task_id}", tags=["Tasks"])
async def get_task_status(task_id: str):
    """Get the status of a background task."""
    task = celery_app.AsyncResult(task_id)
    
    response = {
        "task_id": task_id,
        "status": task.status,
        "result": task.result if task.status == "SUCCESS" else None,
        "error": str(task.result) if task.status == "FAILURE" else None,
    }
    
    return response


# =====================================================
# AI Processing Endpoints
# =====================================================
class TranscriptionRequest(BaseModel):
    """Request model for transcription."""
    session_id: str
    audio_url: str
    language: str = "en"


@app.post("/ai/transcribe", tags=["AI Processing"])
async def transcribe_audio(request: TranscriptionRequest):
    """
    Queue a session for audio transcription.
    This endpoint creates a background task for processing.
    """
    if not settings.openai_api_key:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "AI services are not configured"},
        )
    
    # Queue transcription task
    task = celery_app.send_task(
        "app.tasks.transcribe_audio",
        args=[request.session_id, request.audio_url, request.language],
    )
    
    return {
        "task_id": task.id,
        "status": "queued",
        "session_id": request.session_id,
    }


class AnalysisRequest(BaseModel):
    """Request model for session analysis."""
    session_id: str
    transcript_id: str


@app.post("/ai/analyze", tags=["AI Processing"])
async def analyze_session(request: AnalysisRequest):
    """
    Queue a session transcript for AI analysis.
    This endpoint creates a background task for processing.
    """
    if not settings.openai_api_key:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "AI services are not configured"},
        )
    
    # Queue analysis task
    task = celery_app.send_task(
        "app.tasks.analyze_transcript",
        args=[request.session_id, request.transcript_id],
    )
    
    return {
        "task_id": task.id,
        "status": "queued",
        "session_id": request.session_id,
    }


# =====================================================
# Exception Handlers
# =====================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled exceptions."""
    logger.exception(
        "Unhandled exception",
        url=str(request.url),
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "type": "server_error",
        },
    )


# =====================================================
# Main Entry Point
# =====================================================
if __name__ == "__main__":
    """
    Development entry point.
    Use `uvicorn app.main:app --reload` for development.
    """
    import uvicorn
    
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "127.0.0.1")
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="debug" if settings.debug else "info",
    )
