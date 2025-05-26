"""Глобальные константы и настройки для программы субтитров."""

import os
import threading
from queue import Queue

# Глобальные константы
SAMPLING_RATE = 16000  # Частота дискретизации звука (16 кГц)
CHUNK_SIZE = 512       # Размер блока данных для Silero VAD (требование при частоте 16000 Гц)
LOOKBACK_CHUNKS = 5    # Количество предыдущих блоков данных для анализа
MAX_LINE_LENGTH = 80   # Максимальная длина строки субтитров
MAX_SPEECH_SECS = 15   # Максимальная длительность речи для обработки за один раз
MIN_REFRESH_SECS = 0.5 # Минимальный интервал обновления субтитров

# Глобальные переменные
gui_queue = None       # Очередь для обмена данными между потоками
transcribe = None      # Функция транскрипции
stop_event = None      # Событие для остановки потока обработки аудио
translator = None      # Объект переводчика

# Словарь соответствия кодов языков
LANGUAGE_CODES = {
    "en": "English",
    "ru": "Russian",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "ja": "Japanese",
    "zh": "Chinese",
    "uk": "Ukrainian",
    "pl": "Polish",
    "cs": "Czech",
    "nl": "Dutch",
    "pt": "Portuguese",
    "ar": "Arabic",
    "tr": "Turkish",
    "ko": "Korean",
}

# Доступные переводчики
TRANSLATORS = {
    "none": "Без перевода",
    "argos": "Argos Translate (легкий, офлайн)",
    "m2m100": "M2M100 (высокое качество)",
    "nllb200": "NLLB-200 (Meta, поддержка 200+ языков)",
    "small100": "SMaLL-100 (компактная модель)",
    "pymarian": "PyMarian: MarianMT (быстрый перевод)",
    "gpt4o": "API: GPT-4o (требуется API ключ)",
    "claude": "API: Claude 3.5 Sonnet (требуется API ключ)",
    "easynmt": "EasyNMT (универсальный)"
}
