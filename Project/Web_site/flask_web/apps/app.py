from flask import Flask

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from pathlib import Path

from flask_wtf.csrf import CSRFProtect

from apps.config import config

from flask_login import LoginManager


db = SQLAlchemy()

csrf = CSRFProtect()

login_manager = LoginManager()
login_manager.login_view = "auth.login"

login_manager.login_message = ""

def create_app(config_key):
    app=Flask(__name__)
    app.config.from_object(config[config_key])
         
    db.init_app(app)

    Migrate(app, db)
    
    csrf.init_app(app)
    
    login_manager.init_app(app)

    from apps.auth import views as auth_views    
    app.register_blueprint(auth_views.auth, url_prefix="/auth")

    from apps.detector import views as dt_views    
    app.register_blueprint(dt_views.dt)
    
    from apps.stream import views as stream_views    
    app.register_blueprint(stream_views.stream, url_prefix="/stream")

    return app