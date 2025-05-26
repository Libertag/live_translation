"""Модуль переводчиков для программы субтитров."""

from config import gui_queue
import os
import json
import time

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
            gui_queue.put(f"STATUS: Инициализация Argos Translate ({source_lang} -> {target_lang})...")

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
            gui_queue.put("STATUS: Argos Translate инициализирован!")

        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации Argos Translate: {str(e)}")
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
            gui_queue.put(f"STATUS: Инициализация переводчика M2M100 ({model_size})...")

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
                gui_queue.put("STATUS: Используется GPU (CUDA) для перевода")
                print("Используется GPU (CUDA) для перевода")
            else:
                self.device = torch.device("cpu")
                gui_queue.put("STATUS: Используется CPU для перевода")
                print("Используется CPU для перевода")

            gui_queue.put("STATUS: M2M100 инициализирован!")

        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации M2M100: {str(e)}")
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

    def close(self):
        """Освобождение ресурсов."""
        try:
            # Освобождаем память GPU если использовалась
            import torch
            if hasattr(self, 'model') and hasattr(self, 'device') and self.device.type == "cuda":
                # Удаляем модель из памяти GPU
                self.model = self.model.to('cpu')
                # Очищаем кэш CUDA
                torch.cuda.empty_cache()
        except Exception as e:
            print(f"Ошибка при освобождении ресурсов M2M100: {e}")


class NLLB200Translator(BaseTranslator):
    """Класс для перевода с использованием NLLB-200 от Meta."""

    def __init__(self, source_lang, target_lang, model_size="small"):
        """Инициализация переводчика NLLB-200.

        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
            model_size: Размер модели ('small' для 600M, 'medium' для 1.3B, 'large' для 3.3B)
        """
        super().__init__(source_lang, target_lang)
        self.name = f"NLLB-200 ({model_size})"

        # Словарь для преобразования стандартных кодов языков в коды NLLB
        self.lang_map = {
            "en": "eng_Latn",
            "ru": "rus_Cyrl",
            "fr": "fra_Latn",
            "de": "deu_Latn",
            "es": "spa_Latn",
            "it": "ita_Latn",
            "ja": "jpn_Jpan",
            "zh": "zho_Hans",
            "uk": "ukr_Cyrl",
            "pl": "pol_Latn",
            "cs": "ces_Latn",
            "nl": "nld_Latn",
            "pt": "por_Latn",
            "ar": "arb_Arab",
            "tr": "tur_Latn",
            "ko": "kor_Hang",
        }

        try:
            # Импортируем библиотеки только при создании объекта
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            print(f"Инициализация переводчика NLLB-200 ({model_size})...")
            gui_queue.put(f"STATUS: Инициализация переводчика NLLB-200 ({model_size})...")

            # Выбор модели в зависимости от размера
            if model_size == "small":
                model_name = "facebook/nllb-200-distilled-600M"
            elif model_size == "medium":
                model_name = "facebook/nllb-200-1.3B"
            else:  # large
                model_name = "facebook/nllb-200-3.3B"

            # Загрузка модели и токенизатора
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

            # Если доступно CUDA, используем GPU
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
                self.model = self.model.to(self.device)
                gui_queue.put("STATUS: Используется GPU (CUDA) для перевода")
                print("Используется GPU (CUDA) для перевода")
            else:
                self.device = torch.device("cpu")
                gui_queue.put("STATUS: Используется CPU для перевода")
                print("Используется CPU для перевода")

            gui_queue.put("STATUS: NLLB-200 инициализирован!")

        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации NLLB-200: {str(e)}")
            print(f"Ошибка при инициализации NLLB-200: {e}")
            raise e

    def _get_nllb_lang_code(self, lang_code):
        """Преобразует стандартный код языка в код для NLLB-200."""
        return self.lang_map.get(lang_code, lang_code)

    def translate(self, text):
        """Перевод текста с помощью NLLB-200.

        Args:
            text: Исходный текст для перевода

        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""

        try:
            # Преобразуем коды языков в формат NLLB
            source_lang_nllb = self._get_nllb_lang_code(self.source_lang)
            target_lang_nllb = self._get_nllb_lang_code(self.target_lang)

            # Токенизация текста
            encoded = self.tokenizer(text, return_tensors="pt")

            # Переносим тензоры на GPU, если доступно
            if self.device.type == "cuda":
                encoded = {k: v.to(self.device) for k, v in encoded.items()}

            # Генерация перевода
            generated_tokens = self.model.generate(
                **encoded,
                forced_bos_token_id=self.tokenizer.lang_code_to_id[target_lang_nllb],
                max_length=128
            )

            # Декодирование результата
            translated_text = self.tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
            return translated_text
        except Exception as e:
            print(f"Ошибка при переводе с NLLB-200: {e}")
            return text  # Возвращаем исходный текст в случае ошибки

    def close(self):
        """Освобождение ресурсов."""
        try:
            # Освобождаем память GPU если использовалась
            import torch
            if hasattr(self, 'model') and hasattr(self, 'device') and self.device.type == "cuda":
                # Удаляем модель из памяти GPU
                self.model = self.model.to('cpu')
                # Очищаем кэш CUDA
                torch.cuda.empty_cache()
        except Exception as e:
            print(f"Ошибка при освобождении ресурсов NLLB-200: {e}")


class SMaLL100Translator(BaseTranslator):
    """Класс для перевода с использованием SMaLL-100."""

    def __init__(self, source_lang, target_lang):
        """Инициализация переводчика SMaLL-100.

        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
        """
        super().__init__(source_lang, target_lang)
        self.name = "SMaLL-100"

        try:
            # Импортируем библиотеки только при создании объекта
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            print(f"Инициализация переводчика SMaLL-100...")
            gui_queue.put(f"STATUS: Инициализация переводчика SMaLL-100...")

            # Загрузка модели и токенизатора
            model_name = "facebook/small-100"
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

            # Если доступно CUDA, используем GPU
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
                self.model = self.model.to(self.device)
                gui_queue.put("STATUS: Используется GPU (CUDA) для перевода")
                print("Используется GPU (CUDA) для перевода")
            else:
                self.device = torch.device("cpu")
                gui_queue.put("STATUS: Используется CPU для перевода")
                print("Используется CPU для перевода")

            gui_queue.put("STATUS: SMaLL-100 инициализирован!")

        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации SMaLL-100: {str(e)}")
            print(f"Ошибка при инициализации SMaLL-100: {e}")
            raise e

    def translate(self, text):
        """Перевод текста с помощью SMaLL-100.

        Args:
            text: Исходный текст для перевода

        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""

        try:
            # Токенизация текста с указанием языков
            inputs = self.tokenizer(
                f"{self.source_lang}: {text}",
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512
            )

            # Переносим тензоры на GPU, если доступно
            if self.device.type == "cuda":
                inputs = {k: v.to(self.device) for k, v in inputs.items()}

            # Генерация перевода
            outputs = self.model.generate(
                **inputs,
                decoder_start_token_id=self.tokenizer.lang_code_to_id[self.target_lang],
                max_length=512,
                num_beams=5,
                early_stopping=True
            )

            # Декодирование результата
            translated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

            # Удаляем префикс целевого языка, если он есть
            if translated_text.startswith(f"{self.target_lang}: "):
                translated_text = translated_text[len(f"{self.target_lang}: "):]

            return translated_text
        except Exception as e:
            print(f"Ошибка при переводе с SMaLL-100: {e}")
            return text  # Возвращаем исходный текст в случае ошибки

    def close(self):
        """Освобождение ресурсов."""
        try:
            # Освобождаем память GPU если использовалась
            import torch
            if hasattr(self, 'model') and hasattr(self, 'device') and self.device.type == "cuda":
                # Удаляем модель из памяти GPU
                self.model = self.model.to('cpu')
                # Очищаем кэш CUDA
                torch.cuda.empty_cache()
        except Exception as e:
            print(f"Ошибка при освобождении ресурсов SMaLL-100: {e}")


class PyMarianTranslator(BaseTranslator):
    """Класс для перевода с использованием PyMarian (MarianMT)."""

    def __init__(self, source_lang, target_lang):
        """Инициализация переводчика PyMarian.

        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
        """
        super().__init__(source_lang, target_lang)
        self.name = "PyMarian (MarianMT)"

        try:
            # Импортируем библиотеки только при создании объекта
            import torch
            from transformers import MarianMTModel, MarianTokenizer

            print(f"Инициализация переводчика PyMarian ({source_lang} -> {target_lang})...")
            gui_queue.put(f"STATUS: Инициализация переводчика PyMarian ({source_lang} -> {target_lang})...")

            # Формируем название модели в формате opus-mt-{source}-{target}
            model_name = f"Helsinki-NLP/opus-mt-{source_lang}-{target_lang}"

            # Для некоторых языковых пар может потребоваться специальное название модели
            if source_lang == "en" and target_lang == "ru":
                model_name = "Helsinki-NLP/opus-mt-en-ru"
            elif source_lang == "ru" and target_lang == "en":
                model_name = "Helsinki-NLP/opus-mt-ru-en"

            # Загрузка модели и токенизатора
            self.tokenizer = MarianTokenizer.from_pretrained(model_name)
            self.model = MarianMTModel.from_pretrained(model_name)

            # Если доступно CUDA, используем GPU
            if torch.cuda.is_available():
                self.device = torch.device("cuda")
                self.model = self.model.to(self.device)
                gui_queue.put("STATUS: Используется GPU (CUDA) для перевода")
                print("Используется GPU (CUDA) для перевода")
            else:
                self.device = torch.device("cpu")
                gui_queue.put("STATUS: Используется CPU для перевода")
                print("Используется CPU для перевода")

            gui_queue.put("STATUS: PyMarian инициализирован!")

        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации PyMarian: {str(e)}")
            print(f"Ошибка при инициализации PyMarian: {e}")
            raise e

    def translate(self, text):
        """Перевод текста с помощью PyMarian.

        Args:
            text: Исходный текст для перевода

        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""

        try:
            # Токенизация текста
            encoded = self.tokenizer(text, return_tensors="pt", padding=True)

            # Переносим тензоры на GPU, если доступно
            if self.device.type == "cuda":
                encoded = {k: v.to(self.device) for k, v in encoded.items()}

            # Генерация перевода
            generated_tokens = self.model.generate(**encoded)

            # Декодирование результата
            translated_text = self.tokenizer.decode(generated_tokens[0], skip_special_tokens=True)
            return translated_text
        except Exception as e:
            print(f"Ошибка при переводе с PyMarian: {e}")
            return text  # Возвращаем исходный текст в случае ошибки

    def close(self):
        """Освобождение ресурсов."""
        try:
            # Освобождаем память GPU если использовалась
            import torch
            if hasattr(self, 'model') and hasattr(self, 'device') and self.device.type == "cuda":
                # Удаляем модель из памяти GPU
                self.model = self.model.to('cpu')
                # Очищаем кэш CUDA
                torch.cuda.empty_cache()
        except Exception as e:
            print(f"Ошибка при освобождении ресурсов PyMarian: {e}")


class APITranslator(BaseTranslator):
    """Класс для перевода с использованием API моделей (GPT-4o, Claude 3.5 Sonnet)."""

    def __init__(self, source_lang, target_lang, model_name="gpt-4o", api_key=None, base_url=None):
        """Инициализация переводчика через API.

        Args:
            source_lang: Код исходного языка
            target_lang: Код целевого языка
            model_name: Название модели ('gpt-4o' или 'claude-3-5-sonnet')
            api_key: API ключ для доступа к модели
            base_url: Базовый URL для API (только для OpenAI)
        """
        super().__init__(source_lang, target_lang)
        self.model_name = model_name
        self.name = f"API ({model_name})"
        self.api_key = api_key
        self.base_url = base_url

        # Языки в человекочитаемом формате для подсказки
        self.lang_names = {
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

        try:
            config_dir = os.path.join(os.path.expanduser("~"), ".speech_translation")
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, "api_config.json")

            # Если API ключ не указан, пытаемся загрузить из файла
            if not self.api_key and os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    if model_name == "gpt-4o" and "openai_api_key" in config:
                        self.api_key = config["openai_api_key"]
                        self.base_url = config.get("openai_base_url")
                    elif model_name == "claude-3-5-sonnet" and "anthropic_api_key" in config:
                        self.api_key = config["anthropic_api_key"]

            # Если API ключ всё еще не указан, запрашиваем его
            if not self.api_key:
                gui_queue.put("STATUS: API ключ не найден. Установите ключ через настройки")
                raise ValueError(f"API ключ для {model_name} не указан")

            print(f"Инициализация переводчика через API ({model_name})...")
            gui_queue.put(f"STATUS: Инициализация переводчика через API ({model_name})...")

            # Проверяем наличие необходимых библиотек
            if model_name == "gpt-4o":
                import openai
                self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            elif model_name == "claude-3-5-sonnet":
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)

            gui_queue.put(f"STATUS: Переводчик через API ({model_name}) инициализирован!")

        except ImportError as e:
            error_msg = ""
            if model_name == "gpt-4o":
                error_msg = "Для работы с GPT-4o требуется установить: pip install openai"
            elif model_name == "claude-3-5-sonnet":
                error_msg = "Для работы с Claude 3.5 Sonnet требуется установить: pip install anthropic"

            gui_queue.put(f"STATUS: Ошибка импорта: {error_msg}")
            print(f"Ошибка импорта: {error_msg}")
            raise e
        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации API переводчика: {str(e)}")
            print(f"Ошибка при инициализации API переводчика: {e}")
            raise e

    def translate(self, text):
        """Перевод текста с помощью API модели.

        Args:
            text: Исходный текст для перевода

        Returns:
            str: Переведенный текст
        """
        if not text.strip():
            return ""

        source_lang_name = self.lang_names.get(self.source_lang, self.source_lang)
        target_lang_name = self.lang_names.get(self.target_lang, self.target_lang)

        try:
            # Составляем запрос в зависимости от модели
            if self.model_name == "gpt-4o":
                prompt = f"Translate the following text from {source_lang_name} to {target_lang_name}. Return only the translated text without any additional comments or explanations:\n\n{text}"

                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1024
                )

                translated_text = response.choices[0].message.content.strip()

            elif self.model_name == "claude-3-5-sonnet":
                import anthropic

                prompt = f"Translate the following text from {source_lang_name} to {target_lang_name}. Return only the translated text without any additional comments or explanations:\n\n{text}"

                response = self.client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1024
                )

                translated_text = response.content[0].text

            return translated_text

        except Exception as e:
            print(f"Ошибка при переводе через API ({self.model_name}): {e}")
            # Добавляем задержку, чтобы избежать слишком частых запросов при ошибках
            time.sleep(1)
            return text  # Возвращаем исходный текст в случае ошибки

    @staticmethod
    def save_api_keys(openai_api_key=None, openai_base_url=None, anthropic_api_key=None):
        """Сохраняет API ключи в конфигурационный файл.

        Args:
            openai_api_key: API ключ для OpenAI
            openai_base_url: Базовый URL для OpenAI API
            anthropic_api_key: API ключ для Anthropic
        """
        config_dir = os.path.join(os.path.expanduser("~"), ".speech_translation")
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, "api_config.json")

        # Загружаем существующую конфигурацию, если она есть
        config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
            except:
                pass

        # Обновляем только переданные значения
        if openai_api_key:
            config["openai_api_key"] = openai_api_key
        if openai_base_url:
            config["openai_base_url"] = openai_base_url
        if anthropic_api_key:
            config["anthropic_api_key"] = anthropic_api_key

        # Сохраняем конфигурацию
        with open(config_file, 'w') as f:
            json.dump(config, f)


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
        self.model_name = model_name

        try:
            # Импортируем библиотеку только при создании объекта
            from easynmt import EasyNMT

            print(f"Инициализация EasyNMT с моделью {model_name}...")
            gui_queue.put(f"STATUS: Инициализация EasyNMT с моделью {model_name}...")

            # Загрузка модели
            self.model = EasyNMT(model_name)

            gui_queue.put("STATUS: EasyNMT инициализирован!")

        except Exception as e:
            gui_queue.put(f"STATUS: Ошибка при инициализации EasyNMT: {str(e)}")
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

    def close(self):
        """Освобождение ресурсов."""
        try:
            # Освобождаем память GPU если использовалась
            import torch
            if hasattr(self, 'model') and 'm2m_100' in self.model_name and torch.cuda.is_available():
                # Очищаем кэш CUDA
                torch.cuda.empty_cache()
        except Exception as e:
            print(f"Ошибка при освобождении ресурсов EasyNMT: {e}")


def create_translator(translator_type, source_lang, target_lang, model_size="small", easynmt_model="opus-mt",
                     api_key=None, base_url=None):
    """Создает объект переводчика нужного типа.

    Args:
        translator_type: Тип переводчика ('none', 'argos', 'm2m100', 'nllb200', 'small100', 'pymarian', 'gpt4o', 'claude', 'easynmt')
        source_lang: Код исходного языка
        target_lang: Код целевого языка
        model_size: Размер модели для M2M100 и NLLB200
        easynmt_model: Название модели для EasyNMT
        api_key: API ключ для API моделей
        base_url: Базовый URL для API OpenAI

    Returns:
        BaseTranslator: Объект переводчика
    """
    if translator_type == "none":
        return NoTranslator(source_lang, target_lang)
    elif translator_type == "argos":
        return ArgosTranslator(source_lang, target_lang)
    elif translator_type == "m2m100":
        return M2M100Translator(source_lang, target_lang, model_size)
    elif translator_type == "nllb200":
        return NLLB200Translator(source_lang, target_lang, model_size)
    elif translator_type == "small100":
        return SMaLL100Translator(source_lang, target_lang)
    elif translator_type == "pymarian":
        return PyMarianTranslator(source_lang, target_lang)
    elif translator_type == "gpt4o":
        return APITranslator(source_lang, target_lang, "gpt-4o", api_key, base_url)
    elif translator_type == "claude":
        return APITranslator(source_lang, target_lang, "claude-3-5-sonnet", api_key)
    elif translator_type == "easynmt":
        return EasyNMTTranslator(source_lang, target_lang, easynmt_model)
    else:
        raise ValueError(f"Неизвестный тип переводчика: {translator_type}")
