# ChangeNOW.io research for crypto payments

Fecha de investigacion: 2026-05-24

Alcance: investigacion tecnica previa. No se implementa codigo de produccion en esta fase.

## Resumen ejecutivo

ChangeNOW puede encajar como proveedor cripto para pagos de plataforma y pagos por owner/grupo, pero no recomiendo implementar todavia el acceso automatico completo.

Motivo: la documentacion oficial confirma API, creacion de conversiones, API keys, fixed-rate y estados operativos, pero no queda publicamente cerrado lo mas critico para nuestro caso: payload exacto de callbacks/push, verificacion de autenticidad del callback, endpoint/status contract definitivo y soporte estable de metadata para enlazar de forma segura nuestro `payment_transaction_id`.

Recomendacion:

1. No conceder accesos automaticamente con ChangeNOW hasta confirmar webhook/push y verificacion oficial con ChangeNOW.
2. Implementar primero una fase segura de configuracion cifrada y creacion controlada de transacciones solo cuando tengamos API key y endpoints confirmados.
3. Si se implementa antes del callback firmado, usar el callback solo como pista y verificar siempre el estado consultando la API oficial antes de marcar `paid`.

## Fuentes oficiales revisadas

- ChangeNOW Crypto Exchange API: https://changenow.io/api
- Documentacion API enlazada oficialmente en Postman: https://documenter.getpostman.com/view/8180765/SVfTPnM8
- ChangeNOW dApps / ejemplo `POST /v2/exchange`: https://changenow.io/for-partners/dapps
- ChangeNOW Integration guide: https://support.changenow.io/hc/en-us/articles/20066260886556-ChangeNOW-Integration-guide
- Integration: API setup and customization: https://support.changenow.io/hc/en-us/articles/22686553746204-Integration-API-setup-and-customization
- Integration: Transaction management and troubleshooting: https://support.changenow.io/hc/en-us/articles/22686695418396-Integration-Transaction-management-and-troubleshooting
- Statuses of an exchange: https://changenow.io/faq/statuses-of-an-exchange
- Fixed-rate exchanges: https://changenow.io/faq/fixed-rate-exchanges
- Terms of Use: https://changenow.io/terms-of-use

## API oficial confirmada

### Base URL

La pagina oficial de dApps muestra llamadas contra:

```text
https://api.changenow.io
```

Endpoint de creacion mostrado oficialmente:

```text
POST /v2/exchange
```

Endpoint de monedas mostrado oficialmente:

```text
GET /v2/exchange/currencies?active=&flow=standard&buy=&sell=
```

### Version

La documentacion visible usa endpoints `v2`, especialmente `/v2/exchange`.

### Autenticacion

La documentacion publica muestra el header:

```text
x-changenow-api-key: your_api_key
```

La guia de integracion indica que la API key se obtiene desde la cuenta business/partner. La documentacion de setup distingue public API key y private API key. La private API key se usa para endpoints especificos de `v2/exchanges` y se emite por cuenta business.

### Sandbox/testnet

No hay entorno sandbox dedicado. La documentacion de setup indica que no existe test environment dedicado y recomienda probar con pares de bajo coste. Esto significa que las pruebas reales implican transacciones reales, aunque sean minimas.

## Creacion de pago/transaccion

### Endpoint confirmado

```text
POST https://api.changenow.io/v2/exchange
```

### Body confirmado por ejemplo oficial

```json
{
  "fromCurrency": "btc",
  "toCurrency": "usdt",
  "fromNetwork": "btc",
  "toNetwork": "eth",
  "fromAmount": "0.1",
  "toAmount": "",
  "address": "0x...",
  "extraId": "",
  "refundAddress": "",
  "refundExtraId": "",
  "userId": "",
  "payload": "",
  "contactEmail": "",
  "source": "",
  "flow": "standard",
  "type": "direct",
  "rateId": ""
}
```

### Interpretacion para nuestro bot

- `fromCurrency` / `fromNetwork`: moneda y red que paga el usuario.
- `toCurrency` / `toNetwork`: moneda y red que recibe plataforma u owner.
- `fromAmount`: cantidad que envia el usuario.
- `toAmount`: cantidad objetivo si se usa flujo reverse/fixed, sujeto a confirmacion oficial del flujo exacto.
- `address`: wallet destino donde ChangeNOW enviara la moneda recibida.
- `extraId`: memo/tag destino si la red lo exige.
- `refundAddress` / `refundExtraId`: direccion de reembolso del usuario.
- `userId`: posible campo para segmentacion/metadata; la documentacion de setup menciona que desde mayo de 2025 puede separar comisiones por comunidad/segmento, pero conviene confirmar limites y privacidad.
- `payload`: posible campo para metadata, pero la documentacion de troubleshooting dice que `payloads` necesita habilitacion manual.
- `source`: identificador de integracion/partner si ChangeNOW lo asigna o recomienda.
- `flow`: por ejemplo `standard`.
- `type`: por ejemplo `direct` o `reverse`, segun flujo.
- `rateId`: necesario para fixed-rate si el flujo lo requiere; debe confirmarse con los endpoints de fixed-rate en la documentacion Postman/API.

### Respuesta esperada

La documentacion de ejemplo y los flujos de ChangeNOW muestran que debemos guardar como minimo:

- `id`: identificador de exchange/transaccion ChangeNOW.
- `status`: estado inicial.
- `payinAddress`: direccion a la que el usuario debe enviar fondos.
- `payinExtraId`: memo/tag si aplica.
- `payoutAddress`: wallet destino configurada.
- `expectedAmountFrom` / `amountFrom`: importe esperado de entrada.
- `expectedAmountTo` / `amountTo`: importe esperado de salida.
- `validUntil`: expiracion de la orden.
- `fromCurrency`, `toCurrency`, `fromNetwork`, `toNetwork`.
- `createdAt`.

Para el bot, `id` debe guardarse en `payment_transactions.external_payment_id` o `provider_order_id`, y nunca debe usarse una orden sin validarla contra la fila interna.

## Estados de pago y mapeo recomendado

La documentacion oficial de estados y troubleshooting menciona estados como:

- Awaiting deposit
- New
- Waiting
- Confirming
- Exchanging
- Sending
- Verifying
- Finished
- Failed
- Expired
- Refunded
- Hold
- Overdue

Mapeo recomendado:

| ChangeNOW | Nuestro estado | Acceso |
| --- | --- | --- |
| New | pending | No conceder |
| Awaiting deposit | pending | No conceder |
| Waiting | pending | No conceder |
| Confirming | processing | No conceder |
| Exchanging | processing | No conceder |
| Sending | processing | No conceder |
| Verifying | review | No conceder, requiere espera/KYC/revision |
| Hold | review | No conceder, requiere soporte |
| Finished | paid/completed | Conceder solo tras validacion completa |
| Failed | failed | No conceder |
| Expired | expired | No conceder |
| Refunded | refunded | No conceder |
| Overdue | expired/review | No conceder hasta resolucion |

Regla critica: conceder acceso solo cuando la API verificada devuelva estado final equivalente a `Finished` y coincidan provider id, importe, moneda/red, wallet destino, usuario, grupo, plan y fila interna.

## Callback, webhook o IPN

### Lo confirmado oficialmente

La documentacion de integracion menciona funciones de push/live updates y `payloads`, pero tambien indica que algunas funciones avanzadas deben habilitarse manualmente a traves del account manager o soporte.

### Lo no confirmado publicamente

No he encontrado documentacion oficial publica suficiente que confirme:

- nombre exacto del parametro `callback_url`;
- payload completo del callback;
- metodo HTTP;
- firma HMAC o mecanismo equivalente;
- secret compartido;
- cabeceras de verificacion;
- reintentos;
- contrato exacto para enlazar `payload` con nuestro `payment_transaction_id`.

### Estrategia segura recomendada

1. Tratar cualquier callback como una notificacion no confiable.
2. Buscar la transaccion interna por `external_payment_id` / ChangeNOW `id` / metadata confirmada.
3. Consultar el estado directamente a ChangeNOW con API key server-side.
4. Validar:
   - `provider == changenow`;
   - `payment_scope`;
   - `group_id` o producto plataforma;
   - `plan_id`;
   - `user_id`;
   - importe esperado;
   - moneda y red;
   - wallet destino;
   - estado final;
   - no procesado previamente.
5. Aplicar idempotencia antes de conceder acceso.
6. Si no existe firma oficial o status query fiable, no conceder acceso automaticamente.

## Fixed-rate vs floating-rate

### Floating-rate

Ventaja: mas flexible.

Riesgo para accesos: el importe recibido puede variar. Para una venta de acceso a una comunidad, esto puede provocar pagos por debajo del valor esperado o revisiones manuales.

### Fixed-rate

La documentacion indica que fixed-rate congela la tasa durante una ventana limitada y que el usuario debe enviar la cantidad exacta dentro de ese tiempo. La guia de integracion menciona 20 minutos.

Ventajas para este bot:

- mejor encaje para vender acceso con precio cerrado;
- menos ambiguedad sobre si se pago el plan correcto;
- mas facil validar importe antes de conceder acceso.

Riesgos:

- si el usuario paga tarde, menos, mas o por red equivocada, la transaccion puede procesarse proporcionalmente, cancelarse, revisarse o necesitar soporte;
- fixed-rate, push, refunds, payloads y userId pueden requerir habilitacion manual;
- no equivale a cobrar directamente EUR. ChangeNOW opera como exchange cripto; para precio EUR conviene convertir a una moneda objetivo como USDT/USDC o definir pricing cripto.

Recomendacion: para vender accesos, usar fixed-rate/reverse cuando ChangeNOW confirme endpoints y habilitacion. Si no esta confirmado, no automatizar acceso.

## Limites, comisiones y cumplimiento

### Minimos y limites

Los minimos dependen del par, moneda y red. Deben consultarse por API antes de crear la transaccion. Esto es importante porque un plan barato puede quedar por debajo del minimo de ciertas redes.

### Comisiones

ChangeNOW incluye comisiones y network fees en la tasa de cambio. La pagina de partners menciona revenue share y configuracion de comision para partners, pero condiciones concretas dependen de la cuenta business.

### Cumplimiento

Riesgos relevantes:

- no hay sandbox dedicado;
- algunas transacciones pueden entrar en `verifying` o `hold`;
- fiat buy/sell puede requerir KYB;
- hay restricciones jurisdiccionales, incluyendo menciones a limitaciones para UK en la pagina API/terms;
- AML/KYC puede afectar la experiencia del comprador;
- las transacciones cripto son sensibles a red equivocada, memo/tag faltante y pagos fuera de tiempo.

## Encaje con nuestra arquitectura

### Provider

Opcion recomendada:

- usar `provider = "changenow"` si se anade un proveedor concreto;
- alternativamente, si el sistema obliga a `provider = "crypto"`, guardar `gateway = "changenow"` en metadata/configuracion.

Recomiendo `provider = "changenow"` para evitar mezclarlo con futuros proveedores cripto como Coinbase Commerce, NOWPayments o BTCPay Server.

### payment_transactions

Campos que deberian usarse:

- `provider = "changenow"`;
- `payment_scope = "platform"` o `"group"`;
- `purchase_type`;
- `user_id`;
- `owner_user_id` cuando aplique;
- `group_id` cuando aplique;
- `plan_id` cuando aplique;
- `provider_config_scope = "platform"` o `"group"`;
- `provider_config_id`;
- `external_payment_id` = ChangeNOW exchange id;
- `external_checkout_id` = si se usa una referencia distinta;
- `status = pending/processing/paid/failed/expired/refunded/review`;
- `amount`, `currency`;
- `metadata_json` sin secretos.

### Configuracion cifrada

Encaja con:

- `encrypted_config_json`;
- `masked_public_summary`;
- `public_config_json`;
- `secret_status`;
- `provider_config_id`;
- `payment_secret_store.py`.

No se deben guardar API keys, private keys, wallet seeds ni secrets en texto claro.

### payment_access_service.py

Solo debe llamarse cuando:

1. la transaccion interna esta identificada;
2. el estado ChangeNOW verificado es final;
3. el importe y moneda/red son correctos;
4. la transaccion no ha sido procesada antes.

### checkout_routes.py

Futura ruta sugerida:

```text
POST /create-changenow-platform-transaction
POST /create-changenow-group-transaction
POST /webhook/changenow
```

La ruta webhook no debe conceder acceso directamente sin verificacion por API.

### callback_router.py

Botones futuros:

- plataforma: mostrar ChangeNOW solo si superadmin lo configuro y activo;
- grupo: mostrar ChangeNOW solo si el owner lo configuro, esta activo y globalmente permitido;
- si no esta configurado, no mostrarlo al comprador normal.

## Flujo recomendado para pagos de plataforma

1. Superadmin configura ChangeNOW desde el bot.
2. Se cifran API key/private key y datos sensibles.
3. Se define moneda/red destino de la plataforma, por ejemplo USDT TRC20 o USDC.
4. El comprador elige producto plataforma.
5. El bot crea `payment_transaction` pending.
6. Backend llama a ChangeNOW para crear exchange.
7. Bot muestra al comprador:
   - moneda/red;
   - importe exacto;
   - direccion `payinAddress`;
   - memo/tag si aplica;
   - expiracion.
8. Callback/polling verifica estado.
9. Solo `Finished` validado marca paid y activa el producto.

## Flujo recomendado para pagos owner/grupo

1. Owner entra en metodos de pago del grupo.
2. Conecta ChangeNOW:
   - API key/private key o credencial equivalente;
   - wallet destino;
   - moneda/red destino;
   - modo fixed/floating;
   - source/partner tag;
   - callback secret si ChangeNOW lo proporciona.
3. Credenciales se guardan cifradas.
4. Comprador elige plan.
5. Backend valida que el plan pertenece al grupo y que ChangeNOW esta activo para ese grupo.
6. Se crea `payment_transaction` con `payment_scope = "group"`.
7. Se crea exchange con credenciales del owner/grupo.
8. Se verifica estado final por API antes de conceder acceso.
9. `payment_access_service.py` genera invite link y registra acceso.

## Campos para wizard desde bot

### Plataforma

Campos propuestos:

- API key publica.
- Private API key, si el endpoint final lo requiere.
- Wallet destino.
- Extra ID / memo/tag destino, si aplica.
- Moneda destino, ejemplo `usdt`.
- Red destino, ejemplo `trx` o `eth`.
- Modo: fixed-rate o floating-rate.
- Source / partner identifier.
- Email de contacto opcional.
- Callback/push secret si ChangeNOW lo proporciona.
- Estado: not_configured, pending_verification, active, disabled, error.

### Owner/grupo

Campos propuestos:

- API key del owner/grupo.
- Private API key, si aplica.
- Wallet destino del owner.
- Extra ID / memo/tag destino.
- Moneda destino.
- Red destino.
- Modo: fixed-rate o floating-rate.
- Email de contacto opcional.
- Callback/push secret si existe.
- Estado: not_configured, pending_verification, active, disabled, error.

### Campos que no deben pedirse

- seed phrase;
- private key de wallet;
- contraseña de exchange;
- acceso a email;
- claves no relacionadas con API ChangeNOW.

## Seguridad e idempotencia

Requisitos minimos antes de implementar:

- Cifrar credenciales con `payment_secret_store.py`.
- No mostrar secretos completos en Telegram.
- No imprimir API keys ni wallets sensibles completas si el owner las considera privadas.
- Enmascarar public summaries.
- Crear `payment_transaction` antes de llamar a ChangeNOW.
- Guardar `external_payment_id`.
- Callback como pista, no como verdad.
- Verificacion server-side del estado.
- Idempotencia por `external_payment_id` y fila interna.
- No conceder acceso en `verifying`, `hold`, `expired`, `failed`, `refunded`.
- Logs sin secretos.
- Alertar a soporte/admin si hay `hold` o discrepancia de importe.

## Riesgos y preguntas pendientes

Preguntas que hay que resolver con ChangeNOW antes de codigo real:

1. Cual es el endpoint oficial exacto para consultar estado de una transaccion `v2`.
2. Cual es el payload exacto de push/callback.
3. Si el callback tiene firma, cabecera o secret compartido.
4. Si `payload` puede contener nuestro `payment_transaction_id` sin habilitacion manual.
5. Si `userId` puede usarse para group_id/user_id o solo para comisiones/segmentacion.
6. Como crear fixed-rate/reverse correctamente para recibir importe objetivo.
7. Como obtener y validar `rateId`.
8. Minimos por moneda/red y como consultarlos.
9. Que ocurre exactamente con pagos underpaid/overpaid para planes de acceso.
10. Si owners individuales pueden usar su propia API key o si conviene modelo plataforma con wallet destino por owner.
11. Condiciones de KYB/KYC para el modelo marketplace de comunidades privadas.

## Recomendacion final

No implementar todavia checkout automatico ChangeNOW con concesion de acceso.

Si se quiere avanzar con bajo riesgo, la siguiente tarea deberia ser:

1. Anadir provider `changenow` deshabilitado por defecto.
2. Anadir pantallas de configuracion cifrada para plataforma y owner/grupo.
3. No mostrarlo al comprador hasta completar verificacion oficial.
4. Contactar con ChangeNOW para habilitar/confirmar fixed-rate, push, payloads y endpoint de status.
5. Implementar primero una prueba interna con importes minimos y sin conceder acceso automatico.

Solo despues de confirmar callback/status verification e idempotencia completa se deberia activar:

- creacion real de transacciones;
- polling/verificacion;
- concesion automatica con `payment_access_service.py`;
- logs y alertas beta.
