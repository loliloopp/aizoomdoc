# Папка с данными

Эта папка должна содержать входные данные для анализа.

## Структура

```
data/
├── result.md              # Markdown с OCR-текстом
├── annotation.json        # Аннотации с координатами блоков
├── page_001_full.jpg      # Полноразмерное изображение страницы 1
├── page_002_full.jpg      # Полноразмерное изображение страницы 2
├── ...
└── viewports/             # Сюда сохраняются viewport-кропы (создаётся автоматически)
```

## Примеры данных

### result.md

```markdown
# Раздел ОВ (Отопление и Вентиляция)

## Общие указания

Проект системы вентиляции выполнен для жилого здания.

## Спецификация оборудования

| Поз. | Наименование | Тип | Характеристики | Кол-во |
|------|--------------|-----|----------------|--------|
| 1 | Приточная установка | П1 | L=1000 м³/ч, P=250 Па | 1 |
| 2 | Вытяжной вентилятор | В1 | L=800 м³/ч, P=200 Па | 2 |
| 3 | Воздухонагреватель | ВН1 | N=15 кВт | 1 |

## План подвала

<!-- BLOCK_ID: 550e8400-e29b-41d4-a716-446655440000 -->
АОВ8
<!-- END_BLOCK -->

<!-- BLOCK_ID: 550e8400-e29b-41d4-a716-446655440001 -->
П1
<!-- END_BLOCK -->
```

### annotation.json

```json
{
  "pdf_path": "OV_2024.pdf",
  "pages": [
    {
      "page_number": 1,
      "width": 9932,
      "height": 7015,
      "blocks": [
        {
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "page_index": 1,
          "coords_px": [1234, 2345, 1456, 2456],
          "coords_norm": [0.124, 0.334, 0.147, 0.350],
          "block_type": "text",
          "source": "auto",
          "shape_type": "rectangle",
          "image_file": null,
          "ocr_text": "АОВ8"
        },
        {
          "id": "550e8400-e29b-41d4-a716-446655440001",
          "page_index": 1,
          "coords_px": [3000, 4000, 3200, 4150],
          "coords_norm": [0.302, 0.570, 0.322, 0.591],
          "block_type": "text",
          "source": "auto",
          "shape_type": "rectangle",
          "image_file": null,
          "ocr_text": "П1"
        }
      ]
    }
  ]
}
```

### Изображения

- Формат имени: `page_XXX_full.jpg` где XXX — номер страницы с ведущими нулями
- Примеры: `page_001_full.jpg`, `page_002_full.jpg`, `page_010_full.jpg`
- Размеры изображения должны совпадать с `width` и `height` в `annotation.json`

## Для сравнения стадий

Создайте две подпапки:

```
data/
├── stage_p/
│   ├── result.md
│   ├── annotation.json
│   └── page_XXX_full.jpg
└── stage_r/
    ├── result.md
    ├── annotation.json
    └── page_XXX_full.jpg
```

## Проверка данных

### Проверка наличия файлов

```bash
# Windows PowerShell
Test-Path data\result.md
Test-Path data\annotation.json
Get-ChildItem data\page_*.jpg

# Linux/Mac
ls -l data/result.md
ls -l data/annotation.json
ls -l data/page_*.jpg
```

### Проверка JSON

```bash
# Windows PowerShell
Get-Content data\annotation.json | ConvertFrom-Json

# Linux/Mac (требуется jq)
cat data/annotation.json | jq .
```

### Проверка размеров изображений

```bash
# Linux/Mac (требуется ImageMagick)
identify data/page_001_full.jpg
```

## Получение данных от Приложения 1

Если у вас есть **Приложение 1** (не входит в этот проект), которое обрабатывает PDF:

1. Поместите PDF в Приложение 1
2. Запустите обработку
3. Скопируйте результаты (`result.md`, `annotation.json`, изображения) в эту папку

## Создание тестовых данных вручную

Для тестирования можно создать минимальный набор вручную:

1. **result.md** — текстовый файл с Markdown
2. **annotation.json** — JSON с координатами (см. пример выше)
3. **Изображения** — скриншоты или сканы чертежей

Убедитесь, что:
- BLOCK_ID в `result.md` совпадают с `id` в `annotation.json`
- Координаты `coords_px` соответствуют реальному положению на изображении
- Размеры изображения совпадают с `width` и `height` в JSON

