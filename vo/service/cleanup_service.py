# vo/service/cleanup_service.py
import asyncio
import os
import glob
import logging
from datetime import datetime, time, timedelta
from vo import tables
from fastapi import Depends
from vo.database import get_session, Session

logger = logging.getLogger(__name__)


class CleanupService:
    def __init__(self, records_dir: str = "records", session: Session = Depends(get_session)):
        self.records_dir = records_dir
        self.is_running = False
        self._cleanup_task = None
        self.session = session

    async def start(self):
        """Запустить сервис очистки"""
        self.is_running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("🔄 Сервис очистки записей запущен")
        return self._cleanup_task

    async def stop(self):
        """Остановить сервис очистки"""
        self.is_running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("⏹️ Сервис очистки записей остановлен")

    async def _cleanup_loop(self):
        """Основной цикл очистки - выполняется постоянно"""
        try:
            while self.is_running:
                try:
                    now = datetime.now()

                    # Вычисляем время до следующей полуночи
                    next_run = datetime.combine(now.date() + timedelta(days=1), time.min)
                    seconds_until_midnight = (next_run - now).total_seconds()

                    logger.info(f"🕛 Следующая очистка записей в {next_run.strftime('%Y-%m-%d %H:%M:%S')} "
                                f"(через {seconds_until_midnight / 3600:.1f} часов)")

                    # Ждем до полуночи (с возможностью отмены)
                    try:
                        await asyncio.sleep(seconds_until_midnight)
                    except asyncio.CancelledError:
                        logger.info("🛑 Ожидание отменено")
                        break

                    # Выполняем очистку
                    await self._cleanup_files()
                    self.delete_all_chat_messages()

                except Exception as e:
                    logger.error(f"❌ Ошибка в цикле очистки: {e}")
                    # При ошибке ждем 1 час и пробуем снова
                    try:
                        await asyncio.sleep(3600)
                    except asyncio.CancelledError:
                        break
        except asyncio.CancelledError:
            logger.info("🛑 Задача очистки завершена")
            raise

    async def _cleanup_files(self):
        """Удаление всех WAV файлов"""
        try:
            pattern = os.path.join(self.records_dir, "*.wav")
            wav_files = glob.glob(pattern)

            if not wav_files:
                logger.info(f"📂 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Нет файлов для удаления")
                return

            deleted_count = 0
            total_size = 0
            errors = []

            for file_path in wav_files:
                try:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_count += 1
                    total_size += file_size
                    logger.debug(f"Удален: {os.path.basename(file_path)} ({file_size} байт)")
                except Exception as e:
                    errors.append(f"{os.path.basename(file_path)}: {str(e)}")
                    logger.error(f"Ошибка удаления {file_path}: {e}")

            log_msg = (f"🧹 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - "
                       f"Очистка завершена: удалено {deleted_count} файлов, "
                       f"освобождено {total_size / 1024 / 1024:.2f} MB")

            if errors:
                log_msg += f"\n   Ошибки: {len(errors)}"

            logger.info(log_msg)

        except Exception as e:
            logger.error(f"❌ Ошибка при удалении файлов: {e}")

    def delete_all_chat_messages(self):
        try:
            self.session.query(tables.ChatMessage).delete()
            self.session.commit()
            print("Все сообщения чата успешно удалены")
        except Exception as e:
            self.session.rollback()
            print(f"Ошибка при удалении: {e}")

    async def cleanup_now(self):
        """Принудительная очистка (для тестирования)"""
        logger.info("🧹 Запущена принудительная очистка")
        await self._cleanup_files()