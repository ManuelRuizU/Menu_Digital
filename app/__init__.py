# app/__init__.py
from flask import Flask
from config import Config
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_migrate import Migrate, stamp
from sqlalchemy import inspect
from .extensions import db  # Importa db desde extensions.py
from app.admin import MyAdminIndexView, UserModelView


login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
# In-memory storage is fine for the single Gunicorn worker this app is designed to run with -
# no Redis or other paid/extra service needed just to rate-limit login and order creation.
limiter = Limiter(key_func=get_remote_address)

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # Redirigir a la vista de login
    csrf.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # Los modelos deben importarse antes de create_all() para que sus tablas
    # queden registradas en los metadatos de SQLAlchemy.
    from app.models import User, Product, Category, Subcategory

    with app.app_context():
        inspector = inspect(db.engine)
        is_fresh_install = 'alembic_version' not in inspector.get_table_names()
        if is_fresh_install:
            # A brand new database has no schema at all yet: create it from the
            # current models and mark it as up to date, instead of letting
            # `flask db upgrade` replay history meant for pre-existing installs.
            db.create_all()
            stamp()
        # Existing installs must go through `flask db upgrade` for schema changes -
        # calling create_all() here too would create new tables ahead of their own
        # migration and make it fail with "table already exists".

    # Configurar Flask-Admin (Category/Subcategory/Product/Order tienen su propio panel en /admin/*)
    admin = Admin(app, name='Admin', index_view=MyAdminIndexView())
    admin.add_view(UserModelView(User, db.session))

    from app.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from app.auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from app.catalog import catalog as catalog_blueprint
    app.register_blueprint(catalog_blueprint)

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    _start_backup_scheduler(app)

    return app


def _start_backup_scheduler(app):
    """Daily automatic database backup by email, if the owner has configured it.

    Runs in-process (APScheduler, free/open-source) - no external cron job needed.
    Assumes a single worker process (as used throughout this project); scaling to
    multiple Gunicorn workers would need a guard against sending the backup once per worker.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from app.models import BUSINESS_TZ, User

    def run_backup():
        with app.app_context():
            from datetime import datetime
            from app.backup import send_backup_email
            owner = User.query.filter_by(is_owner=True).first()
            if owner and owner.backup_email_host:
                ok, _ = send_backup_email(owner)
                if ok:
                    owner.backup_last_sent_at = datetime.utcnow()
                    db.session.commit()

    scheduler = BackgroundScheduler(timezone=BUSINESS_TZ, daemon=True)
    scheduler.add_job(run_backup, CronTrigger(hour=3, minute=0))
    scheduler.start()


@login_manager.user_loader
def load_user(user_id):
    from app.models import User  # Importa User dentro de la función
    return User.query.get(int(user_id))

