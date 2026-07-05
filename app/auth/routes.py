# app/auth/routes.py
import hashlib
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import THEMES, User
from app import db, limiter
from app.decorators import admin_required, owner_required
from app.auth import auth
from app.uploads import save_image

HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
TIME_RE = re.compile(r'^\d{2}:\d{2}$')


def _parse_hex_color(value):
    return value if value and HEX_COLOR_RE.match(value) else None


def _parse_time(value):
    return value if value and TIME_RE.match(value) else None


def _save_logo(user, file_storage):
    """Validate and persist an uploaded logo, replacing any previous one."""
    new_filename = save_image(
        existing_filename=user.logo_filename,
        file_storage=file_storage,
        upload_dir=current_app.config['LOGO_UPLOAD_DIR'],
        filename_stub=f'logo_{user.id}',
        allowed_extensions=current_app.config['LOGO_ALLOWED_EXTENSIONS'],
        max_dimension=400,
    )
    if new_filename is None:
        return False
    user.logo_filename = new_filename
    return True


def _login_branding():
    """Logo/name/color for the pre-login screens (login, forgot/reset password) -
    not the full menu theme, since these pages are for the owner/staff, not customers."""
    owner = User.query.filter_by(is_owner=True).first()
    logo_url = (url_for('static', filename='uploads/logos/' + owner.logo_filename)
                if owner and owner.logo_filename else None)
    return {
        'business_name': (owner.business_name if owner and owner.business_name else None),
        'logo_url': logo_url,
        'primary_color': (owner.primary_color if owner and owner.primary_color else '#667eea'),
    }


@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('catalog.dashboard' if user.is_admin else 'main.index'))
        else:
            flash('Invalid email or password')

    return render_template('registration/login.html', **_login_branding())


@auth.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        owner = User.query.filter_by(is_owner=True).first()

        if user and owner and owner.backup_email_host:
            from app.backup import send_password_reset_email
            raw_token = secrets.token_urlsafe(32)
            user.reset_token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            user.reset_token_expires_at = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_url = url_for('auth.reset_password', token=raw_token, _external=True)
            send_password_reset_email(owner, user, reset_url)

        # Same message whether or not the email exists / email is configured,
        # so this can't be used to guess which accounts exist.
        flash('Si el correo existe y tenemos un correo de respaldo configurado, te enviamos un link para recuperar tu contraseña.')
        return redirect(url_for('auth.login'))

    return render_template('registration/forgot_password.html', **_login_branding())


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user = User.query.filter_by(reset_token_hash=token_hash).first()
    if not user or not user.reset_token_expires_at or user.reset_token_expires_at < datetime.utcnow():
        flash('Este link ya no es válido. Solicita uno nuevo.')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.')
            return render_template('registration/reset_password.html', **_login_branding())

        user.set_password(password)
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        db.session.commit()
        flash('Contraseña actualizada, ya puedes iniciar sesión.')
        return redirect(url_for('auth.login'))

    return render_template('registration/reset_password.html', **_login_branding())


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if User.query.first() is not None:
        flash('Este menú ya tiene un dueño configurado.')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not email or not password:
            flash('Completa todos los campos para registrarte.')
            return render_template('registration/register.html')

        try:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                is_admin=True,
                is_owner=True,
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash('Registro creado correctamente')
            return redirect(url_for('auth.setup_profile'))
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {e}')

    return render_template('registration/register.html')


@auth.route('/setup-profile', methods=['GET', 'POST'])
@login_required
def setup_profile():
    if request.method == 'POST':
        current_user.whatsapp_number = request.form.get('whatsapp_number', '').strip()
        current_user.business_name = request.form.get('business_name', '').strip()
        current_user.address = request.form.get('address', '').strip()

        logo = request.files.get('logo')
        if logo and logo.filename:
            if not _save_logo(current_user, logo):
                flash('El logo debe ser una imagen (png, jpg, jpeg o webp).')
                return render_template('registration/setup_profile.html')

        db.session.commit()

        flash('Perfil completado exitosamente')
        return redirect(url_for('main.index'))

    return render_template('registration/setup_profile.html')


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth.route('/admin')
@login_required
@owner_required
def admin_panel():
    return render_template('panel/index.html', themes=THEMES)


@auth.route('/admin/business-profile', methods=['POST'])
@login_required
@owner_required
def update_business_profile():
    current_user.is_closed_temporarily = 'is_closed_temporarily' in request.form
    current_user.closed_message = request.form.get('closed_message', '').strip() or None
    theme = request.form.get('theme', '').strip()
    if theme in THEMES:
        current_user.theme = theme
    current_user.whatsapp_number = request.form.get('whatsapp_number', '').strip()
    current_user.business_name = request.form.get('business_name', '').strip()
    current_user.address = request.form.get('address', '').strip()

    latitude = request.form.get('latitude', type=float)
    longitude = request.form.get('longitude', type=float)
    if latitude is not None and longitude is not None:
        current_user.latitude = latitude
        current_user.longitude = longitude

    primary_color = _parse_hex_color(request.form.get('primary_color', '').strip())
    accent_color = _parse_hex_color(request.form.get('accent_color', '').strip())
    if primary_color:
        current_user.primary_color = primary_color
    if accent_color:
        current_user.accent_color = accent_color

    current_user.accepts_cash = 'accepts_cash' in request.form
    current_user.accepts_transfer = 'accepts_transfer' in request.form
    current_user.accepts_card = 'accepts_card' in request.form
    if not (current_user.accepts_cash or current_user.accepts_transfer or current_user.accepts_card):
        current_user.accepts_cash = True
    current_user.bank_details = request.form.get('bank_details', '').strip() or None
    current_user.min_delivery_order = request.form.get('min_delivery_order', type=float)
    current_user.opens_at = _parse_time(request.form.get('opens_at', '').strip())
    current_user.closes_at = _parse_time(request.form.get('closes_at', '').strip())
    current_user.printer_ip = request.form.get('printer_ip', '').strip() or None
    current_user.printer_width_mm = request.form.get('printer_width_mm', type=int) or 80
    current_user.backup_email_host = request.form.get('backup_email_host', '').strip() or None
    current_user.backup_email_port = request.form.get('backup_email_port', type=int)
    current_user.backup_email_address = request.form.get('backup_email_address', '').strip() or None
    current_user.backup_email_to = request.form.get('backup_email_to', '').strip() or None
    new_backup_password = request.form.get('backup_email_password', '')
    if new_backup_password:
        current_user.backup_email_password = new_backup_password

    logo = request.files.get('logo')
    if logo and logo.filename:
        if not _save_logo(current_user, logo):
            flash('El logo debe ser una imagen (png, jpg, jpeg o webp).')
            return redirect(url_for('auth.admin_panel'))

    db.session.commit()
    flash('Perfil del negocio actualizado')
    return redirect(url_for('auth.admin_panel'))


@auth.route('/admin/staff', methods=['GET', 'POST'])
@login_required
@owner_required
def manage_staff():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('Completa nombre, correo y contraseña para crear la cuenta.')
        elif len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.')
        elif User.query.filter_by(email=email).first() or User.query.filter_by(username=username).first():
            flash('Ya existe una cuenta con ese correo o nombre de usuario.')
        else:
            staff = User(username=username, email=email, is_admin=True, is_owner=False)
            staff.set_password(password)
            db.session.add(staff)
            db.session.commit()
            flash('Cuenta de personal creada.')
        return redirect(url_for('auth.manage_staff'))

    staff_accounts = User.query.filter_by(is_owner=False).order_by(User.id).all()
    return render_template('panel/staff.html', staff_accounts=staff_accounts)


@auth.route('/admin/staff/<int:user_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_staff(user_id):
    staff = User.query.get_or_404(user_id)
    if staff.is_owner:
        flash('No puedes eliminar la cuenta del dueño.')
        return redirect(url_for('auth.manage_staff'))
    db.session.delete(staff)
    db.session.commit()
    flash('Cuenta de personal eliminada.')
    return redirect(url_for('auth.manage_staff'))


@auth.route('/admin/backup/send-now', methods=['POST'])
@login_required
@owner_required
def send_backup_now():
    from app.backup import send_backup_email
    ok, error = send_backup_email(current_user)
    if ok:
        current_user.backup_last_sent_at = datetime.utcnow()
        db.session.commit()
        flash('Respaldo enviado a tu correo.')
    else:
        flash(error)
    return redirect(url_for('auth.admin_panel'))
