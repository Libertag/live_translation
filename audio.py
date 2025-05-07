"""Модуль обработки аудио для программы субтитров."""

import time
import numpy as np
from queue import Queue, Empty
import sounddevice as sd
from silero_vad import VADIterator, load_silero_vad
from sounddevice import InputStream

from config import (
    SAMPLING_RATE, CHUNK_SIZE, LOOKBACK_CHUNKS, 
    MAX_SPEECH_SECS, MIN_REFRESH_SECS, gui_queue, stop_event
)
from utils import create_input_callback, end_recording, soft_reset
from translators import create_translator


def audio_processing(device_id, model_name="moonshine/base", translator_settings=None):
    """Основная функция обработки аудио.

    Args:
        device_id: ID устройства ввода звука
        model_name: Имя модели Moonshine для использования
        translator_settings: Настройки переводчика
    """
    from config import transcribe as transcribe_global
    from transcriber import Transcriber

    print(f"Загрузка модели Moonshine '{model_name}' (с использованием ONNX runtime) ...")
    gui_queue.put(f"STATUS: Загрузка модели Moonshine '{model_name}'...")

    # Создание переводчика, если требуется
    translator = None
    if translator_settings and translator_settings['type'] != 'none':
        try:
            translator = create_translator(
                translator_settings['type'],
                translator_settings['source_lang'],
                translator_settings['target_lang'],
                translator_settings.get('m2m_model_size', 'small'),
                translator_settings.get('easynmt_model', 'opus-mt')
            )
            gui_queue.put(f"STATUS: Переводчик {translator.name} инициализирован")
        except ImportError as e:
            error_msg = f"Ошибка импорта библиотеки для переводчика: {str(e)}"
            print(error_msg)
            gui_queue.put(f"STATUS: {error_msg}")
            gui_queue.put(error_msg)
            translator = None
        except Exception as e:
            error_msg = f"Ошибка при инициализации переводчика: {str(e)}"
            print(error_msg)
            gui_queue.put(f"STATUS: {error_msg}")
            gui_queue.put(error_msg)
            translator = None

    # Инициализация транскрибера
    try:
        gui_queue.put("STATUS: Инициализация транскрибера...")
        # Сохраняем функцию транскрипции в глобальной переменной для использования другими модулями
        global_transcribe = Transcriber(model_name=model_name, rate=SAMPLING_RATE, translator=translator)
        transcribe_global = global_transcribe  # Устанавливаем глобальную переменную
        gui_queue.put("STATUS: Транскрибер инициализирован!")
    except Exception as e:
        error_msg = f"Ошибка при инициализации транскрибера: {str(e)}"
        gui_queue.put(f"STATUS: {error_msg}")
        print(error_msg)
        return

    # Загрузка и инициализация модели Silero VAD для определения голосовой активности
    try:
        gui_queue.put("STATUS: Инициализация детектора голосовой активности...")
        vad_model = load_silero_vad(onnx=True)
        vad_iterator = VADIterator(
            model=vad_model,
            sampling_rate=SAMPLING_RATE,
            threshold=0.5,  # Порог определения речи
            min_silence_duration_ms=2000,  # Минимальная длительность тишины для окончания фрагмента
        )
        gui_queue.put("STATUS: Детектор голосовой активности инициализирован!")
    except Exception as e:
        error_msg = f"Ошибка при инициализации VAD: {str(e)}"
        gui_queue.put(f"STATUS: {error_msg}")
        print(error_msg)
        return

    q = Queue()

    # Вывод информации об используемом устройстве
    print(f"Использование устройства ввода с ID: {device_id}")
    try:
        device_info = sd.query_devices(device_id)
        device_name = device_info['name']
        print(f"Название устройства: {device_name}")
        gui_queue.put(f"STATUS: Используется устройство: {device_name}")
    except Exception as e:
        print(f"Не удалось получить информацию об устройстве: {e}")
        gui_queue.put(f"STATUS: Устройство с ID {device_id}")

    # Создание потока ввода звука с указанным устройством
    try:
        stream = InputStream(
            samplerate=SAMPLING_RATE,
            channels=1,
            blocksize=CHUNK_SIZE,
            dtype=np.float32,
            callback=create_input_callback(q),
            device=device_id,  # Указываем ID устройства ввода
        )
        stream.start()
    except Exception as e:
        error_msg = f"Ошибка: не удалось открыть устройство ввода (ID: {device_id}). {str(e)}"
        gui_queue.put(f"STATUS: {error_msg}")
        print(error_msg)
        gui_queue.put(error_msg)
        return

    caption_cache = []  # Кэш субтитров
    lookback_size = LOOKBACK_CHUNKS * CHUNK_SIZE  # Размер буфера предыдущих данных
    speech = np.empty(0, dtype=np.float32)  # Буфер речи

    recording = False  # Флаг записи

    with stream:
        gui_queue.put("STATUS: Готово к работе. Говорите!")
        gui_queue.put("Готово к работе... Говорите!")
        try:
            while not stop_event.is_set():
                try:
                    # Используем таймаут, чтобы регулярно проверять stop_event
                    chunk, status = q.get(timeout=0.5)
                except Empty:
                    continue

                if status:
                    print(status)

                # Добавление нового блока данных в буфер речи
                speech = np.concatenate((speech, chunk))
                if not recording:
                    speech = speech[-lookback_size:]  # Сохраняем только последние блоки, если не ведется запись

                # Проверка голосовой активности с помощью Silero VAD
                speech_dict = vad_iterator(chunk)
                if speech_dict:
                    # Если обнаружено начало речи
                    if "start" in speech_dict and not recording:
                        recording = True
                        start_time = time.time()
                        gui_queue.put("STATUS: Обнаружена речь...")

                    # Если обнаружен конец речи
                    if "end" in speech_dict and recording:
                        recording = False
                        end_recording(speech, caption_cache, global_transcribe)
                        gui_queue.put("STATUS: Речь обработана!")
                elif recording:
                    # Проверка длительности речи для предотвращения слишком длинных фрагментов
                    if (len(speech) / SAMPLING_RATE) > MAX_SPEECH_SECS:
                        recording = False
                        end_recording(speech, caption_cache, global_transcribe)
                        soft_reset(vad_iterator)
                        gui_queue.put("STATUS: Речь обработана (превышена максимальная длительность)!")

                    # Обновление субтитров во время речи с интервалом не менее MIN_REFRESH_SECS
                    if (time.time() - start_time) > MIN_REFRESH_SECS:
                        text = global_transcribe(speech)
                        from utils import print_captions
                        print_captions(text, caption_cache)
                        start_time = time.time()
        except Exception as e:
            error_msg = f"Ошибка в обработке аудио: {e}"
            print(error_msg)
            gui_queue.put(f"STATUS: {error_msg}")
            gui_queue.put(error_msg)
        finally:
            # Обработка оставшихся данных при выходе
            if recording:
                try:
                    while not q.empty():
                        chunk, _ = q.get(block=False)
                        speech = np.concatenate((speech, chunk))
                    end_recording(speech, caption_cache, global_transcribe, do_print=True)
                except Exception as e:
                    print(f"Ошибка при завершении записи: {e}")

            # Закрываем поток
            stream.close()

            # Освобождаем ресурсы переводчика
            if translator:
                translator.close()

            # Вывод статистики
            print(
                f"""
                 model_name :  {model_name}
           MIN_REFRESH_SECS :  {MIN_REFRESH_SECS}s
          number inferences :  {global_transcribe.number_inferences}
        mean inference time :  {(global_transcribe.inference_secs / global_transcribe.number_inferences):.2f}s
      model realtime factor :  {(global_transcribe.speech_secs / global_transcribe.inference_secs):0.2f}x
    """
            )
            # Информируем пользователя о завершении работы
            gui_queue.put("STATUS: Обработка аудио остановлена.")