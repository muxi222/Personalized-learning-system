"""
RPJ Module - FastAPI Application Entry Point
历史、地理、其他模块
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .config import settings
from .api.router import api_router
from backend.core.db.session import init_db, close_db

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format=settings.LOG_FORMAT,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler
    Handles startup and shutdown events
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} on port {settings.PORT}")
    logger.info(f"Module: {settings.MODULE_NAME}, Subjects: {settings.SUBJECTS}")

    # Initialize database (共享)
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Initialize vector store (模块独立)
    try:
        from backend.core.services.vector_store_service import get_vector_store_service
        vector_store = get_vector_store_service()
        await vector_store.initialize(index_path=settings.module_vector_path)
        logger.info(f"Vector store initialized at {settings.module_vector_path}")
    except Exception as e:
        logger.warning(f"Failed to initialize vector store: {e}")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    await close_db()
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description=f"""
    ## RPJ模块 - 历史、地理、其他学科

    智能错题分析与举一反三推荐系统

    ### 支持学科:
    - 📜 历史 (History)
    - 🗺️ 地理 (Geography)
    - 📚 其他 (Other)

    ### 主要功能:
    - 📝 错题录入与管理
    - 🔍 AI智能错因分析
    - 💡 举一反三题目推荐
    - 📊 学习进度追踪

    ### API文档:
    - Swagger UI: `/docs`
    - ReDoc: `/redoc`
    """,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with better messages"""
    errors = []
    error_details = []

    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error["loc"])
        error_msg = error.get("msg", "Validation failed")
        error_type = error.get("type", "unknown")
        input_value = error.get("input", "N/A")

        errors.append(f"{field}: {error_msg}")
        error_details.append({
            "field": field,
            "message": error_msg,
            "type": error_type,
            "input": str(input_value)[:100] if input_value != "N/A" else "N/A",
        })

    logger.warning(
        f"Validation error on {request.method} {request.url.path}: "
        f"{len(error_details)} error(s) found"
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": errors,
            "error_details": error_details,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    if settings.DEBUG:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": str(exc),
                "type": type(exc).__name__,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# Include API router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """
    健康检查
    """
    return {
        "status": "healthy",
        "module": settings.MODULE_NAME,
        "subjects": settings.SUBJECTS,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "port": settings.PORT,
    }


@app.get("/", tags=["Root"])
async def root():
    """
    根路径 - 欢迎信息
    """
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "module": settings.MODULE_NAME,
        "subjects": settings.SUBJECTS,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "api": settings.API_V1_PREFIX,
    }
