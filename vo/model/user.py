from dataclasses import dataclass
from fastapi import WebSocket
from datetime import datetime


@dataclass
class User:
    id: str
    username: str
    websocket: WebSocket
    connected_at: datetime
    is_speaking: bool = False