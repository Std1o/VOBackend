from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


@dataclass
class RadioStatus:
    channel_id: Optional[int]
    current_speaker: Optional[str]
    current_speaker_name: Optional[str]
    waiting_queue: List[str]
    waiting_names: List[str]
    connected_users: List[str]
    connected_usernames: List[str]
    total_connected: int
    server_time: datetime