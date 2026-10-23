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


HALF_WIDTH = 960


def half_width_filename(filename):
    """'banner_3_ab12.jpg' -> 'banner_3_ab12_960.jpg': the smaller copy save_image_with_half
    writes next to a wide image, for the 960w entry of an <img srcset>."""
    stem, dot, ext = filename.rpartition('.')
    return f'{stem}_{HALF_WIDTH}.{ext}'


def save_image_with_half(existing_filename, file_storage, upload_dir, filename_stub, allowed_extensions,
                         max_dimension=1920):
    """save_image, plus a HALF_WIDTH-wide copy (same format) when the saved image is wider
    than that - phones then download about a quarter of the pixels. A previous image's
    copy is removed along with it. Returns the main filename, or None if rejected."""
    new_filename = save_image(existing_filename, file_storage, upload_dir, filename_stub, allowed_extensions,
                              max_dimension=max_dimension)
    if new_filename is None:
        return None
    if existing_filename:
        # Also when the name is reused (coupon_<id>.jpg): a narrower new image gets no copy.
        delete_image(upload_dir, half_width_filename(existing_filename))
    path = os.path.join(upload_dir, new_filename)
    with Image.open(path) as image:
        if image.width > HALF_WIDTH:
            height = round(image.height * HALF_WIDTH / image.width)
            half = image.resize((HALF_WIDTH, height), Image.LANCZOS)
            options = {'optimize': True} if image.format == 'PNG' else {'quality': 82, 'optimize': True}
            half.save(os.path.join(upload_dir, half_width_filename(new_filename)), format=image.format, **options)
    return new_filename


def delete_image(upload_dir, filename):
    """Remove an uploaded image and its half-width copy, if any - missing files are fine."""
    if not filename:
        return
    for name in (filename, half_width_filename(filename)):
        path = os.path.join(upload_dir, name)
        if os.path.exists(path):
            os.remove(path)
