# Транскриптор речи с переводом

Приложение для создания субтитров речи в реальном времени с использованием микрофона, моделей Moonshine и SileroVAD с графическим интерфейсом и несколькими вариантами перевода.

## Особенности

- Распознавание речи на русском и английском языках
- Несколько вариантов переводчиков:
  - Без перевода
  - Argos Translate (легкий, офлайн)
  - M2M100 (высокое качество)
  - NLLB-200 (Meta, поддержка 200+ языков)
  - SMaLL-100 (компактная модель)
  - PyMarian: MarianMT (быстрый перевод)
  - API: GPT-4o (требуется API ключ)
  - API: Claude 3.5 Sonnet (требуется API ключ)
  - EasyNMT (универсальный)
- Графический интерфейс с настраиваемым размером шрифта
- Обнаружение голосовой активности
- Работа в реальном времени

## Структура проекта

```
project/
├── main.py              # Основной файл запуска программы
├── config.py            # Конфигурации и глобальные настройки
├── audio.py             # Функции обработки аудио
├── transcriber.py       # Класс для транскрипции речи
├── translators.py       # Классы переводчиков
├── gui.py               # Графический интерфейс
├── utils.py             # Вспомогательные функции
└── requirements.txt     # Зависимости проекта
```

## Требования

- Python 3.7+
- NumPy
- SoundDevice
- Silero VAD
- Moonshine ONNX
- Tkinter

Дополнительные требования для переводчиков:
- Argos Translate: `pip install argostranslate`
- M2M100/NLLB-200/SMaLL-100: `pip install torch transformers sentencepiece sacremoses`
- PyMarian: `pip install torch transformers`
- EasyNMT: `pip install easynmt`
- GPT-4o: `pip install openai>=1.0.0`
- Claude 3.5 Sonnet: `pip install anthropic`

## Установка

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/yourusername/speech-transcription-app.git
   cd speech-transcription-app
   ```

2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Установите дополнительные зависимости для нужных переводчиков:
   ```bash
   # Для Argos Translate
   pip install argostranslate

   # Для M2M100, NLLB-200, SMaLL-100
   pip install torch transformers sentencepiece sacremoses

   # Для PyMarian
   pip install torch transformers

   # Для EasyNMT
   pip install easynmt

   # Для GPT-4o
   pip install openai>=1.0.0

   # Для Claude 3.5 Sonnet
   pip install anthropic
   ```

## Использование

Запустите приложение:
```bash
python main.py
```

1. В диалоговом окне настроек выберите:
   - Устройство ввода звука
   - Модель распознавания (Base или Tiny)
   - Настройки перевода
   - Размер шрифта

2. Для работы с API моделями (GPT-4o, Claude 3.5 Sonnet):
   - Введите API ключ в соответствующее поле
   - Нажмите "Сохранить API ключи"
   - API ключи сохраняются локально и используются при последующих запусках

3. Нажмите "Запустить" для начала работы.

4. Говорите в микрофон, и ваша речь будет автоматически преобразована в текст.

5. Нажмите "Выход" в главном окне, чтобы завершить программу.

## Возможные проблемы

- Если не удается инициализировать аудиоустройство, проверьте, что оно подключено и доступно в системе.
- Для работы переводчиков требуются дополнительные библиотеки, убедитесь, что они установлены.
- Модели перевода M2M100 и NLLB-200 требуют значительного объема памяти, особенно на CPU.
- API переводчики (GPT-4o, Claude 3.5 Sonnet) требуют доступа к интернету и валидного API ключа.

## Лицензия

MIT
