"""
PCC Platform - FastAPI Backend Application

This is the main entry point for the PCC Platform API service.
It initializes the FastAPI application, sets up middleware, and includes routers.
"""
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import structlog
from fastapi import Depends, FastAPI, Request, status
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
    api_title: str = "PCC Platform API"
    api_description: str = "Backend API for Private Client Consultants Platform"
    api_version: str = "1.0.0"
    
    # Security settings
    jwt_secret: str = Field(..., env="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", env="JWT_ALGORITHM")
    jwt_expiration: int = Field(86400, env="JWT_EXPIRATION")  # 24 hours
    
    # CORS settings
    cors_origins: List[str] = Field(["*"], env="CORS_ORIGINS")
    
    # Stripe settings
    stripe_secret_key: Optional[str] = Field(None, env="STRIPE_SECRET_KEY")
    stripe_webhook_secret: Optional[str] = Field(None, env="STRIPE_WEBHOOK_SECRET")
    
    # Frontend URL for CORS and redirects
    frontend_url: str = Field("http://localhost:3000", env="FRONTEND_URL")
    
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
# Application Startup and Shutdown
# =====================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting application", environment=settings.app_env)
    
    # Connect to database
    await Database.connect()
    
    # Initialize services
    if settings.stripe_secret_key:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        logger.info("Stripe API initialized")
    
    # Yield control to FastAPI
    yield
    
    # Shutdown
    logger.info("Shutting down application")
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
    database_connected: bool
    timestamp: float


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint for monitoring and Cloud Run.
    Returns the status of the application and its dependencies.
    """
    # Check database connection
    database_connected = Database.client is not None
    
    return HealthResponse(
        status="ok",
        version=settings.api_version,
        environment=settings.app_env,
        database_connected=database_connected,
        timestamp=time.time(),
    )


# =====================================================
# Root Endpoint
# =====================================================
@app.get("/", tags=["System"])
async def root():
    """Root endpoint with basic API information."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "environment": settings.app_env,
        "docs": "/docs" if not settings.is_production else None,
    }


# =====================================================
# Include Routers
# =====================================================
# Import and include routers here
# Example:
# from app.routers import auth, users, courses, sessions
# app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
# app.include_router(users.router, prefix="/users", tags=["Users"])
# app.include_router(courses.router, prefix="/courses", tags=["Courses"])
# app.include_router(sessions.router, prefix="/sessions", tags=["Sessions"])


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
    
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="debug" if settings.debug else "info",
    )
