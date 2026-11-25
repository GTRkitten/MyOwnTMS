"""
Экспорт артефактов в Markdown формат
"""
from typing import List, Dict, Any
from pathlib import Path


class MDExporter:
    """Экспортер в Markdown формат"""
    
    def __init__(self, output_path: str):
        """
        Инициализирует экспортер
        
        Args:
            output_path: Путь к выходному файлу
        """
        self.output_path = output_path
        self.content = []
    
    def export_test_case(self, test_case: Dict[str, Any]) -> str:
        """Экспортирует один тест-кейс"""
        content = f"""# Тест-кейс: {test_case['title']}

**ID:** {test_case['id']}  
**Статус:** {test_case['status']}  
**Приоритет:** {test_case['priority']}  
**Создан:** {test_case['created_at']}  
**Обновлен:** {test_case['updated_at']}

---

"""
        
        if test_case.get('preconditions'):
            content += f"""## Предусловия

{test_case['preconditions']}

---

"""
        
        content += f"""## Шаги

```
{test_case['steps']}
```

---

## Ожидаемый результат

{test_case['expected_result']}

---
"""
        
        if test_case.get('postconditions'):
            content += f"""## Постусловия

{test_case['postconditions']}

---

"""
        
        if test_case.get('environment'):
            content += f"""## Окружение

{test_case['environment']}

---
"""
        
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return self.output_path
    
    def export_bug_report(self, bug_report: Dict[str, Any]) -> str:
        """Экспортирует один баг-репорт"""
        content = f"""# {bug_report['id']}

**Заголовок:** {bug_report['title']}  
**Статус:** {bug_report['status']}  
**Приоритет:** {bug_report['priority']}  
**Серьезность:** {bug_report['severity']}  
**Создан:** {bug_report['created_at']}  
**Обновлен:** {bug_report['updated_at']}

---

"""
        
        if bug_report.get('description'):
            content += f"""## Описание

{bug_report['description']}

---

"""
        
        content += f"""## Шаги воспроизведения

```
{bug_report['reproduction_steps']}
```

---

## Ожидаемый результат

{bug_report['expected_result']}

---

## Фактический результат

{bug_report['actual_result']}

---
"""
        
        if bug_report.get('environment'):
            content += f"""## Окружение

{bug_report['environment']}

---
"""
        
        # Вложения
        if bug_report.get('attachments'):
            content += """## Вложения

"""
            for i, attachment in enumerate(bug_report['attachments'], 1):
                if attachment['file_type'].startswith('image/'):
                    content += f"""<center>

![Рис. {i}]({attachment['file_path']})

Рис. {i}

</center>

"""
        
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return self.output_path
    
    def export_multiple(self, artifacts: List[Dict[str, Any]], single_document: bool = True) -> List[str]:
        """
        Экспортирует несколько артефактов
        
        Args:
            artifacts: Список артефактов
            single_document: True - все в одном файле, False - отдельные файлы
            
        Returns:
            Список путей к созданным файлам
        """
        if single_document:
            return [self._export_combined(artifacts)]
        else:
            paths = []
            base_path = Path(self.output_path)
            
            # Определяем папку для сохранения
            # Если base_path - это файл, берем его родительскую папку
            # Если base_path - это папка, используем её напрямую
            if base_path.is_dir():
                output_dir = base_path
            else:
                output_dir = base_path.parent
            
            for artifact in artifacts:
                if 'steps' in artifact:  # Тест-кейс
                    output = str(output_dir / f"{artifact['id']}_test_case.md")
                else:  # Баг-репорт
                    output = str(output_dir / f"{artifact['id']}_bug_report.md")
                
                exporter = MDExporter(output)
                if 'steps' in artifact:
                    exporter.export_test_case(artifact)
                else:
                    exporter.export_bug_report(artifact)
                
                paths.append(output)
            
            return paths
    
    def _export_combined(self, artifacts: List[Dict[str, Any]]) -> str:
        """Экспортирует все артефакты в один документ"""
        content = """# Отчет о дефектах

---

"""
        
        for i, artifact in enumerate(artifacts):
            if i > 0:
                content += "\n---\n\n"
            
            if 'steps' in artifact:  # Тест-кейс
                content += f"""# Тест-кейс: {artifact['title']}

**ID:** {artifact['id']}  
**Статус:** {artifact['status']}  
**Приоритет:** {artifact['priority']}  
**Создан:** {artifact['created_at']}  
**Обновлен:** {artifact['updated_at']}

---

"""
        
                if artifact.get('preconditions'):
                    content += f"""## Предусловия

{artifact['preconditions']}

---

"""

                content += f"""## Шаги

```
{artifact['steps']}
```

---

## Ожидаемый результат

{artifact['expected_result']}

---
"""
        
                if artifact.get('postconditions'):
                    content += f"""## Постусловия

{artifact['postconditions']}

---

"""
        
                if artifact.get('environment'):
                    content += f"""## Окружение

{artifact['environment']}

---
"""
                
                # Вложения
                if artifact.get('attachments'):
                    content += """## Вложения

"""
                    for i, attachment in enumerate(artifact['attachments'], 1):
                        if attachment['file_type'].startswith('image/'):
                            content += f"""<center>

![Рис. {i}]({attachment['file_path']})

Рис. {i}

</center>

"""
            else:  # Баг-репорт
                content += f"""# {artifact['id']}

**Заголовок:** {artifact['title']}  
**Статус:** {artifact['status']}  
**Приоритет:** {artifact['priority']}  
**Серьезность:** {artifact['severity']}  
**Создан:** {artifact['created_at']}  
**Обновлен:** {artifact['updated_at']}

---

"""

                if artifact.get('description'):
                    content += f"""## Описание

{artifact['description']}

---

"""

                content += f"""## Шаги воспроизведения

```
{artifact['reproduction_steps']}
```

---

## Ожидаемый результат

{artifact['expected_result']}

---

## Фактический результат

{artifact['actual_result']}

---
"""
        
                if artifact.get('environment'):
                    content += f"""## Окружение

{artifact['environment']}

---
"""
        
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return self.output_path
