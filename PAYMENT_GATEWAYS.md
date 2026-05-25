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

## Fase 1D: PayPal real para pagos de plataforma

Esta fase activa PayPal solo para `payment_scope=platform`. No activa PayPal propio por owner/grupo ni concede accesos de comunidades mediante PayPal de grupo.

### Variables necesarias

- `ENABLE_PAYPAL_PAYMENTS=true`
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_WEBHOOK_ID`
- `PAYPAL_MODE=sandbox` o `PAYPAL_MODE=live`

Opcionales:

- `PAYPAL_RETURN_URL`: URL a la que PayPal devuelve al comprador tras aprobar la orden. Si no existe, se usa `SERVER_URL/paypal/return`.
- `PAYPAL_CANCEL_URL`: URL de cancelación. Si no existe, se usa `SERVER_URL/paypal/cancel`.
- `PAYPAL_SUCCESS_REDIRECT`: destino final del navegador tras capturar la orden.
- `PAYPAL_CANCEL_REDIRECT`: destino final tras cancelar.

### Endpoints añadidos

- `POST /create-paypal-platform-order`: crea una orden PayPal para productos de plataforma.
- `GET /paypal/return`: captura la orden aprobada y deja la transacción esperando webhook verificado.
- `GET /paypal/cancel`: marca la transacción como cancelada si seguía pendiente.
- `POST /webhook/paypal`: verifica firma con PayPal y procesa eventos confirmados.

### Flujo sandbox

1. El sistema crea una orden con `create_platform_paypal_order(...)`.
2. Se registra una fila en `payment_transactions` con:
   - `provider=paypal`
   - `payment_scope=platform`
   - `status=pending`
   - `purchase_type=commercial_subscription`, `platform_product` u `owner_upgrade`
   - `destination_type=platform_account`
3. PayPal devuelve `approval_url`.
4. El comprador aprueba en PayPal sandbox.
5. `GET /paypal/return` captura la orden mediante API server-to-server.
6. PayPal envía `PAYMENT.CAPTURE.COMPLETED` a `/webhook/paypal`.
7. El webhook se verifica con `PAYPAL_WEBHOOK_ID` y el endpoint oficial de PayPal.
8. Se valida importe, moneda, scope y tipo de compra.
9. La transacción pasa a `paid` de forma idempotente.

### Idempotencia y seguridad

- La referencia interna usa `paypal_platform_<uuid>` como `idempotency_key`.
- El `order_id` queda en `external_checkout_id`.
- El `capture_id` queda en `external_payment_id`.
- Si el webhook llega repetido y la transacción ya está `paid`, se devuelve OK sin reprocesar.
- No se guarda `PAYPAL_CLIENT_SECRET` en base de datos.
- No se imprimen tokens ni secretos.
- No se concede ningún producto hasta confirmación real. En esta fase los productos de plataforma quedan como `paid_pending_platform_fulfillment` para activación manual o futura.

### Configurar webhook en PayPal Developer

En la app PayPal sandbox/live, crear un webhook apuntando a:

`https://TU_DOMINIO/webhook/paypal`

Eventos mínimos:

- `PAYMENT.CAPTURE.COMPLETED`

Guardar el Webhook ID en `PAYPAL_WEBHOOK_ID`.

### Limitaciones de esta fase

- PayPal solo se usa para pagos de plataforma.
- PayPal por grupo/owner sigue preparado, pero no crea checkouts reales.
- Revolut queda preparado, pero no crea checkouts reales en esta fase.
- No se implementa cripto real.
- La activación automática de productos de plataforma queda para una fase posterior por tipo de producto.

## Fase 1D.2: Revolut real para pagos de plataforma

Esta fase activa Revolut solo para `payment_scope=platform`. No activa Revolut propio por owner/grupo ni guarda API keys de propietarios en base de datos.

### Variables necesarias

- `ENABLE_REVOLUT_PAYMENTS=true`
- `REVOLUT_API_KEY`
- `REVOLUT_WEBHOOK_SECRET`
- `REVOLUT_MODE=sandbox` o `REVOLUT_MODE=live`

Opcionales:

- `REVOLUT_BASE_URL`: permite cambiar la URL base si Revolut actualiza endpoints o si se usa un entorno específico.
- `REVOLUT_API_VERSION`: por defecto `2024-09-01`.
- `REVOLUT_RETURN_URL`: URL a la que vuelve el navegador tras el pago. Si no existe, se usa `SERVER_URL/revolut/return`.
- `REVOLUT_CANCEL_URL`: URL de cancelación. Si no existe, se usa `SERVER_URL/revolut/cancel`.
- `REVOLUT_SUCCESS_REDIRECT`: destino final del navegador tras volver de Revolut.
- `REVOLUT_CANCEL_REDIRECT`: destino final tras cancelar.

### Endpoints añadidos

- `POST /create-revolut-platform-order`: crea una orden Revolut para productos de plataforma.
- `GET /revolut/return`: redirige al comprador tras volver de Revolut.
- `GET /revolut/cancel`: redirige al comprador tras cancelar.
- `POST /webhook/revolut`: verifica firma HMAC y procesa eventos confirmados.

### Flujo sandbox/live

1. El sistema crea una orden con `create_platform_revolut_order(...)`.
2. Se registra una fila en `payment_transactions` con:
   - `provider=revolut`;
   - `payment_scope=platform`;
   - `status=pending`;
   - `purchase_type=commercial_subscription`, `platform_product`, `owner_upgrade` o `group_access`;
   - `destination_type=platform_account`.
3. Revolut devuelve `checkout_url`.
4. El comprador paga en Revolut.
5. Revolut envía el evento a `/webhook/revolut`.
6. El webhook valida `Revolut-Signature` con `REVOLUT_WEBHOOK_SECRET`.
7. Se valida importe, moneda, scope y tipo de compra.
8. La transacción pasa a `paid`, `failed` o `cancelled` de forma idempotente.

### Idempotencia y seguridad

- La referencia interna usa `revolut_platform_<uuid>` como `idempotency_key`.
- El `order_id` queda en `external_checkout_id`.
- El evento/order id queda en `external_payment_id`.
- Si el webhook llega repetido y la transacción ya está `paid`, se devuelve OK sin reprocesar.
- No se guarda `REVOLUT_API_KEY` ni `REVOLUT_WEBHOOK_SECRET` en base de datos.
- No se imprimen tokens ni secretos.
- Si el pago Revolut plataforma corresponde a `purchase_type=group_access` y tiene `group_id`/`plan_id`, se reutiliza el flujo común de concesión de acceso después de webhook verificado.
- Para otros productos de plataforma, el pago queda como `paid_pending_platform_fulfillment` para activación manual o futura.

### Configurar webhook en Revolut

En Revolut Merchant, crear un webhook apuntando a:

`https://TU_DOMINIO/webhook/revolut`

Eventos esperados para esta fase:

- `ORDER_COMPLETED`
- `ORDER_CANCELLED`
- `ORDER_FAILED`

Guardar el secreto de firma en `REVOLUT_WEBHOOK_SECRET`.

### Limitaciones de esta fase

- Revolut solo se usa con credenciales globales de plataforma.
- Revolut owner/grupo ya tiene checkout real si el owner configura credenciales cifradas desde el bot.
- No se capturan credenciales Revolut de owners.
- No se implementan suscripciones recurrentes Revolut.
- Cripto y Bizum siguen pendientes.

## Fase 1E: credenciales seguras por owner/grupo

Hay dos tipos de credenciales y no deben mezclarse.

### Credenciales de plataforma

Van en Railway porque pertenecen al dueño del bot/plataforma:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_WEBHOOK_ID`
- variables futuras globales de Revolut o cripto.

Estas credenciales sirven para productos de plataforma: mensualidades de owners, publicar grupos, bots personalizados, upgrades y módulos premium.

### Credenciales de owner/grupo

No van en Railway. Cada propietario deberá conectarlas desde el bot para sus comunidades.

La configuración queda asociada a:

- `owner_user_id`
- `group_id`
- `provider`
- `status`
- credenciales cifradas o referencia segura.

El super admin puede supervisar estados, pero no debe ver secretos completos.

### Tabla `group_payment_provider_configs`

La tabla queda preparada con campos adicionales:

- `encrypted_config_json`: configuración sensible cifrada.
- `secret_status`: `not_configured`, `pending`, `active`, `error` o `disabled`.
- `last_verified_at`: última verificación segura.
- `verified_by`: usuario que verificó/conectó.
- `verification_error`: último error no sensible.
- `masked_public_summary`: resumen público enmascarado.

`public_config_json` debe contener solo datos no sensibles. Nunca debe guardar `client_secret`, tokens, claves privadas ni webhooks secretos.

### Cifrado

El módulo `payment_secret_store.py` prepara helpers para:

- `encrypt_provider_config(data)`
- `decrypt_provider_config(...)`
- `mask_provider_config(...)`
- `has_payment_encryption_key()`
- `validate_safe_provider_config(...)`

Para guardar credenciales reales debe existir:

`PAYMENT_CONFIG_ENCRYPTION_KEY`

Si esa variable no existe, el bot no debe guardar secretos reales de owners/grupos.

### Pantalla del owner

En `💳 Métodos de pago del grupo`, cada proveedor puede mostrar:

- estado global,
- estado del grupo,
- estado de credenciales,
- si el cifrado está preparado,
- qué falta para conectar,
- opciones para configurar/conectar,
- desactivar,
- borrar configuración.

En esta fase, PayPal y Revolut ya tienen wizard seguro de configuración. Revolut plataforma usa credenciales globales, mientras que Revolut owner/grupo usa credenciales cifradas configuradas desde el bot. Cripto sigue como placeholder seguro hasta tener integración real.

## Fase 1F: wizard PayPal owner/grupo

El owner puede entrar en:

`🏪 Mis comunidades → Comunidad → 💳 Planes y pagos del grupo → 💳 Métodos de pago del grupo → PayPal → Configurar / conectar`

El wizard pide:

- modo `sandbox` o `live`;
- `PAYPAL_CLIENT_ID`;
- `PAYPAL_CLIENT_SECRET`;
- `PAYPAL_WEBHOOK_ID` opcional.

Seguridad aplicada:

- no usa Railway para credenciales de owners;
- requiere `PAYMENT_CONFIG_ENCRYPTION_KEY`;
- intenta borrar del chat los mensajes con credenciales;
- cifra la configuración con `payment_secret_store.py`;
- guarda el secreto en `encrypted_config_json`;
- guarda solo resumen enmascarado en `masked_public_summary`;
- si hay `webhook_id`, deja `status=active`, `secret_status=active` e `is_enabled=true`;
- si falta `webhook_id`, deja la configuración pendiente y no se muestra como checkout real;
- no muestra `client_secret` completo;
- no registra secretos en logs.

## Fase 1G: checkout PayPal real para compradores de grupo

PayPal de owner/grupo puede crear checkout real cuando:

- `ENABLE_PAYPAL_PAYMENTS=true`;
- el grupo tiene configuración PayPal cifrada;
- la configuración incluye `client_id`, `client_secret`, `webhook_id` y modo `sandbox/live`;
- la fila de `group_payment_provider_configs` está activa.

El checkout se crea en:

`POST /create-paypal-group-order`

El endpoint recibe `telegram_id`, `group_id` y `plan_id`, valida que el plan pertenece al grupo y crea una orden PayPal con las credenciales cifradas del owner/grupo. No usa `PAYPAL_CLIENT_ID` ni `PAYPAL_CLIENT_SECRET` de Railway.

La transacción se guarda en `payment_transactions` con:

- `provider=paypal`;
- `payment_scope=group`;
- `purchase_type=group_access`;
- `group_id`;
- `plan_id`;
- `provider_config_scope=group`;
- `provider_config_id`;
- `status=pending`.

El webhook `POST /webhook/paypal` se reutiliza de forma segura:

- transacciones `payment_scope=platform` verifican firma con `PAYPAL_WEBHOOK_ID` de Railway;
- transacciones `payment_scope=group` verifican firma con el `webhook_id` cifrado/configurado del grupo;
- el acceso se concede solo si el evento PayPal es verificado, `COMPLETED`, con importe/moneda correctos;
- el flujo es idempotente: si la transacción ya está `paid`, no vuelve a conceder acceso.

Al confirmarse el pago de grupo:

- se marca la transacción como pagada;
- se crea el invite link real del grupo;
- se guarda `users`, `payments` e `invite_links`;
- se notifica al comprador, super admin y owner;
- se registran logs sin secretos ni invite links completos.

## Fase 1H: Revolut owner/grupo configurable desde el bot

Revolut de owner/grupo ya puede configurarse desde:

`🏪 Mis comunidades → Comunidad → 💳 Planes y pagos del grupo → 💳 Métodos de pago del grupo → Revolut → Configurar / conectar`

El wizard pide:

- modo `sandbox` o `live`;
- `REVOLUT_API_KEY` del comercio/owner;
- `REVOLUT_WEBHOOK_SECRET` del comercio/owner;
- `REVOLUT_BASE_URL` opcional.

Las variables Railway `REVOLUT_API_KEY` y `REVOLUT_WEBHOOK_SECRET` siguen siendo solo para `payment_scope=platform`.

Para comunidades, las credenciales:

- se introducen desde el bot;
- se intentan borrar del chat después de recibirlas;
- se cifran con `payment_secret_store.py`;
- se guardan en `group_payment_provider_configs.encrypted_config_json`;
- se muestran solo mediante `masked_public_summary`;
- no se imprimen en logs ni mensajes.

El checkout real de grupo se crea en:

`POST /create-revolut-group-order`

El endpoint recibe `telegram_id`, `group_id` y `plan_id`, valida que el plan pertenece al grupo y crea una orden Revolut con las credenciales cifradas del owner/grupo. No usa las credenciales Revolut de Railway.

La transacción se guarda en `payment_transactions` con:

- `provider=revolut`;
- `payment_scope=group`;
- `purchase_type=group_access`;
- `group_id`;
- `plan_id`;
- `provider_config_scope=group`;
- `provider_config_id`;
- `status=pending`.

El webhook `POST /webhook/revolut` se reutiliza de forma segura:

- transacciones `payment_scope=platform` verifican firma con `REVOLUT_WEBHOOK_SECRET` de Railway;
- transacciones `payment_scope=group` buscan la transacción por `order_id`/referencia interna y verifican firma con el `webhook_secret` cifrado del grupo;
- el acceso se concede solo si el evento Revolut es verificado, `ORDER_COMPLETED`, con importe/moneda correctos;
- el flujo es idempotente: si la transacción ya está `paid`, no vuelve a conceder acceso.

Al confirmarse el pago de grupo:

- se marca la transacción como pagada;
- se crea el invite link real del grupo;
- se guarda `users`, `payments` e `invite_links`;
- se notifica al comprador, super admin y owner;
- se registran logs sin secretos ni invite links completos.

Pruebas sandbox recomendadas:

1. Configurar Revolut sandbox desde el panel de una comunidad.
2. Confirmar que el resumen muestra API key y webhook secret enmascarados.
3. Comprar un plan de esa comunidad con Revolut.
4. Confirmar que `/create-revolut-group-order` devuelve `checkout_url`.
5. Enviar webhook `ORDER_COMPLETED` firmado con el secreto del grupo.
6. Confirmar que se crea acceso e invite link una sola vez aunque el webhook se repita.
7. Confirmar que Revolut plataforma sigue usando las variables Railway.

### PayPal/Revolut owner/grupo pendiente

Sigue pendiente para una fase posterior:

1. Panel avanzado de verificación/diagnóstico PayPal por owner.
2. Panel avanzado de verificación/diagnóstico Revolut por owner.
3. Renovaciones recurrentes si se implementan suscripciones PayPal/Revolut.
4. PayPal/Revolut propios por owner para productos que no sean acceso de grupo.
5. Cripto y Bizum reales.

## Agrupación visual de métodos de pago

Los paneles del bot muestran los proveedores agrupados para evitar que parezcan duplicados:

### Pagos tradicionales

Incluye:

- Stripe / tarjeta.
- PayPal.
- Revolut.

Estos métodos se presentan como cobros clásicos de plataforma o de grupo, según `payment_scope`.

### Cripto / USDT

Incluye:

- ChangeNOW.io / Cripto.
- Tarjeta EUR -> USDT / Guardarian.

Aunque ambos están relacionados con cripto/USDT, no son el mismo flujo:

- ChangeNOW.io / Cripto permite iniciar pagos cripto/intercambio. En la configuración actual queda en revisión manual y no concede acceso automáticamente.
- Guardarian permite que el comprador pague con tarjeta en EUR y que plataforma/owner reciba USDT en su wallet. Es automático solo cuando Guardarian confirma oficialmente `status == finished` al consultar `GET /v1/transaction/{id}`.

### Promociones

Los códigos comerciales globales y los códigos/promociones de grupo se muestran como rutas separadas. No se mezclan con proveedores de cobro para que owners y superadmin distingan entre pago real y acceso promocional.

## ChangeNOW.io / Cripto en modo seguro

ChangeNOW queda preparado como proveedor cripto configurable desde el bot para dos scopes:

- `payment_scope=platform`: pagos de plataforma configurados por superadmin.
- `payment_scope=group`: pagos de comunidades configurados por owner/superadmin.

### Estado de esta fase

Esta fase activa ChangeNOW en modo controlado:

- la configuracion se hace desde Telegram, no desde Railway;
- los secretos se guardan cifrados con `PAYMENT_CONFIG_ENCRYPTION_KEY`;
- el comprador puede iniciar un pago cripto si el metodo esta activo;
- la transaccion se guarda en `payment_transactions` con `provider=changenow`;
- el estado queda en `manual_review`;
- el acceso NO se concede automaticamente.

La razon es la indicada en `CHANGE_NOW_RESEARCH.md`: la documentacion publica no confirma de forma suficiente el contrato de callback/push firmado, payload e idempotencia fuerte. Por tanto, cualquier callback de ChangeNOW se trata como pista y deja el pago en revision manual.

### Configuracion plataforma

Ruta interna:

`Panel global -> Metodos de pago -> ChangeNOW.io / Cripto`

El superadmin configura:

- API key de ChangeNOW;
- moneda/red que recibe la plataforma;
- wallet destino;
- moneda/red que paga el comprador por defecto;
- modo fixed/floating;
- revision manual siempre activa.

No se piden seeds ni private keys de wallet. La wallet se muestra enmascarada.

### Configuracion owner/grupo

Ruta owner:

`Mis comunidades -> Comunidad -> Planes y pagos -> Metodos de pago del grupo -> ChangeNOW.io / Cripto`

El owner configura:

- API key de ChangeNOW del owner/comercio;
- moneda/red destino;
- wallet destino;
- moneda/red que pagara el comprador por defecto;
- fixed/floating;
- revision manual.

El owner solo puede configurar sus propios grupos. El superadmin puede configurar cualquier grupo.

### Endpoints

- `POST /create-changenow-platform-order`: crea una transaccion ChangeNOW de plataforma en revision manual.
- `POST /create-changenow-group-order`: crea una transaccion ChangeNOW de grupo en revision manual.
- `POST /webhook/changenow`: recibe eventos ChangeNOW y actualiza a revision manual cuando corresponda. No concede acceso automatico.

### Revision manual

El superadmin tiene una vista minima:

`Panel global -> Metodos de pago -> Pagos ChangeNOW en revision`

Desde ahi puede:

- ver pagos `manual_review`;
- rechazar un pago;
- marcar como pagado y conceder acceso si la transaccion corresponde a un grupo/plan.

Antes de confirmar manualmente hay que revisar en ChangeNOW o en soporte externo:

- importe;
- moneda/red;
- wallet destino;
- estado final;
- usuario/grupo/plan interno;
- si hay hold/verifying/expired/refunded.

### Pendiente antes de acceso automatico

- Confirmar payload oficial de callback/push.
- Confirmar firma o mecanismo de verificacion.
- Confirmar endpoint de estado v2 y contrato de respuesta.
- Confirmar uso de `payload` o `userId` para `payment_transaction_id`.
- Confirmar fixed-rate/rateId y minimos por moneda/red.
- Activar polling/verificacion server-side antes de conceder acceso automatico.

### Nota sobre activación automática ChangeNOW

Se evaluó activar acceso automático cuando llega callback de ChangeNOW. No se activa todavía.

El callback no puede ser fuente de verdad. Para conceder acceso automáticamente, el backend debe consultar el estado oficial de ChangeNOW por `transaction_id`/`order_id` y validar estado final, importe, moneda, red, wallet, usuario, grupo y plan.

Mientras el endpoint oficial de consulta de estado y su contrato no estén confirmados en la documentación/API habilitada para la cuenta, ChangeNOW sigue operando en `manual_review`.

## Guardarian directo: EUR con tarjeta -> USDT

Guardarian se integra como proveedor directo para pagos `payment_scope=platform` y `payment_scope=group`.

### Enfoque de seguridad

- El comprador paga con tarjeta en EUR.
- La plataforma u owner recibe USDT en la wallet configurada.
- El webhook `/webhook/guardarian` solo actúa como disparador.
- El backend no confía en el estado enviado por el webhook.
- Antes de marcar un pago como pagado, el backend consulta `GET /v1/transaction/{id}`.
- Solo `status == finished` concede acceso automático.
- Estados dudosos como `hold`, `kyc`, `review`, `blocked`, `unknown` o errores de consulta quedan en `manual_review`.
- Estados `failed`, `cancelled`, `expired` o `refunded` se guardan como fallo/cancelación/expiración/devolución y no conceden acceso.

### Configuración desde el bot

Guardarian no depende principalmente de Railway para owners/grupos. Las credenciales se configuran desde el bot y se guardan cifradas con `PAYMENT_CONFIG_ENCRYPTION_KEY`.

Configuración de plataforma, solo superadmin:

- API key de Guardarian.
- Wallet USDT destino de la plataforma.
- Red USDT: TRC20, ERC20, Polygon, BEP20 u otra soportada por la cuenta.
- Webhook secret si la cuenta lo ofrece.
- Modo sandbox/live si aplica.
- Base URL opcional si Guardarian entrega una URL distinta.

Configuración de grupo, owner o superadmin:

- API key del owner/comercio.
- Wallet USDT destino del owner.
- Red USDT.
- Webhook secret si aplica.
- Modo sandbox/live.
- Activar/desactivar o borrar configuración.

Los secretos nunca se muestran completos en Telegram ni se guardan en texto plano.

### Endpoints añadidos

- `POST /create-guardarian-platform-order`
- `POST /create-guardarian-group-order`
- `POST /webhook/guardarian`

### Flujo group

1. El comprador elige `💳 Tarjeta EUR → USDT` en un plan de comunidad.
2. El bot valida `group_id`, `plan_id`, plan activo y configuración Guardarian activa del grupo.
3. Se crea `payment_transactions` con `provider='guardarian'`, `payment_scope='group'` y `status='pending'`.
4. Se llama `POST /v1/transaction` usando las credenciales cifradas del grupo.
5. Se guarda el `provider_order_id` devuelto por Guardarian.
6. Al llegar webhook, el bot busca la transacción, carga la configuración correcta y consulta `GET /v1/transaction/{id}`.
7. Si el estado oficial es `finished`, se marca como `paid` y se concede acceso con `payment_access_service.py`.

### UX y cumplimiento

Los textos del bot usan el wording: “privacidad frente al comprador y liquidación en USDT”. No se promete ocultación total de identidad ni ausencia de verificación. El comprador ve que algunos pagos pueden requerir verificación KYC/AML o revisión por importe, país o riesgo.
