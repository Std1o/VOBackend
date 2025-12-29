from enum import Enum


class MessageType(str, Enum):
    CONNECTED = "connected"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"
    SPEAKER_CHANGED = "speaker_changed"
    SPEAK_REQUEST = "speak_request"
    SPEAK_GRANTED = "speak_granted"
    SPEAK_RELEASED = "speak_released"
    SPEAK_DENIED = "speak_denied"
    AUDIO_CHUNK = "audio_chunk"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"
    STATUS = "status"