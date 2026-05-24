# Arquitectura Multigateway De Pagos

## Fase 1

Esta fase prepara el bot para múltiples proveedores sin cambiar el flujo real de Stripe.

Proveedor activo por defecto:

- Stripe (`ENABLE_STRIPE_PAYMENTS=true` por defecto)

Proveedores preparados pero desactivados por defecto:

- PayPal (`ENABLE_PAYPAL_PAYMENTS=false`)
- Revolut (`ENABLE_REVOLUT_PAYMENTS=false`)
- Criptomonedas (`ENABLE_CRYPTO_PAYMENTS=false`)

## Flujo actual de Stripe

1. El usuario selecciona una comunidad y un plan.
2. El callback del plan usa `price_...` como `callback_data`.
3. `callback_router.py` llama a `/create-checkout-session`.
4. `checkout_routes.py` valida `plans.price_id`, `plans.group_id` y crea una sesión Stripe Checkout.
5. Stripe llama al webhook `/webhook`.
6. `stripe_handler.py` valida la firma con `STRIPE_WEBHOOK_SECRET`.
7. El webhook obtiene `telegram_id`, `group_id` y `price_id` desde metadata/line items.
8. Se calcula expiración con `plans.duration_days`.
9. Se crea link seguro de Telegram y se registra en `invite_links`.
10. Se activa acceso en `users` y se registra pago en `payments`.
11. Se notifican comprador, super admin y owner.

## Tablas actuales relacionadas

- `plans`: planes por grupo y `price_id` de Stripe.
- `payments`: pagos confirmados.
- `users`: acceso activo, expiración y suscripción.
- `invite_links`: links personales y de un uso.
- `groups`: grupo interno y `telegram_group_id` real.
- `audit_logs`: eventos operativos.

## Tabla preparada

`payment_transactions` queda preparada para una futura capa común:

- provider
- status
- user_id
- group_id
- plan_id
- amount
- currency
- external_payment_id
- external_checkout_id
- idempotency_key
- metadata JSONB

## Seguridad esperada para fases futuras

- Webhooks verificados por proveedor.
- Idempotencia por evento externo.
- No confiar en callbacks del usuario para conceder acceso.
- No guardar secretos ni links completos en logs.
- No conceder acceso hasta confirmación real del proveedor.

## Cripto recomendado

Para una primera integración comercial rápida recomiendo Coinbase Commerce si se acepta proveedor alojado: reduce complejidad de wallets, webhooks y conciliación.

Si se prefiere control/autocustodia, BTCPay Server es mejor a medio plazo, pero exige más operación técnica.


## Fase 1B: configuración por owner/grupo

Esta fase prepara la configuración de métodos de pago propios por comunidad sin activar cobros reales por owner ni crear nuevos webhooks.

Hay dos niveles:

- Plataforma global: controla qué proveedores existen y cuáles están habilitados por flags (`ENABLE_STRIPE_PAYMENTS`, `ENABLE_PAYPAL_PAYMENTS`, `ENABLE_REVOLUT_PAYMENTS`, `ENABLE_CRYPTO_PAYMENTS`).
- Comunidad/owner: muestra el estado de cada proveedor para un grupo concreto y queda preparado para guardar configuración segura en fases posteriores.

Tabla añadida:

`group_payment_provider_configs`

Campos principales:

- `owner_user_id`: propietario de la comunidad.
- `group_id`: ID interno de `groups`.
- `provider`: `stripe`, `paypal`, `revolut` o `crypto`.
- `is_enabled`: si el método queda habilitado para ese grupo en una fase futura.
- `status`: `not_configured`, `pending`, `active`, `disabled` o `error`.
- `public_config_json`: configuración pública/no sensible.
- `secret_ref`: referencia futura a secretos cifrados o almacenados fuera de la base de datos.

Reglas de seguridad:

- Un owner no puede activar un proveedor deshabilitado globalmente.
- No se guardan secretos reales en claro.
- No se imprime ninguna credencial en logs.
- Los admins secundarios no modifican métodos de pago de grupo en esta fase.
- El super admin puede ver el estado de cualquier grupo; el owner solo el de sus comunidades.

Pantalla preparada:

`💳 Métodos de pago del grupo` aparece dentro de `🏪 Mis comunidades → comunidad → 💳 Planes y pagos del grupo`.

La pantalla es informativa por ahora. Muestra Stripe, PayPal, Revolut y Cripto según flags globales y estado por grupo, pero no concede accesos ni crea checkouts nuevos.

Pendiente para activar cobros reales por owner/grupo:

- Captura de credenciales por proveedor con almacenamiento seguro.
- Webhooks verificados por provider y por owner/grupo.
- Idempotencia por evento externo.
- Conciliación de pagos por proveedor.
- Activación de acceso únicamente después de webhook confirmado.

## Fase 1C: scopes de pago platform y group

La arquitectura queda preparada para distinguir dos tipos de cobro sin activar proveedores nuevos todavía.

### `payment_scope=platform`

El dinero va a la plataforma o dueño del bot. Este scope se usa para productos comerciales del bot:

- mensualidades de owners para publicar comunidades,
- bots personalizados,
- upgrades,
- módulos premium,
- servicios comerciales,
- productos futuros de la plataforma.

Stripe global actual sigue funcionando como pago de plataforma. Aunque el pago compre acceso a una comunidad, la configuración de cobro usada es la de la plataforma mientras no se active la configuración propia del owner/grupo.

### `payment_scope=group`

El dinero pertenece al owner o a la configuración propia de una comunidad. Este scope queda preparado para vender acceso o suscripción a una comunidad concreta usando métodos configurados por ese grupo.

Para que un proveedor pueda usarse en un grupo deberán cumplirse todas estas reglas:

1. El proveedor está habilitado globalmente por feature flag.
2. El grupo tiene una fila activa en `group_payment_provider_configs`.
3. La configuración del grupo está en estado `active`.
4. El destino de cobro está definido como `owner_account` o `group_config`.
5. El webhook futuro confirma el pago antes de conceder acceso.

### Nuevas columnas en `payment_transactions`

Se añaden columnas seguras para preparar idempotencia, destino y contexto:

- `payment_scope`: `platform` o `group`.
- `purchase_type`: tipo de compra, por ejemplo `group_access`, `commercial_subscription`, `platform_product` u `owner_upgrade`.
- `owner_user_id`: owner relacionado si aplica.
- `platform_product_key`: clave interna para productos de plataforma.
- `provider_config_id`: configuración de proveedor usada si aplica.
- `provider_config_scope`: `platform` o `group`.
- `destination_type`: `platform_account`, `owner_account` o `group_config`.
- `destination_ref`: referencia no sensible del destino.
- `metadata_json`: metadata sanitizada, sin secretos ni invite links completos.

La columna legacy `metadata` se mantiene por compatibilidad.

### Cambios en `group_payment_provider_configs`

La tabla de configuración por grupo queda preparada con:

- `provider_config_scope`: normalmente `group`.
- `destination_type`: normalmente `group_config` en esta fase.
- `destination_ref`: referencia futura no sensible a la cuenta/configuración.
- `metadata_json`: datos no sensibles de configuración.

No se guardan claves PayPal, Revolut, cripto ni Stripe owner en claro.

### Flujo futuro PayPal global

1. Super admin activa `ENABLE_PAYPAL_PAYMENTS=true` y configura credenciales globales.
2. Una compra de plataforma crea una `payment_transaction` con `payment_scope=platform`.
3. PayPal redirige al checkout externo.
4. Webhook PayPal verificado marca la transacción como `paid`.
5. Solo entonces se activa el producto o acceso correspondiente.

### Flujo futuro PayPal por grupo

1. El owner configura PayPal desde `💳 Métodos de pago del grupo`.
2. La configuración se guarda como referencia segura en `group_payment_provider_configs`.
3. Una compra de comunidad usa `payment_scope=group` y `provider_config_id` del grupo.
4. El webhook PayPal del flujo por grupo valida evento, owner/grupo e idempotencia.
5. Solo entonces se crea acceso, usuario e invite link.

### Decisión de destino de cobro

`payment_service.get_payment_destination_context(...)` define el destino:

- platform: `destination_type=platform_account`.
- group: `destination_type=group_config` o `owner_account` cuando exista configuración real.

### Pendiente antes de PayPal real

- Pantalla segura para credenciales o conexión OAuth/partner.
- Webhook PayPal verificado.
- Mapeo de eventos PayPal a `payment_transactions`.
- Concesión de acceso idempotente reutilizando la lógica actual de Stripe.
- Pruebas sandbox con compra, webhook repetido, cancelación y fallo.
