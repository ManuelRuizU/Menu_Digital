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

---

## Opción C: varios clientes en el mismo VPS, con subdominios

Para cuando alojas varios negocios en un solo servidor (ej. `pizzasdonpedro.surdigital.cl`, `otronegocio.surdigital.cl`) en vez de un VPS por cliente. Es el mismo VPS de la Opción B, con más instalaciones adentro - cada cliente sigue siendo una instalación completa e independiente (su propia base de datos, su propio proceso), solo que conviven en el mismo servidor para ahorrar costo.

**Por qué una copia completa por cliente y no una sola compartida**: así cada negocio queda tan aislado como si tuviera su propio servidor - un problema en los datos de un cliente no puede tocar los de otro, y coincide con el resto de esta guía sin tener que tocar código. El costo es un poco más de disco por cliente (~200-300 MB cada uno, incluyendo su propio entorno virtual) - con almacenamiento NVMe de sobra en estos planes, no es un problema real hasta con 15-20 clientes.

### 1. Una carpeta y un servicio por cliente

Repite esto por cada cliente nuevo, cambiando el nombre y el puerto (8001, 8002, 8003...):

```bash
cd /opt/clientes
git clone https://github.com/ManuelRuizU/Menu_Digital.git pizzasdonpedro
cd pizzasdonpedro
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade
```

Crea `/etc/systemd/system/pizzasdonpedro.service` (mismo formato que en la Opción B, con un puerto distinto por cliente):

```ini
[Unit]
Description=Menu Digital - Pizzas Don Pedro
After=network.target

[Service]
WorkingDirectory=/opt/clientes/pizzasdonpedro
ExecStart=/opt/clientes/pizzasdonpedro/.venv/bin/gunicorn -w 1 --timeout 60 -b 127.0.0.1:8001 manage:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now pizzasdonpedro
```

### 2. DNS: subdominios apuntando al mismo VPS

En el proveedor de DNS de `surdigital.cl`, crea un registro **A** por cada subdominio (o uno solo tipo wildcard `*.surdigital.cl`) apuntando a la IP del VPS.

**Recomendación**: mueve el DNS de `surdigital.cl` a Cloudflare (gratis) en vez de dejarlo en el DNS del registrador - hace mucho más simple el paso siguiente (certificado wildcard), porque certbot tiene un conector oficial para Cloudflare que actualiza los registros automáticamente en cada renovación, sin tocar nada a mano.

### 3. Certificado wildcard (cubre todos los subdominios de una vez)

A diferencia de la Opción B (un dominio simple), acá conviene un solo certificado que cubra `*.surdigital.cl` - así no hay que sacar uno nuevo cada vez que agregas un cliente. Esto requiere validar que controlas el DNS (no basta con que el sitio responda), por eso el paso de Cloudflare de arriba:

```bash
apt install -y certbot python3-certbot-dns-cloudflare
```

Crea `/etc/letsencrypt/cloudflare.ini` con un token de API de Cloudflare (se genera en el dashboard de Cloudflare, con permiso de solo editar DNS):

```ini
dns_cloudflare_api_token = tu_token_aqui
```

```bash
chmod 600 /etc/letsencrypt/cloudflare.ini

certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d surdigital.cl -d '*.surdigital.cl'
```

Certbot renueva esto solo (incluyendo el wildcard) sin que tengas que hacer nada más.

### 4. Nginx: un bloque por cliente, mismo certificado para todos

Crea `/etc/nginx/sites-available/pizzasdonpedro`:

```nginx
server {
    listen 443 ssl;
    server_name pizzasdonpedro.surdigital.cl;

    ssl_certificate /etc/letsencrypt/live/surdigital.cl/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/surdigital.cl/privkey.pem;

    client_max_body_size 15M;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name pizzasdonpedro.surdigital.cl;
    return 301 https://$host$request_uri;
}
```

```bash
ln -s /etc/nginx/sites-available/pizzasdonpedro /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

Repite el bloque de Nginx (con su propio puerto) por cada cliente nuevo - el certificado wildcard ya los cubre a todos, no hay que sacar uno nuevo.

### 5. Primer acceso de cada cliente

`https://pizzasdonpedro.surdigital.cl/register` - igual que siempre, la primera visita crea al dueño de esa instalación específica.

### Cuándo subir de plan

Cada cliente nuevo es una copia completa corriendo en paralelo (~116 MB de RAM medidos en esta app). Con un plan de 4 GB, el techo cómodo son unos 10-12 clientes antes de que convenga subir a un plan con más RAM/CPU - revisa el uso real con `free -h` y `htop` a medida que sumas clientes, y sube de plan antes de que el rendimiento se sienta, no después.

---

## Opción D: Railway (pagado, más barato que el plan pagado de PythonAnywhere)

Railway parte en US$5/mes (incluye ese mismo monto de crédito de uso) contra los US$10/mes del plan Developer de PythonAnywhere - pero a diferencia de las opciones A y B, **la base de datos no es un archivo SQLite**, es un servicio PostgreSQL aparte. El código ya soporta esto (lee `DATABASE_URL` si existe, y si no, usa SQLite por defecto) - lo único que cambia es cómo se despliega.

1. Crea una cuenta en [railway.com](https://railway.com) y un proyecto nuevo.

2. **Agrega un servicio PostgreSQL** ("New" → "Database" → "PostgreSQL"). Railway genera solo la variable `DATABASE_URL` para ese servicio.

3. **Agrega el servicio de la app** ("New" → "GitHub Repo" → elige `Menu_Digital`). Railway detecta que es Python y usa el `Procfile` de la raíz del proyecto:

   ```
   web: gunicorn -w 1 --timeout 60 -b 0.0.0.0:$PORT manage:app
   ```

   (`$PORT` lo asigna Railway solo - no se fija un puerto como en el VPS. `-w 1` sigue siendo importante por la misma razón que en la Opción B: el respaldo automático no debe duplicarse.)

4. En la pestaña **Variables** del servicio de la app, agrega:
   - `SECRET_KEY`: un valor largo y aleatorio.
   - `DATABASE_URL`: usa la referencia a la variable del servicio Postgres (Railway te deja enlazarla directo, sin copiar el valor a mano - busca "Add a Reference" o similar en el editor de variables).

5. **Inicializa la base de datos.** Desde la pestaña del servicio de la app, abre una consola/shell (Railway la ofrece integrada, o usa `railway run` con su CLI desde tu computador) y corre:

   ```bash
   flask db upgrade
   ```

6. Railway te da una URL tipo `menudigital-production.up.railway.app` automáticamente (HTTPS incluido). Si quieres dominio propio, se agrega desde la pestaña **Settings** del servicio.

7. Entra a `https://tu-servicio.up.railway.app/register` y crea la cuenta del dueño.

**Diferencia importante en el respaldo automático:** en SQLite, el respaldo por correo adjunta el archivo `.db` tal cual. En Postgres no hay un archivo que copiar, así que el respaldo se genera como un **JSON con todas las tablas** (mismo botón, mismo correo configurado en Perfil del negocio - la app detecta sola qué motor está usando). Para restaurar ese `.json` en caso de emergencia, existe `restore_backup.py`:

```bash
python restore_backup.py respaldo_2026-01-01.json
```

Esto borra y vuelve a cargar cada tabla que venga en el archivo - úsalo solo para recuperar un desastre, no como rutina.
