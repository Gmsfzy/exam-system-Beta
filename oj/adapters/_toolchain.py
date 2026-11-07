# -*- coding: utf-8 -*-
"""C/C++ 编译器发现（v6.9 阶段 2）：支持「随项目走」的可移植工具链。

三级优先，命中即返回绝对路径，全部落空返回 None（调用方按 supported=False 回落人工）：
1. 显式配置：Config.OJ_GCC_PATH / OJ_GPP_PATH（或同名环境变量），可写绝对路径或可 which 的命令名；
2. 项目内便携工具链：tools/mingw64/bin/{gcc,g++}[.exe]——整目录随项目拷到别的 64 位 Windows 即开箱可用；
3. 系统 PATH：shutil.which（兼容 Linux 部署时 apt 装的 gcc/g++）。

定位与《存在隐患.md》#8 一致：subprocess 防呆级、非防逃逸。
"""
import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))            # .../oj/adapters
_ROOT = os.path.dirname(os.path.dirname(_HERE))               # 项目根

# 项目内便携工具链目录（winlibs 解压后的 mingw64 根）
_PORTABLE_BIN = os.path.join(_ROOT, 'tools', 'mingw64', 'bin')


def _resolve(spec):
    """把配置/环境里的取值解析成可执行绝对路径：绝对路径需存在，命令名走 which。"""
    if not spec:
        return None
    if os.path.isabs(spec):
        return spec if os.path.exists(spec) else None
    return shutil.which(spec)


def find_compiler(exe_name, cfg_attr=None, env_key=None):
    """按三级优先定位编译器可执行文件，返回绝对路径或 None。

    exe_name: 'gcc' / 'g++'（Windows 下项目内档自动补 .exe）。
    cfg_attr / env_key: 第一/二级读取的配置属性名与环境变量名（缺省则跳过该级）。
    """
    # 1. 显式配置（Config 属性）
    if cfg_attr:
        try:
            from config import Config
            p = _resolve(getattr(Config, cfg_attr, None))
            if p:
                return p
        except Exception:
            pass
    # 2. 环境变量
    if env_key:
        p = _resolve(os.environ.get(env_key))
        if p:
            return p
    # 3. 项目内便携工具链
    fname = exe_name + ('.exe' if os.name == 'nt' else '')
    cand = os.path.join(_PORTABLE_BIN, fname)
    if os.path.exists(cand):
        return cand
    # 4. 系统 PATH
    return shutil.which(exe_name)
