import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Optional, Set
import asyncio
import json
import uuid
from datetime import datetime
import logging
from dataclasses import dataclass, asdict
from enum import Enum

from vo.settings import settings

# ========== КОНФИГУРАЦИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    uvicorn.run('vo.app:app',
                host=settings.server_host,
                port=settings.server_port,
                reload=True)

if __name__ == "__main__":
    main()