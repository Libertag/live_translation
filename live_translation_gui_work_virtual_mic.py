"""Live captions from microphone using Moonshine and SileroVAD ONNX models with GUI.
Программа для создания субтитров в реальном времени с распознаванием речи и переводом."""

import argparse
import os
import time
import threading
from queue import Queue, Empty
import argostranslate.package
import argostranslate.translate

####### НАСТРОЙКИ ПЕРЕВОДА ##########
from_code = "en"  # Исходный язык (английский)
to_code = "ru"    # Язык перевода (русский)

# Загрузка и установка пакета Argos Translate для перевода
print("Downloading Argos Translate...")
argostranslate.package.update_package_index()
available_packages = argostranslate.package.get_available_packages()
package_to_install = next(
    filter(
        lambda x: x.from_code == from_code and x.to_code == to_code, available_packages
    )
)
argostranslate.package.install_from_path(package_to_install.download())
#####################################

import numpy as np
import sounddevice as sd  # Импортируем sounddevice полностью для доступа к функциям
from silero_vad import VADIterator, load_silero_vad
from sounddevice import InputStream

from moonshine_onnx import MoonshineOnnxModel, load_tokenizer

import tkinter as tk

SAMPLING_RATE = 16000  # Частота дискретизации звука (16 кГц)

CHUNK_SIZE = 512  # Размер блока данных для Silero VAD (требование при частоте 16000 Гц)
LOOKBACK_CHUNKS = 5  # Количество предыдущих блоков данных для анализа
MAX_LINE_LENGTH = 80  # Максимальная длина строки субтитров

# Параметры обновления субтитров - настройте в соответствии с производительностью вашей системы
MAX_SPEECH_SECS = 15     # Максимальная длительность речи для обработки за один раз
MIN_REFRESH_SECS = 0.2   # Минимальный интервал обновления субтитров


# Функция для получения списка доступных аудиоустройств
def list_audio_devices():
    """Выводит список доступных аудиоустройств."""
    print("\nДоступные аудиоустройства:")
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:  # Проверяем, что устройство поддерживает ввод
            print(f"ID: {i}, Название: {device['name']}")
    print()
    return devices


class Transcriber(object):
    """Класс для транскрипции речи с помощью модели Moonshine."""

    def __init__(self, model_name, rate=16000):
        """Инициализация транскрибера.

        Args:
            model_name: Название модели Moonshine
            rate: Частота дискретизации (должна быть 16000 Гц)
        """
        if rate != 16000:
            raise ValueError("Moonshine поддерживает только частоту дискретизации 16000 Гц.")
        self.model = MoonshineOnnxModel(model_name=model_name)
        self.rate = rate
        self.tokenizer = load_tokenizer()

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

        # Перевод распознанного текста
        text = argostranslate.translate.translate(text, from_code, to_code)

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

    def __init__(self, root):
        """Инициализация GUI.

        Args:
            root: Корневой элемент Tkinter
        """
        self.root = root
        self.root.title("Субтитры в реальном времени")

        # Настройки шрифта - ИЗМЕНИТЕ РАЗМЕР ЗДЕСЬ
        font_settings = ("Helvetica", 24)  # Название шрифта и размер (увеличьте по необходимости)

        # Добавление полосы прокрутки для текстового виджета
        self.text_frame = tk.Frame(self.root)
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
        )
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.text_widget.yview)

        self.update_interval = 100  # Интервал обновления в миллисекундах
        self.last_text = ""

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
        self.root.after(self.update_interval, self.update_gui)


def audio_processing():
    """Основная функция обработки аудио."""
    global transcribe
    parser = argparse.ArgumentParser(
        prog="live_captions",
        description="Демонстрация субтитров в реальном времени с моделями Moonshine",
    )
    parser.add_argument(
        "--model_name",
        help="Модель для запуска демонстрации",
        default="moonshine/base",
        choices=["moonshine/base", "moonshine/tiny"],
    )
    parser.add_argument(
        "--device",
        help="ID устройства ввода (используйте -1 для списка устройств)",
        type=int,
        default=0,  # По умолчанию используется устройство 0
    )
    args = parser.parse_args()
    model_name = args.model_name
    audio_device = args.device

    # Вывод списка аудиоустройств, если указан параметр -1
    if audio_device == -1:
        list_audio_devices()
        print("Запустите программу снова, указав нужный ID устройства с параметром --device")
        return

    print(f"Загрузка модели Moonshine '{model_name}' (с использованием ONNX runtime) ...")
    transcribe = Transcriber(model_name=model_name, rate=SAMPLING_RATE)

    # Загрузка и инициализация модели Silero VAD для определения голосовой активности
    vad_model = load_silero_vad(onnx=True)
    vad_iterator = VADIterator(
        model=vad_model,
        sampling_rate=SAMPLING_RATE,
        threshold=0.5,  # Порог определения речи
        min_silence_duration_ms=300,  # Минимальная длительность тишины для окончания фрагмента
    )

    q = Queue()

    # Вывод информации об используемом устройстве
    print(f"Использование устройства ввода с ID: {audio_device}")
    try:
        device_info = sd.query_devices(audio_device)
        print(f"Название устройства: {device_info['name']}")
    except:
        print("Не удалось получить информацию об устройстве")

    # Создание потока ввода звука с указанным устройством
    stream = InputStream(
        samplerate=SAMPLING_RATE,
        channels=1,
        blocksize=CHUNK_SIZE,
        dtype=np.float32,
        callback=create_input_callback(q),
        device=audio_device,  # Указываем ID устройства ввода
    )
    stream.start()

    caption_cache = []  # Кэш субтитров
    lookback_size = LOOKBACK_CHUNKS * CHUNK_SIZE  # Размер буфера предыдущих данных
    speech = np.empty(0, dtype=np.float32)  # Буфер речи

    recording = False  # Флаг записи

    print("Нажмите Ctrl+C для выхода из программы.\n")

    with stream:
        gui_queue.put("Готово к работе...")
        try:
            while True:
                chunk, status = q.get()  # Получение блока аудиоданных из очереди
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
        except KeyboardInterrupt:
            stream.close()

            # Обработка оставшихся данных при выходе
            if recording:
                while not q.empty():
                    chunk, _ = q.get()
                    speech = np.concatenate((speech, chunk))
                end_recording(speech, caption_cache, do_print=False)

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
            if caption_cache:
                print(f"Кэшированные субтитры.\n{' '.join(caption_cache)}")


if __name__ == "__main__":
    # Создание очереди для обмена данными между потоками аудио и GUI
    gui_queue = Queue()

    # Запуск потока обработки аудио
    audio_thread = threading.Thread(target=audio_processing)
    audio_thread.start()

    # Создание GUI
    root = tk.Tk()
    gui = CaptionGUI(root)
    root.after(100, gui.update_gui)  # Запуск цикла обновления GUI
    root.mainloop()
