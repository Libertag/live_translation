"""Модуль для транскрипции речи с помощью модели Moonshine."""

import time
import numpy as np
from moonshine_onnx import MoonshineOnnxModel, load_tokenizer


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