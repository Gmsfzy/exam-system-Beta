from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

# 创建 db / bcrypt 实例，但不立即初始化（在 app.py 中 init_app）
# bcrypt 放在 database 包下，避免 models.py 反向 import app 造成循环依赖
db = SQLAlchemy()
bcrypt = Bcrypt()
