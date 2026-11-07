# KrmaVerso Store API — paquete inicial

## Qué incluye
- Registro e inicio de sesión con contraseña cifrada (Argon2).
- Código único y enlace de referido por cliente.
- Descuento del 10% en primera compra.
- Recompensa de $3.000 COP para quien invita y quien llega referido, una vez que el administrador confirma el primer pago del referido.
- Historial básico de pedidos y endpoint de administración para confirmar pagos.
- PostgreSQL como base de datos persistente.

## Importante antes de producción
Este paquete es una base funcional para desplegar y probar, no está conectado todavía a tu HTML ni a Wompi. El catálogo.json de ejemplo NO contiene tu catálogo completo y los IDs deben coincidir con los productos del HTML. No lo publiques en producción hasta sincronizar ese archivo y conectar el frontend.

El enlace Wompi actual es fijo. Por ahora el total con descuento se calcula en el servidor, pero el administrador debe verificar el pago manualmente. No se debe marcar un pedido como pagado sin comprobarlo en Wompi. Para automatizar cobros por importe exacto se necesita integrar la API y los webhooks oficiales de Wompi.

## Despliegue manual
Puedes usar un servicio compatible con Python ASGI y PostgreSQL (por ejemplo Render):
1. Sube la carpeta `store_api` a un repositorio privado o a tu repositorio actual.
2. Crea una base de datos PostgreSQL y copia su URL interna/externa según el proveedor.
3. Crea un servicio web Python apuntando a `store_api`.
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Define las variables de `.env.example` en el panel del proveedor. Nunca subas los secretos a GitHub.
7. Agrega el dominio público del frontend a `CORS_ORIGINS`.
8. Prueba `/health` y `/docs`.

## Endpoints
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/me`
- `POST /api/orders`
- `POST /api/orders/{order_id}/cancel`
- `GET /api/admin/orders` (header `X-Admin-Secret`)
- `POST /api/admin/orders/{order_id}/paid` (header `X-Admin-Secret`)

## Variables
Consulta `.env.example`. Usa secretos únicos y largos. La API requiere HTTPS.
