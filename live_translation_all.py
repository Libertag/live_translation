"""Live captions from microphone using Moonshine and SileroVAD ONNX models with GUI and multiple translator options."""

import os
import time
import threading
import sys
from queue import Queue, Empty

# Базовые импорты
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
    "easynmt": "EasyNMT (универсальный)"
}

# ========== КЛАССЫ ПЕРЕВОДЧИКОВ ==========

class BaseTranslator:
    """Базовый класс для всех переводчиков."""
    
    def __init__(self, source_lang, target_lang):
        """Инициализация базового переводчика.
        
        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
        """
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.name = "Base Translator"
        
    def translate(self, text):
        """Метод перевода, должен быть переопределен в наследниках.
        
        Args:
            text: Исходный текст для перевода
            
        Returns:
            str: Переведенный текст
        """
        return text  # По умолчанию возвращаем исходный текст
        
    def close(self):
        """Освобождение ресурсов, если требуется."""
        pass


class NoTranslator(BaseTranslator):
    """Класс 'переводчика', который просто возвращает исходный текст."""
    
    def __init__(self, source_lang, target_lang):
        super().__init__(source_lang, target_lang)
        self.name = "No Translation"
        
    def translate(self, text):
        return text


class ArgosTranslator(BaseTranslator):
    """Класс для перевода с использованием Argos Translate."""
    
    def __init__(self, source_lang, target_lang):
        """Инициализация переводчика Argos Translate.
        
        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
        """
        super().__init__(source_lang, target_lang)
        self.name = "Argos Translate"
        
        try:
            # Импортируем библиотеку только при создании объекта
            import argostranslate.package
            import argostranslate.translate
            self.argostranslate = argostranslate
            
            print(f"Инициализация Argos Translate ({source_lang} -> {target_lang})...")
            gui_queue.put(f"Инициализация Argos Translate ({source_lang} -> {target_lang})...")
            
            # Загрузка и установка пакета
            argostranslate.package.update_package_index()
            available_packages = argostranslate.package.get_available_packages()
            
            # Ищем нужный пакет
            package_to_install = None
            for package in available_packages:
                if package.from_code == source_lang and package.to_code == target_lang:
                    package_to_install = package
                    break
            
            if package_to_install is None:
                raise ValueError(f"Не найден пакет перевода для {source_lang} -> {target_lang}")
                
            # Устанавливаем пакет
            argostranslate.package.install_from_path(package_to_install.download())
            gui_queue.put("Argos Translate инициализирован!")
            
        except Exception as e:
            gui_queue.put(f"Ошибка при инициализации Argos Translate: {str(e)}")
            print(f"Ошибка при инициализации Argos Translate: {e}")
            raise e
    
    def translate(self, text):
        """Перевод текста с помощью Argos Translate.
        
        Args:
            text: Исходный текст для перевода
            
        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""
            
        try:
            translated_text = self.argostranslate.translate.translate(
                text, self.source_lang, self.target_lang
            )
            return translated_text
        except Exception as e:
            print(f"Ошибка при переводе с Argos Translate: {e}")
            return text  # Возвращаем исходный текст в случае ошибки


class M2M100Translator(BaseTranslator):
    """Класс для перевода с использованием M2M100."""
    
    def __init__(self, source_lang, target_lang, model_size="small"):
        """Инициализация переводчика M2M100.
        
        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
            model_size: Размер модели ('small' для Facebook/m2m100_418M или 'large' для Facebook/m2m100_1.2B)
        """
        super().__init__(source_lang, target_lang)
        self.name = f"M2M100 ({model_size})"
        
        try:
            # Импортируем библиотеки только при создании объекта
            import torch
            from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
            
            print(f"Инициализация переводчика M2M100 ({model_size})...")
            gui_queue.put(f"Инициализация переводчика M2M100 ({model_size})...")
            
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
                gui_queue.put("Используется GPU (CUDA) для перевода")
                print("Используется GPU (CUDA) для перевода")
            else:
                self.device = torch.device("cpu")
                gui_queue.put("Используется CPU для перевода")
                print("Используется CPU для перевода")
            
            gui_queue.put("M2M100 инициализирован!")
            
        except Exception as e:
            gui_queue.put(f"Ошибка при инициализации M2M100: {str(e)}")
            print(f"Ошибка при инициализации M2M100: {e}")
            raise e
    
    def translate(self, text):
        """Перевод текста с помощью M2M100.
        
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
            print(f"Ошибка при переводе с M2M100: {e}")
            return text  # Возвращаем исходный текст в случае ошибки


class EasyNMTTranslator(BaseTranslator):
    """Класс для перевода с использованием EasyNMT."""
    
    def __init__(self, source_lang, target_lang, model_name="opus-mt"):
        """Инициализация переводчика EasyNMT.
        
        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
            model_name: Название модели ('opus-mt', 'm2m_100_418M', 'm2m_100_1.2B', 'mbart50_m2m')
        """
        super().__init__(source_lang, target_lang)
        self.name = f"EasyNMT ({model_name})"
        
        try:
            # Импортируем библиотеку только при создании объекта
            from easynmt import EasyNMT
            
            print(f"Инициализация EasyNMT с моделью {model_name}...")
            gui_queue.put(f"Инициализация EasyNMT с моделью {model_name}...")
            
            # Загрузка модели
            self.model = EasyNMT(model_name)
            
            gui_queue.put("EasyNMT инициализирован!")
            
        except Exception as e:
            gui_queue.put(f"Ошибка при инициализации EasyNMT: {str(e)}")
            print(f"Ошибка при инициализации EasyNMT: {e}")
            raise e
    
    def translate(self, text):
        """Перевод текста с помощью EasyNMT.
        
        Args:
            text: Исходный текст для перевода
            
        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""
            
        try:
            translated_text = self.model.translate(
                text, 
                source_lang=self.source_lang, 
                target_lang=self.target_lang
            )
            return translated_text
        except Exception as e:
            print(f"Ошибка при переводе с EasyNMT: {e}")
            return text  # Возвращаем исходный текст в случае ошибки


# ========== ФУНКЦИИ СОЗДАНИЯ ПЕРЕВОДЧИКОВ ==========

def create_translator(translator_type, source_lang, target_lang, model_size="small", easynmt_model="opus-mt"):
    """Создает объект переводчика нужного типа.
    
    Args:
        translator_type: Тип переводчика ('none', 'argos', 'm2m100', 'easynmt')
        source_lang: Код исходного языка
        target_lang: Код целевого языка
        model_size: Размер модели для M2M100
        easynmt_model: Название модели для EasyNMT
        
    Returns:
        BaseTranslator: Объект переводчика
    """
    if translator_type == "none":
        return NoTranslator(source_lang, target_lang)
    elif translator_type == "argos":
        return ArgosTranslator(source_lang, target_lang)
    elif translator_type == "m2m100":
        return M2M100Translator(source_lang, target_lang, model_size)
    elif translator_type == "easynmt":
        return EasyNMTTranslator(source_lang, target_lang, easynmt_model)
    else:
        raise ValueError(f"Неизвестный тип переводчика: {translator_type}")


# ========== GUI КЛАССЫ ==========

class SettingsDialog:
    """Диалоговое окно для выбора устройства ввода, настроек перевода и размера шрифта."""
    
    def __init__(self, root):
        """Создает окно настроек.
        
        Args:
            root: Корневой элемент Tkinter
        """
        self.root = root
        self.root.title("Настройки")
        self.root.geometry("700x650")  # Увеличиваем размер для дополнительных опций
        self.root.resizable(True, True)
        
        # Установка минимального размера окна
        self.root.minsize(600, 600)
        
        # Переменные для хранения выбранных значений
        self.selected_device = tk.IntVar(value=0)
        self.font_size = tk.IntVar(value=64)
        self.model_name = tk.StringVar(value="moonshine/base")
        
        # Настройки переводчика
        self.translator_type = tk.StringVar(value="none")
        self.source_lang = tk.StringVar(value="en")
        self.target_lang = tk.StringVar(value="ru")
        self.m2m_model_size = tk.StringVar(value="small")
        self.easynmt_model = tk.StringVar(value="opus-mt")
        
        # Результаты выбора
        self.result = {
            "device": 0, 
            "font_size": 64, 
            "model_name": "moonshine/base", 
            "translator": {
                "type": "none",
                "source_lang": "en",
                "target_lang": "ru",
                "m2m_model_size": "small",
                "easynmt_model": "opus-mt"
            },
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
        # Основной контейнер с прокруткой
        main_canvas = tk.Canvas(self.root)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        
        main_frame = ttk.Frame(main_canvas)
        main_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        main_canvas.create_window((0, 0), window=main_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        main_canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")
        
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
        
        # Выбор переводчика
        translator_frame = ttk.Frame(translation_frame)
        translator_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(translator_frame, text="Переводчик:").pack(side=tk.LEFT, padx=(0, 10))
        translator_combo = ttk.Combobox(translator_frame, textvariable=self.translator_type, state="readonly")
        translator_combo['values'] = list(TRANSLATORS.keys())
        translator_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Выбор исходного языка
        source_frame = ttk.Frame(translation_frame)
        source_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(source_frame, text="Исходный язык:").pack(side=tk.LEFT, padx=(0, 10))
        source_combo = ttk.Combobox(source_frame, textvariable=self.source_lang, state="readonly")
        source_combo['values'] = list(LANGUAGE_CODES.keys())
        source_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Выбор целевого языка
        target_frame = ttk.Frame(translation_frame)
        target_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(target_frame, text="Целевой язык:").pack(side=tk.LEFT, padx=(0, 10))
        target_combo = ttk.Combobox(target_frame, textvariable=self.target_lang, state="readonly")
        target_combo['values'] = list(LANGUAGE_CODES.keys())
        target_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Дополнительные настройки для M2M100
        m2m_frame = ttk.LabelFrame(translation_frame, text="Настройки M2M100")
        m2m_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Radiobutton(m2m_frame, text="Малая модель (418M, быстрее)", variable=self.m2m_model_size, value="small").pack(anchor=tk.W, padx=5, pady=2)
        ttk.Radiobutton(m2m_frame, text="Большая модель (1.2B, точнее)", variable=self.m2m_model_size, value="large").pack(anchor=tk.W, padx=5, pady=2)
        
        # Дополнительные настройки для EasyNMT
        easynmt_frame = ttk.LabelFrame(translation_frame, text="Настройки EasyNMT")
        easynmt_frame.pack(fill=tk.X, padx=5, pady=5)
        
        easynmt_model_frame = ttk.Frame(easynmt_frame)
        easynmt_model_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(easynmt_model_frame, text="Модель:").pack(side=tk.LEFT, padx=(0, 10))
        easynmt_combo = ttk.Combobox(easynmt_model_frame, textvariable=self.easynmt_model, state="readonly")
        easynmt_combo['values'] = ["opus-mt", "m2m_100_418M", "m2m_100_1.2B", "mbart50_m2m"]
        easynmt_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Обновление состояния элементов управления при изменении типа переводчика
        def update_translator_options(*args):
            is_translator_active = self.translator_type.get() != "none"
            is_m2m100 = self.translator_type.get() == "m2m100"
            is_easynmt = self.translator_type.get() == "easynmt"
            
            # Обновляем состояние элементов
            for widget in source_frame.winfo_children():
                if isinstance(widget, ttk.Combobox):
                    widget.config(state="readonly" if is_translator_active else "disabled")
            
            for widget in target_frame.winfo_children():
                if isinstance(widget, ttk.Combobox):
                    widget.config(state="readonly" if is_translator_active else "disabled")
            
            for widget in m2m_frame.winfo_children():
                widget.config(state="normal" if is_m2m100 else "disabled")
                
            for widget in easynmt_model_frame.winfo_children():
                if isinstance(widget, ttk.Combobox):
                    widget.config(state="readonly" if is_easynmt else "disabled")
        
        # Привязываем функцию обновления к изменению переменной
        self.translator_type.trace_add("write", update_translator_options)
        
        # Инициализируем состояние элементов
        update_translator_options()
        
        # Переводчик комбобокс - описание
        translator_desc_frame = ttk.Frame(translation_frame)
        translator_desc_frame.pack(fill=tk.X, padx=5, pady=5)
        
        translator_desc = {
            "none": "Без перевода: отображение текста в исходном виде",
            "argos": "Argos Translate: легкий переводчик для работы офлайн (~100-200 МБ на языковую пару)",
            "m2m100": "M2M100: высококачественный переводчик от Meta AI (~1.8-5 ГБ, требует больше ресурсов)",
            "easynmt": "EasyNMT: универсальный переводчик с поддержкой различных моделей"
        }
        
        self.translator_desc_label = ttk.Label(translator_desc_frame, text=translator_desc[self.translator_type.get()], wraplength=500)
        self.translator_desc_label.pack(fill=tk.X, padx=5, pady=5)
        
        def update_desc(*args):
            self.translator_desc_label.config(text=translator_desc[self.translator_type.get()])
        
        self.translator_type.trace_add("write", update_desc)

        # Выбор устройства
        device_frame = ttk.LabelFrame(main_frame, text="Устройство ввода звука", padding=10)
        device_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Создаем виджет прокрутки для устройств
        device_canvas = tk.Canvas(device_frame, height=150)
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
        
        # Раздел зависимостей
        deps_frame = ttk.LabelFrame(main_frame, text="Зависимости", padding=10)
        deps_frame.pack(fill=tk.X, padx=5, pady=5)
        
        deps_text = (
            "Для работы переводчиков требуются дополнительные библиотеки:\n\n"
            "• Argos Translate: pip install argostranslate\n"
            "• M2M100: pip install torch transformers sentencepiece sacremoses\n"
            "• EasyNMT: pip install easynmt"
        )
        
        ttk.Label(deps_frame, text=deps_text, wraplength=550, justify="left").pack(fill=tk.X, padx=5, pady=5)
        
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
            "translator": {
                "type": self.translator_type.get(),
                "source_lang": self.source_lang.get(),
                "target_lang": self.target_lang.get(),
                "m2m_model_size": self.m2m_model_size.get(),
                "easynmt_model": self.easynmt_model.get()
            },
            "cancelled": False
        }
        self.root.destroy()
        
    def cancel(self):
        """Отменяет выбор и закрывает окно."""
        self.result["cancelled"] = True
        self.root.destroy()


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

        # Статусная строка
        self.status_frame = tk.Frame(main_container, height=30)
        self.status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_label = tk.Label(
            self.status_frame, 
            text="Готово",
            anchor=tk.W,
            padx=10,
            bg="#e0e0e0"
        )
        self.status_label.pack(fill=tk.X, side=tk.LEFT, expand=True)

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
                if text.startswith("STATUS:"):
                    # Обновляем статусную строку
                    self.status_label.config(text=text[7:])
                else:
                    # Обновляем субтитры
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

        return text_frame = ttk.LabelFrame(main_frame, text="Размер шрифта", padding=10)
        font_frame.pack(fill=tk.X, padx=5, pady=5)
        
        font