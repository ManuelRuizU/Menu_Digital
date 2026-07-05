# app/uploads.py
import os

from PIL import Image, ImageOps
from werkzeug.utils import secure_filename


def save_image(existing_filename, file_storage, upload_dir, filename_stub, allowed_extensions, max_dimension=1000):
    """Validate, resize/compress, and persist an uploaded image, replacing any previous one.

    Re-encoding as JPEG (or PNG when the source has transparency) and capping the
    longest side at max_dimension keeps phone photos from bloating the site - a
    typical 4-8 MB camera shot becomes a couple hundred KB with no visible loss at
    the sizes these images are actually displayed at.

    Returns the new filename, or None if the upload was rejected.
    """
    filename = file_storage.filename or ''
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in allowed_extensions:
        return None

    try:
        image = Image.open(file_storage.stream)
        image.load()
    except Exception:
        return None

    image = ImageOps.exif_transpose(image)
    image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

    has_alpha = image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)

    os.makedirs(upload_dir, exist_ok=True)

    if existing_filename:
        old_path = os.path.join(upload_dir, existing_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    if has_alpha:
        new_filename = secure_filename(f'{filename_stub}.png')
        image.convert('RGBA').save(os.path.join(upload_dir, new_filename), format='PNG', optimize=True)
    else:
        new_filename = secure_filename(f'{filename_stub}.jpg')
        image.convert('RGB').save(os.path.join(upload_dir, new_filename), format='JPEG', quality=82, optimize=True)

    return new_filename
