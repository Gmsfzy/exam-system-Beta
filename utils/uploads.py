# -*- coding: utf-8 -*-
"""统一文件上传工具（v4.6）

竞赛（资料包/作品）、自主学习（笔记/资料附件）、征集悬赏（投稿附件）共用同一
扩展名白名单与落盘逻辑：文档 / 表格(csv/xls/xlsx) / 压缩包 / 图片 / 视频 / 代码，
不收可执行文件。UUID 命名平铺存入根目录 uploads/，单文件上限 50MB
（app.py 另有全局 MAX_CONTENT_LENGTH + nosniff 兜底）。
"""
import os
import secrets

# 上传根目录（项目根 uploads/）：竞赛/学习/悬赏/作业共用同一落盘位置，
# 避免各业务模块重复计算路径或跨模块 import 私有常量（v5.1 上移）。
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')

# 扩展白名单（小写含点）
ALLOWED_EXTENSIONS = {
    # 文档
    '.pdf', '.doc', '.docx', '.txt', '.md', '.ppt', '.pptx',
    # 表格
    '.xls', '.xlsx', '.csv',
    # 压缩包
    '.zip', '.rar', '.7z',
    # 图片
    '.png', '.jpg', '.jpeg', '.gif', '.webp',
    # 视频
    '.mp4', '.webm',
    # 代码
    '.py', '.java', '.c', '.cpp', '.js', '.ts', '.html', '.css', '.sql',
}

MAX_FILE_BYTES = 50 * 1024 * 1024


def _describe_exts():
    return '/'.join(sorted(e.lstrip('.') for e in ALLOWED_EXTENSIONS))


def save_upload(file, prefix, upload_dir=None):
    """校验并保存 Werkzeug FileStorage，返回 (stored_name, size)；出错抛 ValueError。

    prefix 为落盘文件名前缀（如 comp_res/work/note/bounty_sub/hwref）。
    upload_dir 缺省用模块级 UPLOAD_DIR（各业务模块可显式传入自定义目录）。
    """
    if upload_dir is None:
        upload_dir = UPLOAD_DIR
    if not file or not file.filename:
        raise ValueError('请选择文件')
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError('不支持的文件类型：' + (ext or '无扩展名')
                         + '；支持 ' + _describe_exts())
    # multipart 下 content_length 常为 None，用 stream 实际探测大小
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_FILE_BYTES:
        raise ValueError('文件大小不能超过 50MB')
    os.makedirs(upload_dir, exist_ok=True)
    stored = f'{prefix}_{secrets.token_hex(12)}{ext}'
    file.save(os.path.join(upload_dir, stored))
    return stored, size
