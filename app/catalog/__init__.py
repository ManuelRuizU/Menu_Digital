from flask import Blueprint

catalog = Blueprint('catalog', __name__, url_prefix='/admin')

from app.catalog import banners, coupon_usage, routes  # noqa: E402,F401 - registers the routes
