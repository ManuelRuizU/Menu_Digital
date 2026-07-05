# Guía de despliegue

Dos caminos, según lo conversado: **PythonAnywhere** (gratis, para partir sin costo) y un **VPS básico** (pagado, para cuando el cliente quiera su propio dominio `.cl`). Ambos corren la misma aplicación sin cambios de código - lo único que cambia es dónde vive.

> Nota: estos pasos están escritos según cómo documentan su propio funcionamiento estas plataformas - no los probé contra una cuenta real (no tengo forma de crear una). Sigue los pasos y avísame si algo no calza exactamente para ajustarlo.

---

## Opción A: PythonAnywhere (gratis)

Bueno para partir sin gastar nada. Da una URL tipo `tunegocio.pythonanywhere.com` (sin dominio propio en el plan gratis).

1. Crea una cuenta gratis en [pythonanywhere.com](https://www.pythonanywhere.com).

2. Abre una consola **Bash** desde el dashboard y clona el proyecto:

   ```bash
   git clone https://github.com/ManuelRuizU/Menu_Digital.git
   cd Menu_Digital
   ```

3. Crea el entorno virtual e instala las dependencias:

   ```bash
   python3.10 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Inicializa la base de datos:

   ```bash
   flask db upgrade
   ```

5. Ve a la pestaña **Web** del dashboard → "Add a new web app" → elige **Manual configuration** (no uses la plantilla Flask automática) → Python 3.10.

6. En "Virtualenv", indica la ruta al entorno que creaste (ej. `/home/tuusuario/Menu_Digital/.venv`).

7. Abre el archivo WSGI que te generan (link en la misma página) y reemplaza el contenido por:

   ```python
   import sys
   path = '/home/tuusuario/Menu_Digital'
   if path not in sys.path:
       sys.path.insert(0, path)

   from manage import app as application
   ```

8. En "Environment variables" (misma pestaña Web), agrega `SECRET_KEY` con un valor largo y aleatorio.

9. Toca **Reload** en la pestaña Web.

10. Entra a `https://tunegocio.pythonanywhere.com/register` y crea la cuenta del dueño.

**Limitación a verificar**: las cuentas gratuitas de PythonAnywhere restringen las conexiones salientes a una lista blanca de sitios. La búsqueda de direcciones (mapa) corre en el navegador del cliente, así que no debería verse afectada - pero el **respaldo automático por correo** sí corre desde el servidor, y podría no funcionar en el plan gratis si Gmail no está en esa lista blanca. Configúralo y prueba "Enviar respaldo ahora" para confirmar; si falla por esto, la alternativa es el VPS (opción B) o Oracle Cloud Free Tier, que no tienen esa restricción.

---

## Opción B: VPS con dominio propio (pagado)

Sirve igual en DigitalOcean, Vultr, Linode, un plan **VPS** de HostGator, o cualquier proveedor que dé un servidor Ubuntu. Usamos Nginx delante de Gunicorn (lo estándar para Flask en producción) y Let's Encrypt para HTTPS gratis.

### 1. Preparar el servidor

Crea un VPS con **Ubuntu 22.04**, y conéctate por SSH:

```bash
ssh root@la_ip_del_servidor
```

Instala lo necesario:

```bash
apt update && apt upgrade -y
apt install -y python3-venv python3-pip nginx git
```

### 2. Subir y configurar la aplicación

```bash
cd /opt
git clone https://github.com/ManuelRuizU/Menu_Digital.git
cd Menu_Digital
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Inicializa la base de datos (esto también genera sola una clave secreta fija en `instance/secret_key`, que se reutiliza en cada reinicio):

```bash
flask db upgrade
```

### 3. Gunicorn como servicio (para que se reinicie solo)

Crea `/etc/systemd/system/menudigital.service`:

```ini
[Unit]
Description=Menu Digital
After=network.target

[Service]
WorkingDirectory=/opt/Menu_Digital
ExecStart=/opt/Menu_Digital/.venv/bin/gunicorn -w 1 --timeout 60 -b 127.0.0.1:8000 manage:app
Restart=always

[Install]
WantedBy=multi-user.target
```

`-w 1` (un solo worker) es intencional: el respaldo automático corre dentro del proceso y con más de un worker se duplicaría.

```bash
systemctl daemon-reload
systemctl enable --now menudigital
systemctl status menudigital
```

### 4. Nginx como puerta de entrada

Crea `/etc/nginx/sites-available/menudigital`:

```nginx
server {
    listen 80;
    server_name mitienda.cl www.mitienda.cl;

    client_max_body_size 15M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/menudigital /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

`client_max_body_size 15M` es necesario porque las fotos de celular sin comprimir pueden llegar hasta 12 MB (el servidor las comprime al guardarlas, pero primero tienen que poder llegar).

### 5. Dominio y HTTPS

En el proveedor del dominio (NIC Chile u otro), crea un registro **A** apuntando `mitienda.cl` a la IP del VPS.

Una vez que el dominio resuelva a esa IP (puede tardar unas horas), genera el certificado HTTPS gratis:

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d mitienda.cl -d www.mitienda.cl
```

Certbot configura Nginx automáticamente y renueva el certificado solo.

### 6. Primer acceso

Entra a `https://mitienda.cl/register` y crea la cuenta del dueño.

---

## Migrar de la opción gratis a la de dominio propio

Como todo vive en un solo archivo, el traspaso es simple:

1. En PythonAnywhere, descarga `instance/app.db` y la carpeta `app/static/uploads/`.
2. En el VPS ya configurado (pasos de arriba, sin haber creado ninguna cuenta todavía), reemplaza esos mismos archivos/carpetas por los descargados.
3. Reinicia el servicio: `systemctl restart menudigital`.

Todo el negocio, pedidos y clientes quedan intactos en la nueva dirección.
