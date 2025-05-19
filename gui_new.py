"""Модуль с классами графического интерфейса для программы субтитров."""

import os
import tkinter as tk
from tkinter import ttk, messagebox, font, Menu, Toplevel, IntVar
from queue import Empty
from platform import system

from config import LANGUAGE_CODES, TRANSLATORS, gui_queue, stop_event
from utils import list_audio_devices, check_dependencies

# Добавим необходимые функции из detached.py (или можно импортировать их)
def emoji_img(size, emoji, dark=False):
    """Создает изображение из эмодзи."""
    # Заглушка для эмодзи, можно реализовать при необходимости
    return None

def beep():
    """Воспроизводит звуковой сигнал."""
    # Заглушка для звукового сигнала, можно реализовать при необходимости
    pass

class DraggableHtmlLabel(tk.Text):
    """Текстовое поле с возможностью перетаскивания."""

    def __init__(self, parent, root, **kwargs):
        tk.Text.__init__(self, parent, **kwargs)
        self.root = root
        self._offsetx = 0
        self._offsety = 0
        self.bind("<Button-1>", self.click)
        self.bind("<B1-Motion>", self.drag)

    def click(self, event):
        """Реакция на клик."""
        self._offsetx = event.x_root - self.root.winfo_x()
        self._offsety = event.y_root - self.root.winfo_y()

    def drag(self, event):
        """Перетаскивание окна."""
        x = event.x_root - self._offsetx
        y = event.y_root - self._offsety
        self.root.geometry(f"+{x}+{y}")

class SubtitleWindow:
    """Отдельное окно для субтитров с дополнительными функциями."""

    def __init__(self, master, title, win_type="main", font_size=20):
        """
        Инициализация окна.

        Args:
            master: Родительское окно
            title: Заголовок окна
            win_type: Тип окна (main, tc - транскрипция, tl - перевод)
            font_size: Размер шрифта
        """
        dark = False  # Можно настроить в зависимости от темы
        self.close_emoji = emoji_img(16, "❌", dark)
        self.copy_emoji = emoji_img(16, "📋", dark)
        self.pin_emoji = emoji_img(16, "📌", dark)
        self.help_emoji = emoji_img(16, "❓", dark)
        self.title_emoji = emoji_img(16, "🪟", dark)
        self.up_emoji = emoji_img(16, "⬆️", dark)
        self.down_emoji = emoji_img(16, "⬇️", dark)

        self.master = master
        self.title = title
        self.root = Toplevel(master)
        self.root.title(title)
        self.root.geometry("800x300")  # Начальный размер
        self.root.minsize(200, 50)
        self.root.configure(background="#f5f5f5")

        # Сохраняем настройки и переменные
        self.win_type = win_type
        self.win_str = title
        self.x_menu = 0
        self.y_menu = 0
        self.cur_opac = 1.0
        self.always_on_top = IntVar()
        self.no_tooltip = IntVar()
        self.no_title_bar = IntVar()
        self.click_through = IntVar()

        # Создаем текстовый виджет с возможностью перетаскивания
        self.lbl_text = DraggableHtmlLabel(self.root, self.root)
        self.lbl_text.configure(
            background="#f5f5f5",
            font=("Helvetica", font_size),
            wrap="word",
            cursor="hand2"
        )
        self.lbl_text.pack(side="top", fill="both", expand=True)

        # Добавляем скроллбар
        self.hidden_sb_y = ttk.Scrollbar(self.root, orient="vertical")
        self.hidden_sb_y.pack(side="right", fill="y")
        self.lbl_text.configure(yscrollcommand=self.hidden_sb_y.set)
        self.hidden_sb_y.configure(command=self.lbl_text.yview)

        # Создаем контекстное меню
        self._create_menu()

        # Привязываем обработчики событий
        self._setup_bindings()

        # Инициализируем настройки
        self._init_settings()

        # Вставим текст-заглушку
        self.lbl_text.insert("1.0", "Ожидание перевода...")

        # Показываем окно сразу при создании
        self.show()

    def _create_menu(self):
        """Создает контекстное меню для окна."""
        self.menu_dropdown = Menu(self.root, tearoff=0)
        self.menu_dropdown.add_command(label=self.title, command=self.open_menu,
                                      image=self.title_emoji, compound="left")
        self.menu_dropdown.add_command(label="Помощь", command=self.show_help,
                                      image=self.help_emoji, compound="left")
        self.menu_dropdown.add_command(
            label="Копировать",
            command=self.copy_tb_content,
            accelerator="Alt + C",
            image=self.copy_emoji,
            compound="left",
        )
        self.menu_dropdown.add_separator()
        self.menu_dropdown.add_checkbutton(
            label="Скрыть заголовок",
            command=lambda: self.toggle_title_bar(from_keybind=False),
            onvalue=1,
            offvalue=0,
            variable=self.no_title_bar,
            accelerator="Alt + T",
        )

        # Добавляем специфичные для Windows функции
        if system() == "Windows":
            self.menu_dropdown.add_checkbutton(
                label="Прозрачное окно",
                command=lambda: self.toggle_click_through(from_keybind=False),
                onvalue=1,
                offvalue=0,
                variable=self.click_through,
                accelerator="Alt + S",
            )

        self.menu_dropdown.add_checkbutton(
            label="Поверх других окон",
            command=lambda: self.toggle_always_on_top(from_keybind=False),
            onvalue=1,
            offvalue=0,
            variable=self.always_on_top,
            accelerator="Alt + O",
            image=self.pin_emoji,
            compound="right",
        )
        self.menu_dropdown.add_separator()
        self.menu_dropdown.add_command(
            label="Увеличить прозрачность на 0.1",
            command=self.increase_opacity,
            accelerator="Alt + Прокрутка вверх",
            image=self.up_emoji,
            compound="left",
        )
        self.menu_dropdown.add_command(
            label="Уменьшить прозрачность на 0.1",
            command=self.decrease_opacity,
            accelerator="Alt + Прокрутка вниз",
            image=self.down_emoji,
            compound="left",
        )
        self.menu_dropdown.add_separator()
        self.menu_dropdown.add_command(label="Закрыть", command=self.on_closing,
                                      image=self.close_emoji, compound="left")

    def _setup_bindings(self):
        """Настраивает привязки клавиш и других событий."""
        # Обработка закрытия окна
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Привязка для контекстного меню
        self.root.bind("<Button-3>", self.open_menu)

        # Привязки клавиш
        if system() == "Windows":
            self.root.bind("<Alt-KeyPress-s>", lambda event: self.toggle_click_through())
        self.root.bind("<Alt-KeyPress-c>", lambda event: self.copy_tb_content())
        self.root.bind("<Alt-KeyPress-t>", lambda event: self.toggle_title_bar())
        self.root.bind("<Alt-KeyPress-o>", lambda event: self.toggle_always_on_top())
        self.root.bind("<Alt-MouseWheel>", self.change_opacity)

    def _init_settings(self):
        """Инициализирует настройки окна."""
        # Установка начальных значений
        self.always_on_top.set(1)  # По умолчанию поверх других окон
        self.toggle_always_on_top(from_keybind=False, on_init=True)

        self.no_title_bar.set(0)  # По умолчанию с заголовком
        self.toggle_title_bar(from_keybind=False, on_init=True)

        if system() == "Windows":
            self.click_through.set(0)  # По умолчанию без прозрачности
            self.toggle_click_through(from_keybind=False, on_init=True)

    def open_menu(self, event=None):
        """Открывает контекстное меню."""
        if event:
            self.x_menu = event.x_root
            self.y_menu = event.y_root
            self.menu_dropdown.post(event.x_root, event.y_root)
        else:
            self.menu_dropdown.post(self.x_menu, self.y_menu)

    def show_help(self):
        """Показывает справку."""
        extra = "- Alt + s для переключения режима прозрачности\n" if system() == "Windows" else ""

        messagebox.showinfo(
            f"{self.title} - Справка",
            "Это окно показывает результат перевода речи в отдельном окне.\n\n"
            "Сочетания клавиш:\n"
            "- Alt + прокрутка для изменения прозрачности\n"
            "- Alt + c для копирования текста\n"
            "- Alt + t для скрытия/отображения заголовка\n"
            f"{extra}"
            "- Alt + o для переключения режима 'поверх окон'\n\n"
            "Для завершения работы закройте это окно правой кнопкой мыши -> Закрыть"
        )

    def toggle_title_bar(self, from_keybind=True, on_init=False):
        """Переключает отображение заголовка окна."""
        if from_keybind:
            self.no_title_bar.set(0 if self.no_title_bar.get() == 1 else 1)

        if not on_init:
            beep()

        self.root.overrideredirect(True if self.no_title_bar.get() == 1 else False)

    def toggle_click_through(self, from_keybind=True, on_init=False):
        """Переключает режим прозрачности. Только для Windows."""
        if system() != "Windows":
            return

        if from_keybind:
            self.click_through.set(0 if self.click_through.get() == 1 else 1)

        if not on_init:
            beep()

        if self.click_through.get() == 1:
            self.root.wm_attributes("-transparentcolor", "#f5f5f5")
        else:
            self.root.wm_attributes("-transparentcolor", "")

    def toggle_always_on_top(self, from_keybind=True, on_init=False):
        """Переключает режим 'поверх окон'."""
        if from_keybind:
            self.always_on_top.set(0 if self.always_on_top.get() == 1 else 1)

        if not on_init:
            beep()

        self.root.wm_attributes("-topmost", True if self.always_on_top.get() == 1 else False)

    def show(self):
        """Отображает окно."""
        self.root.wm_deiconify()
        self.root.attributes("-alpha", 1)

        # Располагаем окно в центре экрана
        self.center_window()

        # Отключаем режим прозрачности при показе
        if system() == "Windows" and self.click_through.get() == 1:
            self.click_through.set(0)
            self.root.wm_attributes("-transparentcolor", "")

    def center_window(self):
        """Центрирует окно на экране."""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def on_closing(self):
        """Обрабатывает закрытие окна."""
        # Закрываем всё приложение при закрытии окна перевода
        if messagebox.askokcancel("Выход", "Вы уверены, что хотите выйти?"):
            # Останавливаем обработку аудио
            if stop_event:
                stop_event.set()

            # Останавливаем выполнение программы
            print("Завершение работы...")
            self.master.quit()
            self.master.destroy()
            # Принудительное завершение всех потоков
            os._exit(0)

    def increase_opacity(self):
        """Увеличивает прозрачность окна на 0.1."""
        self.cur_opac += 0.1
        if self.cur_opac > 1:
            self.cur_opac = 1
        self.root.attributes("-alpha", self.cur_opac)

    def decrease_opacity(self):
        """Уменьшает прозрачность окна на 0.1."""
        self.cur_opac -= 0.1
        if self.cur_opac < 0.1:
            self.cur_opac = 0.1
        self.root.attributes("-alpha", self.cur_opac)

    def change_opacity(self, event):
        """Изменяет прозрачность окна прокруткой."""
        if event.delta > 0:
            self.cur_opac += 0.1
        else:
            self.cur_opac -= 0.1

        if self.cur_opac > 1:
            self.cur_opac = 1
        elif self.cur_opac < 0.1:
            self.cur_opac = 0.1

        self.root.attributes("-alpha", self.cur_opac)

    def copy_tb_content(self):
        """Копирует содержимое текстового поля в буфер обмена."""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.lbl_text.get("1.0", "end"))

    def update_text(self, text):
        """Обновляет текст в окне."""
        self.lbl_text.delete("1.0", "end")
        self.lbl_text.insert("1.0", text)
        self.lbl_text.see("end")  # Прокручиваем к концу


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
        self.font_size = tk.IntVar(value=20)
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
            "font_size": 20,
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

        # Проверка зависимостей
        self.dependencies = check_dependencies()

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

        # Состояние M2M100
        m2m_status = "✅ Установлено" if self.dependencies["m2m100"] else "❌ Не установлено"
        ttk.Label(m2m_frame, text=f"Статус: {m2m_status}", foreground="green" if self.dependencies["m2m100"] else "red").pack(anchor=tk.W, padx=5, pady=2)

        # Дополнительные настройки для EasyNMT
        easynmt_frame = ttk.LabelFrame(translation_frame, text="Настройки EasyNMT")
        easynmt_frame.pack(fill=tk.X, padx=5, pady=5)

        easynmt_model_frame = ttk.Frame(easynmt_frame)
        easynmt_model_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(easynmt_model_frame, text="Модель:").pack(side=tk.LEFT, padx=(0, 10))
        easynmt_combo = ttk.Combobox(easynmt_model_frame, textvariable=self.easynmt_model, state="readonly")
        easynmt_combo['values'] = ["opus-mt", "m2m_100_418M", "m2m_100_1.2B", "mbart50_m2m"]
        easynmt_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Состояние EasyNMT
        easynmt_status = "✅ Установлено" if self.dependencies["easynmt"] else "❌ Не установлено"
        ttk.Label(easynmt_frame, text=f"Статус: {easynmt_status}", foreground="green" if self.dependencies["easynmt"] else "red").pack(anchor=tk.W, padx=5, pady=2)

        # Состояние Argos
        argos_frame = ttk.LabelFrame(translation_frame, text="Argos Translate")
        argos_frame.pack(fill=tk.X, padx=5, pady=5)

        argos_status = "✅ Установлено" if self.dependencies["argos"] else "❌ Не установлено"
        ttk.Label(argos_frame, text=f"Статус: {argos_status}", foreground="green" if self.dependencies["argos"] else "red").pack(anchor=tk.W, padx=5, pady=2)

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
                if isinstance(widget, ttk.Radiobutton):
                    widget.config(state="normal" if is_m2m100 else "disabled")

            for widget in easynmt_model_frame.winfo_children():
                if isinstance(widget, ttk.Combobox):
                    widget.config(state="readonly" if is_easynmt else "disabled")

            # Проверяем зависимости и обновляем предупреждение
            translator_deps_status = ""
            if self.translator_type.get() == "argos" and not self.dependencies["argos"]:
                translator_deps_status = "⚠️ Argos Translate не установлен. Установите: pip install argostranslate"
            elif self.translator_type.get() == "m2m100" and not self.dependencies["m2m100"]:
                translator_deps_status = "⚠️ M2M100 требует дополнительных библиотек. Установите: pip install torch transformers sentencepiece sacremoses"
            elif self.translator_type.get() == "easynmt" and not self.dependencies["easynmt"]:
                translator_deps_status = "⚠️ EasyNMT не установлен. Установите: pip install easynmt"

            if translator_deps_status:
                self.translator_warning_label.config(text=translator_deps_status, foreground="red")
                self.translator_warning_label.pack(fill=tk.X, padx=5, pady=5)
            else:
                self.translator_warning_label.pack_forget()

        # Привязываем функцию обновления к изменению переменной
        self.translator_type.trace_add("write", update_translator_options)

        # Предупреждение о зависимостях
        self.translator_warning_label = ttk.Label(translation_frame, text="", wraplength=550)

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
        self.font_size_label = ttk.Label(font_preview_frame, text="20")
        self.font_size_label.pack(side=tk.LEFT)

        # Предпросмотр текста
        self.preview_text = tk.Label(
            font_frame,
            text="Пример текста",
            font=("Helvetica", 20),
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

        # Инициализация состояния элементов
        update_translator_options()

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

    def __init__(self, root, font_size=20):
        """Инициализация GUI.

        Args:
            root: Корневой элемент Tkinter
            font_size: Размер шрифта для субтитров
        """
        self.root = root
        self.root.title("Субтитры в реальном времени")

        # Переменные для отслеживания состояния
        self.is_initialized = False
        self.font_size = font_size

        # Создаем окно перевода
        self.translation_window = SubtitleWindow(
            self.root,
            "Перевод",
            win_type="tl",
            font_size=font_size
        )

        # Скрываем главное окно
        root.withdraw()

        # Устанавливаем обработчик обновления
        self.update_interval = 100  # Интервал обновления в миллисекундах
        self.last_text = ""
        self.root.after(self.update_interval, self.update_gui)

        # После инициализации считаем, что настройка выполнена
        self.is_initialized = True

        # Для отладки
        print("CaptionGUI инициализирован")

    def update_gui(self):
        """Обновляет GUI текстом из очереди."""
        try:
            while True:
                text = gui_queue.get_nowait()



                if text.startswith("STATUS:"):
                    # Игнорируем обновления статуса
                    pass
                elif text.startswith("TRANSLATION:"):
                    # Обновляем перевод
                    translation_text = text[12:]  # Убираем префикс
                    if translation_text != self.last_text:
                        if self.translation_window:
                            self.translation_window.update_text(translation_text)

                        self.last_text = translation_text
                else:
                    # Обрабатываем любой текст как перевод, если нет префикса
                    # (на случай, если текст перевода приходит без префикса)
                    if text != self.last_text:
                        if self.translation_window:
                            self.translation_window.update_text(text)

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
            if stop_event:
                stop_event.set()

            # Останавливаем выполнение программы
            print("Завершение работы...")
            self.root.quit()
            self.root.destroy()
            # Принудительное завершение всех потоков
            os._exit(0)