# AI System Audit

## Estado anterior

La IA ya existía en el bot, principalmente en:

- `ai_service.py`: configuración del proveedor/modelo, llamada al modelo y prompts base.
- `ai_handler.py`: comandos `/ia`, `/asistente`, modo de chat IA y salida con `/salir`.
- `ai_permissions.py`: utilidades previas de permisos/contexto IA.
- `ai_product_plans.py`: catálogo auxiliar de planes/productos para respuestas.
- `help_catalog.py`: contenido de ayuda usado como manual.
- `callback_router.py`: callback `public_ai_help` y accesos puntuales a ayuda IA.
- `main.py`: registro de comandos y derivación de texto al modo IA.

La IA recibía contexto manual o genérico. Era útil como ayuda básica, pero no distinguía con suficiente claridad entre comprador, owner, admin de grupo y superadmin. Tampoco registraba interacciones, no tenía feedback y no estaba conectada a flujos concretos como diagnóstico de pagos, soporte o paneles owner.

## Problemas detectados

- Contexto demasiado general para preguntas reales del producto.
- Poca separación por rol y permisos.
- Sin registro de utilidad o feedback.
- Sin panel dedicado para owner o superadmin.
- Sin modo seguro para sugerir respuestas de soporte.
- Riesgo de respuestas inventadas si el modelo no tenía datos suficientes.
- Falta de política explícita para no revelar secretos, wallets completas, invite links o datos de otros grupos.

## Rediseño aplicado

Se añadió una capa IA por contexto y rol:

- `ai_policy.py`: política de seguridad, roles, contextos y sanitización.
- `ai_intent_router.py`: clasificación simple de intención por reglas.
- `ai_context_builder.py`: construcción de contexto resumido y seguro.
- `ai_response_service.py`: respuesta contextual, fallback seguro, logging y feedback.
- `support_ai_service.py`: sugerencias de respuesta para tickets de soporte.

Roles soportados:

- `buyer`
- `owner`
- `group_admin`
- `superadmin`

Contextos principales:

- `public_marketplace`
- `group_detail`
- `checkout_help`
- `subscription_help`
- `support_ticket`
- `owner_dashboard`
- `owner_payments`
- `owner_surveys`
- `owner_users`
- `superadmin_dashboard`
- `user_tracking`
- `payment_diagnostics`

## Paneles y activación

Comprador:

- Botón `🤖 Ayuda inteligente` en `/start`.
- Ayuda para pagos, acceso, ubicación y preguntas libres.

Owner:

- Botón `🤖 Asistente de comunidad` dentro del panel de comunidad.
- Casos guiados para configuración, pagos, encuestas, usuarios, soporte, marketplace y diagnóstico.

Superadmin:

- Botón `🧠 Centro IA` en Herramientas internas.
- Diagnóstico de errores, pagos, usuarios, encuestas, soporte, auditorías y preparación de tareas para Codex.

Soporte:

- Botón `🤖 Sugerir respuesta` en tickets globales y tickets de comunidad.
- La IA genera un borrador, pero no lo envía automáticamente.

## Permisos y privacidad

La IA construye contexto según el rol:

- Comprador: solo contexto público, sus accesos, tickets y pagos propios cuando estén disponibles.
- Owner: solo comunidades accesibles por permisos.
- Admin de grupo: limitado por permisos del grupo.
- Superadmin: puede usar contexto global.

La política IA prohíbe:

- revelar API keys, webhook secrets, tokens o credenciales;
- mostrar wallets completas si no es necesario;
- exponer invite links completos;
- revelar datos de otros grupos a owners;
- ejecutar expulsiones, baneos, cambios de pago o concesión de accesos;
- marcar pagos como pagados;
- inventar comunidades, precios o estados de pago.

La IA sí puede:

- explicar;
- resumir;
- diagnosticar;
- sugerir pasos;
- preparar borradores;
- indicar botones/rutas del bot;
- preparar tareas para Codex.

## Logging y evaluación

Se añadió la tabla `ai_interactions` para registrar:

- usuario;
- rol;
- grupo si aplica;
- intención;
- pregunta;
- resumen de respuesta;
- resumen de contexto seguro;
- éxito/fallback;
- feedback visible: `useful`, `not_useful` o `problem`.

Los callbacks de feedback son:

- `ai_feedback_{id}_up`
- `ai_feedback_{id}_down`
- `ai_feedback_{id}_report`

## Fallbacks

Si el modelo no está disponible o no da respuesta fiable, el bot usa respuestas por reglas.

La respuesta segura por defecto es:

> No tengo suficiente información para confirmarlo.

Y deriva a soporte, pagos, paneles o rutas del bot según el caso.

## Siguiente fase recomendada

- Añadir más contexto cuantitativo por comunidad: conversión, abandono de checkout y tendencias de soporte.
- Crear botones de acción confirmada desde respuestas IA, por ejemplo abrir directamente pagos, soporte o auditoría.
- Añadir evaluación periódica de `ai_interactions` para detectar intenciones donde la IA falla.
- Ampliar borradores de soporte con plantillas específicas por pago, ubicación, códigos y recuperación de acceso.
