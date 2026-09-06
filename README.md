# Экодез Core

## Разработка

На Windows, если путь к виртуальному окружению содержит кириллицу, mypy 2.3.1
нужно устанавливать в pure-Python варианте:

```powershell
pip install --no-binary mypy mypy==2.3.1
```

Скомпилированный wheel в таком пути может завершаться с `DLL ImportError`.
