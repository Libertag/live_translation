"""Live captions from microphone using Moonshine and SileroVAD ONNX models with GUI and M2M100 translation."""

import os
import time
import threading
import sys
from queue import Queue, Empty

# Импорты для перевода с помощью M2M100
import torch
from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

import numpy as np
import sounddevice as sd
from silero_vad import VADIterator, load_silero_vad
from sounddevice import InputStream

from moonshine_onnx import MoonshineOnnxModel, load_tokenizer

import tkinter as tk
from tkinter import ttk, messagebox, font

# Глобальные константы
SAMPLING_RATE = 16000  # Частота дискретизации звука (16 кГц)
CHUNK_SIZE = 512       # Размер блока данных для Silero VAD (требование при частоте 16000 Гц)
LOOKBACK_CHUNKS = 5    # Количество предыдущих блоков данных для анализа
MAX_LINE_LENGTH = 80   # Максимальная длина строки субтитров
MAX_SPEECH_SECS = 15   # Максимальная длительность речи для обработки за один раз
MIN_REFRESH_SECS = 0.2 # Минимальный интервал обновления субтитров

# Глобальные переменные
gui_queue = None       # Очередь для обмена данными между потоками
transcribe = None      # Функция транскрипции
stop_event = None      # Событие для остановки потока обработки аудио

# Словарь соответствия кодов языков для M2M100
LANGUAGE_CODES = {
    "en": "en",   # английский
    "ru": "ru",   # русский
    "fr": "fr",   # французский
    "de": "de",   # немецкий
    "es": "es",   # испанский
    "it": "it",   # итальянский
    "ja": "ja",   # японский
    "zh": "zh",   # китайский
    "uk": "uk",   # украинский
    "pl": "pl",   # польский
    "cs": "cs",   # чешский
    "nl": "nl",   # голландский
    "pt": "pt",   # португальский
    "ar": "ar",   # арабский
    "tr": "tr",   # турецкий
    "ko": "ko",   # корейский
}

# Класс для перевода с использованием M2M100
class M2M100Translator:
    def __init__(self, source_lang, target_lang, model_size="small"):
        """Инициализация переводчика M2M100.

        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
            model_size: Размер модели ('small' для Facebook/m2m100_418M или 'large' для Facebook/m2m100_1.2B)
        """
        print(f"Инициализация переводчика M2M100 ({model_size})...")
        self.source_lang = LANGUAGE_CODES.get(source_lang, source_lang)
        self.target_lang = LANGUAGE_CODES.get(target_lang, target_lang)

        # Выбор модели в зависимости от размера
        if model_size == "small":
            model_name = "facebook/m2m100_418M"
        else:
            model_name = "facebook/m2m100_1.2B"

        # Загрузка модели и токенизатора
        self.tokenizer = M2M100Tokenizer.from_pretrained(model_name)
        self.model = M2M100ForConditionalGeneration.from_pretrained(model_name)

        # Если доступно CUDA, используем GPU
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
            self.model = self.model.to(self.device)
            print("Используется GPU (CUDA) для перевода")
        else:
            self.device = torch.device("cpu")
            print("Используется CPU для перевода")

    def translate(self, text):
        """Перевод текста.

        Args:
            text: Исходный текст для перевода

        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""

        try:
            # Устанавливаем язык источника для токенизатора
            self.tokenizer.src_lang = self.source_lang

            # Токенизация текста
            encoded = self.tokenizer(text, return_tensors="pt")

            # Переносим тензоры на GPU, если доступно
            if self.device.type == "cuda":
                encoded = {k: v.to(self.device) for k, v in encoded.items()}

            # Генерация перевода
            generated_tokens = self.model.generate(
                **encoded,
                forced_bos_token_id=self.tokenizer.get_lang_id(self.target_lang),
                max_length=128
            )

            # Декодирование результата
            translated_text = self.tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
            return translated_text
        except Exception as e:
            print(f"Ошибка при переводе: {e}")
            return text  # Возвращаем исходный текст в случае ошибки


# Функция для получения списка доступных аудиоустройств
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


class SettingsDialog:
    """Диалоговое окно для выбора устройства ввода и настройки размера шрифта."""

    def __init__(self, root):
        """Создает окно настроек.

        Args:
            root: Корневой элемент Tkinter
        """
        self.root = root
        self.root.title("Настройки")
        self.root.geometry("600x500")  # Увеличиваем размер для дополнительных опций
        self.root.resizable(True, True)

        # Установка минимального размера окна
        self.root.minsize(400, 400)

        # Переменные для хранения выбранных значений
        self.selected_device = tk.IntVar(value=0)
        self.font_size = tk.IntVar(value=64)
        self.model_name = tk.StringVar(value="moonshine/base")
        self.source_lang = tk.StringVar(value="en")
        self.target_lang = tk.StringVar(value="ru")
        self.translator_model = tk.StringVar(value="small")

        # Результаты выбора
        self.result = {
            "device": 0,
            "font_size": 64,
            "model_name": "moonshine/base",
            "source_lang": "en",
            "target_lang": "ru",
            "translator_model": "small",
            "cancelled": False
        }

        # Получение списка устройств
        self.devices = list_audio_devices()

        # Создание интерфейса
        self.create_widgets()

        # Центрирование окна
        self.center_window()

    def center_window(self):
        """Размещает окно по центру экрана."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def create_widgets(self):
        """Создает элементы интерфейса."""
        # Основной контейнер
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Заголовок
        header_label = ttk.Label(main_frame, text="Настройки субтитров", font=("Helvetica", 16, "bold"))
        header_label.pack(pady=(0, 20))

        # Выбор модели распознавания
        model_frame = ttk.LabelFrame(main_frame, text="Модель распознавания", padding=10)
        model_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Radiobutton(model_frame, text="Moonshine Base (стандартная)", variable=self.model_name, value="moonshine/base").pack(anchor=tk.W)
        ttk.Radiobutton(model_frame, text="Moonshine Tiny (быстрее, менее точная)", variable=self.model_name, value="moonshine/tiny").pack(anchor=tk.W)

        # Настройки перевода
        translation_frame = ttk.LabelFrame(main_frame, text="Настройки перевода", padding=10)
        translation_frame.pack(fill=tk.X, padx=5, pady=5)

        # Выбор исходного языка
        source_frame = ttk.Frame(translation_frame)
        source_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(source_frame, text="Исходный язык:").pack(side=tk.LEFT, padx=(0, 10))
        source_combo = ttk.Combobox(source_frame, textvariable=self.source_lang)
        source_combo['values'] = list(LANGUAGE_CODES.keys())
        source_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Выбор целевого языка
        target_frame = ttk.Frame(translation_frame)
        target_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(target_frame, text="Целевой язык:").pack(side=tk.LEFT, padx=(0, 10))
        target_combo = ttk.Combobox(target_frame, textvariable=self.target_lang)
        target_combo['values'] = list(LANGUAGE_CODES.keys())
        target_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Выбор размера модели переводчика
        model_size_frame = ttk.Frame(translation_frame)
        model_size_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(model_size_frame, text="Размер модели:").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(model_size_frame, text="Малая (418M, быстрее)", variable=self.translator_model, value="small").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(model_size_frame, text="Большая (1.2B, точнее)", variable=self.translator_model, value="large").pack(side=tk.LEFT)

        # Выбор устройства
        device_frame = ttk.LabelFrame(main_frame, text="Устройство ввода звука", padding=10)
        device_frame.pack(fill=tk.X, padx=5, pady=5)

        # Создаем виджет прокрутки для устройств
        device_canvas = tk.Canvas(device_frame)
        device_scrollbar = ttk.Scrollbar(device_frame, orient="vertical", command=device_canvas.yview)
        device_scrollable_frame = ttk.Frame(device_canvas)

        device_scrollable_frame.bind(
            "<Configure>",
            lambda e: device_canvas.configure(scrollregion=device_canvas.bbox("all"))
        )

        device_canvas.create_window((0, 0), window=device_scrollable_frame, anchor="nw")
        device_canvas.configure(yscrollcommand=device_scrollbar.set)

        device_canvas.pack(side="left", fill="both", expand=True)
        device_scrollbar.pack(side="right", fill="y")

        # Добавляем радиокнопки для устройств
        if not self.devices:
            ttk.Label(device_scrollable_frame, text="Не найдено устройств ввода").pack(anchor=tk.W)
        else:
            for device in self.devices:
                ttk.Radiobutton(
                    device_scrollable_frame,
                    text=f"ID: {device['id']} - {device['name']}",
                    variable=self.selected_device,
                    value=device['id']
                ).pack(anchor=tk.W, pady=2)

        # Настройка размера шрифта
        font_frame = ttk.LabelFrame(main_frame, text="Размер шрифта", padding=10)
        font_frame.pack(fill=tk.X, padx=5, pady=5)

        font_scale = ttk.Scale(
            font_frame,
            from_=16,
            to=120,
            orient="horizontal",
            variable=self.font_size,
            command=self.update_font_preview
        )
        font_scale.pack(fill=tk.X, padx=10)

        font_preview_frame = ttk.Frame(font_frame)
        font_preview_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(font_preview_frame, text="Размер: ").pack(side=tk.LEFT)
        self.font_size_label = ttk.Label(font_preview_frame, text="64")
        self.font_size_label.pack(side=tk.LEFT)

        # Предпросмотр текста
        self.preview_text = tk.Label(
            font_frame,
            text="Пример текста",
            font=("Helvetica", 64),
            bg="#f0f0f0",
            wraplength=500
        )
        self.preview_text.pack(pady=10, fill=tk.X)

        # Кнопки
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=20)

        ttk.Button(button_frame, text="Отмена", command=self.cancel).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Запустить", command=self.submit).pack(side=tk.RIGHT, padx=5)

        # Инициализация превью шрифта
        self.update_font_preview()

    def update_font_preview(self, *args):
        """Обновляет предпросмотр шрифта при изменении размера."""
        size = self.font_size.get()
        self.font_size_label.config(text=str(size))
        self.preview_text.config(font=("Helvetica", size))

    def submit(self):
        """Сохраняет выбранные настройки и закрывает окно."""
        self.result = {
            "device": self.selected_device.get(),
            "font_size": self.font_size.get(),
            "model_name": self.model_name.get(),
            "source_lang": self.source_lang.get(),
            "target_lang": self.target_lang.get(),
            "translator_model": self.translator_model.get(),
            "cancelled": False
        }
        self.root.destroy()

    def cancel(self):
        """Отменяет выбор и закрывает окно."""
        self.result["cancelled"] = True
        self.root.destroy()


class Transcriber(object):
    """Класс для транскрипции речи с помощью модели Moonshine."""

    def __init__(self, model_name, rate=16000, translator=None):
        """Инициализация транскрибера.

        Args:
            model_name: Название модели Moonshine
            rate: Частота дискретизации (должна быть 16000 Гц)
            translator: Объект переводчика
        """
        if rate != 16000:
            raise ValueError("Moonshine поддерживает только частоту дискретизации 16000 Гц.")
        self.model = MoonshineOnnxModel(model_name=model_name)
        self.rate = rate
        self.tokenizer = load_tokenizer()
        self.translator = translator

        self.inference_secs = 0  # Общее время вывода
        self.number_inferences = 0  # Количество выполненных транскрипций
        self.speech_secs = 0  # Общая длительность обработанной речи
        self.__call__(np.zeros(int(rate), dtype=np.float32))  # Прогрев модели

    def __call__(self, speech):
        """Транскрибирует речь и переводит текст.

        Args:
            speech: Numpy массив с аудиоданными

        Returns:
            str: Переведенный текст
        """
        self.number_inferences += 1
        self.speech_secs += len(speech) / self.rate
        start_time = time.time()

        # Распознавание речи
        tokens = self.model.generate(speech[np.newaxis, :].astype(np.float32))
        text = self.tokenizer.decode_batch(tokens)[0]

        # Перевод распознанного текста, если переводчик доступен
        if self.translator and text.strip():
            text = self.translator.translate(text)

        # Учет времени вывода
        self.inference_secs += time.time() - start_time

        return text


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


def end_recording(speech, caption_cache, do_print=True):
    """Транскрибирует, выводит и кэширует субтитры, затем очищает буфер речи.

    Args:
        speech: Numpy массив с аудиоданными
        caption_cache: Список для кэширования субтитров
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
    gui_queue.put(full_text)


def soft_reset(vad_iterator):
    """Мягкий сброс Silero VADIterator без влияния на состояние модели VAD.

    Args:
        vad_iterator: Итератор VAD для сброса
    """
    vad_iterator.triggered = False
    vad_iterator.temp_end = 0
    vad_iterator.current_sample = 0


class CaptionGUI:
    """Класс для создания графического интерфейса субтитров."""

    def __init__(self, root, font_size=64):
        """Инициализация GUI.

        Args:
            root: Корневой элемент Tkinter
            font_size: Размер шрифта для субтитров
        """
        self.root = root
        self.root.title("Субтитры в реальном времени")

        # Настройка для полноэкранного режима
        self.root.attributes("-zoomed", True)  # Для Linux
        try:
            self.root.state('zoomed')  # Для Windows
        except:
            pass

        # Настройки шрифта с учетом переданного размера
        font_settings = ("Helvetica", font_size)

        # Создание меню
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)

        # Меню "Файл"
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(label="Выход", command=self.exit_application)

        # Основной контейнер
        main_container = tk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)

        # Добавление полосы прокрутки для текстового виджета
        self.text_frame = tk.Frame(main_container)
        self.text_frame.pack(fill=tk.BOTH, expand=True)

        self.scrollbar = tk.Scrollbar(self.text_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Создание текстового виджета для отображения субтитров
        self.text_widget = tk.Text(
            self.text_frame,
            wrap="word",  # Перенос по словам
            height=20,
            width=80,
            font=font_settings,
            yscrollcommand=self.scrollbar.set,
            bg="#f5f5f5",  # Светло-серый фон для лучшей читаемости
        )
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.text_widget.yview)

        # Кнопка выхода внизу окна
        button_frame = tk.Frame(main_container)
        button_frame.pack(fill=tk.X, pady=10, padx=10)

        exit_button = tk.Button(button_frame, text="Выход", command=self.exit_application,
                              bg="#ff6b6b", fg="white", font=("Helvetica", 12),
                              padx=10, pady=5)
        exit_button.pack(side=tk.RIGHT)

        self.update_interval = 100  # Интервал обновления в миллисекундах
        self.last_text = ""

        # Обработка закрытия окна
        self.root.protocol("WM_DELETE_WINDOW", self.exit_application)

    def update_gui(self):
        """Обновляет GUI текстом из очереди."""
        try:
            while True:
                text = gui_queue.get_nowait()
                if text != self.last_text:
                    self.text_widget.delete("1.0", tk.END)
                    self.text_widget.insert(tk.END, text)
                    self.text_widget.see(tk.END)  # Автоматическая прокрутка вниз
                    self.last_text = text
        except Empty:
            pass
        # Проверяем, не был ли закрыт root
        if self.root.winfo_exists():
            self.root.after(self.update_interval, self.update_gui)

    def exit_application(self):
        """Закрывает приложение."""
        if messagebox.askokcancel("Выход", "Вы уверены, что хотите выйти?"):
            # Останавливаем обработку аудио
            global stop_event
            if stop_event:
                stop_event.set()

            # Останавливаем выполнение программы
            print("Завершение работы...")
            self.root.quit()
            self.root.destroy()
            # Принудительное завершение всех потоков
            os._exit(0)


def audio_processing(device_id, model_name="moonshine/base", source_lang="en", target_lang="ru", translator_model="small"):
    """Основная функция обработки аудио.

    Args:
        device_id: ID устройства ввода звука
        model_name: Имя модели Moonshine для использования
        source_lang: Исходный язык
        target_lang: Целевой язык
        translator_model: Размер модели переводчика
    """
    global transcribe, stop_event

    print(f"Загрузка модели Moonshine '{model_name}' (с использованием ONNX runtime) ...")

    # Инициализация переводчика
    try:
        gui_queue.put(f"Инициализация переводчика M2M100 ({translator_model})...")
        translator = M2M100Translator(source_lang, target_lang, model_size=translator_model)
        gui_queue.put("Переводчик инициализирован!")
    except Exception as e:
        gui_queue.put(f"Ошибка при инициализации переводчика: {str(e)}")
        print(f"Ошибка при инициализации переводчика: {e}")
        return

    # Инициализация транскрибера
    try:
        gui_queue.put("Инициализация транскрибера...")
        transcribe = Transcriber(model_name=model_name, rate=SAMPLING_RATE, translator=translator)
        gui_queue.put("Транскрибер инициализирован!")
    except Exception as e:
        gui_queue.put(f"Ошибка при инициализации транскрибера: {str(e)}")
        print(f"Ошибка при инициализации транскрибера: {e}")
        return

    # Загрузка и инициализация модели Silero VAD для определения голосовой активности
    try:
        gui_queue.put("Инициализация детектора голосовой активности...")
        vad_model = load_silero_vad(onnx=True)
        vad_iterator = VADIterator(
            model=vad_model,
            sampling_rate=SAMPLING_RATE,
            threshold=0.5,  # Порог определения речи
            min_silence_duration_ms=300,  # Минимальная длительность тишины для окончания фрагмента
        )
        gui_queue.put("Детектор голосовой активности инициализирован!")
    except Exception as e:
        gui_queue.put(f"Ошибка при инициализации VAD: {str(e)}")
        print(f"Ошибка при инициализации VAD: {e}")
        return

    q = Queue()

    # Вывод информации об используемом устройстве
    print(f"Использование устройства ввода с ID: {device_id}")
    try:
        device_info = sd.query_devices(device_id)
        device_name = device_info['name']
        print(f"Название устройства: {device_name}")
        gui_queue.put(f"Используется устройство: {device_name}")
    except Exception as e:
        print(f"Не удалось получить информацию об устройстве: {e}")
        gui_queue.put(f"Устройство с ID {device_id}")

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
        gui_queue.put(f"Ошибка: не удалось открыть устройство ввода (ID: {device_id}). {str(e)}")
        print(f"Ошибка при открытии устройства: {e}")
        return

    caption_cache = []  # Кэш субтитров
    lookback_size = LOOKBACK_CHUNKS * CHUNK_SIZE  # Размер буфера предыдущих данных
    speech = np.empty(0, dtype=np.float32)  # Буфер речи

    recording = False  # Флаг записи

    with stream:
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

                    # Если обнаружен конец речи
                    if "end" in speech_dict and recording:
                        recording = False
                        end_recording(speech, caption_cache)
                elif recording:
                    # Проверка длительности речи для предотвращения слишком длинных фрагментов
                    if (len(speech) / SAMPLING_RATE) > MAX_SPEECH_SECS:
                        recording = False
                        end_recording(speech, caption_cache)
                        soft_reset(vad_iterator)

                    # Обновление субтитров во время речи с интервалом не менее MIN_REFRESH_SECS
                    if (time.time() - start_time) > MIN_REFRESH_SECS:
                        text = transcribe(speech)
                        print_captions(text, caption_cache)
                        start_time = time.time()
        except Exception as e:
            print(f"Ошибка в обработке аудио: {e}")
            gui_queue.put(f"Ошибка: {str(e)}")
        finally:
            # Обработка оставшихся данных при выходе
            if recording:
                try:
                    while not q.empty():
                        chunk, _ = q.get(block=False)
                        speech = np.concatenate((speech, chunk))
                    end_recording(speech, caption_cache, do_print=True)
                except Exception as e:
                    print(f"Ошибка при завершении записи: {e}")

            # Закрываем поток
            stream.close()

            # Вывод статистики
            print(
                f"""
                 model_name :  {model_name}
           MIN_REFRESH_SECS :  {MIN_REFRESH_SECS}s
          number inferences :  {transcribe.number_inferences}
        mean inference time :  {(transcribe.inference_secs / transcribe.number_inferences):.2f}s
      model realtime factor :  {(transcribe.speech_secs / transcribe.inference_secs):0.2f}x
    """
            )
            # Информируем пользователя о завершении работы
            gui_queue.put("Обработка аудио остановлена.")


def main():
    """Основная функция программы."""
    global gui_queue, stop_event

    # Создание очереди для обмена данными между потоками
    gui_queue = Queue()

    # Создание события для остановки потока обработки аудио
    stop_event = threading.Event()

    # Инициализация Tkinter для окна настроек
    settings_root = tk.Tk()
    settings_dialog = SettingsDialog(settings_root)
    settings_root.mainloop()

    # Проверяем, не была ли отменена настройка
    if settings_dialog.result["cancelled"]:
        print("Настройка отменена. Выход из программы.")
        return

    # Получаем выбранные настройки
    device_id = settings_dialog.result["device"]
    font_size = settings_dialog.result["font_size"]
    model_name = settings_dialog.result["model_name"]
    source_lang = settings_dialog.result["source_lang"]
    target_lang = settings_dialog.result["target_lang"]
    translator_model = settings_dialog.result["translator_model"]

    # Запуск потока обработки аудио
    audio_thread = threading.Thread(
        target=audio_processing,
        args=(device_id, model_name, source_lang, target_lang, translator_model),
        daemon=True  # Поток завершится при завершении основного потока
    )
    audio_thread.start()

    # Создание GUI для субтитров
    main_root = tk.Tk()
    gui = CaptionGUI(main_root, font_size=font_size)
    main_root.after(100, gui.update_gui)  # Запуск цикла обновления GUI
    main_root.mainloop()


if __name__ == "__main__":
    main()
