# app/admin.py
from flask_admin import AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_login import current_user
from flask import redirect, url_for

class MyAdminIndexView(AdminIndexView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login'))

class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login'))


class UserModelView(MyModelView):
    """Owner-only, view/edit only - staff accounts are created via /admin/staff,
    never through this generic CRUD view, so it can't be used to mint more owners."""
    can_create = False
    can_delete = False

    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin and current_user.is_owner
