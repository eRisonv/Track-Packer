import os
import sys
import re
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from tkinterdnd2 import TkinterDnD, DND_FILES
import winreg
import ctypes
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

def resource_path(relative_path):
    """ Получает корректный путь для ресурсов в exe и dev режиме """
    if hasattr(sys, '_MEIPASS'):
        # В скомпилированном виде используем директорию PyInstaller
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # В режиме разработки используем директорию скрипта
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, relative_path)
    
def save_to_registry(key_name, value):
    try:
        reg_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\MergeApp")
        winreg.SetValueEx(reg_key, key_name, 0, winreg.REG_DWORD, value)
        winreg.CloseKey(reg_key)
    except Exception as e:
        print(f"Ошибка при сохранении в реестр: {e}")

def load_from_registry(key_name, default_value):
    try:
        reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\MergeApp")
        value, _ = winreg.QueryValueEx(reg_key, key_name)
        winreg.CloseKey(reg_key)
        return value
    except FileNotFoundError:
        return default_value
    except Exception as e:
        print(f"Ошибка при загрузке из реестра: {e}")
        return default_value

def minimize_console():
    """Сворачивает консольное окно"""
    kernel32 = ctypes.WinDLL('kernel32')
    user32 = ctypes.WinDLL('user32')
    hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 6)

video_ext = ['.flv', '.mp4', '.avi', '.mov', '.mkv', '.m4v']
audio_ext = ['.mp3', '.wav', '.flac']

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip = None
        self.delay = 1000  # Задержка в миллисекундах (2 секунды)
        self.timer_id = None
        self.widget.bind("<Enter>", self.schedule_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def schedule_tooltip(self, event=None):
        """Запланировать показ тултипа через указанное время."""
        self.timer_id = self.widget.after(self.delay, self.show_tooltip)

    def show_tooltip(self, event=None):
        """Показать тултип."""
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")

        label = tk.Label(self.tooltip, text=self.text, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()

    def hide_tooltip(self, event=None):
        """Скрыть тултип и отменить запланированный показ."""
        if self.timer_id:
            self.widget.after_cancel(self.timer_id)
            self.timer_id = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

class MergeApp(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.version = "1.010"
        self.title(f"Track-Packer - [{self.version}]")
        self.animation_phases = ['⏳', '⌛']
        self.animation_index = 0
        self.after_id = None
        minimize_console()
        self.title("Track-Packer")
        self.geometry("370x520")
        self.minsize(370, 520)
        
        # Центрируем окно
        self.attributes('-topmost', 1)
        self.after(2000, lambda: self.attributes('-topmost', 0))
        self.center_window()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.status = tk.StringVar()
        self.progress = tk.DoubleVar()
        self.file_pairs = {}
        self.created_files = []
        self.skipped_files = []
        self.orig_volume = tk.DoubleVar(value=load_from_registry("orig_volume", 5))
        self.new_volume = tk.DoubleVar(value=load_from_registry("new_volume", 100))
        self.remove_source = tk.BooleanVar(value=False)
        self.invert_tracks = tk.BooleanVar(value=False)
        self.is_processing = False
        self.backup_files = tk.BooleanVar(value=True)
        self.file_status = {}

        self.create_widgets()
        self.setup_volume_labels()
        self.setup_dnd()

    def start_animation(self):
        """Запускает анимацию статуса обработки с эффектом пересыпания песка"""
        if self.is_processing:
            # Фазы анимации с фиксированной длиной (дополнены пробелами)
            self.animation_phases = ['⏳', '⏳', '⏳', '⌛', '⌛', '⌛']
            self.animation_index = 0
            if not hasattr(self, 'after_id') or self.after_id is None:
                self.update_animation()

    def update_animation(self):
        """Обновляет анимацию для элементов в статусе processing с эффектом пересыпания"""
        if not self.is_processing:
            if hasattr(self, 'after_id') and self.after_id:
                self.after_cancel(self.after_id)
                self.after_id = None
            return

        # Проходим по всем элементам в дереве
        for item in self.tree.get_children():
            if self.tree.item(item, 'tags')[0] == 'processing':
                values = self.tree.item(item, 'values')
                # Обновляем символ анимации с фиксированной длиной
                new_symbol = self.animation_phases[self.animation_index]
                new_values = (new_symbol, values[1], values[2])
                self.tree.item(item, values=new_values)

        # Переходим к следующей фазе анимации
        self.animation_index = (self.animation_index + 1) % len(self.animation_phases)
        self.after_id = self.after(300, self.update_animation)
            
    def setup_dnd(self):
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.on_drop)
 
    def _show_track_details(self):
        """
        Показывает диалог с детальной информацией о распознанных аудиодорожках
        """
        details_window = tk.Toplevel(self)
        details_window.title("Детали аудиодорожек")
        details_window.geometry("600x400")
        details_window.grab_set()  # Модальное окно
        
        # Заголовок
        ttk.Label(details_window, text="Распознанные аудиодорожки в файлах", 
                 font=('Arial', 12, 'bold')).pack(pady=10)
        
        # Текстовое поле с информацией
        text_area = tk.Text(details_window, wrap=tk.WORD, width=70, height=15)
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Полоса прокрутки
        scrollbar = ttk.Scrollbar(text_area, command=text_area.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_area.config(yscrollcommand=scrollbar.set)
        
        # Вставляем информацию о дорожках
        for base, pair in self.file_pairs.items():
            if pair.get('video') and pair.get('track_info'):
                video_name = os.path.basename(pair['video'])
                text_area.insert(tk.END, f"\nФайл: {video_name}\n", "header")
                
                for track in pair.get('track_info', []):
                    language = track.get('language', 'неизвестно').upper()
                    index = track.get('track_index', -1)
                    info = track.get('full_info', '')
                    
                    # Определяем роль дорожки
                    role = ""
                    if language == "ENG":
                        role = "(оригинал)"
                    elif language == "RUS":
                        role = "(перевод)"
                    
                    text_area.insert(tk.END, f"  Дорожка #{index}: {language} {role}\n")
                    text_area.insert(tk.END, f"    {info}\n", "info")
        
        # Стили текста
        text_area.tag_configure("header", font=('Arial', 10, 'bold'))
        text_area.tag_configure("info", foreground="gray")
        
        text_area.config(state=tk.DISABLED)  # Только для чтения
        
        # Кнопка закрытия
        ttk.Button(details_window, text="ОК", command=details_window.destroy).pack(pady=10)
 
    def center_window(self):
        """Размещает окно по центру экрана."""
        self.update_idletasks()  # Обновляем геометрию окна
        width = self.winfo_width()  # Ширина окна
        height = self.winfo_height()  # Высота окна
        screen_width = self.winfo_screenwidth()  # Ширина экрана
        screen_height = self.winfo_screenheight()  # Высота экрана

        # Вычисляем координаты для размещения окна по центру
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)

        # Устанавливаем положение окна
        self.geometry(f"+{x}+{y}")
 
    def on_enter_merge_button(self, event):
        """Обработчик наведения курсора на кнопку 'Склеить'."""
        self.merge_button.config(bg="#45a049")  # Изменяем цвет фона на более темный зеленый

    def on_leave_merge_button(self, event):
        """Обработчик ухода курсора с кнопки 'Склеить'."""
        self.merge_button.config(bg="#4CAF50")  # Возвращаем исходный цвет фона
 
    def create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=2)
        main_frame.grid_rowconfigure(6, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # Область перетаскивания
        self.drop_area = tk.Canvas(main_frame, bg="#e8f4ff", bd=2, relief=tk.RIDGE, height=100)
        self.drop_area.grid(row=0, column=0, sticky="nsew", pady=2)
        self.drop_area.bind("<Configure>", self.update_drop_area_text)
        self.drop_area.bind("<Button-1>", self.on_click)

        # Таблица файлов
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=1, column=0, sticky="nsew", pady=2)
        file_frame.grid_columnconfigure(0, weight=1)
        file_frame.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(file_frame, columns=('status', 'video', 'audio'), show='headings')
        self.tree.heading('status', text='Статус', anchor=tk.CENTER)
        self.tree.heading('video', text='Видео')
        self.tree.heading('audio', text='Аудио')
        self.tree.column('status', width=70, anchor=tk.CENTER, stretch=False)
        self.tree.column('video', width=100)
        self.tree.column('audio', width=100)

        vsb = ttk.Scrollbar(file_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(file_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Панель для кнопок
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, sticky="ew", pady=2)

        invert_checkbox = ttk.Checkbutton(button_frame, text="Инвертировать дорожки",
                                          variable=self.invert_tracks)
        invert_checkbox.pack(side=tk.LEFT, padx=5)
        ToolTip(invert_checkbox, "Попробуй, если вдруг глушится не та дорожка.\nРаботает только с внутренними дорожками.")

        self.clear_button = ttk.Button(button_frame, text="Очистить список",
                                      command=self.clear_list)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        self.merge_button = tk.Button(button_frame, text="Склеить", bg="#4CAF50", fg="white",
                                     command=self.process_files, relief=tk.FLAT, cursor="hand2")
        self.merge_button.pack(side=tk.RIGHT, padx=5)
        self.merge_button.bind("<Enter>", self.on_enter_merge_button)
        self.merge_button.bind("<Leave>", self.on_leave_merge_button)

        # Настройки громкости
        volume_frame = ttk.Frame(main_frame)
        volume_frame.grid(row=3, column=0, sticky="ew", pady=2)
        
        self.orig_frame = ttk.Frame(volume_frame)
        self.orig_frame.grid(row=0, column=0, sticky="ew")
        self.orig_frame.columnconfigure(1, weight=1)
        ttk.Label(self.orig_frame, text="Eng Volume:").grid(row=0, column=0, sticky='w')
        ttk.Scale(self.orig_frame, variable=self.orig_volume, from_=1, to=100,
                  command=lambda v: self.update_volume_labels()).grid(row=0, column=1, sticky='ew', padx=5)
        self.orig_label = tk.Label(self.orig_frame, text="5%", width=5)
        self.orig_label.grid(row=0, column=2, padx=5, sticky='e')

        self.new_frame = ttk.Frame(volume_frame)
        self.new_frame.grid(row=1, column=0, sticky="ew")
        self.new_frame.columnconfigure(1, weight=1)
        ttk.Label(self.new_frame, text="Rus Volume:").grid(row=0, column=0, sticky='w')
        ttk.Scale(self.new_frame, variable=self.new_volume, from_=1, to=100,
                  command=lambda v: self.update_volume_labels()).grid(row=0, column=1, sticky='ew', padx=5)
        self.new_label = tk.Label(self.new_frame, text="100%", width=5)
        self.new_label.grid(row=0, column=2, padx=5, sticky='e')

        # Статус-бар (уменьшен отступ от ползунков)
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=4, column=0, sticky="ew", pady=(2, 1))  # Уменьшил нижний pady до 1
        status_frame.columnconfigure(0, weight=1)

        self.done_label = ttk.Label(status_frame, text="", anchor="center")
        self.done_label.grid(row=0, column=0, sticky="ew")

        self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress, length=300)
        self.progress_bar.grid(row=1, column=0, sticky="ew")

        style = ttk.Style()
        bg_color = style.lookup('TFrame', 'background')
        self.progress_label = tk.Label(
            status_frame, 
            text="", 
            anchor="center", 
            bg=bg_color, 
            fg="black", 
            borderwidth=0, 
            highlightthickness=0
        )
        self.progress_label.place(in_=self.progress_bar, relx=0.5, rely=0.5, anchor="center")


        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.grid(row=5, column=0, sticky="ew", pady=1)
        

        ttk.Checkbutton(bottom_frame, text="Backup", variable=self.backup_files).pack(side=tk.LEFT, padx=5) 
        version_label = ttk.Label(bottom_frame, text=f"Version: {self.version}", anchor="e")
        version_label.pack(side=tk.RIGHT, padx=5)

        self.tree.tag_configure('pending', foreground='gray')
        self.tree.tag_configure('processing', foreground='orange')
        self.tree.tag_configure('done', foreground='green')
        self.tree.tag_configure('error', foreground='red')    
    
    def create_color_image(self, color):
        """Создает цветной квадрат 16x16 указанного цвета"""
        img = tk.PhotoImage(width=16, height=16)
        img.put(color, to=(0, 0, 15, 15))
        return img

    def create_status_image(self, color, symbol):
        """Создает изображение для статуса"""
        img = tk.PhotoImage(width=24, height=24)
        img.put(color, to=(0,0,23,23))
        img.put('white', (symbol,), (12,12))
        return img

    def animate_processing_status(self, base):
        phases = ['⏳', '⌛']  # Два состояния анимации
        current_phase = 0
        
        def update_animation():
            nonlocal current_phase
            for item in self.tree.get_children():
                values = self.tree.item(item, 'values')
                if self.get_base_name(values[1]) == base and self.file_status.get(base) == 'processing':
                    new_values = (phases[current_phase], values[1], values[2])
                    self.tree.item(item, values=new_values)
                    current_phase = (current_phase + 1) % len(phases)
                    self.animation_job = self.after(500, update_animation)
                    break
            else:
                self.animation_job = None
        
        update_animation()

    def check_audio_tracks(self, video_path):
        ffmpeg_path = resource_path("ffmpeg.exe")
        cmd = [ffmpeg_path, '-i', f'"{video_path}"', '-hide_banner']
        try:
            process = subprocess.Popen(
                ' '.join(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            output_text = ""
            while True:
                line = process.stdout.readline()
                if line == '' and process.poll() is not None:
                    break
                if line:
                    output_text += line
            
            audio_streams = []
            audio_index = 0  # Счетчик для аудиопотоков
            for line in output_text.split('\n'):
                if "Stream #" in line and "Audio:" in line:
                    stream_id = line.split('#')[1].split('[')[0].strip()
                    lang_match = re.search(r'\(([a-z]{3})\)', line)
                    lang = lang_match.group(1) if lang_match else "und"
                    
                    track_index_match = re.search(r'Stream #0:(\d+)', line)
                    track_index = int(track_index_match.group(1)) if track_index_match else -1
                    
                    # Извлекаем количество каналов
                    parts = [p.strip() for p in line.split(',')]
                    channel_layout = parts[2] if len(parts) > 2 else "unknown"
                    
                    audio_streams.append({
                        "stream_id": stream_id,
                        "language": lang,
                        "track_index": track_index,
                        "audio_index": audio_index,  # Индекс среди аудиопотоков
                        "full_info": line.strip(),
                        "channel_layout": channel_layout  # mono, stereo и т.д.
                    })
                    audio_index += 1
            
            return len(audio_streams), audio_streams
        except Exception as e:
            print(f"Ошибка при проверке аудио дорожек: {e}")
            return 0, []

    def create_status_icon(self, text='⌛', color='gray'):
        # Создаем изображение для статуса
        img = tk.Canvas(self, width=20, height=20, highlightthickness=0)
        img.create_text(10, 10, text=text, fill=color, font=('Arial', 12))
        return img

    def update_drop_area_text(self, event=None):
        width = self.drop_area.winfo_width()
        height = self.drop_area.winfo_height()
        
        self.drop_area.delete("all")
        self.drop_area.create_text(width // 2, height // 3, text="＋", 
                                 fill="#0078d4", font=('Arial', 48))
        self.drop_area.create_text(width // 2, height * 2 // 3, 
                                 text="Перетащите файлы/папки в любое место\nили кликните сюда чтобы выбрать вручную",
                                 fill="#666666", font=('Arial', 10), justify=tk.CENTER)

    def setup_volume_labels(self):
        # Настройка шрифта для "ссылок"
        self.link_font = ('Arial', 9, 'underline')
        
        # Обновляем существующие метки
        self.orig_label.config(
            text=f"{int(self.orig_volume.get())}%",
            fg='blue',
            font=self.link_font,
            cursor='hand2',
            width=5
        )
        self.new_label.config(
            text=f"{int(self.new_volume.get())}%",
            fg='blue',
            font=self.link_font,
            cursor='hand2',
            width=5
        )
        
        # Настройка событий для меток
        for label in [self.orig_label, self.new_label]:
            label.bind("<Enter>", lambda e: e.widget.config(fg='#0000ff'))
            label.bind("<Leave>", lambda e: e.widget.config(fg='blue'))
            label.bind("<Button-1>", self.edit_volume_inplace) 
        
        # Связываем изменение значений переменных
        self.orig_volume.trace_add("write", lambda *_: self.update_volume_labels_and_save())
        self.new_volume.trace_add("write", lambda *_: self.update_volume_labels_and_save())

    def update_volume_labels_and_save(self):
        self.update_volume_labels()
        save_to_registry("orig_volume", int(self.orig_volume.get()))
        save_to_registry("new_volume", int(self.new_volume.get()))


    def edit_volume(self, vol_type):
        top = tk.Toplevel(self)
        top.title("Ручной ввод")
        top.geometry("250x100")
        
        ttk.Label(top, text="Введите новое значение (1-100):").pack(pady=5)
        
        entry = ttk.Entry(top)
        entry.pack(pady=5)
        entry.focus_set()
        
        def apply_changes():
            try:
                value = int(entry.get())
                if 1 <= value <= 100:
                    if vol_type == 'orig':
                        self.orig_volume.set(value)
                    else:
                        self.new_volume.set(value)
                    top.destroy()
                else:
                    tk.messagebox.showerror("Ошибка", "Значение должно быть от 1 до 100")
            except ValueError:
                tk.messagebox.showerror("Ошибка", "Введите целое число")
        
        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=5)
        
        ttk.Button(btn_frame, text="OK", command=apply_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=top.destroy).pack(side=tk.LEFT, padx=5)

    def edit_volume_inplace(self, event):
        if hasattr(self, "_active_entry"):
            return

        label = event.widget
        parent = label.master

        if label == self.orig_label:
            value_var = self.orig_volume
            col = 2  # Позиция метки в orig_frame
        else:
            value_var = self.new_volume
            col = 2  # Позиция метки в new_frame

        # Скрываем метку
        label.grid_remove()

        # Создаем Entry в той же позиции
        entry = ttk.Entry(parent, width=5, font=('Arial', 9))
        entry.insert(0, str(int(value_var.get())))
        entry.grid(row=0, column=col, padx=5, sticky='w')

        self._active_entry = entry
        self.bind_all("<Button-1>", self.check_focus_out)
        self._current_value_var = value_var
        self._active_label = label

        entry.bind("<Return>", self.save_volume)
        entry.bind("<Escape>", self.cancel_edit)
        entry.bind("<FocusOut>", lambda e: self.save_volume())
        entry.focus_set()
        entry.select_range(0, tk.END)

    def check_focus_out(self, event):
        if hasattr(self, "_active_entry"):
            # Проверяем, был ли клик вне поля ввода
            entry_x = self._active_entry.winfo_rootx()
            entry_y = self._active_entry.winfo_rooty()
            entry_width = self._active_entry.winfo_width()
            entry_height = self._active_entry.winfo_height()

            if not (entry_x <= event.x_root <= entry_x + entry_width and
                    entry_y <= event.y_root <= entry_y + entry_height):
                self.save_volume()

    def save_volume(self, event=None):
        if hasattr(self, "_active_entry"):
            try:
                # Получаем значение из поля ввода
                value = int(self._active_entry.get())
                if 1 <= value <= 100:
                    # Обновляем связанную переменную
                    self._current_value_var.set(value)
            except ValueError:
                pass
            finally:
                # Удаляем поле ввода и восстанавливаем метку
                self._active_entry.destroy()
                self._active_label.grid()
                
                # Убираем глобальный обработчик кликов
                self.unbind_all("<Button-1>")
                
                # Очищаем временные атрибуты
                del self._active_entry
                del self._current_value_var
                del self._active_label
            
    def cancel_edit(self, event=None):
        if hasattr(self, "_active_entry"):
            # Отменяем редактирование без сохранения
            self._active_entry.destroy()
            self._active_label.grid()
            
            # Убираем глобальный обработчик кликов
            self.unbind_all("<Button-1>")
            
            # Очищаем временные атрибуты
            del self._active_entry
            del self._current_value_var
            del self._active_label

    def update_volume_labels(self, *args):
        # Обновляем только если нет активного поля
        if not hasattr(self, "_active_entry"):
            self.orig_label.config(text=f"{int(self.orig_volume.get())}%")
            self.new_label.config(text=f"{int(self.new_volume.get())}%")

    def _cleanup_entry(self):
        if hasattr(self, "_active_entry_frame"):
            parent = self._active_entry_frame.master
            parent.config(relief=self._label_relief)
            self._active_entry_frame.destroy()
        
        for attr in ["_active_entry", "_active_entry_frame", "_current_value_var"]:
            if hasattr(self, attr):
                delattr(self, attr)
        
        self.unbind("<Button-1>")
    
    def update_volume_labels(self):
        self.orig_label.config(text=f"{int(self.orig_volume.get())}%")
        self.new_label.config(text=f"{int(self.new_volume.get())}%")

    def on_drop(self, event):
        files = self.tk.splitlist(event.data)
        self.process_paths(files)

    def on_click(self, event):
        paths = filedialog.askopenfilenames(
            title="Выберите файлы или папки",
            filetypes=(("Все файлы", "*.*"),))
        if paths:
            self.process_paths(paths)

    def process_paths(self, paths):
        new_files = {'video': [], 'audio': []}
        for path in self.tk.splitlist(paths):
            path = path.strip('{}')
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        self.classify_file(full_path, new_files)
            else:
                self.classify_file(path, new_files)
                
        self.old_file_pairs = self.file_pairs.copy()
        self.update_file_pairs(new_files)
        self.update_treeview()

    def classify_file(self, path, storage):
        ext = os.path.splitext(path)[1].lower()
        if ext in audio_ext:
            storage['audio'].append(path)
        elif ext in video_ext:
            storage['video'].append(path)

    def update_file_pairs(self, new_files):
        base_names = {}
        
        for path in new_files['video'] + list(self.file_pairs.keys()):
            base = self.get_base_name(path)
            base_names[base] = self.file_pairs.get(base, {'video': None, 'audio': None})
            if path in new_files['video']:
                base_names[base]['video'] = path

        for path in new_files['audio']:
            base = self.get_base_name(path)
            if base not in base_names:
                base_names[base] = {'video': None, 'audio': path}
            else:
                base_names[base]['audio'] = path

        self.file_pairs = base_names

    def get_base_name(self, path):
        name = os.path.basename(path)
        
        name = re.sub(r'^\d+[_.]', '', name)
        
        name = re.sub(r'_(rus|eng)(?=\.[^.]+$)', '', name, flags=re.IGNORECASE)
        
        base_name = os.path.splitext(name)[0].lower()
        
        base_name = re.sub(r'[^a-z0-9]', '', base_name)
        
        return base_name

    def update_treeview(self):
        self.tree.delete(*self.tree.get_children())
        for base, pair in self.file_pairs.items():
            if base in self.old_file_pairs and \
               self.file_pairs[base]['video'] == self.old_file_pairs[base]['video'] and \
               self.file_pairs[base].get('audio', None) == self.old_file_pairs[base].get('audio', None):
                # Пара файлов не изменилась
                status = self.file_status.get(base, 'pending')
                video = os.path.basename(pair['video'])
                if pair['audio']:
                    audio = os.path.basename(pair['audio'])
                else:
                    track_info = pair.get('track_info', [])
                    if track_info:
                        lang_info = self.get_track_language_info(track_info)
                        audio = f"({lang_info})"
                    else:
                        audio = "None"
            else:
                # Пара файлов изменилась или новая
                status = None
                video = os.path.basename(pair['video']) if pair['video'] else ""
                if pair['video'] and pair['audio']:
                    status = 'pending'
                    audio = os.path.basename(pair['audio'])
                elif pair['video'] and not pair['audio']:
                    track_count, track_info = self.check_audio_tracks(pair['video'])
                    pair['track_info'] = track_info
                    if track_count > 1:
                        status = 'pending'
                        lang_info = self.get_track_language_info(track_info)
                        audio = f"({lang_info})"
                    else:
                        status = 'error'
                        audio = "None"
                else:
                    status = 'error'
                    audio = "None"
            # Вставляем элемент со статусом
            self.tree.insert('', 'end', values=(self.status_text(status), video, audio), tags=(status,))
            self.file_status[base] = status
        # Удаляем из file_status базы, которых нет в file_pairs
        for base in list(self.file_status.keys()):
            if base not in self.file_pairs:
                del self.file_status[base]
            
    def get_track_language_info(self, track_info):
        if not track_info:
            return "неизвестно"
        
        lang_info = []
        for track in track_info:
            lang = track["language"].upper()
            idx = track["track_index"]
            lang_info.append(f"{idx}:{lang}")
        
        return ", ".join(lang_info)

    def clear_list(self):
        self.file_pairs = {}
        self.tree.delete(*self.tree.get_children())
        self.created_files = []
        self.skipped_files = []
        self.progress.set(0)  # Сброс прогресс-бара
        self.progress_label.config(text="")  # Удаление текста прогресса (например, "2/10")
    
    def process_files(self):
        if self.is_processing:
            return
        self.done_label.config(text="")  # Очищаем статус

        has_error = False
        error_file = None
        
        for item in self.tree.get_children():
            status = self.tree.item(item, 'tags')[0]
            values = self.tree.item(item, 'values')
            if status == 'error':
                has_error = True
                error_file = values[1]
                tk.messagebox.showerror(
                    "Ошибка", 
                    f"Ошибка: {error_file} - Отсутствует внешняя или вторая внутренняя аудио дорожка. Добавьте аудиодорожку."
                )
                return
        
        self.is_processing = True
        self.clear_button.config(state='disabled')  # Отключаем кнопку "Очистить список"
        self.start_animation()  # Запускаем анимацию перед началом обработки
        
        # Вычисляем общее количество файлов для обработки
        total = sum(1 for base, pair in self.file_pairs.items() 
                    if pair['video'] and self.file_status.get(base, 'pending') == 'pending')
        
        # Устанавливаем начальное значение прогресса "0/total" сразу после нажатия
        self.after(0, lambda t=total: [
            self.progress_label.config(text=f"0/{t}")
        ])
        
        # Запускаем поток обработки
        threading.Thread(target=self._processing_thread, daemon=True).start()

    def run_ffmpeg_external(self, video, audio, output):
        ffmpeg_path = resource_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_path):
            raise FileNotFoundError(f"FFmpeg не найден: {ffmpeg_path}")

        orig_vol = self.orig_volume.get() / 100
        new_vol = self.new_volume.get() / 100

        cmd = [
            ffmpeg_path,
            '-i', f'"{video}"',
            '-i', f'"{audio}"',
            '-filter_complex',
            f'[0:a]volume={orig_vol}[a0];[1:a]volume={new_vol}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a_mix]',
            '-map', '0:v:0',
            '-map', '[a_mix]',
            '-c:v', 'copy',
            '-c:a', 'aac', '-aac_coder twoloop',
            '-b:a 192k',
            '-y', f'"{output}"'
        ]

        process = subprocess.Popen(
            ' '.join(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            errors='ignore'
        )

        output_text = ""
        while True:
            line = process.stdout.readline()
            if line == '' and process.poll() is not None:
                break
            if line:
                output_text += line
                print(line.strip())

        if process.returncode != 0:
            raise Exception(f"FFmpeg error (code {process.returncode})")

    def _processing_thread(self):
        try:
            total = sum(1 for base, pair in self.file_pairs.items() 
                        if pair['video'] and self.file_status.get(base, 'pending') == 'pending')
            processed = 0
            lock = threading.Lock()

            def process_file(base, pair):
                nonlocal processed
                try:
                    self.update_item_status(base, 'processing')
                    video_path = pair['video']
                    video_dir = os.path.dirname(video_path)
                    name, ext = os.path.splitext(os.path.basename(video_path))
                    output_path = os.path.join(video_dir, f"{name}_RUS.mkv")

                    # Обработка файла
                    if pair['audio']:
                        self.run_ffmpeg_external(pair['video'], pair['audio'], output_path)
                    else:
                        self.run_ffmpeg_embedded(pair['video'], output_path, pair.get('track_info', []))

                    # Обновление статуса
                    self.update_item_status(base, 'done')
                    self.created_files.append(pair['video'])
                    if pair['audio']:
                        self.created_files.append(pair['audio'])

                except Exception as e:
                    print(f"Ошибка при обработке {pair['video']}: {str(e)}")
                    self.update_item_status(base, 'error')
                    self.skipped_files.append(pair['video'])

                # Обновление прогресса
                with lock:
                    processed += 1
                    progress = (processed / total) * 100 if total > 0 else 100
                    self.after(0, lambda p=progress, pr=processed, t=total: [
                        self.progress.set(p),
                        self.progress_label.config(text=f"{pr}/{t}")
                    ])

            # Запуск обработки в пуле потоков
            with ThreadPoolExecutor() as executor:
                futures = []
                for base, pair in self.file_pairs.items():
                    if pair['video'] and self.file_status.get(base, 'pending') == 'pending':
                        futures.append(executor.submit(process_file, base, pair))

                # Ожидание завершения всех задач
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Ошибка в потоке: {e}")

            self._finalize_processing()

        except Exception as e:
            print(f"Критическая ошибка: {str(e)}")
        finally:
            self.is_processing = False
            if hasattr(self, 'after_id') and self.after_id:
                self.after_cancel(self.after_id)

    def update_status(self, message, progress):
        self.after(0, lambda: [
            self.status.set(message),
            self.progress.set(progress)
        ])

    def update_item_status(self, base, status):
        symbol = {
            'pending': '🕒',
            'processing': self.animation_phases[self.animation_index],
            'done': '✓',
            'error': '✗'
        }[status]
        
        for item in self.tree.get_children():
            values = self.tree.item(item, 'values')
            if self.get_base_name(values[1]) == base:
                new_values = (symbol, values[1], values[2])
                self.tree.item(item, values=new_values, tags=(status,))
                self.file_status[base] = status
                print(f"Статус {base} обновлен на {status} с символом {symbol}")
                break
        
        # Очищаем надпись, если обработка еще идет
        if self.is_processing:
            self.done_label.config(text="")

    @staticmethod
    def status_text(status):
        return {
            'pending': 'Ожидает',
            'processing': 'Обработка',
            'done': 'Готово',
            'error': 'Ошибка'
        }.get(status, '')

    def run_ffmpeg_embedded(self, video, output):
        track_count, track_info = self.check_audio_tracks(video)
        if track_count <= 1:
            raise Exception("Недостаточно аудио дорожек для склейки")
        
        orig_vol = self.orig_volume.get() / 100
        new_vol = self.new_volume.get() / 100
        
        original_track = 1
        translation_track = 0
        
        if self.invert_tracks.get():
            original_track, translation_track = translation_track, original_track
        
        cmd = [
            'ffmpeg', '-i', video,
            '-filter_complex',
            f'[0:a:{original_track}]volume={orig_vol}[a0];'
            f'[0:a:{translation_track}]volume={new_vol}[a1];'
            f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a_mix]',
            '-map', '0:v:0',  # Видео
            '-map', '[a_mix]',  # Смешанная дорожка
            '-c:v', 'copy',  # Копируем видео без перекодировки
            '-c:a', 'aac',  # Кодируем смешанную дорожку в AAC
            '-strict', 'experimental',
            '-y', output
        ]
        
        # Запуск FFmpeg
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',  # Указываем кодировку
            errors='ignore'    # Игнорируем ошибки декодирования
        )

        # Вывод логов FFmpeg
        output_text = ""
        while True:
            line = process.stdout.readline()
            if line == '' and process.poll() is not None:
                break
            if line:
                output_text += line
                print(line.strip())
        
        # Проверка результата
        if process.returncode != 0:
            raise Exception(f"FFmpeg error (code {process.returncode})")

    def run_ffmpeg_embedded(self, video, output, track_info=None):
        """
        Обрабатывает видео с внутренними аудиодорожками.
        :param video: Путь к видеофайлу
        :param output: Путь для сохранения результата
        :param track_info: Информация о дорожках (опционально)
        """
        ffmpeg_path = resource_path("ffmpeg.exe")
        if not os.path.exists(ffmpeg_path):
            raise FileNotFoundError(f"FFmpeg не найден: {ffmpeg_path}")

        # Если track_info не передан, получаем его
        if track_info is None:
            track_count, track_info = self.check_audio_tracks(video)
        else:
            track_count = len(track_info)
        
        if track_count < 2:
            raise Exception("Недостаточно аудиодорожек для склейки")

        # Находим дорожки по языку
        eng_track = next((t for t in track_info if t['language'] == 'eng'), None)
        rus_track = next((t for t in track_info if t['language'] == 'rus'), None)
        
        if eng_track and rus_track:
            orig_track = eng_track
            trans_track = rus_track
        else:
            # Если языки не определены, берем первые две дорожки
            orig_track = track_info[0]
            trans_track = track_info[1]
        
        orig_audio_index = orig_track['audio_index']
        trans_audio_index = trans_track['audio_index']
        orig_channel = orig_track.get('channel_layout', 'stereo')
        trans_channel = trans_track.get('channel_layout', 'stereo')
        
        # Определяем громкость
        orig_vol = self.orig_volume.get() / 100  # Оригинальная (английская)
        new_vol = self.new_volume.get() / 100    # Перевод (русский)
        
        # Инверсия дорожек, если выбрано
        if self.invert_tracks.get():
            orig_audio_index, trans_audio_index = trans_audio_index, orig_audio_index
            orig_vol, new_vol = new_vol, orig_vol
        
        # Формируем фильтры с учетом количества каналов
        if orig_channel == 'mono':
            orig_filter = f"[0:a:{orig_audio_index}]pan=stereo|c0=c0|c1=c0,volume={orig_vol}[a0]"
        else:
            orig_filter = f"[0:a:{orig_audio_index}]volume={orig_vol}[a0]"
        
        if trans_channel == 'mono':
            trans_filter = f"[0:a:{trans_audio_index}]pan=stereo|c0=c0|c1=c0,volume={new_vol}[a1]"
        else:
            trans_filter = f"[0:a:{trans_audio_index}]volume={new_vol}[a1]"
        
        filter_complex = f"{orig_filter};{trans_filter};[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a_mix]"
        
        # Команда FFmpeg
        cmd = [
            ffmpeg_path, 
            '-i', f'"{video}"',
            '-filter_complex', filter_complex,
            '-map', '0:v:0',
            '-map', '[a_mix]',
            '-c:v', 'copy',
            '-c:a', 'aac', '-aac_coder twoloop',
            '-b:a 192k',  # Фиксированный битрейт
            '-y', f'"{output}"'
        ]
        
        # Запуск FFmpeg
        process = subprocess.Popen(
            ' '.join(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        output_text = ""
        while True:
            line = process.stdout.readline()
            if line == '' and process.poll() is not None:
                break
            if line:
                output_text += line
                print(line.strip())
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error (code {process.returncode})")

    def mix_audio_tracks(self, video, output, orig_track, trans_track, orig_vol, new_vol):
        """
        Смешивает две аудио дорожки и добавляет их в выходной файл
        """
        ffmpeg_path = resource_path("ffmpeg.exe")
        cmd = [
            ffmpeg_path, '-i', f'"{video}"',
            '-filter_complex', 
            f'[0:a:{orig_track}]volume={orig_vol}[a0];'
            f'[0:a:{trans_track}]volume={new_vol}[a1];'
            f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a_mix]',
            '-map', '0:v:0', 
            '-map', f'0:a:{orig_track}', 
            '-map', f'0:a:{trans_track}', 
            '-map', '[a_mix]',
            '-c:v', 'copy', 
            '-c:a:0', 'copy', 
            '-c:a:1', 'copy', 
            '-c:a:2', 'aac', 
            '-strict', 'experimental', 
            '-y', f'"{output}"'
        ]
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )

        output_text = ""
        while True:
            line = process.stdout.readline()
            if line == '' and process.poll() is not None:
                break
            if line:
                output_text += line
                print(line.strip())
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg error (code {process.returncode})")

    def _finalize_processing(self):
        if hasattr(self, 'after_id') and self.after_id:
            self.after_cancel(self.after_id)
        
        try:
            if self.created_files:
                if self.backup_files.get():
                    if self.remove_source.get():
                        self.remove_source_files()
                    else:
                        self.create_backup_files()
                else:
                    self.remove_source_files()

            success_count = len([base for base, status in self.file_status.items() 
                               if status == 'done'])
            error_count = len([base for base, status in self.file_status.items() 
                             if status == 'error'])
            
            status_text = f"Готово! Успешно: {success_count}, Ошибок: {error_count}"
            
            self.after(0, lambda: [
                self.status.set(status_text),
                self.progress.set(100),
                self.progress_label.config(text=""),  # Очищаем текст прогресса
                self.done_label.config(text="Готово!" if success_count > 0 else ""),
                self.clear_button.config(state='normal')
            ])
            
            print("Финализация завершена, вызываем window_focus_effect")
            self.window_focus_effect()

        except Exception as e:
            print(f"Ошибка при завершении обработки: {str(e)}")
        finally:
            self.is_processing = False
            self.clear_button.config(state='normal')  # Гарантируем включение кнопки даже при ошибке
            self.animation_index = 0
            if hasattr(self, 'after_id'):
                self.after_id = None

    def window_focus_effect(self):
        print("Вызов window_focus_effect")  # Отладка
        self.bell()  # Звуковой сигнал для привлечения внимания
        self.lift()  # Поднимаем окно поверх других

    def reset_window_state(self, original_title):
        self.attributes('-topmost', False)  # Только убираем topmost

        # Снимаем флаг "поверх всех окон"
        self.attributes('-topmost', False)
    
    def create_backup_files(self):
        for f in self.created_files:
            try:
                if os.path.exists(f):  # Проверяем, существует ли файл
                    backup_dir = os.path.join(os.path.dirname(f), "backup")
                    os.makedirs(backup_dir, exist_ok=True)
                    dest = os.path.join(backup_dir, os.path.basename(f))
                    
                    if os.path.exists(dest):
                        os.remove(dest)
                    
                    shutil.move(f, backup_dir)
                else:
                    print(f"Файл не существует: {f}")
            except Exception as e:
                print(f"Ошибка перемещения {f}: {str(e)}")
            
    def remove_source_files(self):
        """
        Удаляет оригинальные файлы (видео и аудио).
        """
        for f in self.created_files:
            try:
                os.remove(f)
            except Exception as e:
                print(f"Ошибка удаления {f}: {str(e)}")

    def backup_files(self):
        """
        Создает резервные копии оригинальных файлов.
        """
        for f in self.created_files:
            try:
                backup_dir = os.path.join(os.path.dirname(f), "backup")
                print(f"Создаем папку backup: {backup_dir}")  # Отладочное сообщение
                os.makedirs(backup_dir, exist_ok=True)
                dest = os.path.join(backup_dir, os.path.basename(f))
                
                if os.path.exists(dest):
                    print(f"Файл уже существует: {dest}")  # Отладочное сообщение
                    os.remove(dest)
                
                print(f"Перемещаем файл: {f} -> {dest}")  # Отладочное сообщение
                shutil.move(f, backup_dir)
            except Exception as e:
                print(f"Ошибка перемещения {f}: {str(e)}")

if __name__ == "__main__":
    app = MergeApp()
    app.mainloop()