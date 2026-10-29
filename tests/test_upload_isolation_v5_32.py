# -*- coding: utf-8 -*-
"""v5.32 上传目录隔离契约：测试进程一律不得写/读真实 uploads/。

背景：临时库只隔开数据，上传链路把文件写到库外的项目根 uploads/，
`stored_name` 随临时库销毁而文件留存 → 每轮全量测试稳定制造约 60 个孤儿
（v5.26.1 清 828、v5.28.1 清 54 后又积 63）。conftest 的 `isolate_upload_dir`
逐个替换各模块 import 期绑定的目录属性，本文件把隔离效果钉死。
"""
import os

from werkzeug.datastructures import FileStorage

from utils.uploads import save_upload

# 业务模块 → 它自己那份落盘目录属性名（conftest._UPLOAD_BINDINGS 的同源副本）
_MODULE_ATTRS = (
    ('api.learning_routes', '_UPLOAD_DIR'),
    ('bounty.routes', '_UPLOAD_DIR'),
    ('competition.routes', '_UPLOAD_DIR'),
    ('dsci.routes', '_UPLOAD_DIR'),
    ('homework.routes', '_UPLOAD_DIR'),
    ('api.question_routes', 'UPLOAD_FOLDER'),
    ('app', 'UPLOAD_FOLDER'),
)


def _real_dir():
    """项目根 uploads/（与 utils.uploads 计算源一致，但绕过已被打补丁的值）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, 'uploads')


def test_every_module_binding_points_to_sandbox(isolate_upload_dir):
    """逐个替换必须全部生效：只改 utils.uploads.UPLOAD_DIR 挡不住按位置传参的调用点。"""
    stale = [(m, a) for m, a in _MODULE_ATTRS
             if getattr(__import__(m, fromlist=[a]), a) != isolate_upload_dir]
    assert stale == [], '这些模块的上传目录没被隔离：%s' % stale


def test_source_of_truth_and_serving_route_isolated(isolate_upload_dir):
    import utils.uploads as uploads_mod
    import api.question_routes as question_mod
    import app as app_mod

    assert uploads_mod.UPLOAD_DIR == isolate_upload_dir
    # 读路径同样隔开：/uploads/<name> 不得回落到真实用户文件
    assert question_mod.UPLOAD_FOLDER == isolate_upload_dir
    assert app_mod.UPLOAD_FOLDER == isolate_upload_dir
    assert os.path.realpath(isolate_upload_dir) != os.path.realpath(_real_dir())


def test_default_dir_caller_writes_into_sandbox(isolate_upload_dir):
    """`save_upload(f, prefix)` 省略目录时回落模块级 UPLOAD_DIR（dsci/homework 用法）。"""
    before = set(os.listdir(_real_dir()))
    stored, size = save_upload(
        FileStorage(stream=__import__('io').BytesIO(b'a,b\n1,2\n'),
                    filename='iso.csv'), 'iso')
    assert size == 8
    assert os.path.isfile(os.path.join(isolate_upload_dir, stored))
    assert not os.path.exists(os.path.join(_real_dir(), stored))
    assert set(os.listdir(_real_dir())) == before, '真实 uploads/ 出现新增文件'


def test_direct_disk_writer_isolated(isolate_upload_dir):
    """绕过 save_upload 的裸写盘点（dsci._save_pred_csv 直接 open）也要落沙箱。"""
    from dsci import routes as dsci_routes

    before = set(os.listdir(_real_dir()))
    stored = dsci_routes._save_pred_csv('id,label\n0,1\n')
    assert stored.startswith('dssub_')
    assert os.path.isfile(os.path.join(isolate_upload_dir, stored))
    assert set(os.listdir(_real_dir())) == before


def test_note_image_inline_writer_isolated(isolate_upload_dir):
    """学习笔记配图内嵌用 file.save(_UPLOAD_DIR)（v5.31 引入的用法），同属隔离面。"""
    import uuid
    from api import learning_routes as lr

    before = set(os.listdir(_real_dir()))
    name = 'note_%s.png' % uuid.uuid4().hex
    with open(os.path.join(lr._UPLOAD_DIR, name), 'wb') as f:
        f.write(b'\x89PNG\r\n')
    assert os.path.isfile(os.path.join(isolate_upload_dir, name))
    assert set(os.listdir(_real_dir())) == before
