"""Live captions from microphone using Moonshine and SileroVAD ONNX models with GUI and multiple translator options."""

import threading
from queue import Queue
import tkinter as tk
import os
import sys

# Инициализируем глобальные переменные перед импортом других модулей
import config
config.gui_queue = Queue()
config.stop_event = threading.Event()

# Теперь импортируем модули, использующие эти переменные
from gui_new import SettingsDialog, CaptionGUI
from audio import audio_processing


def main():
    """Основная функция программы."""
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
    translator_settings = settings_dialog.result["translator"]

    # Проверяем наличие необходимых зависимостей для выбранного переводчика
    from utils import check_dependencies
    translator_type = translator_settings["type"]
    if translator_type != "none":
        deps = check_dependencies()
        if translator_type == "argos" and not deps["argos"]:
            from tkinter import messagebox
            messagebox.showwarning(
                "Отсутствуют зависимости",
                "Для Argos Translate требуется установить: pip install argostranslate"
            )
        elif translator_type == "m2m100" and not deps["m2m100"]:
            from tkinter import messagebox
            messagebox.showwarning(
                "Отсутствуют зависимости",
                "Для M2M100 требуется установить: pip install torch transformers sentencepiece sacremoses"
            )
        elif translator_type == "easynmt" and not deps["easynmt"]:
            from tkinter import messagebox
            messagebox.showwarning(
                "Отсутствуют зависимости",
                "Для EasyNMT требуется установить: pip install easynmt"
            )

    # Запуск потока обработки аудио
    audio_thread = threading.Thread(
        target=audio_processing,
        args=(device_id, model_name, translator_settings),
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