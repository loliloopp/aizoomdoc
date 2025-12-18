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
    QGroupBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QFont, QPixmap, QAction, QDragEnterEvent, QDropEvent, QTextCursor, QKeyEvent

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


class DragDropTextEdit(QTextEdit):
    """QTextEdit с поддержкой Drag & Drop для .md файлов и автоматическим изменением размера."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        # Настройка минимальной и максимальной высоты
        self.document().documentLayout().documentSizeChanged.connect(self.adjust_height)
        self.max_lines = 5
        
        # Начальная настройка высоты
        font_metrics = self.fontMetrics()
        self.min_height_val = font_metrics.lineSpacing() + 10 # Запас для паддингов
        self.setMinimumHeight(self.min_height_val)
        self.adjust_height()
    
    def adjust_height(self):
        """Автоматически подстраивает высоту под содержимое (до 5 строк)."""
        doc_height = self.document().size().height()
        margins = self.contentsMargins()
        
        # Вычисляем высоту одной строки
        font_metrics = self.fontMetrics()
        line_height = font_metrics.lineSpacing()
        
        # Корректируем total_height
        total_height = int(doc_height + margins.top() + margins.bottom())
        
        # Максимальная высота = 5 строк
        max_height = int(line_height * self.max_lines + margins.top() + margins.bottom() + 10)
        
        # Минимальная высота
        min_h = self.min_height_val
        
        if total_height < min_h:
            total_height = min_h
        elif total_height > max_height:
            total_height = max_height
            
        self.setFixedHeight(total_height)
        self.updateGeometry()
    
    def keyPressEvent(self, event: QKeyEvent):
        """Обработка нажатия клавиш: Enter отправляет, Shift+Enter - новая строка."""
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                # Shift+Enter - вставляем новую строку
                super().keyPressEvent(event)
            else:
                # Enter без модификаторов - отправляем сообщение
                parent = self.parent()
                while parent:
                    if isinstance(parent, MainWindow):
                        parent.start_agent()
                        return
                    parent = parent.parent()
        else:
            super().keyPressEvent(event)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        for url in urls:
            path = url.toLocalFile()
            if path.endswith(".md"):
                # Добавляем путь в поле
                current = self.toPlainText()
                if current:
                    self.setPlainText(f"{current} @файл:{path}")
                else:
                    self.setPlainText(f"@файл:{path}")
                break


class ChatMessageWidget(QFrame):
    def __init__(self, role: str, text: str, parent=None, is_dark_theme=True):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.role = role
        self.is_dark_theme = is_dark_theme
        
        # Основной контейнер с ограниченной шириной (как в ChatGPT)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Создаем центральный контейнер с максимальной шириной
        self.content_widget = QWidget()
        content_layout = QHBoxLayout(self.content_widget)
        content_layout.setContentsMargins(24, 16, 24, 16)
        
        # Иконка/аватар
        icon_label = QLabel()
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        if role == "user":
            icon_label.setText("👤")
            icon_label.setStyleSheet("""
                background-color: #19C37D;
                border-radius: 16px;
                color: white;
                font-size: 18px;
                padding: 6px;
            """)
        else:
            icon_label.setText("🤖")
            icon_label.setStyleSheet("""
                background-color: #10A37F;
                border-radius: 16px;
                color: white;
                font-size: 18px;
                padding: 6px;
            """)
        
        content_layout.addWidget(icon_label)
        content_layout.addSpacing(16)
        
        # Текст сообщения
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        
        self.lbl_text = QLabel(text)
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        text_layout.addWidget(self.lbl_text)
        content_layout.addWidget(text_widget, 1)
        
        main_layout.addWidget(self.content_widget)
        
        self.apply_theme(is_dark_theme)
    
    def apply_theme(self, is_dark_theme):
        """Применяет тему к виджету сообщения."""
        self.is_dark_theme = is_dark_theme
        
        if is_dark_theme:
            if self.role == "user":
                self.content_widget.setStyleSheet("background-color: #2d2d2d;")
                self.lbl_text.setStyleSheet("""
                    color: #ececec;
                    font-size: 14px;
                    line-height: 1.6;
                """)
            else:
                self.content_widget.setStyleSheet("background-color: #1e1e1e;")
                self.lbl_text.setStyleSheet("""
                    color: #ececec;
                    font-size: 14px;
                    line-height: 1.6;
                """)
            
            self.setStyleSheet("""
                ChatMessageWidget {
                    border: none;
                    border-bottom: 1px solid #3d3d3d;
                }
            """)
        else:
            if self.role == "user":
                self.content_widget.setStyleSheet("background-color: #f7f7f8;")
                self.lbl_text.setStyleSheet("""
                    color: #2d333a;
                    font-size: 14px;
                    line-height: 1.6;
                """)
            else:
                self.content_widget.setStyleSheet("background-color: #ffffff;")
                self.lbl_text.setStyleSheet("""
                    color: #2d333a;
                    font-size: 14px;
                    line-height: 1.6;
                """)
            
            self.setStyleSheet("""
                ChatMessageWidget {
                    border: none;
                    border-bottom: 1px solid #ececf1;
                }
            """)

class ImageMessageWidget(QFrame):
    def __init__(self, image_path: str, description: str, parent=None, is_dark_theme=True):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.is_dark_theme = is_dark_theme
        
        # Основной контейнер
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Центральный контейнер
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(24, 12, 24, 12)
        content_layout.setSpacing(8)
        
        # Описание
        self.lbl_desc = QLabel(f"🖼 {description}")
        content_layout.addWidget(self.lbl_desc)
        
        # Изображение
        self.lbl_image = QLabel()
        pixmap = QPixmap(image_path)
        
        if pixmap.width() > 600:
            pixmap = pixmap.scaledToWidth(600, Qt.TransformationMode.SmoothTransformation)
            
        self.lbl_image.setPixmap(pixmap)
        content_layout.addWidget(self.lbl_image)
        
        main_layout.addWidget(self.content_widget)
        
        self.apply_theme(is_dark_theme)
    
    def apply_theme(self, is_dark_theme):
        """Применяет тему к виджету изображения."""
        self.is_dark_theme = is_dark_theme
        
        if is_dark_theme:
            self.lbl_desc.setStyleSheet("""
                color: #8e8ea0;
                font-size: 12px;
            """)
            
            self.lbl_image.setStyleSheet("""
                border: 1px solid #4d4d4f;
                border-radius: 8px;
                background: #2d2d2d;
                padding: 4px;
            """)
            
            self.content_widget.setStyleSheet("background-color: #1e1e1e;")
            
            self.setStyleSheet("""
                ImageMessageWidget {
                    border: none;
                    border-bottom: 1px solid #3d3d3d;
                }
            """)
        else:
            self.lbl_desc.setStyleSheet("""
                color: #6e6e80;
                font-size: 12px;
            """)
            
            self.lbl_image.setStyleSheet("""
                border: 1px solid #e5e5e5;
                border-radius: 8px;
                background: white;
                padding: 4px;
            """)
            
            self.content_widget.setStyleSheet("background-color: #ffffff;")
            
            self.setStyleSheet("""
                ImageMessageWidget {
                    border: none;
                    border-bottom: 1px solid #ececf1;
                }
            """)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AIZoomDoc")
        self.resize(1400, 900)
        
        # Загружаем конфиг
        self.app_config = load_config_file()
        self.data_root = Path(self.app_config.get("data_root", Path.cwd() / "data"))
        self.data_root.mkdir(parents=True, exist_ok=True)
        
        # Инициализация темной темы (по умолчанию)
        self.is_dark_theme = self.app_config.get("dark_theme", True)
        
        self.current_worker = None
        self.selected_md_files = []
        
        # Меню
        self.menubar = self.menuBar()
        settings_menu = self.menubar.addMenu("Настройки")
        
        action_settings = QAction("Открыть настройки...", self)
        action_settings.triggered.connect(self.open_settings)
        settings_menu.addAction(action_settings)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Верхняя панель с переключателем темы
        self.top_bar = QFrame()
        self.top_bar.setFixedHeight(50)
        top_bar_layout = QHBoxLayout(self.top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 8)
        
        top_bar_layout.addStretch()
        
        # Переключатель темы
        self.theme_toggle = QPushButton("🌙" if self.is_dark_theme else "☀️")
        self.theme_toggle.setFixedSize(40, 34)
        self.theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_toggle.setToolTip("Переключить тему")
        self.theme_toggle.clicked.connect(self.toggle_theme)
        top_bar_layout.addWidget(self.theme_toggle)
        
        main_layout.addWidget(self.top_bar)
        
        # Контейнер для основного содержимого
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # ЛЕВАЯ ПАНЕЛЬ (стиль ChatGPT)
        self.left_panel = QFrame()
        self.left_panel.setFixedWidth(260)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(12, 12, 12, 12)
        
        # Кнопка "Новый чат" в стиле ChatGPT
        self.btn_new_chat = QPushButton("+ Новый чат")
        self.btn_new_chat.clicked.connect(self.new_chat)
        left_layout.addWidget(self.btn_new_chat)
        
        left_layout.addSpacing(12)
        
        # Заголовок истории
        self.history_label = QLabel("Недавние чаты")
        left_layout.addWidget(self.history_label)
        
        # Список истории
        self.list_history = QListWidget()
        self.list_history.itemClicked.connect(self.load_chat_history)
        left_layout.addWidget(self.list_history)
        
        # ЦЕНТР
        self.center_panel = QFrame()
        center_layout = QVBoxLayout(self.center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        
        # Область чата
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(0)
        self.chat_layout.addStretch()
        
        self.scroll_area.setWidget(self.chat_container)
        center_layout.addWidget(self.scroll_area)
        
        # Панель ввода в стиле ChatGPT
        self.input_container = QWidget()
        self.input_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        input_container_layout = QVBoxLayout(self.input_container)
        input_container_layout.setContentsMargins(0, 8, 0, 12)
        
        # Центрируем панель ввода с отступами 5% с каждой стороны
        input_center_layout = QHBoxLayout()
        input_center_layout.setSpacing(0)
        input_center_layout.setContentsMargins(0, 0, 0, 0)
        
        # Левый отступ (5%)
        left_spacer = QWidget()
        left_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        input_center_layout.addWidget(left_spacer, 1)
        
        self.input_frame = QFrame()
        self.input_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        
        input_layout = QHBoxLayout(self.input_frame)
        input_layout.setContentsMargins(6, 4, 4, 4)
        input_layout.setSpacing(4)
        input_layout.setAlignment(Qt.AlignmentFlag.AlignBottom) # Выравнивание элементов по низу
        
        # Кнопка добавления файлов
        self.btn_attach = QPushButton("+")
        self.btn_attach.setFixedSize(28, 28)
        self.btn_attach.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_attach.setToolTip("Прикрепить файлы")
        self.btn_attach.clicked.connect(self.on_attach_clicked)
        input_layout.addWidget(self.btn_attach, 0, Qt.AlignmentFlag.AlignBottom)
        
        # Поле ввода
        self.txt_input = DragDropTextEdit()
        self.txt_input.setPlaceholderText("Введите сообщение... (Enter - отправить, Shift+Enter - новая строка)")
        input_layout.addWidget(self.txt_input, 1)
        
        # Индикатор файлов (кликабельный)
        self.lbl_file_count = QLabel("")
        self.lbl_file_count.setVisible(False)
        self.lbl_file_count.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_file_count.mousePressEvent = lambda e: self.show_files_menu()
        input_layout.addWidget(self.lbl_file_count, 0, Qt.AlignmentFlag.AlignBottom)
        
        # Кнопка отправки
        self.btn_send = QPushButton("↑")
        self.btn_send.setFixedSize(28, 28)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self.start_agent)
        input_layout.addWidget(self.btn_send, 0, Qt.AlignmentFlag.AlignBottom)
        
        # Центральная часть (90%)
        input_center_layout.addWidget(self.input_frame, 18)
        
        # Правый отступ (5%)
        right_spacer = QWidget()
        right_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        input_center_layout.addWidget(right_spacer, 1)
        
        input_container_layout.addLayout(input_center_layout)
        center_layout.addWidget(self.input_container)
        
        # ПРАВАЯ ПАНЕЛЬ (стиль ChatGPT)
        self.right_panel = QFrame()
        self.right_panel.setFixedWidth(320)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setSpacing(16)
        right_layout.setContentsMargins(20, 20, 20, 20)
        
        # Выбор модели
        self.model_label = QLabel("Модель")
        right_layout.addWidget(self.model_label)
        
        self.combo_models = QComboBox()
        for name, mid in MODELS.items():
            self.combo_models.addItem(name, mid)
        # Устанавливаем Gemini 3 Pro по умолчанию
        self.combo_models.setCurrentIndex(1)
        right_layout.addWidget(self.combo_models)
        
        right_layout.addSpacing(8)
        
        # Путь к данным
        self.lbl_data_root = QLabel(f"📁 {self.data_root}")
        self.lbl_data_root.setWordWrap(True)
        right_layout.addWidget(self.lbl_data_root)
        
        # Логи
        self.logs_label = QLabel("Логи выполнения")
        right_layout.addWidget(self.logs_label)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        right_layout.addWidget(self.log_view)
        
        # Прогресс бар
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        right_layout.addWidget(self.progress)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(1, 1)
        content_layout.addWidget(splitter)
        
        main_layout.addWidget(content_widget)
        
        # Применяем тему
        self.apply_theme()
        
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

    def on_attach_clicked(self):
        """Обработчик клика по кнопке прикрепления файлов."""
        if self.selected_md_files:
            # Если файлы уже прикреплены, показываем меню
            menu = QMenu(self)
            menu.setStyleSheet("""
                QMenu {
                    background-color: white;
                    border: 1px solid #d1d5db;
                    border-radius: 8px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 8px 20px;
                    border-radius: 4px;
                }
                QMenu::item:selected {
                    background-color: #f3f4f6;
                }
            """)
            
            action_add = menu.addAction("➕ Добавить еще файлы")
            action_clear = menu.addAction("🗑️ Очистить все файлы")
            
            action = menu.exec(self.btn_attach.mapToGlobal(self.btn_attach.rect().bottomLeft()))
            
            if action == action_add:
                self.browse_md_files()
            elif action == action_clear:
                self.clear_md_files()
        else:
            # Если файлов нет, сразу открываем диалог
            self.browse_md_files()
    
    def browse_md_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 
            "Выберите файлы Markdown", 
            str(self.data_root), 
            "Markdown Files (*.md)"
        )
        if files:
            # Добавляем новые файлы к существующим
            for f in files:
                if f not in self.selected_md_files:
                    self.selected_md_files.append(f)
            self.update_file_indicator()
            self.log(f"Всего файлов: {len(self.selected_md_files)}")

    def clear_md_files(self):
        self.selected_md_files = []
        self.update_file_indicator()
    
    def update_file_indicator(self):
        """Обновляет индикатор количества прикрепленных файлов."""
        if self.selected_md_files:
            count = len(self.selected_md_files)
            self.lbl_file_count.setText(f"📎 {count}")
            self.lbl_file_count.setVisible(True)
            self.lbl_file_count.setToolTip("Нажмите, чтобы посмотреть список файлов")
        else:
            self.lbl_file_count.setVisible(False)
    
    def show_files_menu(self):
        """Показывает меню со списком прикрепленных файлов."""
        if not self.selected_md_files:
            return
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #d1d5db;
                border-radius: 8px;
                padding: 8px;
                min-width: 300px;
            }
            QMenu::item {
                padding: 8px 12px;
                border-radius: 4px;
                color: #2d333a;
            }
            QMenu::item:selected {
                background-color: #f3f4f6;
            }
            QMenu::separator {
                height: 1px;
                background: #e5e5e5;
                margin: 4px 0;
            }
        """)
        
        # Заголовок
        title_action = menu.addAction(f"📎 Прикрепленные файлы ({len(self.selected_md_files)})")
        title_action.setEnabled(False)
        menu.addSeparator()
        
        # Список файлов
        for idx, file_path in enumerate(self.selected_md_files):
            file_name = Path(file_path).name
            action = menu.addAction(f"  {file_name}")
            # Сохраняем индекс для удаления
            action.setData(idx)
        
        menu.addSeparator()
        clear_action = menu.addAction("🗑️ Очистить все")
        
        action = menu.exec(self.lbl_file_count.mapToGlobal(self.lbl_file_count.rect().bottomLeft()))
        
        if action == clear_action:
            self.clear_md_files()
        elif action and action.data() is not None:
            # Удаляем конкретный файл
            idx = action.data()
            if 0 <= idx < len(self.selected_md_files):
                removed_file = self.selected_md_files.pop(idx)
                self.update_file_indicator()
                self.log(f"Удален файл: {Path(removed_file).name}")

    def log(self, text):
        self.log_view.append(f"{datetime.now().strftime('%H:%M:%S')} {text}")

    def add_chat_message(self, role, text):
        w = ChatMessageWidget(role, text, is_dark_theme=self.is_dark_theme)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, w)
        QApplication.processEvents()
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def add_chat_image(self, path, desc):
        w = ImageMessageWidget(path, desc, is_dark_theme=self.is_dark_theme)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, w)
        QApplication.processEvents()
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def new_chat(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.txt_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.btn_attach.setEnabled(True)
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
                        # Ограничиваем длину запроса для отображения
                        display_query = query[:45] + "..." if len(query) > 45 else query
                        item = QListWidgetItem(f"💬 {display_query}")
                        item.setData(Qt.ItemDataRole.UserRole, str(hist_file))
                        item.setToolTip(query)  # Полный текст в подсказке
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
        query = self.txt_input.toPlainText().strip()
        if not query: return
        
        # ВАЖНО: Сохраняем список файлов ДО очистки чата!
        files_to_use = self.selected_md_files.copy()
        
        self.new_chat()
        self.add_chat_message("user", query)
        self.txt_input.clear()
        self.txt_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.btn_attach.setEnabled(False)
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
        self.btn_attach.setEnabled(True)
        self.progress.setVisible(False)
        self.log("Готово.")
    
    def toggle_theme(self):
        """Переключает тему интерфейса."""
        self.is_dark_theme = not self.is_dark_theme
        self.theme_toggle.setText("🌙" if self.is_dark_theme else "☀️")
        self.app_config["dark_theme"] = self.is_dark_theme
        save_config_file(self.app_config)
        self.apply_theme()
    
    def apply_theme(self):
        """Применяет текущую тему к интерфейсу."""
        if self.is_dark_theme:
            # ТЕМНАЯ ТЕМА
            # Общие стили
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #1e1e1e;
                }
                QMenuBar {
                    background-color: #2d2d2d;
                    color: #ececec;
                    border-bottom: 1px solid #3d3d3d;
                }
                QMenuBar::item {
                    background-color: transparent;
                    color: #ececec;
                    padding: 4px 8px;
                }
                QMenuBar::item:selected {
                    background-color: #3d3d3d;
                }
                QMenu {
                    background-color: #2d2d2d;
                    color: #ececec;
                    border: 1px solid #3d3d3d;
                }
                QMenu::item:selected {
                    background-color: #3d3d3d;
                }
                QScrollBar:vertical {
                    border: none;
                    background: transparent;
                    width: 8px;
                    margin: 0;
                }
                QScrollBar::handle:vertical {
                    background: #4d4d4f;
                    border-radius: 4px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #6e6e70;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    border: none;
                    background: none;
                }
            """)
            
            # Верхняя панель
            self.top_bar.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                    border-bottom: 1px solid #3d3d3d;
                }
            """)
            
            self.theme_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #3d3d3d;
                    color: white;
                    border: 1px solid #4d4d4f;
                    border-radius: 6px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #4d4d4f;
                }
            """)
            
            # Левая панель
            self.left_panel.setStyleSheet("""
                QFrame {
                    background-color: #171717;
                    border-right: 1px solid #2d2d2d;
                }
            """)
            
            self.btn_new_chat.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #ececec;
                    border: 1px solid #4d4d4f;
                    border-radius: 8px;
                    padding: 10px;
                    font-size: 13px;
                    text-align: left;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #2d2d2d;
                }
                QPushButton:pressed {
                    background-color: #3d3d3d;
                }
            """)
            
            self.history_label.setStyleSheet("""
                color: #8e8ea0;
                font-size: 11px;
                font-weight: 500;
                padding-left: 8px;
            """)
            
            self.list_history.setStyleSheet("""
                QListWidget {
                    border: none;
                    background: transparent;
                    outline: none;
                }
                QListWidget::item {
                    color: #ececec;
                    padding: 8px;
                    border-radius: 6px;
                    margin: 1px 0;
                    font-size: 12px;
                }
                QListWidget::item:hover {
                    background-color: #2d2d2d;
                }
                QListWidget::item:selected {
                    background-color: #3d3d3d;
                }
            """)
            
            # Центральная панель
            self.center_panel.setStyleSheet("""
                QFrame {
                    background-color: #2d2d2d;
                }
            """)
            
            self.scroll_area.setStyleSheet("""
                QScrollArea {
                    background-color: #2d2d2d;
                    border: none;
                }
            """)
            
            self.chat_container.setStyleSheet("""
                QWidget {
                    background-color: #2d2d2d;
                }
            """)
            
            self.input_container.setStyleSheet("background-color: #2d2d2d;")
            
            self.input_frame.setStyleSheet("""
                QFrame {
                    background-color: #3d3d3d;
                    border-radius: 12px;
                    border: 1px solid #4d4d4f;
                }
            """)
            
            self.btn_attach.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #8e8ea0;
                    border: none;
                    border-radius: 14px;
                    font-size: 18px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #4d4d4f;
                    color: #ececec;
                }
            """)
            
            self.txt_input.setStyleSheet("""
                QTextEdit {
                    background-color: transparent;
                    border: none;
                    color: #ececec;
                    font-size: 14px;
                    padding: 2px 8px;
                }
            """)
            
            self.lbl_file_count.setStyleSheet("""
                color: #10A37F;
                font-size: 12px;
                padding: 4px 8px;
                background-color: rgba(16, 163, 127, 0.2);
                border-radius: 12px;
            """)
            
            self.btn_send.setStyleSheet("""
                QPushButton {
                    background-color: #10A37F;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0d8c6d;
                }
                QPushButton:disabled {
                    background-color: #4d4d4f;
                }
            """)
            
            # Правая панель
            self.right_panel.setStyleSheet("""
                QFrame {
                    background-color: #1e1e1e;
                    border-left: 1px solid #2d2d2d;
                }
            """)
            
            self.model_label.setStyleSheet("""
                color: #ececec;
                font-size: 13px;
                font-weight: 600;
            """)
            
            self.combo_models.setStyleSheet("""
                QComboBox {
                    background-color: #3d3d3d;
                    border: 1px solid #4d4d4f;
                    border-radius: 8px;
                    padding: 10px;
                    color: #ececec;
                    font-size: 13px;
                }
                QComboBox:hover {
                    border-color: #10A37F;
                }
                QComboBox::drop-down {
                    border: none;
                    padding-right: 10px;
                }
                QComboBox QAbstractItemView {
                    background-color: #3d3d3d;
                    color: #ececec;
                    selection-background-color: #4d4d4f;
                }
            """)
            
            self.lbl_data_root.setStyleSheet("""
                color: #8e8ea0;
                font-size: 11px;
                padding: 8px;
                background-color: #2d2d2d;
                border-radius: 6px;
            """)
            
            self.logs_label.setStyleSheet("""
                color: #ececec;
                font-size: 13px;
                font-weight: 600;
                margin-top: 8px;
            """)
            
            self.log_view.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 11px;
                    background-color: #0d0d0d;
                    color: #d4d4d4;
                    border: 1px solid #2d2d2d;
                    border-radius: 8px;
                    padding: 12px;
                }
            """)
            
            self.progress.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 4px;
                    background-color: #2d2d2d;
                    height: 4px;
                }
                QProgressBar::chunk {
                    background-color: #10A37F;
                    border-radius: 4px;
                }
            """)
        else:
            # СВЕТЛАЯ ТЕМА
            # Общие стили
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #ffffff;
                }
                QMenuBar {
                    background-color: #f7f7f8;
                    color: #2d333a;
                    border-bottom: 1px solid #e5e5e5;
                }
                QMenuBar::item {
                    background-color: transparent;
                    color: #2d333a;
                    padding: 4px 8px;
                }
                QMenuBar::item:selected {
                    background-color: #e5e5e5;
                }
                QMenu {
                    background-color: white;
                    color: #2d333a;
                    border: 1px solid #d1d5db;
                }
                QMenu::item:selected {
                    background-color: #f3f4f6;
                }
                QScrollBar:vertical {
                    border: none;
                    background: transparent;
                    width: 8px;
                    margin: 0;
                }
                QScrollBar::handle:vertical {
                    background: #d1d5db;
                    border-radius: 4px;
                    min-height: 20px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #9ca3af;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    border: none;
                    background: none;
                }
            """)
            
            # Верхняя панель
            self.top_bar.setStyleSheet("""
                QFrame {
                    background-color: #f7f7f8;
                    border-bottom: 1px solid #e5e5e5;
                }
            """)
            
            self.theme_toggle.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    color: #2d333a;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #f3f4f6;
                }
            """)
            
            # Левая панель
            self.left_panel.setStyleSheet("""
                QFrame {
                    background-color: #f7f7f8;
                    border-right: 1px solid #e5e5e5;
                }
            """)
            
            self.btn_new_chat.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #2d333a;
                    border: 1px solid #d1d5db;
                    border-radius: 8px;
                    padding: 10px;
                    font-size: 13px;
                    text-align: left;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #e5e5e5;
                }
                QPushButton:pressed {
                    background-color: #d1d5db;
                }
            """)
            
            self.history_label.setStyleSheet("""
                color: #6e6e80;
                font-size: 11px;
                font-weight: 500;
                padding-left: 8px;
            """)
            
            self.list_history.setStyleSheet("""
                QListWidget {
                    border: none;
                    background: transparent;
                    outline: none;
                }
                QListWidget::item {
                    color: #2d333a;
                    padding: 8px;
                    border-radius: 6px;
                    margin: 1px 0;
                    font-size: 12px;
                }
                QListWidget::item:hover {
                    background-color: #e5e5e5;
                }
                QListWidget::item:selected {
                    background-color: #d1d5db;
                }
            """)
            
            # Центральная панель
            self.center_panel.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                }
            """)
            
            self.scroll_area.setStyleSheet("""
                QScrollArea {
                    background-color: #ffffff;
                    border: none;
                }
            """)
            
            self.chat_container.setStyleSheet("""
                QWidget {
                    background-color: #ffffff;
                }
            """)
            
            self.input_container.setStyleSheet("background-color: #ffffff;")
            
            self.input_frame.setStyleSheet("""
                QFrame {
                    background-color: #f4f4f4;
                    border-radius: 12px;
                    border: 1px solid #e5e5e5;
                }
            """)
            
            self.btn_attach.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #8e8ea0;
                    border: none;
                    border-radius: 14px;
                    font-size: 18px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #e5e5e5;
                    color: #2d333a;
                }
            """)
            
            self.txt_input.setStyleSheet("""
                QTextEdit {
                    background-color: transparent;
                    border: none;
                    color: #2d333a;
                    font-size: 14px;
                    padding: 2px 8px;
                }
            """)
            
            self.lbl_file_count.setStyleSheet("""
                color: #10A37F;
                font-size: 12px;
                padding: 4px 8px;
                background-color: #d1f4e8;
                border-radius: 12px;
            """)
            
            self.btn_send.setStyleSheet("""
                QPushButton {
                    background-color: #10A37F;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0d8c6d;
                }
                QPushButton:disabled {
                    background-color: #d0d0d0;
                }
            """)
            
            # Правая панель
            self.right_panel.setStyleSheet("""
                QFrame {
                    background-color: #f7f7f8;
                    border-left: 1px solid #ececf1;
                }
            """)
            
            self.model_label.setStyleSheet("""
                color: #2d333a;
                font-size: 13px;
                font-weight: 600;
            """)
            
            self.combo_models.setStyleSheet("""
                QComboBox {
                    background-color: white;
                    border: 1px solid #d1d5db;
                    border-radius: 8px;
                    padding: 10px;
                    color: #2d333a;
                    font-size: 13px;
                }
                QComboBox:hover {
                    border-color: #10A37F;
                }
                QComboBox::drop-down {
                    border: none;
                    padding-right: 10px;
                }
                QComboBox QAbstractItemView {
                    background-color: white;
                    color: #2d333a;
                    selection-background-color: #f3f4f6;
                }
            """)
            
            self.lbl_data_root.setStyleSheet("""
                color: #6e6e80;
                font-size: 11px;
                padding: 8px;
                background-color: #ececf1;
                border-radius: 6px;
            """)
            
            self.logs_label.setStyleSheet("""
                color: #2d333a;
                font-size: 13px;
                font-weight: 600;
                margin-top: 8px;
            """)
            
            self.log_view.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 11px;
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    border: 1px solid #2d2d2d;
                    border-radius: 8px;
                    padding: 12px;
                }
            """)
            
            self.progress.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 4px;
                    background-color: #ececf1;
                    height: 4px;
                }
                QProgressBar::chunk {
                    background-color: #10A37F;
                    border-radius: 4px;
                }
            """)
        
        # Обновляем тему для всех существующих сообщений в чате
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, ChatMessageWidget) or isinstance(widget, ImageMessageWidget):
                    widget.apply_theme(self.is_dark_theme)

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
