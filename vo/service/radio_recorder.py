import os
import uuid
import asyncio
import numpy as np
import av
from datetime import datetime
from typing import Dict, Optional, List
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class RadioRecorder:
    """Класс для управления записью эфиров с использованием PyAV"""

    def __init__(self, records_dir: str = "records"):
        self.records_dir = records_dir
        self.active_recordings: Dict[int, RecordingSession] = {}
        self._ensure_records_dir()

    def _ensure_records_dir(self):
        """Создание директории для записей, если её нет"""
        if not os.path.exists(self.records_dir):
            os.makedirs(self.records_dir)
            logger.info(f"✅ Создана директория для записей: {self.records_dir}")

    async def start_recording(self, channel_id: int, speaker_name: str) -> Dict:
        """Начать запись эфира в канале"""
        if channel_id in self.active_recordings:
            return {
                "success": False,
                "message": f"Recording already in progress for channel {channel_id}",
                "channel_id": channel_id
            }

        try:
            # Создаем новую сессию записи
            session = RecordingSession(channel_id, self.records_dir, speaker_name)
            self.active_recordings[channel_id] = session

            logger.info(f"🎙️ НАЧАТА ЗАПИСЬ в канале {channel_id}")

            return {
                "success": True,
                "message": f"Recording started for channel {channel_id}",
                "channel_id": channel_id,
                "recording_id": session.recording_id,
                "filename": session.filename,
                "start_time": session.start_time.isoformat(),
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при старте записи: {e}")
            return {
                "success": False,
                "message": f"Error starting recording: {str(e)}",
                "channel_id": channel_id
            }

    async def stop_recording(self, channel_id: int) -> Dict:
        """Остановить запись эфира в канале"""
        if channel_id not in self.active_recordings:
            return {
                "success": False,
                "message": f"No active recording for channel {channel_id}",
                "channel_id": channel_id
            }

        session = self.active_recordings[channel_id]

        try:
            # Завершаем запись и сохраняем файл
            result = await session.finalize()

            if result["success"]:
                # Удаляем из активных записей
                del self.active_recordings[channel_id]
                logger.info(f"⏹️ ОСТАНОВЛЕНА ЗАПИСЬ в канале {channel_id}")
            else:
                logger.error(f"❌ Ошибка при сохранении записи канала {channel_id}: {result.get('error')}")

            return result

        except Exception as e:
            logger.error(f"❌ Ошибка при остановке записи: {e}")
            return {
                "success": False,
                "message": f"Error stopping recording: {str(e)}",
                "channel_id": channel_id,
                "filename": session.filename
            }

    async def record_audio_chunk(self, channel_id: int, audio_data: bytes, speaker_id: str, speaker_name: str = None):
        """Добавить аудио чанк в текущую запись канала"""
        if channel_id not in self.active_recordings:
            return

        session = self.active_recordings[channel_id]
        await session.add_audio_chunk(audio_data, speaker_id, speaker_name)

    def get_recording_status(self, channel_id: int) -> Optional[Dict]:
        """Получить статус записи для канала"""
        if channel_id not in self.active_recordings:
            return {
                "is_recording": False,
            }

        session = self.active_recordings[channel_id]
        return {
            "is_recording": True,
            "recording_id": session.recording_id,
            "filename": session.filename,
            "start_time": session.start_time.isoformat(),
            "duration_seconds": session.get_duration(),
            "chunks_received": session.chunks_received,
            "speakers": list(session.speakers),
        }

    async def get_recordings_list(self, channel_id: Optional[int] = None) -> List[Dict]:
        """Получить список всех записей или записей для конкретного канала"""
        import glob

        if channel_id:
            pattern = f"channel_{channel_id}_*.wav"
        else:
            pattern = "channel_*.wav"

        search_path = os.path.join(self.records_dir, pattern)
        recordings = []

        for filepath in glob.glob(search_path):
            filename = os.path.basename(filepath)
            # Парсим имя файла: channel_123_20240101_153045_abc123.wav
            parts = filename.replace('.wav', '').split('_')

            if len(parts) >= 5:
                rec_channel_id = int(parts[1])
                timestamp_str = f"{parts[2]}_{parts[3]}"
                recording_id = parts[4]

                # Пытаемся получить длительность из метаданных
                duration = None
                try:
                    container = av.open(filepath)
                    duration = float(container.duration) / av.time_base if container.duration else None
                    container.close()
                except:
                    pass

                recordings.append({
                    "filename": filename,
                    "filepath": filepath,
                    "channel_id": rec_channel_id,
                    "recording_id": recording_id,
                    "timestamp": timestamp_str,
                    "file_size_bytes": os.path.getsize(filepath),
                    "duration_seconds": duration,
                    "created": datetime.fromtimestamp(os.path.getctime(filepath)).isoformat()
                })

        # Сортируем по дате (новые сверху)
        recordings.sort(key=lambda x: x["created"], reverse=True)
        return recordings


class RecordingSession:
    """Класс для хранения данных одной сессии записи"""

    def __init__(self, channel_id: int, records_dir: str, speaker_name: str):
        self.channel_id = channel_id
        self.speaker_name = speaker_name
        self.records_dir = records_dir
        self.recording_id = str(uuid.uuid4())[:8]
        self.start_time = datetime.now()

        # Буфер для аудио данных
        self.audio_buffer = bytearray()
        self.chunks_received = 0
        self.speakers = set()  # speaker_id
        self.speaker_names = set()  # speaker_name
        self._lock = asyncio.Lock()

        # Генерируем имя файла: records/channel_123_20240101_153045_abc123.mp3
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.filename = f"channel_{channel_id}_{speaker_name}_{timestamp}.mp3"
        self.filepath = os.path.join(records_dir, self.filename)

        # Параметры аудио (предполагаем стандартные)
        self.sample_rate = 16000
        self.channels = 1
        self.sample_width = 2  # 16-bit = 2 bytes

        logger.debug(f"Создана сессия записи: {self.filename}")

    async def add_audio_chunk(self, audio_data: bytes, speaker_id: str, speaker_name: str = None):
        """Добавить аудио чанк в буфер записи"""
        async with self._lock:
            self.audio_buffer.extend(audio_data)
            self.chunks_received += 1
            self.speakers.add(speaker_id)
            if speaker_name:
                self.speaker_names.add(speaker_name)

    def get_duration(self) -> float:
        """Примерная длительность в секундах"""
        if not self.audio_buffer:
            return 0.0
        # Для 16-bit моно: bytes / (sample_rate * bytes_per_sample)
        bytes_per_second = self.sample_rate * self.sample_width
        return len(self.audio_buffer) / bytes_per_second

    async def finalize(self) -> Dict:
        """Завершить запись и сохранить в WAV файл"""
        async with self._lock:
            logger.info(f"ФИНАЛИЗАЦИЯ: всего байт={len(self.audio_buffer)}, чанков={self.chunks_received}")

            if not self.audio_buffer:
                return {
                    "success": False,
                    "message": "No audio data recorded",
                    "filename": self.filename,
                    "channel_id": self.channel_id
                }

            # Сохраняем WAV
            try:
                wav_filename = self.filename.replace('.mp3', '.wav')
                wav_filepath = os.path.join(self.records_dir, wav_filename)

                with open(wav_filepath, 'wb') as f:
                    # Пишем правильный WAV заголовок
                    f.write(self._create_wav_header(len(self.audio_buffer)))
                    f.write(self.audio_buffer)

                file_size = os.path.getsize(wav_filepath)
                duration = self.get_duration()

                logger.info(f"✅ WAV сохранен: {wav_filepath} ({file_size} байт, {duration:.1f} сек)")

                return {
                    "success": True,
                    "message": "Recording saved successfully",
                    "filename": wav_filename,
                    "filepath": wav_filepath,
                    "file_size_bytes": file_size,
                    "duration_seconds": duration,
                    "chunks_processed": self.chunks_received,
                    "speakers_count": len(self.speakers),
                    "speakers_names": list(self.speaker_names),
                    "channel_id": self.channel_id,
                    "recording_id": self.recording_id
                }

            except Exception as e:
                logger.error(f"❌ Ошибка сохранения WAV: {e}", exc_info=True)
                return {
                    "success": False,
                    "message": f"Error saving recording: {str(e)}",
                    "filename": self.filename,
                    "channel_id": self.channel_id
                }

    def _create_wav_header(self, data_size: int) -> bytes:
        """Создает заголовок WAV файла для 16-bit PCM моно"""
        sample_rate = self.sample_rate
        bits_per_sample = 16
        channels = self.channels
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8

        header = bytearray()
        # RIFF header
        header.extend(b'RIFF')
        header.extend((36 + data_size).to_bytes(4, 'little'))
        header.extend(b'WAVE')

        # fmt subchunk
        header.extend(b'fmt ')
        header.extend((16).to_bytes(4, 'little'))
        header.extend((1).to_bytes(2, 'little'))  # PCM
        header.extend(channels.to_bytes(2, 'little'))
        header.extend(sample_rate.to_bytes(4, 'little'))
        header.extend(byte_rate.to_bytes(4, 'little'))
        header.extend(block_align.to_bytes(2, 'little'))
        header.extend(bits_per_sample.to_bytes(2, 'little'))

        # data subchunk
        header.extend(b'data')
        header.extend(data_size.to_bytes(4, 'little'))

        return bytes(header)