# Разработка

На Windows при кириллическом пути устанавливайте mypy в pure-Python варианте:

```powershell
pip install --no-binary mypy mypy==1.18.2
```

Так обходится ошибка DLL ImportError у compiled wheel.
