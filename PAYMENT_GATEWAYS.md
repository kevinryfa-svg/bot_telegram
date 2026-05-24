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
