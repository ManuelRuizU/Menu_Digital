from flask import Blueprint

catalog = Blueprint('catalog', __name__, url_prefix='/admin')

from app.catalog import routes
