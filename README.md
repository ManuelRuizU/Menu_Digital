# Menú Digital

Menú digital para negocios de comida que reciben y cierran sus pedidos por WhatsApp. El cliente arma su pedido en una página web simple (sin registrarse), y lo envía por WhatsApp al negocio. El dueño gestiona todo desde un panel de administración: productos, categorías, zonas de reparto, pedidos, repartidores, personal, respaldo automático e impresión de tickets.

Pensado para un solo negocio por instalación - no es un SaaS ni un marketplace. Se instala una vez y queda funcionando de forma independiente.

## Requisitos

- Python 3.10 o superior
- Una base de datos SQLite (se crea sola, no requiere instalar nada aparte)

## Instalación

1. Clona o descarga este repositorio.

2. Crea un entorno virtual e instala las dependencias:

   ```bash
   python -m venv .venv
   source .venv/bin/activate       # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Aplica las migraciones de base de datos (en una instalación nueva, esto crea `instance/app.db` automáticamente):

   ```bash
   flask db upgrade
   ```

   Si por algún motivo no existe todavía la carpeta `instance/`, créala primero:

   ```bash
   mkdir -p instance
   ```

4. Levanta el servidor para probarlo:

   ```bash
   python manage.py --port 5000
   ```

   Abre `http://localhost:5000` en el navegador.

## Primer uso: crear el dueño

Ve a `http://localhost:5000/register` y crea la cuenta del dueño (nombre, correo, contraseña). Esta pantalla **solo funciona una vez** - la primera persona que se registra queda como dueño permanente de esta instalación. Después de esa primera cuenta, `/register` queda bloqueado y solo se puede entrar por `/login`.

Tras registrarte, entra a **Perfil del negocio** para configurar:

- Nombre del negocio, dirección, logo, colores
- Número de WhatsApp donde llegan los pedidos
- Métodos de pago que aceptas
- Horario de atención (opcional)
- Impresora térmica WiFi/LAN (opcional, ej. Xprinter)
- Respaldo automático por correo (opcional, muy recomendado)

Luego en **Categorías** y **Productos** carga tu menú, y en **Zonas de reparto** define tus rangos de despacho por distancia o áreas dibujadas en el mapa (si no configuras ninguna, el despacho queda oculto y solo se ofrece Retiro).

## Recuperar acceso si se te olvida la contraseña

Si ya configuraste el respaldo por correo en Perfil del negocio, usa "¿Olvidaste tu contraseña?" en la pantalla de login.

Si no lo configuraste, hay un script de emergencia que restablece (o crea) la cuenta del dueño directamente en la base de datos:

```bash
python create_superuser.py
```

Pide un correo y contraseña por consola (o se pueden pasar como variables de entorno `SUPERUSER_EMAIL`, `SUPERUSER_USERNAME`, `SUPERUSER_PASSWORD`).

**Importante**: usa el mismo `SUPERUSER_EMAIL` de la cuenta que ya existe, para que el script actualice esa cuenta en vez de crear una nueva. Si no indicas `SUPERUSER_USERNAME`, el script lo deja como "admin" por defecto - no afecta el login (que usa el correo, no el usuario), pero puede sorprenderte si esperabas ver tu nombre de usuario original.

## Ejecutar en producción

Para un uso real (no solo pruebas), usa Gunicorn en vez del servidor de desarrollo:

```bash
gunicorn -w 1 --timeout 60 -b 0.0.0.0:5000 manage:app
```

Se recomienda mantener **un solo worker** (`-w 1`): el respaldo automático por correo corre dentro del mismo proceso, y con más de un worker se enviaría duplicado.

## Variables de entorno opcionales

| Variable | Para qué sirve | Valor por defecto |
|---|---|---|
| `SECRET_KEY` | Clave de seguridad de Flask | Se genera sola y se guarda en `instance/secret_key` |
| `DATABASE_URL` | Ubicación de la base de datos | `sqlite:///app.db` (queda en `instance/app.db`) |

## Pruebas automáticas

Cubren la lógica que es fácil de romper sin darse cuenta (zonas de reparto, horario de atención,
descuento de stock, recálculo de totales) - no la parte visual. Antes de instalar Flask-Limiter
y cryptography por separado, `requirements-dev.txt` ya incluye todo lo necesario:

```bash
pip install -r requirements-dev.txt
pytest
```

## Estructura del proyecto

```
app/
  main/       - Menú público, carrito, checkout (blueprint sin login)
  auth/       - Registro, login, perfil del negocio, personal
  catalog/    - Panel de administración: productos, pedidos, repartidores, etc.
  templates/  - HTML (index.html es el menú público, panel/ es el admin)
  static/     - CSS, JS, e imágenes subidas (logos, fotos de productos)
migrations/   - Historial de cambios a la base de datos (Alembic)
instance/     - Base de datos real y clave secreta (no se sube a git)
```

## Notas importantes

- La confirmación de pedidos es **manual**: el sistema no puede saber si una negociación por WhatsApp realmente terminó en una venta, así que el dueño (o personal autorizado) marca "Confirmar" solo en los pedidos que efectivamente se cerraron.
- No hay pago en línea integrado a propósito - todo pago se coordina por WhatsApp (efectivo, transferencia, o tarjeta al recibir), para no depender de comisiones de pasarelas de pago.
- La carpeta `instance/` (base de datos, clave secreta) y `app/static/uploads/` (imágenes subidas) están fuera de git a propósito - son datos de cada instalación, no del código.
