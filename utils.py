"""Модуль с вспомогательными функциями для программы субтитров."""

import sounddevice as sd
import numpy as np
from queue import Queue
from silero_vad import VADIterator

from config import gui_queue

def list_audio_devices():
    """Возвращает список доступных аудиоустройств ввода.

    Returns:
        list: Список словарей с информацией об устройствах
    """
    devices = []
    all_devices = sd.query_devices()
    for i, device in enumerate(all_devices):
        if device['max_input_channels'] > 0:  # Проверяем, что устройство поддерживает ввод
            devices.append({"id": i, "name": device['name']})
    return devices


def create_input_callback(q):
    """Создает функцию обратного вызова для аудиопотока sounddevice.

    Args:
        q: Очередь для передачи аудиоданных

    Returns:
        function: Функция обратного вызова
    """
    def input_callback(data, frames, time, status):
        if status:
            print(status)
        q.put((data.copy().flatten(), status))

    return input_callback


def end_recording(speech, caption_cache, transcribe, do_print=True):
    """Транскрибирует, выводит и кэширует субтитры, затем очищает буфер речи.

    Args:
        speech: Numpy массив с аудиоданными
        caption_cache: Список для кэширования субтитров
        transcribe: Функция транскрипции
        do_print: Флаг для вывода субтитров
    """
    text = transcribe(speech)
    if do_print:
        print_captions(text, caption_cache)
    caption_cache.append(text)
    speech *= 0.0  # Очистка буфера речи


def print_captions(text, caption_cache):
    """Обновляет GUI новыми субтитрами.

    Args:
        text: Новый текст субтитров
        caption_cache: Кэш предыдущих субтитров
    """
    # Объединение кэшированных субтитров и текущего текста
    full_text = " ".join(caption_cache + [text])

    # Обработка знаков конца предложения - добавление переноса строки
    full_text = full_text.replace(". ", ".\n").replace("! ", "!\n").replace("? ", "?\n")

    gui_queue.put(full_text)

def soft_reset(vad_iterator):
    """Мягкий сброс Silero VADIterator без влияния на состояние модели VAD.

    Args:
        vad_iterator: Итератор VAD для сброса
    """
    vad_iterator.triggered = False
    vad_iterator.temp_end = 0
    vad_iterator.current_sample = 0


def check_dependencies():
    """Проверяет наличие необходимых зависимостей.

    Returns:
        dict: Словарь со статусом зависимостей
    """
    dependencies = {
        "argos": False,
        "m2m100": False,
        "easynmt": False,
        "openai": False,
        "anthropic": False
    }

    # Проверяем наличие argostranslate
    try:
        import importlib
        importlib.import_module("argostranslate.translate")
        dependencies["argos"] = True
    except ImportError:
        pass

    # Проверяем наличие transformers и torch для M2M100, NLLB-200, SMaLL-100 и PyMarian
    try:
        import torch
        importlib.import_module("transformers")
        dependencies["m2m100"] = True
    except ImportError:
        pass

    # Проверяем наличие easynmt
    try:
        importlib.import_module("easynmt")
        dependencies["easynmt"] = True
    except ImportError:
        pass

    # Проверяем наличие openai для GPT-4o
    try:
        import openai
        dependencies["openai"] = True
    except ImportError:
        pass

    # Проверяем наличие anthropic для Claude 3.5 Sonnet
    try:
        import anthropic
        dependencies["anthropic"] = True
    except ImportError:
        pass

    return dependencies
