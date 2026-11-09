"""Explicit, collect-only loading of trusted adapters from one local Python package.

No discovery, installation, download, or sys.path changes. A configured package is
trusted executable Python, not sandboxed data. Its relative imports stay in its package.
"""

import importlib.util
import os
import re
import sys
from pathlib import Path

from jobsearch_cn import schema

MODULE_ENV = "JOBSEARCH_CN_PERSONAL_MODULE"
_PACKAGE = "_jobsearch_cn_personal"
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,39}")
RESERVED = ("beisen",)  # collect's own public adapters
_FUNCTIONS = ("search_url", "job_id_from_url", "canonical_url", "parse_cards", "list_is_empty",
              "page_problem", "is_closed", "parse_detail", "detail_text", "same_job", "location_matches")


class ModuleError(Exception):
    """An explicit local module cannot be loaded; no browser has been opened."""


def _local_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ModuleError(f"{MODULE_ENV} 必须是本机绝对路径，不接受 URL、相对路径或网络共享")
    if os.name == "nt":
        import ctypes
        # Mapped network drives are remote too; check before touching the path.
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ModuleError("个人模块不接受映射的网络盘")
    resolved = path.resolve(strict=True)
    if str(resolved).startswith(("\\\\", "//")):
        raise ModuleError("个人模块不能指向网络共享")
    if resolved.is_dir():
        resolved = resolved / "__init__.py"
    if resolved.name != "__init__.py" or not resolved.is_file():
        raise ModuleError("个人模块应是包含 __init__.py 的本地 Python 包目录")
    return resolved


def _validate(adapters):
    if not isinstance(adapters, dict):
        raise ModuleError("个人模块必须导出 ADAPTERS 字典")
    for name, site in adapters.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ModuleError("适配器名只能用小写字母、数字、下划线和短横线")
        if name in RESERVED:
            raise ModuleError(f"适配器名 {name} 已被公开适配器使用，换一个名字")
        if getattr(site, "SITE", None) not in schema.SITES:
            raise ModuleError(f"适配器 {name} 的 SITE 不属于收件格式")
        for attr in ("NAME", "CITY_CODES", "PAGINATION", "SELECTORS", "LIST_READY", "DETAIL_READY"):
            if not hasattr(site, attr):
                raise ModuleError(f"适配器 {name} 缺少 {attr}")
        if site.CITY_CODES is not None and any(not hasattr(site, attr) for attr in ("CITY_CODE", "CITY_CODE_HELP")):
            raise ModuleError(f"适配器 {name} 缺少城市代码规则")
        if site.PAGINATION not in ("url", "scroll"):
            raise ModuleError(f"适配器 {name} 的 PAGINATION 无效")
        if any(not callable(getattr(site, attr, None)) for attr in _FUNCTIONS):
            raise ModuleError(f"适配器 {name} 缺少采集契约函数")
    return dict(adapters)


def load_adapters() -> dict:
    value = os.environ.get(MODULE_ENV, "").strip()
    if not value:
        return {}
    try:
        path = _local_path(value)
        # A subsequent invocation may choose a different package. Never reuse its submodules.
        for name in list(sys.modules):
            if name == _PACKAGE or name.startswith(_PACKAGE + "."):
                del sys.modules[name]
        spec = importlib.util.spec_from_file_location(_PACKAGE, path,
                                                     submodule_search_locations=[str(path.parent)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[_PACKAGE] = module
        spec.loader.exec_module(module)
        return _validate(getattr(module, "ADAPTERS", None))
    except ModuleError:
        raise
    except Exception as exc:
        raise ModuleError(f"无法加载本地个人模块：{type(exc).__name__}: {exc}") from None
