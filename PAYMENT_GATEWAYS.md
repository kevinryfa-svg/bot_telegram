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
