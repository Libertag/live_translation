"""Модуль переводчиков для программы субтитров."""

from config import gui_queue

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