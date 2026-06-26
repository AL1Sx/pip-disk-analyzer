"""
pip-disk-analyzer GUI: 图形化界面版本。

功能:
    - 扫描并展示所有 pip 包的磁盘占用
    - 支持搜索、排序、筛选
    - 复制卸载命令到剪贴板（带预览）
    - 打开文件所在位置

用法:
    python gui.py
"""

import os
import subprocess
import sys
from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from main import PackageResult, human_readable, parse_size, scan_packages


class SizeTableWidgetItem(QTableWidgetItem):
    """自定义大小列单元格，按数值排序而非字符串。"""

    def __init__(self, display_text: str, sort_value: int):
        super().__init__(display_text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, SizeTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


class UninstallPreviewDialog(QDialog):
    """卸载命令预览对话框。"""

    def __init__(self, packages: List[PackageResult], parent=None):
        super().__init__(parent)
        self.setWindowTitle("卸载命令预览")
        self.setMinimumWidth(500)
        self.init_ui(packages)

    def init_ui(self, packages: List[PackageResult]):
        layout = QVBoxLayout(self)

        # 选中的包列表
        layout.addWidget(QLabel(f"将卸载以下 {len(packages)} 个包:"))

        pkg_list = QTextEdit()
        pkg_list.setReadOnly(True)
        pkg_list.setMaximumHeight(150)
        pkg_names = "\n".join(f"  • {r.name} ({human_readable(r.size)})" for r in packages)
        pkg_list.setText(pkg_names)
        layout.addWidget(pkg_list)

        # 命令预览
        layout.addWidget(QLabel("命令:"))
        self.cmd_edit = QTextEdit()
        self.cmd_edit.setMaximumHeight(60)
        names = [r.name for r in packages]
        self.cmd = f"pip uninstall {' '.join(names)} -y"
        self.cmd_edit.setText(self.cmd)
        self.cmd_edit.setReadOnly(True)
        layout.addWidget(self.cmd_edit)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_copy = QPushButton("复制并关闭")
        btn_copy.setDefault(True)
        btn_copy.clicked.connect(self.accept)
        btn_layout.addWidget(btn_copy)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def get_command(self) -> str:
        return self.cmd


def get_installed_pythons() -> list:
    """获取已安装的 Python 版本列表（排除绿色版）。"""
    try:
        output = subprocess.check_output(
            ["py", "--list"],
            text=True, encoding='utf-8', errors='replace',
            stderr=subprocess.DEVNULL
        )
        versions = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("-V:"):
                # 格式: -V:3.11 *        Python 3.11 (64-bit)
                parts = line.split()
                version = parts[0].replace("-V:", "")
                is_default = "*" in line
                arch = "(64-bit)" if "64-bit" in line else "(32-bit)"
                versions.append({
                    "version": version,
                    "arch": arch,
                    "is_default": is_default
                })
        return versions
    except Exception:
        return []


class ScanWorker(QThread):
    """后台扫描线程，避免阻塞 UI。"""

    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(list, list)  # all_results, valid_results
    error = pyqtSignal(str)

    def __init__(self, python_path: str = None):
        super().__init__()
        self.python_path = python_path
        self._cancelled = False

    def cancel(self):
        """请求取消扫描。"""
        self._cancelled = True

    def run(self):
        # 重定向 stdout/stderr 到空设备，避免管道错误
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
        try:
            from main import Config
            config = Config(use_color=False)

            def on_progress(current: int, total: int):
                if self._cancelled:
                    return
                self.progress.emit(current, total)

            def cancel_check():
                return self._cancelled

            all_results, valid_results = scan_packages(
                config,
                show_all=False,
                sort_by='size',
                python_path=self.python_path,
                progress_callback=on_progress,
                cancel_check=cancel_check
            )
            if not self._cancelled:
                self.finished.emit(all_results, valid_results)
        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))
        finally:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout, sys.stderr = old_stdout, old_stderr


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(self):
        super().__init__()
        self.all_results: List[PackageResult] = []
        self.valid_results: List[PackageResult] = []
        self.worker: Optional[ScanWorker] = None
        self.init_ui()
        self.start_scan()

    def init_ui(self):
        self.setWindowTitle("PIP 磁盘占用分析")
        self.setMinimumSize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- 筛选区域 ---
        filter_group = QGroupBox("筛选")
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入包名关键字...")
        self.search_input.textChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.search_input)

        filter_layout.addWidget(QLabel("最小大小:"))
        self.min_size_input = QLineEdit()
        self.min_size_input.setPlaceholderText("如 1MB, 500KB")
        self.min_size_input.setFixedWidth(120)
        self.min_size_input.returnPressed.connect(self.apply_filters)
        filter_layout.addWidget(self.min_size_input)

        filter_layout.addWidget(QLabel("排序:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["按大小降序", "按大小升序", "按名称升序", "按名称降序"])
        self.sort_combo.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.sort_combo)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # --- 进度条（表格上方） ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # --- 表格 ---
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["包名", "大小", "路径"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 500)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        # --- 状态栏 ---
        status_layout = QHBoxLayout()
        self.status_label = QLabel("就绪")
        status_layout.addWidget(self.status_label)

        self.python_label = QLabel()
        self.python_label.setStyleSheet("color: #888; padding-right: 10px;")
        status_layout.addWidget(self.python_label)

        status_layout.addStretch()

        # --- 操作按钮 ---
        self.btn_copy = QPushButton("复制卸载命令")
        self.btn_copy.setToolTip("预览并复制 pip uninstall 命令到剪贴板")
        self.btn_copy.clicked.connect(self.copy_uninstall_command)
        self.btn_copy.setEnabled(False)
        status_layout.addWidget(self.btn_copy)

        self.btn_open = QPushButton("打开文件位置")
        self.btn_open.setToolTip("在资源管理器中打开并选中文件")
        self.btn_open.clicked.connect(self.open_file_location)
        self.btn_open.setEnabled(False)
        status_layout.addWidget(self.btn_open)

        self.btn_refresh = QPushButton("刷新扫描")
        self.btn_refresh.clicked.connect(self.start_scan)
        status_layout.addWidget(self.btn_refresh)

        self.btn_cancel = QPushButton("取消扫描")
        self.btn_cancel.setToolTip("取消正在进行的扫描")
        self.btn_cancel.clicked.connect(self.cancel_scan)
        self.btn_cancel.setVisible(False)
        status_layout.addWidget(self.btn_cancel)

        layout.addLayout(status_layout)

        # 表格选择变化时更新按钮状态
        self.table.itemSelectionChanged.connect(self.on_selection_changed)

    def update_python_versions(self):
        """更新已安装 Python 版本显示。"""
        versions = get_installed_pythons()
        if versions:
            parts = []
            for v in versions:
                text = f"{v['version']} {v['arch']}"
                if v['is_default']:
                    text += "*"
                parts.append(text)
            self.python_label.setText(f"Python: {' | '.join(parts)}")
        else:
            self.python_label.setText("Python: 未检测到")

    def start_scan(self):
        """开始扫描。"""
        self.update_python_versions()
        self.btn_refresh.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在扫描已安装的包...")
        self.table.setRowCount(0)

        self.worker = ScanWorker()
        self.worker.progress.connect(self.on_scan_progress)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.error.connect(self.on_scan_error)
        self.worker.start()

    def on_scan_progress(self, current: int, total: int):
        """扫描进度更新。"""
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.status_label.setText(f"正在扫描: {current}/{total} 个包 ({percent}%)")

    def on_scan_finished(self, all_results: list, valid_results: list):
        """扫描完成。"""
        self.all_results = all_results
        self.valid_results = valid_results
        self.progress_bar.setVisible(False)
        self.btn_refresh.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.update_table(self.valid_results)
        total_size = sum(r.size for r in self.valid_results if r.size)
        self.status_label.setText(
            f"扫描完成: {len(self.valid_results)}/{len(self.all_results)} 个包, "
            f"总大小 {human_readable(total_size)}"
        )

    def on_scan_error(self, error_msg: str):
        """扫描出错。"""
        self.progress_bar.setVisible(False)
        self.btn_refresh.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.status_label.setText("扫描失败")
        QMessageBox.critical(self, "扫描错误", f"扫描过程中发生错误:\n{error_msg}")

    def cancel_scan(self):
        """取消正在进行的扫描。"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.terminate()
            self.worker.wait(3000)
            self.progress_bar.setVisible(False)
            self.btn_refresh.setEnabled(True)
            self.btn_cancel.setVisible(False)
            self.status_label.setText("扫描已取消")

    def closeEvent(self, event):
        """窗口关闭时清理线程。"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.terminate()
            self.worker.wait(3000)
        event.accept()

    def apply_filters(self):
        """应用搜索和筛选条件。"""
        filtered = self.valid_results[:]

        # 搜索过滤
        keyword = self.search_input.text().strip().lower()
        if keyword:
            filtered = [r for r in filtered if keyword in r.name.lower()]

        # 最小大小过滤
        min_size_text = self.min_size_input.text().strip()
        if min_size_text:
            try:
                min_size = parse_size(min_size_text)
                filtered = [r for r in filtered if r.size and r.size >= min_size]
            except Exception:
                pass  # 忽略无效输入

        # 排序
        sort_index = self.sort_combo.currentIndex()
        if sort_index == 0:  # 按大小降序
            filtered.sort(key=lambda r: r.size or 0, reverse=True)
        elif sort_index == 1:  # 按大小升序
            filtered.sort(key=lambda r: r.size or 0)
        elif sort_index == 2:  # 按名称升序
            filtered.sort(key=lambda r: r.name.lower())
        elif sort_index == 3:  # 按名称降序
            filtered.sort(key=lambda r: r.name.lower(), reverse=True)

        self.update_table(filtered)

    def update_table(self, results: List[PackageResult]):
        """更新表格数据。"""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))

        for row, r in enumerate(results):
            name_item = QTableWidgetItem(r.name)
            name_item.setData(Qt.UserRole, r.path)  # 存储路径

            size_item = SizeTableWidgetItem(human_readable(r.size), r.size or 0)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            path_item = QTableWidgetItem(r.path or "N/A")

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, size_item)
            self.table.setItem(row, 2, path_item)

        self.table.setSortingEnabled(True)

    def on_selection_changed(self):
        """表格选择变化。"""
        has_selection = len(self.table.selectedItems()) > 0
        self.btn_copy.setEnabled(has_selection)
        self.btn_open.setEnabled(has_selection)

    def get_selected_packages(self) -> List[PackageResult]:
        """获取选中的包。"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())

        results = []
        for row in selected_rows:
            name = self.table.item(row, 0).text()
            path = self.table.item(row, 0).data(Qt.UserRole)
            # 从 valid_results 中找到对应的完整结果
            for r in self.valid_results:
                if r.name == name:
                    results.append(r)
                    break
        return results

    def copy_uninstall_command(self):
        """预览并复制卸载命令到剪贴板。"""
        selected = self.get_selected_packages()
        if not selected:
            return

        dialog = UninstallPreviewDialog(selected, self)
        if dialog.exec_() == QDialog.Accepted:
            cmd = dialog.get_command()
            clipboard = QApplication.clipboard()
            clipboard.setText(cmd)
            self.status_label.setText(f"已复制卸载命令到剪贴板")

    def open_file_location(self):
        """打开文件所在位置。"""
        selected = self.get_selected_packages()
        if not selected:
            return

        opened = 0
        for r in selected:
            if r.path and os.path.exists(r.path):
                try:
                    subprocess.Popen(["explorer", "/select,", r.path])
                    opened += 1
                except Exception as e:
                    QMessageBox.warning(self, "打开失败", f"无法打开 {r.path}:\n{e}")

        if opened > 0:
            self.status_label.setText(f"已打开 {opened} 个文件位置")


def is_dark_mode() -> bool:
    """检测 Windows 系统是否为深色模式。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0  # 0 表示深色模式
    except Exception:
        return False


def get_dark_stylesheet() -> str:
    """返回深色模式的 QSS 样式表。"""
    return """
        QMainWindow, QWidget {
            background-color: #2b2b2b;
            color: #e0e0e0;
        }
        QGroupBox {
            background-color: #333333;
            border: 1px solid #555555;
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 16px;
            color: #e0e0e0;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
            color: #e0e0e0;
        }
        QLabel {
            color: #e0e0e0;
        }
        QLineEdit, QComboBox, QTextEdit {
            background-color: #353535;
            color: #e0e0e0;
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 4px;
        }
        QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
            border: 1px solid #4a6fa5;
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #e0e0e0;
            margin-right: 8px;
        }
        QComboBox QAbstractItemView {
            background-color: #353535;
            color: #e0e0e0;
            selection-background-color: #4a6fa5;
        }
        QPushButton {
            background-color: #404040;
            color: #e0e0e0;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 6px 16px;
        }
        QPushButton:hover {
            background-color: #4a4a4a;
            border: 1px solid #666666;
        }
        QPushButton:pressed {
            background-color: #3a3a3a;
        }
        QPushButton:disabled {
            background-color: #333333;
            color: #777777;
        }
        QTableWidget {
            background-color: #2b2b2b;
            color: #e0e0e0;
            gridline-color: #444444;
            selection-background-color: #4a6fa5;
            selection-color: #ffffff;
            alternate-background-color: #303030;
        }
        QTableWidget::item {
            padding: 4px;
        }
        QHeaderView::section {
            background-color: #353535;
            color: #e0e0e0;
            border: 1px solid #444444;
            padding: 6px;
        }
        QProgressBar {
            background-color: #353535;
            border: 1px solid #555555;
            border-radius: 4px;
            text-align: center;
            color: #e0e0e0;
        }
        QProgressBar::chunk {
            background-color: #4a6fa5;
            border-radius: 3px;
        }
        QScrollBar:vertical {
            background-color: #2b2b2b;
            width: 12px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background-color: #555555;
            min-height: 30px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #666666;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        QScrollBar:horizontal {
            background-color: #2b2b2b;
            height: 12px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background-color: #555555;
            min-width: 30px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal:hover {
            background-color: #666666;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0;
        }
    """


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if is_dark_mode():
        app.setStyleSheet(get_dark_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
