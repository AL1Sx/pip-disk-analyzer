# AGENTS.md

## Project Overview

Python CLI + GUI tool that analyzes disk usage of pip-installed packages. Two entrypoints:

- `main.py` — CLI version (standalone)
- `gui.py` — PyQt5 GUI version (imports from `main.py`)

**Dependency direction**: `gui.py` → `main.py`. Never the reverse.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run CLI
python main.py --top 10 --sort size

# Run GUI
python gui.py

# Syntax check (no test framework exists)
python -m py_compile main.py
python -m py_compile gui.py
```

## Architecture

`main.py` exports these symbols used by `gui.py`:
- `scan_packages()` — core scanner, accepts `progress_callback` and `cancel_check`
- `PackageResult` — NamedTuple with fields: `name`, `size`, `path`, `error`
- `human_readable()` — bytes to "1.2 MB" string
- `parse_size()` — "1MB" to integer bytes

`gui.py` key classes:
- `SizeTableWidgetItem` — custom QTableWidgetItem for numeric sort (not string sort)
- `UninstallPreviewDialog` — confirmation dialog before copying uninstall command
- `ScanWorker` — QThread wrapper around `scan_packages` with progress/cancel signals
- `MainWindow` — main GUI window

## Important Quirks

1. **No test framework** — verify changes with `py_compile` only
2. **Soft dependencies** — `tqdm` and `colorama` are optional; code degrades gracefully if missing
3. **PyQt5 required** for GUI — not optional like the other deps
4. **Windows-specific**: `is_dark_mode()` reads registry; `explorer /select` opens file location
5. **Sorting bug fix**: `SizeTableWidgetItem` stores numeric value in `Qt.UserRole` and overrides `__lt__` — do not revert to plain `QTableWidgetItem` for size column
6. **Progress callback**: `scan_packages()` calls `progress_callback(current, total)` inside the `as_completed` loop — GUI depends on this for progress bar updates
7. **Cancel support**: `scan_packages()` accepts `cancel_check: Callable[[], bool]` — returns early with partial results when cancelled
8. **stdout suppression**: `ScanWorker.run()` redirects stdout/stderr to `os.devnull` to prevent pipe errors when GUI is launched from terminal

## Conventions

- All user-facing strings in Chinese (comments, labels, messages)
- No type checking or linting configured
- No CI/CD workflows
