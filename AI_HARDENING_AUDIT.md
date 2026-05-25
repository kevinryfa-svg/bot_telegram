# AI Hardening Audit

## Motivo

Tras desplegar el asistente IA por roles se detectaron respuestas demasiado genéricas:

- En un caso de acceso tras pago, la respuesta podía mencionar correo, bandeja o spam, aunque el bot no entrega accesos por email.
- En ayuda de pagos, el modelo podía listar métodos no implementados, como transferencias bancarias o criptomonedas concretas no confirmadas para una comunidad.
- Los botones de feedback `👍 Útil`, `👎 No útil` y `📝 Reportar problema` actualizaban de forma silenciosa y no daban una respuesta visible al usuario.

## Textos incorrectos corregidos

Se endureció la respuesta para:

- `Pagué y no tengo link`.
- `Cómo puedo pagar`.
- `Qué es EUR → USDT`.
- `Qué es ChangeNOW`.
- `Qué métodos acepta una comunidad`.

La IA ya no debe recomendar revisar email, correo, bandeja de entrada o spam para recuperar acceso.

## Palabras y conceptos restringidos

La política IA ahora prohíbe responder como chatbot genérico y restringe:

- email/correo como canal de entrega de acceso;
- bandeja de entrada/spam;
- transferencias bancarias;
- métodos de pago no implementados;
- criptomonedas concretas si el contexto de la comunidad no las confirma;
- estados de pago inventados.

## Métodos reales permitidos

La IA solo puede mencionar estos métodos del bot:

- Stripe.
- PayPal.
- Revolut.
- ChangeNOW.io / Cripto.
- Guardarian / Tarjeta EUR → USDT.
- Códigos y promociones.

Si no hay comunidad concreta, debe aclarar que cada comunidad activa sus propios métodos.

Si hay `group_id`, debe usar los métodos activos/configurados de esa comunidad.

## Contexto de métodos por comunidad

`ai_context_builder.py` ahora añade contexto seguro:

- métodos soportados globalmente;
- métodos activos/configurados para el grupo;
- `group_has_stripe`;
- `group_has_paypal`;
- `group_has_revolut`;
- `group_has_changenow`;
- `group_has_guardarian`;
- `codes_available`.

No se exponen API keys, webhook secrets, wallets completas, provider_config_id ni enlaces privados.

## Respuestas endurecidas

### Pagué y no tengo link

La respuesta nueva indica:

1. Entrar en Mis suscripciones.
2. Comprobar si el acceso aparece activo.
3. Usar recuperar o reenviar enlace.
4. Esperar si el pago está pendiente de proveedor.
5. Abrir soporte si aparece pagado pero no llega el enlace.

### EUR → USDT

La respuesta nueva explica Guardarian:

- comprador paga con tarjeta en euros;
- owner recibe USDT en wallet configurada;
- acceso automático solo con `status finished`;
- puede haber KYC/AML.

### Cómo puedo pagar

Sin comunidad concreta:

- lista solo métodos soportados por el bot;
- aclara que cada owner activa sus métodos;
- indica que el plan concreto muestra solo métodos disponibles.

Con comunidad concreta:

- lista solo métodos activos detectados para ese `group_id`.

### ChangeNOW

La respuesta nueva explica que ChangeNOW es pago cripto/intercambio y que algunos pagos pueden quedar en revisión manual antes de activar acceso.

## Feedback IA

Se actualizó el flujo de feedback:

- `ai_feedback_{id}_up` guarda `feedback_rating=useful` y `success=true`.
- `ai_feedback_{id}_down` guarda `feedback_rating=not_useful` y `success=false`.
- `ai_feedback_{id}_report` guarda `feedback_rating=problem` y `success=false`.

Después de pulsar, el bot responde de forma visible y ofrece:

- hacer otra pregunta;
- abrir soporte cuando corresponde;
- volver a inicio.

Si no encuentra la interacción original, registra `ai_feedback_missing_interaction` en `bot_user_events`.

## Panel superadmin

El `🧠 Centro IA` incluye `📋 Feedback IA / problemas`.

Esta vista muestra las últimas interacciones marcadas como `not_useful` o `problem` con:

- user_id;
- rol;
- group_id;
- intent;
- fecha;
- resumen de respuesta.

No muestra secrets, wallets completas ni enlaces privados.

## Riesgos pendientes

- La IA sigue usando modelo externo si está configurado para intenciones no críticas. Las respuestas se filtran por términos prohibidos y caen a fallback seguro si detectan contenido genérico incorrecto.
- La precisión de métodos activos depende de que los providers estén correctamente marcados como activos/configurados en la base de datos.

## Pruebas recomendadas

1. Preguntar como comprador: `Pagué y no tengo link`.
2. Confirmar que no menciona email/correo/bandeja/spam.
3. Preguntar: `Cómo puedo pagar`.
4. Confirmar que no menciona transferencias bancarias.
5. Preguntar: `Qué es EUR a USDT`.
6. Confirmar que explica Guardarian con `status finished`.
7. Preguntar: `Qué es ChangeNOW`.
8. Confirmar que explica revisión manual cuando aplica.
9. Pulsar `👍 Útil`.
10. Pulsar `👎 No útil`.
11. Pulsar `📝 Reportar problema`.
12. Confirmar que Telegram no queda cargando y que aparece respuesta visible.
