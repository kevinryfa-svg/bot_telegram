# Guardarian Security Audit

Fecha: 2026-05-25

## Resumen ejecutivo

Estado: APTO CON HARDENING APLICADO.

Se revisó la integración Guardarian automática para pagos `EUR con tarjeta -> USDT` en `payment_scope=platform` y `payment_scope=group`.

No se encontró un camino que conceda acceso únicamente por el payload del webhook, por la respuesta inicial de creación de orden, por un callback de comprador o por un botón normal de compra. La integración ya usaba el webhook solo como disparador y consultaba `GET /v1/transaction/{id}` antes de conceder acceso.

Se aplicó hardening mínimo para reducir riesgos de concurrencia e inconsistencias:

- Marcado `paid` atómico antes de conceder acceso, con protección para webhooks duplicados.
- Validación de `provider_config_id` frente a la configuración cifrada usada.
- Validación de `transaction_id` oficial devuelto por Guardarian frente al `external_checkout_id` interno.
- Validación de payout USDT/red si Guardarian devuelve esos campos.
- Botón de reconsulta de pagos pendientes/manual review para superadmin.
- Textos UX reforzados para evitar prometer ocultación total de identidad, ausencia de verificación o activación inmediata.

## Archivos revisados

- `payment_providers/guardarian_provider.py`
- `checkout_routes.py`
- `callback_router.py`
- `payment_service.py`
- `payment_gateway_config.py`
- `admin_permission_map.py`
- `payment_access_service.py`
- `db.py`
- `PAYMENT_GATEWAYS.md`
- `GUARDARIAN_AUTO_USDT_RESEARCH.md`

## Concesión automática

El único camino automático válido queda así:

1. Existe una `payment_transactions` con `provider='guardarian'`.
2. El webhook llega a `/webhook/guardarian` y solo aporta el id de transacción.
3. El backend busca la transacción interna por `external_checkout_id`.
4. Carga la configuración cifrada correcta según `payment_scope`.
5. Comprueba que el `provider_config_id` coincide.
6. Consulta `GET /v1/transaction/{id}` en Guardarian.
7. Valida estado, importe, moneda y, si están presentes, payout USDT/red.
8. Solo si el estado oficial es `finished`, marca `paid` y concede acceso.

No se concede acceso por:

- Estado recibido en webhook.
- Payload de webhook sin consulta a API.
- Respuesta inicial de creación de orden.
- Callback del comprador.
- Configuración del owner.
- Estado pending, review, hold, KYC o unknown.

## Idempotencia

Antes del hardening, el flujo consultaba `status == paid` al inicio y después concedía acceso antes de guardar `paid`. Eso era correcto en ejecución normal, pero dejaba una ventana si dos webhooks duplicados entraban simultáneamente.

Ahora el provider usa una transición atómica `mark_guardarian_paid_once(...)`:

- Si la transacción ya está `paid`, devuelve OK sin repetir concesión.
- Si dos webhooks llegan a la vez, solo uno puede cambiar el estado a `paid`.
- Solo el proceso que marca `paid` concede acceso.
- Si la concesión falla después de marcar `paid`, se mueve a `manual_review` con motivo.

Riesgo residual: si la creación del invite link falla después de marcar `paid`, el pago queda en `manual_review` para intervención manual. Es preferible a duplicar links/accesos.

## Estados Guardarian

Mapeo revisado:

- `finished` -> `paid` y acceso automático.
- `new`, `pending`, `waiting`, `waitingfordeposit`, `depositreceived`, `depositcaptured`, `paymentsubmitted`, `processing`, `processed`, `cryptosent` -> `pending`.
- `hold`, `review`, `manual_review`, `kycstarted`, `kycfinished`, `kyc`, `aml`, `blocked`, `unknown` -> `manual_review`.
- `failed`, `depositfailed`, `kycfailed` -> `failed`.
- `canceled`, `cancelled` -> `cancelled`.
- `expired` -> `expired`.
- `refunded` -> `refunded`.

Cualquier estado desconocido se trata como `manual_review`.

## Validaciones antes de acceso

Validado actualmente:

- `provider='guardarian'` por la consulta interna.
- `payment_scope` `group` o `platform`.
- Configuración cifrada correspondiente a plataforma o grupo.
- `provider_config_id` si está presente.
- `user_id`, `group_id` y `plan_id` para pagos de grupo.
- Plan activo y perteneciente al grupo, vía `payment_access_service.py`.
- Transacción no marcada ya como `paid`.
- `external_checkout_id` coincide con el id oficial si Guardarian lo devuelve.
- Moneda EUR si Guardarian devuelve moneda de entrada.
- Importe si Guardarian devuelve importe esperado.
- Payout USDT/red si Guardarian devuelve esos campos.

Limitación documentada: si Guardarian no devuelve payout currency o payout network en `GET /v1/transaction/{id}`, no se puede validar ese punto y no se bloquea el pago solo por ausencia del campo.

## Configuración cifrada

Revisado:

- API key y webhook secret se guardan dentro de `encrypted_config_json`.
- La configuración usa `payment_secret_store.py`.
- La wallet se muestra enmascarada en resúmenes.
- Los logs de Guardarian no imprimen API key ni webhook secret.
- Los logs guardan ids de transacción, importes, estados y motivos sin secretos.

## Permisos y scope

- Plataforma usa `platform_payment_provider_configs`.
- Grupo usa `group_payment_provider_configs`.
- Owner solo puede configurar sus grupos.
- Superadmin puede configurar plataforma y cualquier grupo.
- Los callbacks owner Guardarian están cubiertos en `admin_permission_map.py`.
- La confirmación manual de Guardarian está en callbacks `admin_*`, reservados a superadmin por el mapa global de permisos.

## UX y tutorial

Revisado y reforzado:

- Nombre visible: `💳 EUR → USDT / Guardarian` y `💳 Tarjeta EUR → USDT` para comprador.
- Tutorial explica qué es Guardarian, cómo funciona, qué necesita el owner y cuándo se activa el acceso.
- Se añadió explicación sencilla de redes USDT: TRC20, ERC20, Polygon/BEP20.
- Se evita prometer ocultación total de identidad, ausencia de verificación o activación al momento.
- El comprador ve que paga con tarjeta en EUR y que el acceso se activa cuando Guardarian confirma oficialmente.
- Se advierte que algunos pagos pueden tardar o requerir revisión KYC/AML.

## Revisión manual

Quedan en revisión manual:

- `hold`, `review`, `kyc`, `aml`, `blocked`, `unknown`.
- Webhook sin id de transacción.
- Transacción interna no encontrada.
- Error al consultar `GET /v1/transaction/{id}`.
- Descuadre de transaction id, importe, moneda o payout/red cuando esos campos están disponibles.
- Fallo creando invite link o guardando acceso.

Superadmin puede:

- Ver pagos Guardarian en revisión.
- Reconsultar pagos pending/manual review.
- Rechazar pagos.
- Confirmar manualmente, si decide hacerlo tras revisión externa.

Owners pueden configurar Guardarian para sus grupos, pero no tienen botón de concesión manual global.

## Riesgos pendientes

- Confirmar con Guardarian el contrato exacto de payload de `POST /v1/transaction`; el provider usa campos documentados en research y base URL configurable.
- Confirmar si `GET /v1/transaction/{id}` devuelve siempre importe, moneda, payout currency y payout network. Si no los devuelve, esas validaciones quedan como best-effort.
- Confirmar mecanismo oficial de webhook secret/firma. La integración no depende de la firma para conceder acceso porque siempre reconsulta el estado oficial.
- Revisar la unidad de `plans.amount` frente a lo que Guardarian espera en `from_amount` antes de prueba real si los planes están guardados en céntimos.

## Pruebas manuales recomendadas

1. Configurar Guardarian plataforma como superadmin.
2. Configurar Guardarian en una comunidad como owner.
3. Verificar que los secretos no se muestran completos.
4. Confirmar que el botón de compra solo aparece cuando Guardarian está activo/configurado.
5. Crear orden de grupo y verificar `payment_transactions` en `pending`.
6. Enviar webhook duplicado con estado no final y confirmar que no concede acceso.
7. Simular respuesta oficial `finished` y confirmar que concede acceso una sola vez.
8. Repetir webhook `finished` y confirmar que no duplica invite links.
9. Simular `hold`, `kyc`, `review`, `unknown` y confirmar `manual_review`.
10. Simular `failed`, `cancelled`, `expired`, `refunded` y confirmar que no concede acceso.
11. Probar Stripe, PayPal, Revolut, ChangeNOW, `mis_subs`, soporte y ubicación para regresión.
