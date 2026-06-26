# pip-disk-analyzer

分析已安装 Python 包的磁盘使用情况，帮助清理磁盘空间。

## 功能特性

### 命令行版本 (CLI)

- 扫描所有已安装的 pip 包
- 计算每个包的磁盘占用
- 支持多线程并行处理，提高扫描速度
- 提供多种输出格式（文本、JSON、CSV）
- 支持按大小/名称排序
- 支持按名称过滤
- 支持最小大小阈值过滤
- 彩色输出，便于阅读
- 支持指定 Python 解释器路径
- 支持虚拟环境分析

### 图形界面版本 (GUI)

- 可视化展示所有 pip 包的磁盘占用
- 实时搜索过滤（按包名关键字）
- 最小大小筛选
- 多种排序方式（按大小/名称升降序）
- 点击表头排序
- 多选支持
- 复制卸载命令（带预览确认框）
- 打开文件所在位置（资源管理器定位并选中）
- 扫描进度条显示（表格上方，自适应宽度）
- 自动适配系统深色/浅色模式
- 表格支持水平滚动

## 安装

首先确保你已经安装了所需依赖：

```bash
pip install -r requirements.txt
```

或者手动安装依赖：

```bash
pip install tqdm colorama PyQt5
```

## 使用方法

### 图形界面版本 (GUI)

```bash
python gui.py
```

**GUI 功能说明：**

| 功能 | 说明 |
|------|------|
| 搜索框 | 输入关键字实时过滤包名 |
| 最小大小 | 输入如 `1MB`, `500KB` 筛选大包 |
| 排序 | 下拉菜单选择：按大小/名称升降序 |
| 复制卸载命令 | 多选后点击，弹出预览框确认后复制 |
| 打开文件位置 | 在资源管理器中打开并选中文件 |
| 取消扫描 | 扫描期间可随时取消，立即停止 |
| 刷新扫描 | 重新执行扫描 |
| Python 版本 | 状态栏显示已安装的 Python 版本（排除绿色版） |

### 命令行版本 (CLI)

```bash
python main.py
```

这将扫描所有已安装的包并按大小降序显示它们的磁盘使用情况。

### 命令行选项

- `--top N` 或 `-t N`：只显示最大的 N 个包
- `--filter STR` 或 `-f STR`：只显示包名包含指定字符串的包
- `--sort {size,name}` 或 `-s {size,name}`：排序方式（默认按大小）
- `--min-size SIZE` 或 `-m SIZE`：只显示大于指定大小的包（如 1MB, 500KB）
- `--format {text,json,csv}`：输出格式（默认文本）
- `--no-color`：禁用彩色输出
- `--quiet` 或 `-q`：静默模式，只输出数据
- `--python PATH` 或 `-p PATH`：指定要分析的 Python 解释器路径
- `--version` 或 `-v`：显示版本信息

### 示例

```bash
# 只显示最大的 10 个包
python main.py --top 10

# 按名称排序
python main.py --sort name

# 只显示包含 "django" 的包
python main.py --filter "django"

# 只显示大于 1MB 的包
python main.py --min-size 1MB

# 以 JSON 格式输出结果
python main.py --format json

# 以 CSV 格式输出结果
python main.py --format csv

# 禁用彩色输出
python main.py --no-color

# 静默模式
python main.py --quiet

# 分析指定的 Python 解释器
python main.py --python /path/to/python

# 组合使用
python main.py --top 10 --sort size --format json
```

## 输出格式

### 默认文本格式

程序会显示每个包的名称、大小和安装路径。最后会显示统计摘要，包括找到的包数量、总大小和扫描耗时。

### JSON 格式

使用 `--format json` 选项时，输出格式为 JSON，包含 `packages` 和 `summary` 两个部分：

```json
{
  "packages": [
    {
      "name": "package-name",
      "size": 1234567,
      "path": "/path/to/package"
    }
  ],
  "summary": {
    "total_packages": 100,
    "total_size_bytes": 123456789,
    "total_size_human": "117.7 MB",
    "scan_time_seconds": 2.5
  }
}
```

### CSV 格式

使用 `--format csv` 选项时，输出标准 CSV 格式：

```csv
name,size_bytes,size_human,path
package-name,1234567,1.2 MB,/path/to/package
```

## 依赖项

- Python 3.6+
- tqdm（可选，用于进度条）
- colorama（可选，用于彩色输出）
- PyQt5（GUI 版本必需）

## 开发

### 代码结构

- `main.py`：CLI 主程序，包含核心扫描逻辑
- `gui.py`：图形界面版本
- `requirements.txt`：依赖列表

### 主要功能模块

- `PackageResult`：NamedTuple，定义包扫描结果数据结构
- `Config`：配置类，管理颜色等设置
- `human_readable()`：将字节数转换为人类可读格式
- `parse_size()`：解析人类可读的大小字符串
- `get_path_size()`：递归计算路径的磁盘占用
- `_find_package_path()`：查找包的安装路径
- `_process_package()`：处理单个包，获取大小信息
- `_print_result()`：统一的结果输出函数
- `scan_packages()`：扫描所有已安装的包

### 性能优化

- 使用 `os.scandir` 替代 `os.walk` 提高文件系统遍历效率
- 多线程并行处理包信息查询
- 优化包路径查找算法，减少重复目录遍历

### 错误处理

- 优雅处理 pip 调用失败
- 区分不同类型的异常（文件系统错误、编码错误等）
- 处理键盘中断，清理进度条

## 作者

AL1Sx + Xiaomi Mimo

## 许可证

MIT License
