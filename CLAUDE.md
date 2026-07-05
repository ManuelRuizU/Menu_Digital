# Menú Digital - contexto del proyecto

## Qué es esto (y qué NO es)

Esto **no** es un sistema de gestión/POS como Loyverse, Bsale o similar. No lleva inventario contable,
no reemplaza la caja, no hace facturación. Eso ya existe, es gratis (Loyverse) y casi ningún emprendedor
chico que arranca lo usa igual.

Esto es un **menú digital + canal de pedidos por WhatsApp**, con un plus: agilizar la entrega al repartidor.

## El problema real que resuelve

El público objetivo son **emprendedores recién empezando** a vender comida: su canal de venta son redes
sociales (Instagram, Facebook), tienen fotos propias de sus productos, y **todo el cierre de venta pasa por
WhatsApp** - ahí negocian, cobran, coordinan la entrega. No usan pasarelas de pago web, cobran en efectivo,
transferencia o con una máquina tipo SumUp.

Hoy, sin esta app, cuando un cliente escribe "¿me mandas la carta?" - el emprendedor le manda un Word, un
PDF, o fotos sueltas de sus productos/promociones. Es lento, desordenado, y no ayuda al cliente a armar un
pedido real (cantidades, variantes, dirección, hora).

Y del otro lado: cuando hay que despachar, el repartidor sale con un papelito a mano o mensajes de WhatsApp
sueltos, sin la dirección exacta, sin saber bien qué pidió cada quien, y el dueño tiene que estar
respondiéndole "¿a quién le llevas eso? ¿cuál es el nombre? ¿cuál es la dirección?" una y otra vez.

**Este proyecto resuelve exactamente esas dos cosas:**
1. Un catálogo digital de verdad (con fotos, categorías, variantes, stock) en vez de un PDF o fotos sueltas.
2. Información de despacho estructurada y lista para el repartidor (nombre, teléfono, dirección con pin de
   mapa, hora, forma de pago, vuelto si es efectivo) - por WhatsApp, sin apps nuevas que instalar, sin que
   el dueño tenga que re-escribir nada a mano.

Todo lo demás (impresora térmica, respaldo automático, dashboard, personal con roles, temas visuales) existe
para apoyar ese objetivo central, no para competir con un sistema de gestión.

## Decisiones de diseño que vienen de este contexto

- **Sin pagos en línea, a propósito.** El cierre de venta siempre pasa por WhatsApp - agregar una pasarela
  de pago sería una función nueva, con costos de comisión, que nadie en este público pidió.
- **Sin costos recurrentes obligatorios.** Se vende una vez (~US$50-70), no es una suscripción. Cualquier
  función nueva debe evaluarse contra esto: si depende de un servicio de pago externo, probablemente no va.
- **La confirmación de un pedido es manual.** El sistema no puede saber si una negociación por WhatsApp
  terminó en una venta real - por eso el dueño (o personal autorizado) marca "Confirmado" a mano.
- **Un solo negocio por instalación**, no es un SaaS multi-tenant. Cada emprendedor tiene su propia
  instalación independiente (ver DEPLOY.md). No se debe diseñar como si varios negocios compartieran una
  misma base de datos.
- **No se integra con POS/gestión externos (Loyverse, etc.)** - ver arriba. Si se necesita sacar datos hacia
  afuera, la respuesta es un export universal (CSV), no una integración puntual con una herramienta que solo
  usa una fracción de los clientes.
- **Nunca confiar en el cliente**: precios, stock, zonas de reparto, horarios, variantes - todo se
  revalida en el servidor, nunca se confía en lo que mande el navegador.

## Para más detalle

- `README.md` - instalación local y desarrollo.
- `DEPLOY.md` - despliegue real (PythonAnywhere gratis, VPS con dominio propio, múltiples clientes con
  subdominios).
- `tests/` - pruebas automáticas de la lógica más propensa a romperse en silencio (zonas de reparto,
  horarios, stock, variantes, `get_owner()`).
