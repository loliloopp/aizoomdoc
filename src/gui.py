"""
Графический интерфейс приложения (PyQt6).
"""

import sys
import os
import json
import shutil
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QComboBox, QSplitter,
    QListWidget, QListWidgetItem, QFrame, QScrollArea, QProgressBar,
    QFileDialog, QMenuBar, QMenu, QDialog, QDialogButtonBox, QMessageBox,
    QGroupBox, QSizePolicy, QTreeView, QButtonGroup, QInputDialog,
    QHeaderView, QTabWidget
)
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import (
    QFont, QPixmap, QAction, QDragEnterEvent, QDropEvent, 
    QTextCursor, QKeyEvent, QFileSystemModel, QStandardItemModel, QStandardItem
)

from .config import config
from .gui_agent import AgentWorker
from .supabase_client import supabase_client
from .s3_storage import s3_storage
from .utils import transliterate
import asyncio

MODELS = {
    "Gemini 3 Flash": "gemini-3-flash-preview",
    "Gemini 3 Pro": "gemini-3-pro-preview",
    "Gemini 3 Flash (openrouter)": "google/gemini-3-flash-preview",
    "Gemini 3 Pro (openrouter)": "google/gemini-3-pro-preview",
    "Qwen3 VL": "qwen/qwen3-vl-235b-a22b-thinking"
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
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        
        layout = QVBoxLayout(self)
        
        # Используем вкладки для разделения настроек
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # --- ВКЛАДКА: ОБЩИЕ ---
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        
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
        
        general_layout.addWidget(gb_data)
        
        # 1.1. Выбор модели по умолчанию
        gb_model = QGroupBox("Модель по умолчанию")
        model_layout = QVBoxLayout(gb_model)
        self.combo_default_model = QComboBox()
        for name, mid in MODELS.items():
            self.combo_default_model.addItem(name, mid)
        
        # Загружаем текущую модель по умолчанию
        if config.USE_DATABASE and supabase_client.is_connected():
            try:
                def_model = asyncio.run(supabase_client.get_default_model())
                if def_model:
                    idx = self.combo_default_model.findData(def_model)
                    if idx >= 0:
                        self.combo_default_model.setCurrentIndex(idx)
            except Exception as e:
                print(f"Ошибка загрузки модели по умолчанию: {e}")
        
        model_layout.addWidget(self.combo_default_model)
        general_layout.addWidget(gb_model)
        
        # 2. Группа "Системные Промты AI"
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
        
        prompts_layout_main.addSpacing(10)
        
        # 2.3. Промт для JSON файлов
        prompts_layout_main.addWidget(QLabel("📌 ДОПОЛНИТЕЛЬНО: JSON аннотации (json_annotation_prompt.txt):"))
        
        json_file_layout = QHBoxLayout()
        self.json_prompt_label = QLineEdit()
        self.json_prompt_label.setReadOnly(True)
        self.json_prompt_label.setText(str(data_root / "json_annotation_prompt.txt"))
        
        btn_edit_json = QPushButton("Редактировать...")
        btn_edit_json.clicked.connect(self.edit_json_prompt)
        
        json_file_layout.addWidget(self.json_prompt_label)
        json_file_layout.addWidget(btn_edit_json)
        prompts_layout_main.addLayout(json_file_layout)
        
        prompts_layout_main.addSpacing(10)
        
        # 2.4. Промт для HTML файлов
        prompts_layout_main.addWidget(QLabel("📌 ДОПОЛНИТЕЛЬНО: HTML OCR (html_ocr_prompt.txt):"))
        
        html_file_layout = QHBoxLayout()
        self.html_prompt_label = QLineEdit()
        self.html_prompt_label.setReadOnly(True)
        self.html_prompt_label.setText(str(data_root / "html_ocr_prompt.txt"))
        
        btn_edit_html = QPushButton("Редактировать...")
        btn_edit_html.clicked.connect(self.edit_html_prompt)
        
        html_file_layout.addWidget(self.html_prompt_label)
        html_file_layout.addWidget(btn_edit_html)
        prompts_layout_main.addLayout(html_file_layout)
        
        general_layout.addWidget(gb_prompts)
        general_layout.addStretch()
        
        self.tabs.addTab(general_tab, "Общие")
        
        # --- ВКЛАДКА: ПОЛЬЗОВАТЕЛЬСКИЕ ПРОМТЫ ---
        prompts_tab = QWidget()
        prompts_tab_layout = QVBoxLayout(prompts_tab)
        self.prompts_manager = UserPromptsSettingsWidget()
        prompts_tab_layout.addWidget(self.prompts_manager)
        
        self.tabs.addTab(prompts_tab, "Промты")
        
        # Кнопки
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
1. Документ содержит блоки описания изображений в формате JSON.
2. Каждый блок содержит:
   - `doc_metadata`: метаданные (имя файла, номер страницы).
   - `image`: объект с полем `uri` — ПРЯМАЯ ССЫЛКА на изображение.
   - `analysis`: объект с результатами анализа, содержащий вложенный объект `analysis`:
     - `content_summary`: краткое описание.
     - `detailed_description`: подробное описание.
     - `clean_ocr_text`: распознанный текст (OCR).
     - `key_entities`: ключевые сущности.

ИНСТРУКЦИЯ:
1. Прочитай запрос пользователя.
2. Найди в тексте блоки JSON, которые релевантны запросу.
   - Используй `content_summary`, `detailed_description`, `clean_ocr_text` и `doc_metadata.page` для поиска.
3. Извлеки URL изображения из поля `image.uri` внутри найденного JSON блока.
4. Верни JSON:
```json
{
  "reasoning": "Нужен план 1 этажа (найден блок на стр. 9 с описанием 'Ситуационный план')",
  "needs_images": true,
  "image_urls": ["https://..."]
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

ПОРЯДОК РАБОТЫ (ОБЯЗАТЕЛЬНО ПЕРЕД ОТВЕТОМ):
1. Сначала тщательно изучи текстовую информацию и таблицы (включая спецификации и OCR‑текст).
2. Затем внимательно изучи изображения. Если детали не читаются на превью — запрашивай ZOOM и изучай зумы.
3. Сопоставь данные из текста/таблиц и изображений/зумов, отметь источники и возможные противоречия.
4. Только после этого делай выводы и формулируй ответ на основе суммарной информации. Если данных не хватает — явно скажи об этом.

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
    
    def edit_json_prompt(self):
        """Редактирование промта для JSON аннотаций"""
        prompt_file = Path(self.json_prompt_label.text())
        
        if not prompt_file.exists():
            QMessageBox.warning(self, "Файл не найден", 
                f"Файл {prompt_file} не найден.\nОн должен быть создан в папке data/")
            return
        
        dialog = PromptEditDialog(self, prompt_file)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Сохранено", f"Промт для JSON сохранён в:\n{prompt_file}")
    
    def edit_html_prompt(self):
        """Редактирование промта для HTML OCR"""
        prompt_file = Path(self.html_prompt_label.text())
        
        if not prompt_file.exists():
            QMessageBox.warning(self, "Файл не найден", 
                f"Файл {prompt_file} не найден.\nОн должен быть создан в папке data/")
            return
        
        dialog = PromptEditDialog(self, prompt_file)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Сохранено", f"Промт для HTML сохранён в:\n{prompt_file}")
    
    def get_data_root(self):
        return self.path_edit.text()

    def get_default_model(self):
        return self.combo_default_model.currentData()


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


class UserPromptEditDialog(QDialog):
    """Диалог добавления/редактирования пользовательского промта."""
    def __init__(self, parent=None, name="", content=""):
        super().__init__(parent)
        self.setWindowTitle("Пользовательский промт")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Название:"))
        self.name_edit = QLineEdit(name)
        layout.addWidget(self.name_edit)
        
        layout.addWidget(QLabel("Промт:"))
        self.content_edit = QTextEdit(content)
        self.content_edit.setMinimumHeight(200)
        layout.addWidget(self.content_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_data(self):
        return self.name_edit.text().strip(), self.content_edit.toPlainText().strip()


class UserPromptsSettingsWidget(QWidget):
    """Виджет управления пользовательскими промтами в настройках."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        self.btn_add = QPushButton("+ Добавить промт")
        self.btn_add.clicked.connect(self.add_prompt)
        self.layout.addWidget(self.btn_add)
        
        self.list_prompts = QListWidget()
        self.layout.addWidget(self.list_prompts)
        
        # Контейнер для кнопок управления выбранным промтом
        actions_layout = QHBoxLayout()
        self.btn_edit = QPushButton("Редактировать")
        self.btn_edit.clicked.connect(self.edit_prompt)
        self.btn_delete = QPushButton("Удалить")
        self.btn_delete.clicked.connect(self.delete_prompt)
        
        actions_layout.addWidget(self.btn_edit)
        actions_layout.addWidget(self.btn_delete)
        self.layout.addLayout(actions_layout)
        
        self.load_prompts()
        
    def load_prompts(self):
        self.list_prompts.clear()
        if not supabase_client.is_connected():
            return
            
        try:
            # Используем asyncio.run для синхронного вызова в GUI (упрощенно)
            prompts = asyncio.run(supabase_client.get_user_prompts())
            for p in prompts:
                item = QListWidgetItem(p["name"])
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.list_prompts.addItem(item)
        except Exception as e:
            print(f"Ошибка загрузки промтов: {e}")

    def add_prompt(self):
        dialog = UserPromptEditDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, content = dialog.get_data()
            if name and content:
                try:
                    asyncio.run(supabase_client.create_user_prompt(name, content))
                    self.load_prompts()
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось создать промт: {e}")

    def edit_prompt(self):
        item = self.list_prompts.currentItem()
        if not item:
            return
            
        data = item.data(Qt.ItemDataRole.UserRole)
        dialog = UserPromptEditDialog(self, name=data["name"], content=data["content"])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, content = dialog.get_data()
            if name and content:
                try:
                    asyncio.run(supabase_client.update_user_prompt(data["id"], name, content))
                    self.load_prompts()
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось обновить промт: {e}")

    def delete_prompt(self):
        item = self.list_prompts.currentItem()
        if not item:
            return
            
        data = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, "Удаление", f"Удалить промт '{data['name']}'?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                asyncio.run(supabase_client.delete_user_prompt(data["id"]))
                self.load_prompts()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось удалить промт: {e}")


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
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(self.lbl_desc)
        
        # Изображение
        self.lbl_image = QLabel()
        
        # Проверяем, это локальный путь или URL
        if image_path.startswith(("http://", "https://")):
            # Загружаем из сети асинхронно
            self.lbl_image.setText("Загрузка изображения...")
            self.load_image_from_url(image_path)
        else:
            pixmap = QPixmap(image_path)
            if pixmap.width() > 600:
                pixmap = pixmap.scaledToWidth(600, Qt.TransformationMode.SmoothTransformation)
            self.lbl_image.setPixmap(pixmap)
            
        content_layout.addWidget(self.lbl_image)
        
        main_layout.addWidget(self.content_widget)
        
        self.apply_theme(is_dark_theme)

    def load_image_from_url(self, url):
        """Загружает изображение по URL и отображает его."""
        import requests
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class ImageLoader(QThread):
            finished = pyqtSignal(bytes)
            def run(self):
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        self.finished.emit(response.content)
                except:
                    pass
        
        self.loader = ImageLoader(self)
        def on_loaded(data):
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                if pixmap.width() > 600:
                    pixmap = pixmap.scaledToWidth(600, Qt.TransformationMode.SmoothTransformation)
                self.lbl_image.setPixmap(pixmap)
            else:
                self.lbl_image.setText("Ошибка загрузки изображения")
                
        self.loader.finished.connect(on_loaded)
        self.loader.start()
    
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
        self.current_chat_id = None
        self.current_db_chat_id = None
        
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
        
        # Вкладки переключения левой панели
        tabs_container = QWidget()
        tabs_layout = QHBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(4)

        self.btn_tab_chats = QPushButton("Чаты")
        self.btn_tab_chats.setCheckable(True)
        self.btn_tab_chats.setChecked(True)
        self.btn_tab_chats.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_chats.clicked.connect(lambda: self.switch_left_tab("chats"))
        self.btn_tab_chats.setFixedSize(80, 34)

        self.btn_tab_folders = QPushButton("Папки")
        self.btn_tab_folders.setCheckable(True)
        self.btn_tab_folders.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_folders.clicked.connect(lambda: self.switch_left_tab("folders"))
        self.btn_tab_folders.setFixedSize(80, 34)
        
        # Группа для взаимоисключения (визуально)
        self.left_tabs_group = QButtonGroup(self)
        self.left_tabs_group.addButton(self.btn_tab_chats)
        self.left_tabs_group.addButton(self.btn_tab_folders)
        
        tabs_layout.addWidget(self.btn_tab_chats)
        tabs_layout.addWidget(self.btn_tab_folders)

        top_bar_layout.addWidget(tabs_container)
        
        top_bar_layout.addStretch()
        
        # Переключатель режима MD (RAG / Full MD)
        self.combo_md_mode = QComboBox()
        self.combo_md_mode.addItem("RAG (блоки)", "rag")
        self.combo_md_mode.addItem("Полный MD", "full_md")
        self.combo_md_mode.setFixedWidth(140)
        self.combo_md_mode.setFixedHeight(34)
        self.combo_md_mode.currentIndexChanged.connect(self.save_md_mode)
        top_bar_layout.addWidget(self.combo_md_mode)
        
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
        left_layout.setSpacing(0)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- ВКЛАДКА ЧАТЫ ---
        self.chats_widget = QWidget()
        chats_layout = QVBoxLayout(self.chats_widget)
        chats_layout.setSpacing(8)
        chats_layout.setContentsMargins(12, 12, 12, 12)

        # Кнопка "Новый чат" в стиле ChatGPT
        self.btn_new_chat = QPushButton("+ Новый чат")
        self.btn_new_chat.clicked.connect(self.new_chat)
        chats_layout.addWidget(self.btn_new_chat)
        
        chats_layout.addSpacing(12)
        
        # Заголовок истории
        self.history_label = QLabel("Недавние чаты")
        chats_layout.addWidget(self.history_label)
        
        # Список истории
        self.list_history = QListWidget()
        self.list_history.itemClicked.connect(self.load_chat_history)
        self.list_history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_history.customContextMenuRequested.connect(self.show_chat_context_menu)
        chats_layout.addWidget(self.list_history)
        
        left_layout.addWidget(self.chats_widget)

        # --- ВКЛАДКА ПАПКИ ---
        self.folders_widget = QWidget()
        self.folders_widget.setVisible(False)
        folders_layout = QVBoxLayout(self.folders_widget)
        folders_layout.setSpacing(8)
        folders_layout.setContentsMargins(12, 12, 12, 12)
        
        # Кнопки управления папками
        folders_btns_layout = QHBoxLayout()
        folders_btns_layout.setSpacing(4)
        
        self.btn_new_folder = QPushButton("+ Папка")
        self.btn_new_folder.clicked.connect(self.create_new_folder)
        self.btn_new_folder.setToolTip("Создать тематическую папку")
        
        self.btn_refresh_folders = QPushButton("🔄")
        self.btn_refresh_folders.setFixedWidth(30)
        self.btn_refresh_folders.clicked.connect(self.refresh_folders)
        
        folders_btns_layout.addWidget(self.btn_new_folder)
        folders_btns_layout.addWidget(self.btn_refresh_folders)
        folders_layout.addLayout(folders_btns_layout)
        
        self.folders_label = QLabel("Файлы проекта")
        folders_layout.addWidget(self.folders_label)
        
        # Дерево файлов
        self.tree_folders = QTreeView()
        self.tree_folders.setHeaderHidden(True)
        self.tree_folders.setIndentation(20)
        self.tree_folders.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_folders.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree_folders.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        
        # Логическая модель (БД)
        self.logical_model = QStandardItemModel()
        self.tree_folders.setModel(self.logical_model)
        
        self.tree_folders.doubleClicked.connect(self.on_tree_double_clicked)
        folders_layout.addWidget(self.tree_folders)
        
        # Кнопка прикрепления выбранных
        self.btn_attach_selected = QPushButton("📎 Прикрепить выбранные")
        self.btn_attach_selected.clicked.connect(self.attach_selected_from_tree)
        folders_layout.addWidget(self.btn_attach_selected)
        
        left_layout.addWidget(self.folders_widget)
        
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
        
        # Выпадающий список пользовательских промтов
        self.combo_user_prompts = QComboBox()
        self.combo_user_prompts.setFixedWidth(150)
        self.combo_user_prompts.setToolTip("Выберите пользовательский промт")
        self.load_user_prompts()
        input_layout.addWidget(self.combo_user_prompts, 0, Qt.AlignmentFlag.AlignBottom)
        
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
        
        # Кнопка остановки
        self.btn_stop = QPushButton("■")
        self.btn_stop.setFixedSize(28, 28)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setVisible(False)  # Скрыта по умолчанию
        self.btn_stop.clicked.connect(self.stop_agent)
        input_layout.addWidget(self.btn_stop, 0, Qt.AlignmentFlag.AlignBottom)
        
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
        # Устанавливаем Gemini 3 Flash по умолчанию (индекс 0)
        self.combo_models.setCurrentIndex(0)
        right_layout.addWidget(self.combo_models)
        
        right_layout.addSpacing(8)
        
        # Путь к данным
        self.lbl_data_root = QLabel(f"📁 {self.data_root}")
        self.lbl_data_root.setWordWrap(True)
        right_layout.addWidget(self.lbl_data_root)
        
        # Счетчик использования
        self.usage_frame = QFrame()
        self.usage_frame.setStyleSheet("""
            QFrame {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 4px;
            }
            QLabel {
                font-size: 11px;
                color: #4b5563;
                border: none;
                background: transparent;
            }
        """)
        usage_layout = QHBoxLayout(self.usage_frame)
        usage_layout.setContentsMargins(8, 4, 8, 4)
        
        self.lbl_used = QLabel("Использовано: 0")
        self.lbl_remaining = QLabel("Осталось: 0")
        
        usage_layout.addWidget(self.lbl_used)
        usage_layout.addStretch()
        usage_layout.addWidget(self.lbl_remaining)
        
        right_layout.addWidget(self.usage_frame)
        
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
        
        # Загружаем настройки режима MD из БД
        self.load_md_mode()
        
        # Загружаем модель по умолчанию из БД
        self.load_default_model()
        
        self.refresh_history_list()

    def load_default_model(self):
        """Загружает модель по умолчанию из БД."""
        if config.USE_DATABASE and supabase_client.is_connected():
            try:
                def_model = self.run_async(supabase_client.get_default_model())
                if def_model:
                    idx = self.combo_models.findData(def_model)
                    if idx >= 0:
                        self.combo_models.setCurrentIndex(idx)
            except Exception as e:
                print(f"Ошибка загрузки модели по умолчанию: {e}")

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            # 1. Сохраняем модель по умолчанию в БД
            new_model = dialog.get_default_model()
            if config.USE_DATABASE and supabase_client.is_connected():
                try:
                    self.run_async(supabase_client.set_default_model(new_model))
                    # Обновляем текущий выбор в главном окне
                    idx = self.combo_models.findData(new_model)
                    if idx >= 0:
                        self.combo_models.setCurrentIndex(idx)
                except Exception as e:
                    print(f"Ошибка сохранения модели по умолчанию: {e}")

            self.load_user_prompts() # Перезагружаем промты после настроек
            new_path = dialog.get_data_root()
            if new_path:
                self.data_root = Path(new_path)
                self.data_root.mkdir(parents=True, exist_ok=True)
                self.app_config["data_root"] = str(self.data_root)
                save_config_file(self.app_config)
                self.lbl_data_root.setText(f"📁 {self.data_root}")
                self.refresh_history_list()
                QMessageBox.information(self, "Настройки", f"Папка обновлена:\n{self.data_root}")

    def load_user_prompts(self):
        """Загружает список пользовательских промтов в выпадающий список."""
        self.combo_user_prompts.clear()
        self.combo_user_prompts.addItem("Без промта", None)
        
        if config.USE_DATABASE and supabase_client.is_connected():
            try:
                prompts = self.run_async(supabase_client.get_user_prompts())
                for p in prompts:
                    # Избегаем дублирования системного пункта "Без промта"
                    if p["name"] != "Без промта":
                        self.combo_user_prompts.addItem(p["name"], p["content"])
            except Exception as e:
                print(f"Ошибка загрузки пользовательских промтов: {e}")

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
            "Выберите файлы", 
            str(self.data_root), 
            "Поддерживаемые файлы (*.md *.jpg *.png *.html *.json);;Все файлы (*)"
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

    def update_usage(self, used, remaining):
        """Обновляет счетчик использованного и оставшегося контента."""
        self.lbl_used.setText(f"Использовано: {used:,}".replace(",", " "))
        self.lbl_remaining.setText(f"Осталось: {remaining:,}".replace(",", " "))

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
        self.current_chat_id = None
        self.current_db_chat_id = None
        self.update_usage(0, 0)

    def show_chat_context_menu(self, pos):
        """Контекстное меню для списка чатов."""
        item = self.list_history.itemAt(pos)
        if not item: return
        
        menu = QMenu()
        delete_action = menu.addAction("🗑️ Удалить чат")
        
        action = menu.exec(self.list_history.mapToGlobal(pos))
        if action == delete_action:
            self.confirm_delete_chat(item)

    def confirm_delete_chat(self, item):
        """Подтверждение удаления чата."""
        chat_name = item.text()
        reply = QMessageBox.question(
            self, "Удаление чата",
            f"Вы уверены, что хотите полностью удалить чат '{chat_name}'?\n"
            "Это удалит данные из БД, S3 и локальной папки.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.perform_delete_chat(item)

    def perform_delete_chat(self, item):
        """Выполнение удаления чата (БД + S3 + Локально)."""
        data_id = item.data(Qt.ItemDataRole.UserRole)
        origin = item.data(Qt.ItemDataRole.UserRole + 1)
        
        try:
            if origin == "cloud":
                # 1. Получаем инфо о чате для метаданных
                chat_info = self.run_async(supabase_client.get_chat(data_id))
                local_chat_id = None
                if chat_info and "metadata" in chat_info:
                    local_chat_id = chat_info["metadata"].get("local_chat_id")
                
                # 2. Удаляем из S3
                if s3_storage.is_connected():
                    self.log(f"Удаление файлов чата {data_id} из S3...")
                    # Удаляем и картинки и документы этого чата
                    self.run_async(s3_storage.delete_folder(f"chats/{data_id}/"))
                
                # 3. Удаляем из БД
                self.log(f"Удаление чата {data_id} из БД...")
                self.run_async(supabase_client.delete_chat(data_id))
                
                # 4. Удаляем локальную папку (если есть)
                if local_chat_id:
                    local_dir = self.data_root / "chats" / local_chat_id
                    if local_dir.exists():
                        self.log(f"Удаление локальной папки {local_chat_id}...")
                        shutil.rmtree(local_dir)
                else:
                    # Попытка найти локальную папку по названию если UUID не совпадает
                    # (на случай если мы в облаке видим чат, созданный на этой же машине)
                    pass
            else:
                # Локальное удаление
                history_file = Path(data_id)
                chat_dir = history_file.parent
                if chat_dir.exists():
                    self.log(f"Удаление локальной папки {chat_dir.name}...")
                    shutil.rmtree(chat_dir)
            
            self.log("Чат успешно удален.")
            self.refresh_history_list()
            # Очищаем текущий экран чата
            self.new_chat()
            
        except Exception as e:
            self.log(f"Ошибка при удалении чата: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось полностью удалить чат: {e}")

    def refresh_history_list(self):
        self.list_history.clear()
        
        cloud_local_ids = set()
        
        # 1. Загружаем из облака, если включено
        if config.USE_DATABASE and supabase_client.is_connected():
            try:
                chats = self.run_async(supabase_client.get_chats())
                for chat in chats:
                    title = chat.get("title") or chat.get("description", "Без названия")
                    display_query = title[:45] + "..." if len(title) > 45 else title
                    item = QListWidgetItem(f"☁️ {display_query}")
                    item.setData(Qt.ItemDataRole.UserRole, chat["id"])
                    item.setData(Qt.ItemDataRole.UserRole + 1, "cloud")
                    item.setToolTip(title)
                    self.list_history.addItem(item)
                    
                    # Запоминаем локальный ID, чтобы не дублировать
                    if chat.get("metadata") and isinstance(chat["metadata"], dict):
                        local_id = chat["metadata"].get("local_chat_id")
                        if local_id:
                            cloud_local_ids.add(local_id)
            except Exception as e:
                print(f"Ошибка загрузки чатов из БД: {e}")

        # 2. Загружаем локальные чаты
        chats_dir = self.data_root / "chats"
        if not chats_dir.exists(): return
        
        dirs = sorted([d for d in chats_dir.iterdir() if d.is_dir()], reverse=True)
        
        for d in dirs:
            hist_file = d / "history.json"
            if hist_file.exists():
                try:
                    with open(hist_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                        # Пропускаем, если этот чат уже загружен из облака
                        local_id = data.get("id")
                        if local_id in cloud_local_ids:
                            continue
                            
                        query = data.get("query", "Без названия")
                        # Ограничиваем длину запроса для отображения
                        display_query = query[:45] + "..." if len(query) > 45 else query
                        item = QListWidgetItem(f"💬 {display_query}")
                        item.setData(Qt.ItemDataRole.UserRole, str(hist_file))
                        item.setData(Qt.ItemDataRole.UserRole + 1, "local")
                        item.setToolTip(query)  # Полный текст в подсказке
                        self.list_history.addItem(item)
                except: pass

    def run_async(self, coro):
        """Вспомогательный метод для запуска асинхронных задач без предупреждений."""
        return asyncio.run(coro)

    def load_chat_history(self, item):
        data_id = item.data(Qt.ItemDataRole.UserRole)
        origin = item.data(Qt.ItemDataRole.UserRole + 1)
        
        self.new_chat()
        
        if origin == "cloud":
            try:
                self.current_db_chat_id = data_id
                self.log(f"Загрузка чата {data_id} из облака...")
                
                # Загружаем инфо о чате для получения метаданных (local_chat_id)
                chat_info = self.run_async(supabase_client.get_chat(data_id))
                if chat_info and "metadata" in chat_info:
                    self.current_chat_id = chat_info["metadata"].get("local_chat_id")
                    self.selected_md_files = chat_info["metadata"].get("md_files", [])
                    self.update_file_indicator()

                messages = self.run_async(supabase_client.get_chat_messages(data_id))
                for msg in messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    self.add_chat_message(role, content)
                    
                    # Проверяем наличие картинок в сообщении
                    images = self.run_async(supabase_client.get_message_images(msg["id"]))
                    for img in images:
                        # В новой схеме путь лежит в storage_files, связанном через file_id
                        # Проверяем оба варианта для совместимости
                        s3_key = img.get("s3_key") # Старый вариант
                        
                        if not s3_key and img.get("file_id"):
                            # Новый вариант: нужно получить storage_path из storage_files
                            try:
                                file_info = self.run_async(supabase_client.get_file_info(img["file_id"]))
                                if file_info:
                                    s3_key = file_info.get("storage_path")
                            except: pass

                        if s3_key and s3_storage.is_connected():
                            # Получаем временный URL для отображения
                            url = s3_storage.get_signed_url(s3_key)
                            if url:
                                # TODO: ImageMessageWidget пока не умеет грузить по URL
                                # Но мы хотя бы пытаемся
                                self.add_chat_image(url, "Из облака")
                
                self.log("История загружена из облака.")
                return
            except Exception as e:
                self.log(f"Ошибка загрузки истории из облака: {e}")
                return

        # Локальная загрузка
        path = data_id
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.current_chat_id = data.get("id")
                self.selected_md_files = data.get("md_files", [])
                self.update_file_indicator()
                
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
        
        # ВАЖНО: Сохраняем список файлов
        files_to_use = self.selected_md_files.copy()
        
        # Если это новый вопрос в существующем чате - не очищаем чат
        if not self.current_chat_id:
            self.new_chat()
            
        self.add_chat_message("user", query)
        self.txt_input.clear()
        self.txt_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.btn_send.setVisible(False)  # Скрываем кнопку отправки
        self.btn_stop.setVisible(True)   # Показываем кнопку остановки
        self.btn_attach.setEnabled(False)
        self.progress.setVisible(True)
        
        mid = self.combo_models.currentData()
        md_mode = self.combo_md_mode.currentData()
        user_prompt = self.combo_user_prompts.currentData()
        
        # Передаем сохраненные md файлы и текущие ID чата в воркера
        self.current_worker = AgentWorker(
            self.data_root, 
            query, 
            mid, 
            md_files=files_to_use,
            existing_chat_id=self.current_chat_id,
            existing_db_chat_id=self.current_db_chat_id,
            md_mode=md_mode,
            user_prompt=user_prompt
        )
        self.current_worker.sig_log.connect(self.log)
        self.current_worker.sig_message.connect(self.add_chat_message)
        self.current_worker.sig_image.connect(self.add_chat_image)
        self.current_worker.sig_finished.connect(self.on_finished)
        self.current_worker.sig_history_saved.connect(self.on_history_saved)
        self.current_worker.sig_usage.connect(self.update_usage)
        self.current_worker.start()
    
    def stop_agent(self):
        """Останавливает текущий воркер."""
        if self.current_worker:
            self.log("⚠️ Остановка диалога...")
            self.current_worker.stop()
            # Не ждем завершения, просто возвращаем интерфейс
            self.txt_input.setEnabled(True)
            self.btn_send.setEnabled(True)
            self.btn_send.setVisible(True)
            self.btn_stop.setVisible(False)
            self.btn_attach.setEnabled(True)
            self.progress.setVisible(False)
            self.log("Диалог остановлен.")

    def on_history_saved(self, chat_id, title):
        """Обновляет текущие ID чата после первого сохранения."""
        self.current_chat_id = chat_id
        # Если воркер сохранил db_chat_id, мы должны его тоже запомнить
        if hasattr(self.current_worker, 'db_chat_id'):
            self.current_db_chat_id = self.current_worker.db_chat_id
        self.refresh_history_list()

    def on_finished(self):
        self.txt_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.btn_send.setVisible(True)
        self.btn_stop.setVisible(False)
        self.btn_attach.setEnabled(True)
        self.progress.setVisible(False)
        self.log("Готово.")
    
    def switch_left_tab(self, tab_name):
        """Переключает вкладку левой панели."""
        if tab_name == "chats":
            self.chats_widget.setVisible(True)
            self.folders_widget.setVisible(False)
            self.btn_tab_chats.setChecked(True)
            self.btn_tab_folders.setChecked(False)
        else:
            self.chats_widget.setVisible(False)
            self.folders_widget.setVisible(True)
            self.btn_tab_chats.setChecked(False)
            self.btn_tab_folders.setChecked(True)
            # Обновляем логические папки при переключении
            self.refresh_folders()

    def refresh_folders(self):
        """Обновляет дерево логических папок из БД."""
        self.logical_model.clear()
        if not supabase_client.is_connected():
            item = QStandardItem("Supabase не подключен")
            item.setEnabled(False)
            self.logical_model.appendRow(item)
            return

        try:
            folders = self.run_async(supabase_client.get_folders())
            
            # Строим дерево
            # Для простоты пока плоский список или один уровень вложенности, 
            # но можно сделать рекурсивно по parent_id
            folder_items = {}
            
            # Сначала создаем все папки
            for f in folders:
                # Если slug пустой (старая папка), генерируем его на лету
                slug = f.get('slug')
                if not slug:
                    slug = transliterate(f['name'])
                    
                f_item = QStandardItem(f"📁 {f['name']}")
                f_item.setData(f['id'], Qt.ItemDataRole.UserRole) # ID папки
                f_item.setData("folder", Qt.ItemDataRole.UserRole + 1) # Тип
                f_item.setData(slug, Qt.ItemDataRole.UserRole + 4) # Slug для S3
                folder_items[f['id']] = f_item

            # Добавляем в модель (учитывая parent_id)
            for f in folders:
                f_item = folder_items[f['id']]
                parent_id = f.get('parent_id')
                if parent_id and parent_id in folder_items:
                    folder_items[parent_id].appendRow(f_item)
                else:
                    self.logical_model.appendRow(f_item)
            
            # Загружаем файлы для каждой папки
            for f_id, f_item in folder_items.items():
                files = self.run_async(supabase_client.get_folder_files(f_id))
                for file in files:
                    name = file.get('filename') or "Без названия"
                    file_item = QStandardItem(f"📄 {name}")
                    file_item.setData(file['id'], Qt.ItemDataRole.UserRole) # ID файла
                    file_item.setData("file", Qt.ItemDataRole.UserRole + 1) # Тип
                    file_item.setData(file.get('storage_path') or file.get('external_url'), Qt.ItemDataRole.UserRole + 2) # Путь/URL
                    file_item.setData(f_id, Qt.ItemDataRole.UserRole + 3) # ID родительской папки в БД
                    f_item.appendRow(file_item)
            
            # Разворачиваем все папки, чтобы видеть файлы
            self.tree_folders.expandAll()
                    
        except Exception as e:
            self.log(f"Ошибка обновления папок: {e}")

    def create_new_folder(self):
        """Создает новую логическую папку в БД."""
        name, ok = QInputDialog.getText(self, "Новая папка", "Введите название тематической папки:")
        if ok and name:
            try:
                slug = transliterate(name)
                folder_id = self.run_async(supabase_client.create_folder(name, slug=slug))
                if folder_id:
                    self.log(f"Логическая папка создана: {name} (slug: {slug})")
                    self.refresh_folders()
                else:
                    QMessageBox.warning(self, "Ошибка", "Не удалось создать папку в БД")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка: {e}")

    def show_tree_context_menu(self, position):
        """Контекстное меню для дерева логических папок."""
        indexes = self.tree_folders.selectedIndexes()
        if not indexes:
            menu = QMenu()
            action_new_folder = menu.addAction("➕ Создать папку")
            action_new_folder.triggered.connect(self.create_new_folder)
            menu.exec(self.tree_folders.viewport().mapToGlobal(position))
            return

        index = indexes[0]
        item = self.logical_model.itemFromIndex(index)
        db_id = item.data(Qt.ItemDataRole.UserRole)
        item_type = item.data(Qt.ItemDataRole.UserRole + 1)
        folder_slug = item.data(Qt.ItemDataRole.UserRole + 4)
        
        menu = QMenu()
        
        if item_type == "folder":
            action_attach_all = menu.addAction("📎 Прикрепить ВСЕ файлы")
            action_add_files = menu.addAction("📥 Добавить файлы в эту папку")
            menu.addSeparator()
            action_new_subfolder = menu.addAction("➕ Создать подпапку")
            action_delete = menu.addAction("🗑️ Удалить папку")
            
            action_attach_all.triggered.connect(lambda: self.attach_folder_files_db(db_id, item.text()))
            action_add_files.triggered.connect(lambda: self.add_external_files_to_db_folder(db_id, folder_slug))
            action_new_subfolder.triggered.connect(lambda: self.create_subfolder_db(db_id))
            action_delete.triggered.connect(lambda: self.delete_db_item(db_id, "folder", item.text(), folder_slug=folder_slug))
        else:
            action_attach = menu.addAction("📎 Прикрепить к чату")
            action_delete = menu.addAction("🗑️ Удалить из этой папки")
            
            file_path = item.data(Qt.ItemDataRole.UserRole + 2)
            parent_folder_id = item.data(Qt.ItemDataRole.UserRole + 3)
            
            action_attach.triggered.connect(lambda: self.attach_single_file_db(db_id, item.text(), file_path))
            action_delete.triggered.connect(lambda: self.delete_db_item(db_id, "file", item.text(), parent_folder_id=parent_folder_id))

        menu.exec(self.tree_folders.viewport().mapToGlobal(position))

    def create_subfolder_db(self, parent_id):
        name, ok = QInputDialog.getText(self, "Новая подпапка", "Введите название:")
        if ok and name:
            slug = transliterate(name)
            self.run_async(supabase_client.create_folder(name, parent_id=parent_id, slug=slug))
            self.refresh_folders()

    def add_external_files_to_db_folder(self, folder_id, folder_slug=None):
        """Загружает внешние файлы в S3, регистрирует в БД и добавляет в папку."""
        if not s3_storage.is_connected():
            QMessageBox.critical(self, "Ошибка S3", "S3 не подключен. Проверьте настройки в .env")
            return

        files, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для загрузки в S3", "", "All Files (*)")
        if files:
            count = 0
            # Если slug не передан, берем из имени папки (хотя он должен быть передан)
            slug = folder_slug or "unsorted"
            
            for f_path in files:
                p = Path(f_path)
                try:
                    # Путь в S3: folders/slug/filename (используем строчный регистр для folders)
                    s3_key = f"folders/{slug}/{p.name}"
                    
                    self.log(f"Загрузка {p.name} в S3 (путь: {s3_key})...")
                    s3_url = self.run_async(s3_storage.upload_file(
                        file_path=str(p),
                        s3_key=s3_key
                    ))
                    
                    if s3_url:
                        self.log(f"Успешно загружено в S3. Регистрация в БД...")
                        file_id = self.run_async(supabase_client.register_file(
                            source_type="user_upload",
                            filename=p.name,
                            storage_path=s3_key,
                            size_bytes=p.stat().st_size
                        ))
                        if file_id:
                            success = self.run_async(supabase_client.add_file_to_folder(folder_id, file_id))
                            if success:
                                count += 1
                            else:
                                self.log(f"Ошибка привязки {p.name} к папке в БД")
                        else:
                            self.log(f"Ошибка регистрации {p.name} в БД")
                    else:
                        error_msg = f"Ошибка загрузки {p.name} в S3. Проверьте логи терминала (возможно ошибка региона или доступов)."
                        self.log(error_msg)
                        QMessageBox.warning(self, "Ошибка загрузки", error_msg)
                except Exception as e:
                    self.log(f"Ошибка добавления {p.name}: {e}")
            
            self.log(f"Завершено. Загружено и добавлено в папку: {count}")
            self.refresh_folders()

    def attach_single_file_db(self, file_id, name, path):
        """Прикрепить файл из БД."""
        if path and path not in self.selected_md_files:
            self.selected_md_files.append(path)
            self.update_file_indicator()
            self.log(f"Прикреплен файл из БД: {name}")

    def attach_folder_files_db(self, folder_id, folder_name):
        """Прикрепить все файлы из папки БД."""
        files = self.run_async(supabase_client.get_folder_files(folder_id))
        added_count = 0
        for f in files:
            path = f.get('storage_path') or f.get('external_url')
            if path and path not in self.selected_md_files:
                self.selected_md_files.append(path)
                added_count += 1
        
        if added_count > 0:
            self.update_file_indicator()
            self.log(f"Из папки '{folder_name}' прикреплено файлов: {added_count}")
        else:
            self.log(f"В папке '{folder_name}' не найдено новых файлов для прикрепления")

    def on_tree_double_clicked(self, index):
        item = self.logical_model.itemFromIndex(index)
        item_type = item.data(Qt.ItemDataRole.UserRole + 1)
        if item_type == "file":
            db_id = item.data(Qt.ItemDataRole.UserRole)
            path = item.data(Qt.ItemDataRole.UserRole + 2)
            self.attach_single_file_db(db_id, item.text(), path)

    def attach_selected_from_tree(self):
        """Прикрепляет все выбранные в дереве файлы из БД."""
        indexes = self.tree_folders.selectedIndexes()
        added_count = 0
        
        unique_items = set()
        for index in indexes:
            if index.column() == 0:
                item = self.logical_model.itemFromIndex(index)
                if item.data(Qt.ItemDataRole.UserRole + 1) == "file":
                    unique_items.add((item.text(), item.data(Qt.ItemDataRole.UserRole + 2)))
        
        for name, path in unique_items:
            if path and path not in self.selected_md_files:
                self.selected_md_files.append(path)
                added_count += 1
        
        if added_count > 0:
            self.update_file_indicator()
            self.log(f"Прикреплено из дерева БД: {added_count}")

    def delete_db_item(self, db_id, item_type, name, parent_folder_id=None, folder_slug=None):
        """Удалить папку или файл из БД и S3."""
        msg = f"Удалить папку '{name}' и все её связи?" if item_type == "folder" else f"Удалить '{name}' из этой папки?"
        reply = QMessageBox.question(self, "Удаление", msg,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                success = False
                if item_type == "folder":
                    # 1. Сначала удаляем из S3 если это папка
                    if folder_slug:
                        s3_prefix = f"folders/{folder_slug}/"
                        self.log(f"Удаление содержимого папки в S3: {s3_prefix}")
                        self.run_async(s3_storage.delete_folder(s3_prefix))
                    
                    # 2. Затем из БД
                    success = self.run_async(supabase_client.delete_folder(db_id))
                else:
                    success = self.run_async(supabase_client.delete_file_from_folder(parent_folder_id, db_id))
                
                if success:
                    self.log(f"Удалено: {name}")
                    self.refresh_folders()
                else:
                    self.log(f"Ошибка при удалении {name}")
            except Exception as e:
                self.log(f"Ошибка удаления: {e}")

    def load_md_mode(self):
        """Загружает режим обработки MD из Supabase."""
        if config.USE_DATABASE and supabase_client.is_connected():
            try:
                mode = self.run_async(supabase_client.get_md_processing_mode())
                index = self.combo_md_mode.findData(mode)
                if index >= 0:
                    self.combo_md_mode.blockSignals(True)
                    self.combo_md_mode.setCurrentIndex(index)
                    self.combo_md_mode.blockSignals(False)
            except Exception as e:
                self.log(f"Ошибка загрузки режима MD: {e}")

    def save_md_mode(self):
        """Сохраняет режим обработки MD в Supabase."""
        mode = self.combo_md_mode.currentData()
        if config.USE_DATABASE and supabase_client.is_connected():
            try:
                self.run_async(supabase_client.set_md_processing_mode(mode))
                self.log(f"Режим MD изменен на: {mode}")
            except Exception as e:
                self.log(f"Ошибка сохранения режима MD: {e}")

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
            
            self.folders_label.setStyleSheet("""
                color: #8e8ea0;
                font-size: 11px;
                font-weight: 500;
                padding-left: 8px;
            """)

            self.tree_folders.setStyleSheet("""
                QTreeView {
                    border: none;
                    background: transparent;
                    outline: none;
                }
                QTreeView::item {
                    color: #ececec;
                    padding: 4px;
                }
                QTreeView::item:hover {
                    background-color: #2d2d2d;
                }
                QTreeView::item:selected {
                    background-color: #3d3d3d;
                }
            """)
            
            tab_style_dark = """
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: #8e8ea0;
                    font-size: 14px;
                    font-weight: 600;
                }
                QPushButton:checked {
                    color: #ececec;
                    border-bottom: 2px solid #10A37F;
                }
                QPushButton:hover {
                    color: #ececec;
                }
            """
            self.btn_tab_chats.setStyleSheet(tab_style_dark)
            self.btn_tab_folders.setStyleSheet(tab_style_dark)

            # Кнопки папок
            folders_btn_style_dark = """
                QPushButton {
                    background-color: #3d3d3d;
                    color: #ececec;
                    border: 1px solid #4d4d4f;
                    border-radius: 6px;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #4d4d4f;
                }
            """
            self.btn_new_folder.setStyleSheet(folders_btn_style_dark)
            self.btn_refresh_folders.setStyleSheet(folders_btn_style_dark)
            self.btn_attach_selected.setStyleSheet("""
                QPushButton {
                    background-color: #10A37F;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px;
                    font-weight: 600;
                    margin-top: 4px;
                }
                QPushButton:hover {
                    background-color: #0d8c6d;
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
            
            self.btn_stop.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #dc2626;
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
                    selection-color: #ececec;
                    outline: none;
                }
                QComboBox::item {
                    color: #ececec;
                    background-color: #3d3d3d;
                }
                QComboBox::item:selected {
                    background-color: #4d4d4f;
                    color: #ececec;
                }
            """)

            md_combo_style_dark = """
                QComboBox {
                    background-color: #3d3d3d;
                    border: 1px solid #4d4d4f;
                    border-radius: 6px;
                    padding: 4px 8px;
                    color: #ececec;
                    font-size: 12px;
                }
                QComboBox:hover {
                    border-color: #10A37F;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: #3d3d3d;
                    color: #ececec;
                    selection-background-color: #4d4d4f;
                    selection-color: #ececec;
                    outline: none;
                }
                QComboBox::item {
                    color: #ececec;
                    background-color: #3d3d3d;
                }
                QComboBox::item:selected {
                    background-color: #4d4d4f;
                    color: #ececec;
                }
            """
            self.combo_md_mode.setStyleSheet(md_combo_style_dark)
            self.combo_user_prompts.setStyleSheet(md_combo_style_dark)
            
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
            
            self.folders_label.setStyleSheet("""
                color: #6e6e80;
                font-size: 11px;
                font-weight: 500;
                padding-left: 8px;
            """)

            self.tree_folders.setStyleSheet("""
                QTreeView {
                    border: none;
                    background: transparent;
                    outline: none;
                }
                QTreeView::item {
                    color: #2d333a;
                    padding: 4px;
                }
                QTreeView::item:hover {
                    background-color: #e5e5e5;
                }
                QTreeView::item:selected {
                    background-color: #d1d5db;
                }
            """)
            
            tab_style_light = """
                QPushButton {
                    background-color: transparent;
                    border: none;
                    color: #6e6e80;
                    font-size: 14px;
                    font-weight: 600;
                }
                QPushButton:checked {
                    color: #2d333a;
                    border-bottom: 2px solid #10A37F;
                }
                QPushButton:hover {
                    color: #2d333a;
                }
            """
            self.btn_tab_chats.setStyleSheet(tab_style_light)
            self.btn_tab_folders.setStyleSheet(tab_style_light)

            # Кнопки папок
            folders_btn_style_light = """
                QPushButton {
                    background-color: #ffffff;
                    color: #2d333a;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 4px 8px;
                }
                QPushButton:hover {
                    background-color: #f3f4f6;
                }
            """
            self.btn_new_folder.setStyleSheet(folders_btn_style_light)
            self.btn_refresh_folders.setStyleSheet(folders_btn_style_light)
            self.btn_attach_selected.setStyleSheet("""
                QPushButton {
                    background-color: #10A37F;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px;
                    font-weight: 600;
                    margin-top: 4px;
                }
                QPushButton:hover {
                    background-color: #0d8c6d;
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
            
            self.btn_stop.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 14px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #dc2626;
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
                    selection-color: #2d333a;
                    outline: none;
                }
                QComboBox::item {
                    color: #2d333a;
                    background-color: #ffffff;
                }
                QComboBox::item:selected {
                    background-color: #f3f4f6;
                    color: #2d333a;
                }
            """)

            md_combo_style_light = """
                QComboBox {
                    background-color: #ffffff;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 4px 8px;
                    color: #2d333a;
                    font-size: 12px;
                }
                QComboBox:hover {
                    border-color: #10A37F;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    color: #2d333a;
                    selection-background-color: #f3f4f6;
                    selection-color: #2d333a;
                    outline: none;
                }
                QComboBox::item {
                    color: #2d333a;
                    background-color: #ffffff;
                }
                QComboBox::item:selected {
                    background-color: #f3f4f6;
                    color: #2d333a;
                }
            """
            self.combo_md_mode.setStyleSheet(md_combo_style_light)
            self.combo_user_prompts.setStyleSheet(md_combo_style_light)
            
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
