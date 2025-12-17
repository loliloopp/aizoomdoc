"""
Графический интерфейс приложения (PyQt6).
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QComboBox, QSplitter,
    QListWidget, QListWidgetItem, QFrame, QScrollArea, QProgressBar,
    QFileDialog, QMenuBar, QMenu, QDialog, QDialogButtonBox, QMessageBox,
    QGroupBox
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QFont, QPixmap, QAction, QDragEnterEvent, QDropEvent

from .config import config
from .gui_agent import AgentWorker

MODELS = {
    "Qwen3 VL (Default)": "qwen/qwen3-vl-235b-a22b-thinking",
    "Gemini 3 Pro": "google/gemini-3-pro-preview",
    "Gemini 2.0 Flash": "google/gemini-2.0-flash-thinking-exp",
    "Claude 3.5 Sonnet": "anthropic/claude-3.5-sonnet"
}

CONFIG_PATH = Path.home() / ".aizoomdoc_config.json"

def load_config_file():
    """Загружает настройки из файла."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"data_root": str(Path.cwd() / "data")}

def save_config_file(data):
    """Сохраняет настройки в файл."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

class SettingsDialog(QDialog):
    """Диалог настроек."""
    def __init__(self, parent=None):
        super().__init__(parent)
        print("[DEBUG] Инициализация SettingsDialog (Simplified)")
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(600)
        
        layout = QVBoxLayout(self)
        
        # 1. Группа "Папка с данными"
        gb_data = QGroupBox("Данные")
        gb_layout = QVBoxLayout(gb_data)
        
        gb_layout.addWidget(QLabel("Папка проекта (создаются chats/, images/):"))
        
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        cfg = load_config_file()
        self.path_edit.setText(cfg.get("data_root", ""))
        
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self.browse_folder)
        
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(btn_browse)
        gb_layout.addLayout(path_layout)
        
        layout.addWidget(gb_data)
        
        # 2. Группа "Промты AI"
        gb_prompts = QGroupBox("AI Ассистент - Системные Промты")
        prompts_layout_main = QVBoxLayout(gb_prompts)
        
        # Вычисляем data_root
        data_root = Path(self.path_edit.text()) if self.path_edit.text() else Path.cwd() / "data"
        
        # 2.1. Промт выбора картинок (ЭТАП 1)
        prompts_layout_main.addWidget(QLabel("📌 ЭТАП 1: Выбор изображений (selection_prompt.txt):"))
        
        selection_file_layout = QHBoxLayout()
        self.selection_prompt_label = QLineEdit()
        self.selection_prompt_label.setReadOnly(True)
        self.selection_prompt_label.setText(str(data_root / "selection_prompt.txt"))
        
        btn_edit_selection = QPushButton("Редактировать...")
        btn_edit_selection.clicked.connect(self.edit_selection_prompt)
        
        selection_file_layout.addWidget(self.selection_prompt_label)
        selection_file_layout.addWidget(btn_edit_selection)
        prompts_layout_main.addLayout(selection_file_layout)
        
        prompts_layout_main.addSpacing(10)
        
        # 2.2. Промт анализа (ЭТАП 2)
        prompts_layout_main.addWidget(QLabel("📌 ЭТАП 2: Анализ документов (llm_system_prompt.txt):"))
        
        analysis_file_layout = QHBoxLayout()
        self.analysis_prompt_label = QLineEdit()
        self.analysis_prompt_label.setReadOnly(True)
        self.analysis_prompt_label.setText(str(data_root / "llm_system_prompt.txt"))
        
        btn_edit_analysis = QPushButton("Редактировать...")
        btn_edit_analysis.clicked.connect(self.edit_analysis_prompt)
        
        analysis_file_layout.addWidget(self.analysis_prompt_label)
        analysis_file_layout.addWidget(btn_edit_analysis)
        prompts_layout_main.addLayout(analysis_file_layout)
        
        layout.addWidget(gb_prompts)
        
        # Кнопки
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        print("[DEBUG] Диалог настроек готов")
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", self.path_edit.text())
        if folder:
            self.path_edit.setText(folder)
            # Обновляем путь к файлу промта
            data_root = Path(folder)
            prompt_file = data_root / "llm_system_prompt.txt"
            self.prompt_file_label.setText(str(prompt_file))
    
    def edit_selection_prompt(self):
        """Редактирование промта для выбора изображений (ЭТАП 1)"""
        prompt_file = Path(self.selection_prompt_label.text())
        
        # Если файл не существует, создаем с содержимым по умолчанию
        if not prompt_file.exists():
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            default_content = """Ты — ассистент по анализу технической документации.
Твоя задача — найти в тексте ИЗОБРАЖЕНИЯ, необходимые для ответа на запрос пользователя.

ВАЖНО ПРО СТРУКТУРУ ДОКУМЕНТА:
1. Документ содержит блоки описания изображений, которые выглядят так:
   ```
   *Изображение:*
   { ... JSON метаданные ... }
   ![Изображение](https://... .pdf)  <-- ЭТА ССЫЛКА ПРАВИЛЬНАЯ (находится ПОСЛЕ метаданных)
   ```
2. Иногда перед блоком *Изображение:* может быть ошибочная ссылка. ИГНОРИРУЙ ЕЕ.
3. Бери только ту ссылку, которая идет СРАЗУ ПОСЛЕ блока метаданных (JSON).

ИНСТРУКЦИЯ:
1. Прочитай запрос пользователя.
2. Найди в тексте блоки с `*Изображение:*`, которые релевантны запросу.
   - Используй `ocr_text` и `content_summary` внутри JSON для поиска.
3. Извлечь URL изображения, который находится ПОД JSON блоком.
4. Верни JSON:
```json
{
  "reasoning": "Нужен план 1 этажа для проверки коллекторов (найден в блоке *Изображение:* с content_summary 'План 1 этажа')",
  "needs_images": true,
  "image_urls": ["https://... .pdf"]
}
```
Если картинок нет или они не нужны - верни `needs_images: false`."""
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(default_content)
        
        # Открываем файл в диалоге редактирования
        dialog = PromptEditDialog(self, prompt_file)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Сохранено", f"Промт выбора изображений сохранён в:\n{prompt_file}")
    
    def edit_analysis_prompt(self):
        """Редактирование промта для анализа (ЭТАП 2)"""
        prompt_file = Path(self.analysis_prompt_label.text())
        
        # Если файл не существует, создаем с содержимым по умолчанию
        if not prompt_file.exists():
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            default_content = """Ты — эксперт-инженер по анализу технической документации (чертежи, схемы, планы).

КРИТИЧЕСКИ ВАЖНО:
- Технические чертежи содержат МЕЛКИЕ детали: размеры, маркировки, надписи, диаметры труб, обозначения элементов.
- На preview-изображениях эти детали НЕ ЧИТАЮТСЯ.
- Для ДОТОШНОГО анализа ты ДОЛЖЕН использовать ZOOM для каждой важной зоны чертежа.

СТРАТЕГИЯ АНАЛИЗА:
1. Если видишь ⚠️ SCALED PREVIEW - это уменьшенное изображение:
   - Сначала оцени общую структуру
   - Затем ОБЯЗАТЕЛЬНО запроси ZOOM для КАЖДОЙ зоны с важными деталями:
     * Узлы и соединения
     * Таблицы с размерами/диаметрами
     * Маркировки элементов
     * Надписи и обозначения
     * Спецификации

2. Если видишь ✓ FULL RESOLUTION - полноразмерное изображение:
   - Можно анализировать без ZOOM (если детали видны)
   - Но если есть таблицы или мелкий текст - все равно используй ZOOM

ФОРМАТ ЗАПРОСА ZOOM:
Ты можешь указать координаты в ДВУХ форматах (выбирай удобный):

**1. Пиксельные координаты (coords_px):**
```json
{
  "tool": "zoom",
  "image_id": "uuid-изображения",
  "coords_px": [x1, y1, x2, y2],
  "reason": "Читаю диаметры труб в таблице"
}
```
Где x1,y1 - левый верхний угол, x2,y2 - правый нижний угол в пикселях ОРИГИНАЛА.

**2. Нормализованные координаты (coords_norm) [0.0 - 1.0]:**
```json
{
  "tool": "zoom",
  "image_id": "uuid-изображения",
  "coords_norm": [0.2, 0.3, 0.5, 0.6],
  "reason": "Проверяю узел в центре чертежа"
}
```
Где 0.0 - левый/верхний край, 1.0 - правый/нижний край.

ПРИМЕРЫ КОГДА НУЖЕН ZOOM:
- "Вижу таблицу с размерами, но текст размыт" → ZOOM на таблицу
- "Есть узел соединения, нужно проверить диаметры" → ZOOM на узел
- "Маркировка элемента нечитаема" → ZOOM на маркировку
- "Спецификация в углу чертежа" → ZOOM на спецификацию

НЕ ЛЕНИСЬ использовать ZOOM - это твой главный инструмент для точного анализа!"""
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(default_content)
        
        # Открываем файл в диалоге редактирования
        dialog = PromptEditDialog(self, prompt_file)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Сохранено", f"Промт анализа сохранён в:\n{prompt_file}")
    
    def get_data_root(self):
        return self.path_edit.text()


class PromptEditDialog(QDialog):
    """Диалог редактирования системного промта."""
    def __init__(self, parent=None, prompt_file: Path = None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование системного промта")
        self.resize(700, 500)
        self.prompt_file = prompt_file
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Отредактируйте системный промт для LLM:"))
        
        self.text_edit = QTextEdit()
        self.text_edit.setFont(QFont("Courier", 10))
        
        # Загружаем содержимое файла
        if prompt_file and prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                self.text_edit.setPlainText(f.read())
        
        layout.addWidget(self.text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_prompt)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def save_prompt(self):
        """Сохраняет отредактированный промт."""
        try:
            if self.prompt_file:
                self.prompt_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.prompt_file, "w", encoding="utf-8") as f:
                    f.write(self.text_edit.toPlainText())
                QMessageBox.information(self, "Успех", "Промт сохранен!")
                self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при сохранении: {e}")


class DragDropLineEdit(QLineEdit):
    """QLineEdit с поддержкой Drag & Drop для .md файлов."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        for url in urls:
            path = url.toLocalFile()
            if path.endswith(".md"):
                # Добавляем путь в поле (можно добавить команду @file:path)
                current = self.text()
                if current:
                    self.setText(f"{current} @файл:{path}")
                else:
                    self.setText(f"@файл:{path}")
                break


class ChatMessageWidget(QFrame):
    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)
        
        self.lbl_header = QLabel(self)
        font = QFont()
        font.setBold(True)
        self.lbl_header.setFont(font)
        
        if role == "user":
            self.lbl_header.setText("ВЫ:")
            self.lbl_header.setStyleSheet("color: #2980b9;")
        else:
            self.lbl_header.setText("АГЕНТ:")
            self.lbl_header.setStyleSheet("color: #27ae60;")
            
        self.layout.addWidget(self.lbl_header)
        
        self.lbl_text = QLabel(text, self)
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.layout.addWidget(self.lbl_text)
        
        self.setStyleSheet("""
            ChatMessageWidget {
                background-color: #ffffff;
                border-radius: 5px;
                border: 1px solid #e0e0e0;
            }
        """)

class ImageMessageWidget(QFrame):
    def __init__(self, image_path: str, description: str, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        self.lbl_desc = QLabel(f"🖼 {description}", self)
        self.lbl_desc.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        self.layout.addWidget(self.lbl_desc)
        
        self.lbl_image = QLabel(self)
        pixmap = QPixmap(image_path)
        
        if pixmap.width() > 600:
            pixmap = pixmap.scaledToWidth(600, Qt.TransformationMode.SmoothTransformation)
            
        self.lbl_image.setPixmap(pixmap)
        self.layout.addWidget(self.lbl_image)
        
        self.setStyleSheet("border: 1px solid #ddd; background: #f9f9f9; margin: 5px;")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AIZoomDoc v2.0")
        self.resize(1400, 900)
        
        # Загружаем конфиг
        self.app_config = load_config_file()
        self.data_root = Path(self.app_config.get("data_root", Path.cwd() / "data"))
        self.data_root.mkdir(parents=True, exist_ok=True)
        
        self.current_worker = None
        self.selected_md_files = []
        
        # Меню
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Настройки")
        
        action_settings = QAction("Открыть настройки...", self)
        action_settings.triggered.connect(self.open_settings)
        settings_menu.addAction(action_settings)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # ЛЕВАЯ ПАНЕЛЬ
        left_panel = QFrame()
        left_panel.setFixedWidth(280)
        left_panel.setStyleSheet("background-color: #f0f0f0; border-right: 1px solid #ccc;")
        left_layout = QVBoxLayout(left_panel)
        
        self.btn_new_chat = QPushButton("Новый чат")
        self.btn_new_chat.setStyleSheet("background-color: #3498db; color: white; border: none; padding: 10px; font-weight: bold;")
        self.btn_new_chat.clicked.connect(self.new_chat)
        left_layout.addWidget(self.btn_new_chat)
        
        # Кнопка настроек
        self.btn_settings = QPushButton("⚙️ Настройки")
        self.btn_settings.setStyleSheet("background-color: #95a5a6; color: white; border: none; padding: 8px; margin-top: 5px;")
        self.btn_settings.clicked.connect(self.open_settings)
        left_layout.addWidget(self.btn_settings)
        
        left_layout.addWidget(QLabel("ИСТОРИЯ ЧАТОВ:"))
        self.list_history = QListWidget()
        self.list_history.setStyleSheet("border: none; background: transparent;")
        self.list_history.itemClicked.connect(self.load_chat_history)
        left_layout.addWidget(self.list_history)
        
        # ЦЕНТР
        center_panel = QFrame()
        center_layout = QVBoxLayout(center_panel)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background-color: white; border: none;")
        
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.addStretch()
        
        self.scroll_area.setWidget(self.chat_container)
        center_layout.addWidget(self.scroll_area)
        
        # Панель выбора файлов
        files_frame = QFrame()
        files_frame.setStyleSheet("background-color: #ffeaa7; border: 1px solid #fdcb6e; padding: 5px;")
        files_layout = QHBoxLayout(files_frame)
        
        self.lbl_selected_files = QLabel("Файлы: нет")
        self.lbl_selected_files.setStyleSheet("color: #2d3436; font-size: 10px;")
        
        btn_browse_files = QPushButton("Обзор MD...")
        btn_browse_files.setFixedWidth(120)
        btn_browse_files.clicked.connect(self.browse_md_files)
        
        btn_clear_files = QPushButton("Очистить")
        btn_clear_files.setFixedWidth(80)
        btn_clear_files.clicked.connect(self.clear_md_files)
        
        files_layout.addWidget(self.lbl_selected_files, 1)
        files_layout.addWidget(btn_browse_files)
        files_layout.addWidget(btn_clear_files)
        
        center_layout.addWidget(files_frame)
        
        # Поле ввода (с Drag & Drop)
        input_frame = QFrame()
        input_frame.setStyleSheet("background-color: #ecf0f1; border-top: 1px solid #ccc;")
        input_frame.setFixedHeight(80)
        input_layout = QHBoxLayout(input_frame)
        
        self.txt_input = DragDropLineEdit()
        self.txt_input.setPlaceholderText("Введите запрос (или перетащите .md файл сюда)...")
        self.txt_input.returnPressed.connect(self.start_agent)
        
        self.btn_send = QPushButton("Отправить")
        self.btn_send.clicked.connect(self.start_agent)
        
        input_layout.addWidget(self.txt_input)
        input_layout.addWidget(self.btn_send)
        center_layout.addWidget(input_frame)
        
        # ПРАВАЯ ПАНЕЛЬ
        right_panel = QFrame()
        right_panel.setFixedWidth(300)
        right_panel.setStyleSheet("background: #f8f9fa;")
        right_layout = QVBoxLayout(right_panel)
        
        self.combo_models = QComboBox()
        for name, mid in MODELS.items():
            self.combo_models.addItem(name, mid)
        right_layout.addWidget(QLabel("Модель:"))
        right_layout.addWidget(self.combo_models)
        
        right_layout.addSpacing(10)
        
        self.lbl_data_root = QLabel(f"📁 {self.data_root}")
        self.lbl_data_root.setWordWrap(True)
        self.lbl_data_root.setStyleSheet("font-size: 10px; color: #555;")
        right_layout.addWidget(self.lbl_data_root)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas; font-size: 10px; background: #2c3e50; color: #ecf0f1;")
        right_layout.addWidget(QLabel("Логи:"))
        right_layout.addWidget(self.log_view)
        
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        right_layout.addWidget(self.progress)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)
        
        self.refresh_history_list()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            new_path = dialog.get_data_root()
            if new_path:
                self.data_root = Path(new_path)
                self.data_root.mkdir(parents=True, exist_ok=True)
                self.app_config["data_root"] = str(self.data_root)
                save_config_file(self.app_config)
                self.lbl_data_root.setText(f"📁 {self.data_root}")
                self.refresh_history_list()
                QMessageBox.information(self, "Настройки", f"Папка обновлена:\n{self.data_root}")

    def browse_md_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 
            "Выберите файлы Markdown", 
            str(self.data_root), 
            "Markdown Files (*.md)"
        )
        if files:
            self.selected_md_files = files
            self.lbl_selected_files.setText(f"Файлы: {len(files)} шт.")
            self.log(f"Выбрано файлов: {len(files)}")

    def clear_md_files(self):
        self.selected_md_files = []
        self.lbl_selected_files.setText("Файлы: нет")

    def log(self, text):
        self.log_view.append(f"{datetime.now().strftime('%H:%M:%S')} {text}")

    def add_chat_message(self, role, text):
        w = ChatMessageWidget(role, text)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, w)
        QApplication.processEvents()
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def add_chat_image(self, path, desc):
        w = ImageMessageWidget(path, desc)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, w)
        QApplication.processEvents()
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def new_chat(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.txt_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.clear_md_files()

    def refresh_history_list(self):
        self.list_history.clear()
        chats_dir = self.data_root / "chats"
        if not chats_dir.exists(): return
        
        dirs = sorted([d for d in chats_dir.iterdir() if d.is_dir()], reverse=True)
        
        for d in dirs:
            hist_file = d / "history.json"
            if hist_file.exists():
                try:
                    with open(hist_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        query = data.get("query", "Без названия")
                        item = QListWidgetItem(f"{d.name[:15]}... - {query[:20]}")
                        item.setData(Qt.ItemDataRole.UserRole, str(hist_file))
                        self.list_history.addItem(item)
                except: pass

    def load_chat_history(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        self.new_chat()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for msg in data.get("messages", []):
                    self.add_chat_message(msg["role"], msg["content"])
                    if "images" in msg:
                        for img_path in msg["images"]:
                            if Path(img_path).exists():
                                self.add_chat_image(img_path, "Из истории")
        except Exception as e:
            self.log(f"Ошибка загрузки истории: {e}")

    def start_agent(self):
        query = self.txt_input.text().strip()
        if not query: return
        
        # ВАЖНО: Сохраняем список файлов ДО очистки чата!
        files_to_use = self.selected_md_files.copy()
        
        self.new_chat()
        self.add_chat_message("user", query)
        self.txt_input.clear()
        self.txt_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.progress.setVisible(True)
        
        mid = self.combo_models.currentData()
        
        # Передаем сохраненные md файлы в воркера
        self.current_worker = AgentWorker(
            self.data_root, 
            query, 
            mid, 
            md_files=files_to_use
        )
        self.current_worker.sig_log.connect(self.log)
        self.current_worker.sig_message.connect(self.add_chat_message)
        self.current_worker.sig_image.connect(self.add_chat_image)
        self.current_worker.sig_finished.connect(self.on_finished)
        self.current_worker.sig_history_saved.connect(self.refresh_history_list)
        self.current_worker.start()

    def on_finished(self):
        self.txt_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.progress.setVisible(False)
        self.log("Готово.")

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
