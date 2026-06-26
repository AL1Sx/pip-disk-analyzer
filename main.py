"""
pip-disk-analyzer: 分析已安装 Python 包的磁盘使用情况。

用法:
    python main.py [--top N] [--filter STR] [--sort {size,name}]
                   [--min-size SIZE] [--format {text,json,csv}]
                   [--no-color] [--quiet] [--python PATH]
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
except ImportError:
    Fore = None
    Style = None


class PackageResult(NamedTuple):
    """包扫描结果。"""
    name: str
    size: Optional[int]
    path: Optional[str]
    error: Optional[str]


class Config:
    """配置类，管理颜色等设置。"""
    def __init__(self, use_color: bool = True):
        self.use_color = use_color and Fore is not None

    def color(self, text: str, fore_color) -> str:
        """应用颜色。"""
        if not self.use_color or fore_color is None:
            return text
        return f"{fore_color}{text}{Style.RESET_ALL}"


def human_readable(size: float) -> str:
    """将字节数转换为人类可读的格式。"""
    if size is None or size < 0:
        return "N/A"
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024.0:
            if unit == 'B':
                return f"{int(size)} B"
            return f"{size:6.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def parse_size(size_str: str) -> int:
    """解析人类可读的大小字符串为字节数，如 '1MB' -> 1048576。"""
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?$', size_str.strip(), re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid size: {size_str}")
    value, unit = float(match.group(1)), (match.group(2) or 'B').upper()
    multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    return int(value * multipliers[unit])


def get_path_size(path: str) -> int:
    """递归计算路径的磁盘占用大小（字节）。"""
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += get_path_size(entry.path)
                except OSError:
                    continue
    except OSError:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    return total


def _find_package_path(location: str, package_name: str) -> Optional[str]:
    """查找包的安装路径。"""
    if not location:
        return None

    normalized = package_name.replace('-', '_')
    norm_lower = normalized.lower()

    exact_candidates = [
        os.path.join(location, package_name),
        os.path.join(location, normalized),
        os.path.join(location, package_name + '.py'),
    ]
    for c in exact_candidates:
        if os.path.exists(c):
            return c

    try:
        entries = os.listdir(location)
    except OSError:
        return None

    for item in entries:
        lower = item.lower()
        if lower.startswith(norm_lower) and (
            lower.endswith('.dist-info') or lower.endswith('.egg-info')
        ):
            return os.path.join(location, item)

    for item in entries:
        if norm_lower in item.lower():
            return os.path.join(location, item)

    return None


def _process_package(package_name: str, pip_cmd: List[str], env: Dict[str, str]) -> PackageResult:
    """处理单个包，获取其大小信息。"""
    try:
        package_info = subprocess.check_output(
            pip_cmd + ['show', package_name],
            env=env, text=True, encoding='utf-8', errors='replace'
        )
        location = None
        for line in package_info.splitlines():
            if line.startswith('Location:'):
                location = line.split(':', 1)[1].strip()
                break

        package_path = _find_package_path(location, package_name)
        if package_path and os.path.exists(package_path):
            size = get_path_size(package_path)
            return PackageResult(package_name, size, package_path, None)
        else:
            return PackageResult(package_name, None, None, 'Path not found')

    except subprocess.CalledProcessError as e:
        return PackageResult(package_name, None, None, f'pip show failed (exit code {e.returncode})')
    except OSError as e:
        return PackageResult(package_name, None, None, f'File system error: {e}')
    except UnicodeDecodeError as e:
        return PackageResult(package_name, None, None, f'Encoding error: {e}')


def _print_result(result: PackageResult, config: Config, writer=print):
    """统一的结果输出函数。"""
    name, size, package_path, err = result
    if size is not None:
        colored_name = config.color(name, Fore.GREEN)
        colored_size = config.color(human_readable(size), Fore.WHITE)
        colored_path = config.color(f"({package_path})", Fore.LIGHTBLACK_EX)
        writer(f"{colored_name}: {colored_size}  {colored_path}")
    else:
        line = f"{name}: {err}"
        color = Fore.YELLOW if err == 'Path not found' else Fore.RED
        writer(config.color(line, color))


def scan_packages(
    config: Config,
    show_all: bool = False,
    top_n: int = None,
    sort_by: str = 'size',
    filter_str: str = None,
    min_size: int = 0,
    python_path: str = None,
    progress_callback: Callable[[int, int], None] = None,
    cancel_check: Callable[[], bool] = None
) -> Tuple[List[PackageResult], List[PackageResult]]:
    """扫描所有已安装的包。"""
    pip_cmd = [python_path or sys.executable, '-m', 'pip']
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'

    try:
        installed_output = subprocess.check_output(
            pip_cmd + ['list', '--format=freeze'],
            env=env, text=True, encoding='utf-8', errors='replace'
        )
    except FileNotFoundError:
        print("Error: Python or pip not found. Please ensure Python and pip are installed.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to list installed packages: {e}", file=sys.stderr)
        sys.exit(1)

    package_names = [pkg.split('==')[0] for pkg in installed_output.splitlines() if pkg.strip()]

    if filter_str:
        package_names = [name for name in package_names if filter_str.lower() in name.lower()]

    workers = min(32, (os.cpu_count() or 1) * 5)
    pbar = tqdm(total=len(package_names), desc="Scanning", unit="pkg") if tqdm else None

    results = []
    writer = tqdm.write if (tqdm and pbar) else print

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_process_package, name, pip_cmd, env): name for name in package_names}
        try:
            for i, fut in enumerate(as_completed(futures)):
                # 检查是否取消
                if cancel_check and cancel_check():
                    for f in futures:
                        f.cancel()
                    return results, []
                
                result = fut.result()
                results.append(result)
                if show_all:
                    _print_result(result, config, writer=writer)
                if pbar:
                    pbar.update(1)
                if progress_callback:
                    progress_callback(i + 1, len(package_names))
        except KeyboardInterrupt:
            if pbar:
                pbar.close()
            for f in futures:
                f.cancel()
            print("\nScan interrupted by user.", file=sys.stderr)
            sys.exit(130)

    if pbar:
        pbar.close()

    valid_results = [r for r in results if r.size is not None]

    if min_size > 0:
        valid_results = [r for r in valid_results if r.size >= min_size]

    if sort_by == 'size':
        valid_results.sort(key=lambda x: x.size, reverse=True)
    elif sort_by == 'name':
        valid_results.sort(key=lambda x: x.name.lower())

    if top_n:
        valid_results = valid_results[:top_n]

    return results, valid_results


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(
        description='分析已安装 pip 包的磁盘使用情况',
        epilog='示例: python main.py --top 10 --sort size',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--top', '-t', type=int, help='显示最大的 N 个包')
    parser.add_argument('--filter', '-f', type=str, help='只显示包名包含指定字符串的包')
    parser.add_argument('--sort', '-s', choices=['size', 'name'], default='size', help='排序方式：size（按大小）或 name（按名称）')
    parser.add_argument('--min-size', '-m', type=str, default='0', help='只显示大于指定大小的包，如 1MB, 500KB')
    parser.add_argument('--format', choices=['text', 'json', 'csv'], default='text', help='输出格式：text, json, csv')
    parser.add_argument('--no-color', action='store_true', help='禁用彩色输出')
    parser.add_argument('--quiet', '-q', action='store_true', help='静默模式，只输出数据')
    parser.add_argument('--python', '-p', type=str, default=sys.executable, help='指定要分析的 Python 解释器路径')
    parser.add_argument('--version', '-v', action='version', version='pip-disk-analyzer 1.0.0')

    args = parser.parse_args()

    config = Config(use_color=not args.no_color)
    min_size = parse_size(args.min_size)

    start_time = time.monotonic()
    results, valid_results = scan_packages(
        config,
        show_all=not args.quiet and args.format == 'text',
        top_n=args.top,
        sort_by=args.sort,
        filter_str=args.filter,
        min_size=min_size,
        python_path=args.python
    )
    elapsed = time.monotonic() - start_time

    total_size = sum(r.size for r in valid_results)
    total_count = len(valid_results)

    if args.format == 'json':
        output = {
            'packages': [{'name': r.name, 'size': r.size, 'path': r.path} for r in valid_results],
            'summary': {
                'total_packages': total_count,
                'total_size_bytes': total_size,
                'total_size_human': human_readable(total_size),
                'scan_time_seconds': round(elapsed, 2)
            }
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))

    elif args.format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['name', 'size_bytes', 'size_human', 'path'])
        for r in valid_results:
            writer.writerow([r.name, r.size, human_readable(r.size), r.path])
        print(output.getvalue(), end='')

    else:
        if not args.quiet:
            sep = "=" * 60
            print(config.color(sep, Fore.CYAN))
            packages_text = config.color("Packages found & counted: ", Fore.GREEN)
            count_text = config.color(f"{total_count}/{len(results)}", Fore.WHITE)
            print(f"{packages_text}{count_text}")
            size_label = config.color("Total size: ", Fore.GREEN)
            size_value = config.color(human_readable(total_size), Fore.WHITE)
            print(f"{size_label}{size_value}")
            time_label = config.color("Scan time: ", Fore.GREEN)
            time_value = config.color(f"{elapsed:.1f}s", Fore.WHITE)
            print(f"{time_label}{time_value}")
        else:
            for r in valid_results:
                _print_result(r, config)


if __name__ == "__main__":
    main()
