from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from vo.api import router
from vo.service.cleanup_service import CleanupService
import asyncio
import logging

logger = logging.getLogger(__name__)

# Создаем сервис очистки
cleanup_service = CleanupService(records_dir="records")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: запускается при старте приложения
    logger.info("🚀 Приложение запускается, активируем сервис очистки")
    cleanup_task = asyncio.create_task(cleanup_service.start())

    yield  # Приложение работает здесь

    # Shutdown: запускается при остановке приложения
    logger.info("👋 Приложение останавливается, останавливаем сервис очистки")
    await cleanup_service.stop()
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# Создаем приложение с lifespan
app = FastAPI(
    max_request_size=None,
    lifespan=lifespan,
    title="VO Radio Service",
    description="Сервис для радио-каналов с записью эфиров",
    version="1.0.0"
)
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)