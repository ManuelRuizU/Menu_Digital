# app/backup.py
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

from flask import current_app


def _database_path():
    uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    if not uri.startswith('sqlite:///'):
        return None
    path = uri[len('sqlite:///'):]
    if not os.path.isabs(path):
        path = os.path.join(current_app.instance_path, path)
    return path


def _send_email(owner, to_address, subject, body_text, attachment_bytes=None, attachment_filename=None):
    """Low-level send using the owner's own configured SMTP account - the same
    one used for database backups, reused here so password resets don't need
    any separate email service or vendor-shared inbox.

    Returns (ok, error_message).
    """
    required = [owner.backup_email_host, owner.backup_email_address, owner.backup_email_password]
    if not owner or not all(required):
        return False, 'No hay un correo de respaldo configurado en Perfil del negocio.'

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = owner.backup_email_address
    msg['To'] = to_address
    msg.set_content(body_text)

    if attachment_bytes is not None:
        msg.add_attachment(attachment_bytes, maintype='application', subtype='octet-stream',
                            filename=attachment_filename)

    try:
        port = owner.backup_email_port or 587
        with smtplib.SMTP(owner.backup_email_host, port, timeout=20) as server:
            server.starttls()
            server.login(owner.backup_email_address, owner.backup_email_password)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, f'No se pudo enviar el correo ({e}).'


def send_backup_email(owner):
    """Email the current SQLite database as an attachment using the owner's own
    email account (no third-party backup service, no extra cost).

    Returns (ok, error_message).
    """
    if not owner or not owner.backup_email_to:
        return False, 'Configura los datos de correo para el respaldo en Perfil del negocio.'

    db_path = _database_path()
    if not db_path or not os.path.exists(db_path):
        return False, 'No se encontró el archivo de la base de datos.'

    business_name = owner.business_name or 'Menu Digital'
    today = datetime.utcnow().strftime('%Y-%m-%d')

    with open(db_path, 'rb') as f:
        db_bytes = f.read()

    return _send_email(
        owner,
        to_address=owner.backup_email_to,
        subject=f'Respaldo {business_name} - {today}',
        body_text=(
            f'Respaldo automático de la base de datos de {business_name}, generado el {today}.\n'
            'Guarda este correo - si algo le pasa al computador o al pendrive, este archivo permite recuperar todo.'
        ),
        attachment_bytes=db_bytes,
        attachment_filename=f'respaldo_{today}.db',
    )


def send_password_reset_email(owner, user, reset_url):
    """Send a password reset link to `user` (owner or staff), sent out through
    the owner's own configured SMTP account - the only mail sender this app has.

    Returns (ok, error_message).
    """
    business_name = owner.business_name or 'Menu Digital'
    return _send_email(
        owner,
        to_address=user.email,
        subject=f'Recuperar contraseña - {business_name}',
        body_text=(
            f'Hola {user.username},\n\n'
            f'Alguien solicitó restablecer la contraseña de tu cuenta en el panel de {business_name}.\n'
            f'Si fuiste tú, entra a este link (válido por 1 hora):\n\n{reset_url}\n\n'
            'Si no fuiste tú, ignora este correo y tu contraseña seguirá igual.'
        ),
    )
