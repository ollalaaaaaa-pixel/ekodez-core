# Экодез Core

## Разработка

На Windows, если путь к виртуальному окружению содержит кириллицу, mypy 1.18.2
нужно устанавливать в pure-Python варианте:

```powershell
pip install --no-binary mypy mypy==1.18.2
```

Скомпилированный wheel в таком пути может завершаться с `DLL ImportError`.
