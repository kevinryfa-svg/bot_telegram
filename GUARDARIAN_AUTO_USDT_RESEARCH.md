# Guardarian automatic EUR card to USDT research

Fecha de investigacion: 2026-05-24

Alcance: investigacion tecnica previa. No se implementa codigo de produccion en esta fase.

## Resumen ejecutivo

Guardarian es una candidata fuerte para el caso:

```text
comprador paga con tarjeta en EUR -> owner recibe USDT en su wallet
```

La documentacion oficial confirma API de exchange, autenticacion por `x-api-key`, creacion de transacciones, consulta de transaccion por `id`, webhooks por cambios de estado, estados finales claros y soporte de compra fiat-to-crypto con Visa/Mastercard.

Recomendacion: **implementar con restricciones**, no "activar sin revisar".

Motivo:

- Si usamos `POST /v1/transaction` para crear la operacion y guardamos el `id` devuelto en `payment_transactions`, podemos consultar el estado oficial con `GET /v1/transaction/{id}`.
- El webhook puede usarse solo como disparador. La fuente de verdad debe ser siempre `GET /v1/transaction/{id}`.
- El estado final seguro documentado es `finished`.
- La documentacion publica de webhooks no confirma una firma HMAC o cabecera criptografica. Dice que el webhook esta disponible por solicitud y que pueden proporcionar IPs para allowlist.
- Antes de produccion real hay que confirmar con Guardarian el mecanismo exacto de autenticacion del webhook y el campo soportado para nuestro `payment_transaction_id` o `external_partner_link_id`.

Conclusion operativa:

1. **Si Guardarian confirma webhook autenticado o IP allowlist + `GET /v1/transaction/{id}`**, se puede implementar acceso automatico verificado.
2. **Si no confirma webhook firmado**, aun puede hacerse automatico con restricciones: callback como disparador, consulta oficial por API como fuente de verdad, idempotencia estricta y rate limiting.
3. **No prometer "sin verificacion"**. El texto correcto es: puede requerir verificacion segun importe, pais, riesgo, metodo de pago o politica AML.

## Enlaces oficiales revisados

- API Documentation: https://guardarian.com/api-doc
- Guardarian Docs intro: https://docs.guardarian.com/docs/intro/
- Exchange API reference: https://docs.guardarian.com/docs/category/reference/
- API introduction/authentication: https://docs.guardarian.com/docs/exchange/guardarian-api/
- Transaction API: https://docs.guardarian.com/docs/exchange/transaction/
- Create transaction: https://docs.guardarian.com/docs/exchange/create-cransaction/
- Get transaction by id: https://docs.guardarian.com/docs/exchange/get-transaction-by-id/
- Transactions list: https://docs.guardarian.com/docs/exchange/get-transactions/
- Webhooks: https://docs.guardarian.com/docs/webhooks/
- Widget integration: https://docs.guardarian.com/docs/widget-integration/
- Institutional/B2B exchanges: https://docs.guardarian.com/docs/exchange/institutional-exchanges/
- Transaction limits: https://guardarian.freshdesk.com/support/solutions/articles/80001151818-what-are-guardarian-transaction-limits-
- KYC/AML explained: https://guardarian.freshdesk.com/support/solutions/articles/80001151835-kyc-aml-explained
- Verify identity: https://guardarian.freshdesk.com/support/solutions/articles/80001151838-how-%D1%81an-i-verify-my-identity-
- Payment methods: https://guardarian.freshdesk.com/support/solutions/articles/80001151815-what-payment-methods-does-guardarian-offer-
- Refund policy / Terms: https://guardarian.com/terms-of-service
- Chargeback article: https://guardarian.com/blog/chargeback-fraud-prevention-and-resolution/
- ChangeNOW article on Guardarian: https://support.changenow.io/hc/en-us/articles/18588145203228-Guardarian
- ChangeNOW fiat/card article: https://support.changenow.io/hc/en-us/articles/360011502400-Can-I-buy-crypto-with-a-credit-debit-card-What-is-a-fiat-exchange
- ChangeNOW integration guide: https://support.changenow.io/hc/en-us/articles/20066260886556-ChangeNOW-Integration-guide

## Producto/API Guardarian

Guardarian se presenta como plataforma no custodial para conectar fiat y crypto. La documentacion de API indica que los partners deben:

1. Crear contrato con Guardarian.
2. Recibir acceso a partner account.
3. Obtener API token desde el partner account.
4. Implementar endpoints de estado, monedas, market-info, estimate y transaction.

La referencia de API confirma autenticacion con:

```text
Header: x-api-key
```

La documentacion publica no muestra de forma clara la base URL final de API en las paginas renderizadas, pero el dominio operativo visible en integraciones y subdominios publicos apunta a servicios de Guardarian. Para implementacion real hay que confirmar la base URL exacta con el partner account o account manager.

### Capacidades confirmadas

| Pregunta | Estado | Evidencia / comentario |
| --- | --- | --- |
| API oficial | Confirmado | Docs oficiales `docs.guardarian.com` y `guardarian.com/api-doc`. |
| Widget/checkout | Confirmado | `https://guardarian.com/calculator/v1?...` con `partner_api_token`. |
| Crear transaccion fiat-to-crypto | Confirmado | `POST /v1/transaction`. |
| Consultar estado por id | Confirmado | `GET /v1/transaction/{id}`. |
| EUR con tarjeta | Confirmado | Payment categories y soporte Visa/Mastercard; widget permite fiat EUR. |
| USDT a wallet externa | Confirmado a nivel de producto | Flujo publico pide recipient wallet address; webhook muestra `payout_address`, `to_currency`, `to_network`. |
| Wallet destino dinamica | Probable, confirmar | Flujo publico permite wallet del usuario; API schema publico no muestra todos los campos en HTML. Confirmar campo exacto en partner docs. |
| Marketplace / multiples owners | No confirmado como marketplace | Se puede modelar con configuraciones separadas por owner/grupo si Guardarian permite API keys por owner o partner subaccounts. Necesita acuerdo partner. |
| Owner configura wallet desde bot | Viable tecnicamente | Guardamos wallet/red/API key cifrada; hay que validar que Guardarian permite payout wallet dinamica o previamente verificada. |

## Endpoints confirmados

| Uso | Metodo | Endpoint | Estado | Notas |
| --- | --- | --- | --- | --- |
| Healthcheck | GET | `/v1/status` | Confirmado | Comprueba si API esta operativa. |
| Monedas | GET | `/v1/currencies` | Confirmado | Lista fiat/crypto soportadas. |
| Fiat | GET | `/v1/currencies/fiat` | Confirmado | Lista fiat soportadas. |
| Crypto | GET | `/v1/currencies/crypto` | Confirmado | Lista crypto soportadas. |
| Payment categories | GET | `/v1/payment-categories` | Confirmado | Incluye categorias como `VISA_MC`, `REVOLUT_PAY`, `SEPA`, `GOOGLE_PAY`, `APPLE_PAY`. |
| Market/min-max | GET | MarketInfo endpoints | Confirmado | La pagina publica indica minimo/maximo deposito/withdrawal. |
| Estimate | GET | `/v1/estimate` | Confirmado | Estimacion de importe de cambio. |
| Crear transaccion | POST | `/v1/transaction` | Confirmado | Crea una transaccion de exchange. |
| Ver transaccion | GET | `/v1/transaction/{id}` | Confirmado | Recupera detalles completos por ID unico. |
| Listar transacciones | GET | `/v1/transactions` | Confirmado | Lista transacciones del partner. |
| Webhook | POST hacia nuestro endpoint | Configurado por Guardarian | Confirmado por solicitud | Se activa contactando account manager/soporte. |
| B2B create transaction | POST | `/v1/b2b/transaction` | Confirmado | Requiere payout address verificada. Puede ser relevante para cuentas de owner/negocio. |
| B2B transactions | GET | `/v1/b2b/transactions` | Confirmado | Lista transacciones B2B. |

## Creacion de pago/transaccion

Endpoint confirmado:

```text
POST /v1/transaction
```

La pagina publica confirma que crea una transaccion de exchange, pero el HTML publico no expone el schema completo de request/response. El webhook oficial si muestra campos que deben esperarse en una transaccion:

- `id`
- `status`
- `email`
- `from_currency`
- `from_network`
- `from_amount`
- `expected_from_amount`
- `to_currency`
- `to_network`
- `to_amount`
- `expected_to_amount`
- `deposit_type`
- `payout_type`
- `deposit_payment_category`
- `payout_payment_category`
- `payout_address`
- `output_hash`
- `external_partner_link_id`
- `partner_id`
- `created_at`
- `updated_at`

Para nuestro bot, la creacion deberia forzar:

```text
from_currency = EUR
from_network = EUR
to_currency = USDT
to_network = red elegida por owner: TRX / ETH / BSC / MATIC / SOL si esta soportada
expected_from_amount = precio del plan
payout_address = wallet USDT del owner/plataforma
payment_category = VISA_MC o dejar al checkout seleccionar tarjeta
external_partner_link_id = payment_transactions.id o uuid interno, si Guardarian confirma soporte
redirect_success / redirect_failed / redirect_cancelled = URLs del bot/web
```

### Metadata/order id

El payload de webhook oficial contiene `external_partner_link_id`. Esto parece el mejor candidato para enlazar con `payment_transactions`.

Pendiente de confirmar con Guardarian:

- Nombre exacto del campo para enviarlo en `POST /v1/transaction`.
- Longitud maxima.
- Si se devuelve en `GET /v1/transaction/{id}`.
- Si siempre llega en webhooks.

Si `external_partner_link_id` no se puede fijar, la alternativa segura es:

1. Crear transaccion Guardarian.
2. Guardar su `id` en `payment_transactions.provider_order_id`.
3. Procesar solo transacciones cuyo `id` exista en nuestra BD.

## Estados oficiales y mapeo interno

La pagina oficial de webhooks documenta estos estados principales:

| Guardarian | Significado operativo | Estado interno | Acceso |
| --- | --- | --- | --- |
| `new` | Transaccion creada/iniciada | `pending` | No conceder |
| `finished` | Transaccion completada | `paid` / `completed` | Conceder tras validar API |
| `failed` | Fallo | `failed` | No conceder |
| `refunded` | Reembolsada | `refunded` | No conceder / revistar acceso si ya existiera |
| `expired` | Expirada | `expired` | No conceder |
| `canceled` / `cancelled` | Cancelada | `cancelled` | No conceder |

La documentacion tambien menciona webhooks adicionales bajo solicitud:

| Estado adicional | Uso |
| --- | --- |
| `kycStarted` | Cliente inicia KYC |
| `kycFailed` | KYC falla |
| `kycFinished` | KYC termina correctamente |
| `waitingForDeposit` | Esperando deposito |
| `depositReceived` | Fondos recibidos o preautorizados |
| `depositCaptured` | Fondos capturados tras preautorizacion |
| `depositFailed` | Deposito fallido |
| `cryptoSent` | Estado de envio |
| `paymentSubmitted` | Pago enviado/pagado, pero no necesariamente final |

Regla recomendada para acceso:

```text
Conceder acceso solo si GET /v1/transaction/{id} devuelve status == "finished"
y coinciden provider, payment_scope, user_id, group_id, plan_id, importe, moneda,
red, wallet destino y la transaccion no fue procesada antes.
```

No conceder con `depositReceived`, `depositCaptured`, `paymentSubmitted` ni `cryptoSent` sin confirmar que `GET /v1/transaction/{id}` ya esta en `finished`.

## Webhook/callback y verificacion

Guardarian documenta webhooks para cambios de estado. La activacion no parece self-service: debe solicitarse al account manager o a soporte. La documentacion dice que, si el partner quiere incluir IPs en allowlist, Guardarian las proporcionara por email.

### Confirmado

- Webhook existe.
- Guardarian envia cambios de estado.
- Payload contiene `requesterType`, `version` y `payload`.
- Payload contiene `payload.id`, `payload.status` y datos de la transaccion.
- Webhook se configura bajo solicitud.
- Guardarian puede proporcionar IPs para allowlist.

### No confirmado publicamente

- Firma HMAC.
- Header de firma.
- Secret compartido.
- Algoritmo de firma.
- Reintentos y politica de retry.
- Identificador unico de evento.

### Estrategia segura

El webhook no debe ser fuente de verdad. Debe ser solo disparador.

Flujo seguro:

1. Recibir webhook.
2. Extraer `payload.id`.
3. Buscar `payment_transactions` por `provider="guardarian"` y `provider_order_id=payload.id`.
4. Cargar credenciales segun `payment_scope`:
   - `platform`: configuracion plataforma.
   - `group`: configuracion owner/grupo.
5. Consultar `GET /v1/transaction/{id}` con `x-api-key`.
6. Ignorar `payload.status` como fuente de verdad.
7. Validar todos los campos contra nuestra transaccion.
8. Si estado oficial es `finished`, aplicar idempotencia y conceder acceso.
9. Si estado es dudoso o KYC/hold/error, pasar a `manual_review`.

Para produccion:

- Pedir a Guardarian firma HMAC si existe.
- Si no hay firma, usar allowlist de IPs + status API + rate limiting + dedupe.
- No procesar ningun webhook cuyo `id` no exista en nuestra BD.

## KYC/KYB y verificacion

No es correcto decir "no pide verificacion".

Documentacion oficial:

- Guardarian explica KYC/AML como parte de sus controles.
- Para verificar identidad, puede pedir email, datos personales, documentos y liveness/selfie.
- Las verificaciones suelen procesarse automaticamente, pero pueden pasar a revision manual.
- Los limites fiat-crypto publicados indican un rango diario por cliente de `EUR 15 - EUR 12,000` y maximo mensual `EUR 50,000` bajo condiciones.
- El articulo de ChangeNOW sobre Guardarian dice que el usuario "may need to complete verification"; no siempre, pero puede ocurrir.
- La guia de ChangeNOW indica que fiat buy/sell mediante Guardarian esta disponible para empresas registradas y requiere KYB.

Wording obligatorio en el bot:

```text
Guardarian puede pedir verificacion segun importe, pais, metodo de pago,
riesgo o politica AML. No podemos garantizar que un pago no requiera KYC/KYB.
```

### Comprador

Puede requerir:

- Email.
- Telefono/SMS.
- Datos personales.
- Documento de identidad.
- Selfie/liveness.
- Source of Funds / Source of Wealth en casos de riesgo o limites.

### Merchant / plataforma / owner

Para integracion API/partner, Guardarian requiere contrato y partner account. Para fiat buy/sell via ChangeNOW se menciona KYB para empresas registradas. Para owners individuales o multiples owners, hay que confirmar:

- Si cada owner necesita partner account propio.
- Si basta una cuenta plataforma con wallets dinamicas.
- Si Guardarian permite marketplace/submerchant model.
- Si Guardarian permite wallets de terceros sin KYB del tercero.

## Redes USDT

Fuentes oficiales de Guardarian y sus paginas de compra USDT mencionan soporte flexible de USDT en redes como:

- TRC20 / Tron
- ERC20 / Ethereum
- BEP20 / BSC
- Polygon

Otras paginas mencionan tambien redes como:

- Solana
- TON
- Optimism

Para implementacion no se debe hardcodear solo por marketing. Debe consultarse `GET /v1/currencies/crypto` o la lista partner actual y construir opciones desde API. Como lista inicial recomendada para wizard:

| Red mostrada | Codigo probable | Estado |
| --- | --- | --- |
| Tron / TRC20 | `TRX` o red Guardarian equivalente | Prioritaria, confirmar codigo exacto |
| Ethereum / ERC20 | `ETH` | Prioritaria |
| BSC / BEP20 | `BSC` | Prioritaria |
| Polygon | `MATIC` | Prioritaria |
| Solana | `SOL` | Confirmar disponibilidad actual |
| TON | `TON` | Confirmar disponibilidad actual |

El bot debe advertir que una wallet de una red incorrecta puede perder fondos.

## Fixed / floating / importe

Para vender accesos a comunidades conviene precio fijo en EUR.

Riesgo:

- Si el comprador paga EUR y el owner recibe USDT, el importe USDT recibido depende de tasa, fees y red.
- Guardarian muestra `expected_from_amount`, `expected_to_amount`, `from_amount_in_eur`, `estimate_breakdown`, `serviceFees`, `partnerFee`, `networkFee`.

Regla recomendada:

- Validar precio por `expected_from_amount` / `from_amount` en EUR.
- No validar acceso por cantidad exacta de USDT recibida, porque fees/red pueden variar.
- Dar acceso si Guardarian confirma `finished` para la transaccion interna creada para ese plan y el importe EUR coincide dentro de tolerancia documentada.

## Chargeback/riesgo

Guardarian usa pagos con tarjeta y habla de 3DS como capa de seguridad para reducir chargebacks. Sus terminos indican que, una vez enviada la crypto a la wallet especificada, la operacion es final e irrevocable salvo requisitos legales u otros casos de refund.

Riesgo para nuestro bot:

- Aunque la crypto enviada sea irreversible, los pagos con tarjeta tienen riesgo de disputa/chargeback.
- No esta documentado publicamente si Guardarian asume totalmente el riesgo o si puede repercutirlo al partner/merchant bajo contrato.
- Si el owner recibe USDT y despues hay disputa, el bot podria haber concedido acceso y el owner conservar fondos o tener obligacion contractual con Guardarian.
- Para marketplace/multiples owners, el riesgo contractual y AML debe quedar claro antes de activar.

Mitigaciones:

- No prometer que no hay chargebacks.
- Guardar evidencia de acceso concedido, plan, usuario, grupo, timestamps y estado Guardarian.
- Marcar pagos con disputa/refund si Guardarian envia `refunded` o estados de riesgo.
- Para beta, empezar con importes bajos y owners aprobados.
- Pedir contrato/condiciones partner antes de produccion comercial.

## Encaje con nuestra arquitectura

### Tablas

`payment_transactions`:

- `provider="guardarian"`
- `payment_scope="platform"` o `"group"`
- `status`: `pending`, `paid`, `failed`, `expired`, `cancelled`, `refunded`, `manual_review`
- `provider_order_id`: Guardarian `id`
- `external_checkout_id`: URL o id de checkout si existe
- `external_payment_id`: Guardarian `id` o payment processor id si aparece
- `provider_config_id`: configuracion usada
- `provider_config_scope`: `platform` o `group`
- `destination_type`: `platform_account`, `owner_wallet`, `group_config`
- `destination_ref`: wallet enmascarada o identificador de config, nunca wallet completa si no hace falta
- `metadata_json`: snapshot seguro: fiat currency, crypto payout, network, masked wallet, external_partner_link_id, expected amounts

`platform_payment_provider_configs`:

- Guardarian plataforma configurado por superadmin.
- API key cifrada.
- Wallet USDT plataforma cifrada o enmascarada segun sensibilidad.
- Red USDT.
- Modo live/sandbox si Guardarian lo confirma.
- Webhook secret/firma si existe.

`group_payment_provider_configs`:

- Guardarian owner/grupo.
- `owner_user_id`
- `group_id`
- `provider="guardarian"`
- `encrypted_config_json` con API key / partner token / wallet / red.
- `public_config_json` solo datos no sensibles o codigos de red.
- `masked_public_summary`.
- `status`: `not_configured`, `pending`, `active`, `disabled`, `error`.
- `secret_status`: `encrypted`, `missing_key`, `invalid`, `deleted`.

### Servicios

`payment_service.py`:

- `get_available_payment_methods_for_platform_purchase`
- `get_available_payment_methods_for_group_purchase`
- Incluir Guardarian solo si config activa y completa.

`checkout_routes.py`:

- `POST /create-guardarian-platform-order`
- `POST /create-guardarian-group-order`
- `POST /webhook/guardarian`
- Webhook solo dispara consulta de estado.

`payment_access_service.py`:

- Conceder acceso solo si `payment_scope="group"`, `provider="guardarian"`, `status oficial == finished`, plan activo, user_id/group_id/plan_id validos e idempotencia OK.

`callback_router.py`:

- Wizard plataforma superadmin.
- Wizard owner/grupo.
- Pantalla tutorial comprador.
- Panel revision manual.

## Configuracion desde bot

### A) Plataforma / superadmin

Campos:

- API key / partner API token.
- Partner id si Guardarian lo expone.
- Payout currency: `USDT`.
- Payout network: TRC20/ERC20/BSC/Polygon/etc desde API.
- Payout wallet plataforma.
- Fiat currency default: `EUR`.
- Payment category default: tarjeta / `VISA_MC` o dejar seleccionable.
- Webhook mode:
  - firmado si Guardarian lo confirma;
  - IP allowlist si no hay firma.
- Success URL.
- Failed URL.
- Cancelled URL.
- Enabled true/false.

Wizard:

1. Explicar que compradores pagan con tarjeta en EUR.
2. Explicar que la plataforma recibe USDT.
3. Pedir API key.
4. Pedir moneda/red USDT.
5. Pedir wallet.
6. Validar red/wallet de forma basica.
7. Mostrar resumen enmascarado.
8. Guardar cifrado con `payment_secret_store.py`.
9. Marcar `pending_verification`.
10. Superadmin activa tras prueba real.

### B) Owner/grupo

Campos:

- API key propia del owner si Guardarian exige cuenta propia.
- O marcar que usa integracion plataforma con wallet del owner si Guardarian lo permite.
- Wallet USDT destino.
- Red USDT destino.
- Fiat currency: `EUR`.
- Crypto payout: `USDT`.
- Payment category: tarjeta.
- Enabled true/false.
- Limites por plan o importe maximo.
- Texto comprador.

Wizard:

1. Explicar que el comprador paga con tarjeta en EUR.
2. Explicar que el owner recibe USDT en la wallet indicada.
3. Advertir que Guardarian puede pedir KYC al comprador.
4. Advertir que wallet/red equivocada puede perder fondos.
5. Pedir red USDT.
6. Pedir wallet.
7. Pedir API key solo si el modelo final requiere API key del owner.
8. Guardar cifrado.
9. Estado `pending_verification`.
10. Activar solo tras prueba.

## UX comprador recomendada

Texto corto:

```text
Paga con tarjeta en euros.
El propietario recibe USDT en su wallet.
Tu acceso se activa automaticamente cuando Guardarian confirme oficialmente el pago.
Algunos pagos pueden tardar o requerir verificacion por seguridad.
```

Antes de redirigir:

```text
Importante:
- Usa datos reales si Guardarian los solicita.
- No cierres el proceso hasta terminar el pago.
- Si Guardarian requiere verificacion, el acceso se activara cuando el pago quede confirmado.
```

Si queda en revision:

```text
Tu pago esta en revision.
Esto puede pasar por controles de tarjeta, KYC, pais, importe o politica AML.
Te avisaremos cuando Guardarian confirme el resultado.
```

## Relacion ChangeNOW + Guardarian

Fuentes oficiales de ChangeNOW confirman que Guardarian es uno de sus proveedores de fiat-to-crypto. ChangeNOW tambien indica que en compras fiat/card los detalles internos se operan del lado de Guardarian.

Opciones:

| Opcion | Ventaja | Riesgo |
| --- | --- | --- |
| Guardarian directo | Mas control: API, status endpoint, webhooks, partner account | Requiere contrato/API y resolver modelo marketplace |
| ChangeNOW + Guardarian | Mas simple si ya hay ChangeNOW integrado | ChangeNOW dice que no ve detalles internos de Guardarian; menos control para automatico |
| Ambos | Flexibilidad | Mas complejidad operativa |

Recomendacion: **Guardarian directo** para automatizar tarjeta EUR -> USDT. Es mas rapido y seguro para nuestro caso porque la documentacion oficial de Guardarian confirma `GET /v1/transaction/{id}` y webhooks de estado. ChangeNOW + Guardarian debe quedar como fallback o referencia, no como camino principal para acceso automatico.

## Plan de implementacion por fases

### Fase 0 - Confirmacion partner

Antes de codigo productivo:

- Confirmar base URL API.
- Confirmar request schema de `POST /v1/transaction`.
- Confirmar response schema.
- Confirmar campo para `external_partner_link_id`.
- Confirmar si webhook puede firmarse.
- Confirmar IPs para allowlist.
- Confirmar si wallets dinamicas de owners estan permitidas.
- Confirmar si owners necesitan KYB propio.
- Confirmar chargeback/liability contractual.

### Fase 1 - Configuracion cifrada

- Provider `guardarian_provider.py`.
- Config plataforma y owner/grupo desde bot.
- Wallet/red/API key cifradas.
- Validacion de moneda/red por API.
- Metodo visible como `Tarjeta EUR -> USDT`.

### Fase 2 - Checkout sin acceso automatico para beta tecnica

- Crear transaccion.
- Guardar `provider_order_id`.
- Redirigir comprador.
- Webhook + status polling.
- Mantener `manual_review` mientras se valida con pruebas reales.

### Fase 3 - Automatico verificado

- Activar acceso automatico solo con:
  - `GET /v1/transaction/{id}` oficial;
  - estado `finished`;
  - importe EUR validado;
  - wallet/red validada;
  - plan activo;
  - idempotencia;
  - webhook autenticado o callback tratado solo como trigger.

### Fase 4 - Monitor y disputas

- Panel de pagos Guardarian.
- Alertas por `failed`, `refunded`, `expired`, KYC.
- Acciones de suspension manual si llega refund/disputa.
- Reportes owner/superadmin.

## Riesgos y preguntas pendientes

P0 antes de produccion:

- Firma o autenticacion webhook no documentada publicamente.
- Modelo marketplace/submerchant no confirmado.
- Responsabilidad ante chargebacks no confirmada publicamente.
- Request schema completo de `POST /v1/transaction` no visible en HTML publico.
- Wallet dinamica de terceros vs wallet verificada no confirmado.
- Sandbox no confirmado publicamente.

P1:

- Codigos exactos de redes USDT deben salir de API, no de texto marketing.
- Necesitamos probar `external_partner_link_id`.
- Necesitamos tolerancias de importe/fees.
- Hay que preparar textos de KYC claros.

## Recomendacion final

Estado: **implementar con restricciones**.

Guardarian parece viable para automatizacion real, mejor que ChangeNOW directo para este caso concreto. No recomiendo activar produccion comercial sin confirmacion partner, pero si recomiendo avanzar con una segunda fase tecnica porque las piezas criticas existen:

- creacion de transaccion;
- consulta oficial por id;
- webhooks de estado;
- estado final `finished`;
- metadata probable `external_partner_link_id`;
- pagos fiat con tarjeta;
- USDT como payout.

Condicion para conceder acceso automatico:

```text
Nunca por webhook solo.
Solo tras consultar GET /v1/transaction/{id} y recibir status == finished.
```

Proveedor recomendado: **Guardarian directo**, no ChangeNOW+Guardarian, porque Guardarian directo da mas control sobre estado, webhook, partner account y payload de transaccion.

## Decisión de implementación en el bot

Se implementa Guardarian directo como proveedor automático condicionado a verificación por API.

Regla operativa:

- `POST /v1/transaction` crea la operación.
- `/webhook/guardarian` solo dispara la revisión.
- `GET /v1/transaction/{id}` es la fuente de verdad.
- Único estado automático de acceso: `finished`.
- Estados pending/processing se mantienen pendientes.
- Estados hold/KYC/review/unknown pasan a revisión manual.
- Estados failed/cancelled/expired/refunded no conceden acceso.

El bot mantiene revisión manual para pagos retenidos, no verificables, con discrepancias de importe/moneda/red o con errores al consultar la API oficial.
