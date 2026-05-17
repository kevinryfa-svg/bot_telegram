# Checklist manual de pruebas

Este documento sirve para validar el bot después de cada fase grande.

## 1. Arranque

- [ ] El deploy arranca sin errores.
- [ ] No aparece error de import circular.
- [ ] No aparece error de tabla o columna inexistente.
- [ ] Aparece mensaje de base de datos preparada.
- [ ] El bot responde a `/start`.

## 2. Usuario público

Cuenta sin permisos admin.

- [ ] `/start` muestra comunidades disponibles si existen.
- [ ] `/start` muestra soluciones para comunidad.
- [ ] No aparece panel de control.
- [ ] Puede abrir soporte.
- [ ] Puede abrir ayuda IA.
- [ ] Puede solicitar publicar comunidad.
- [ ] Puede solicitar bot personalizado.
- [ ] Si intenta callback admin, recibe bloqueo.

## 3. Formulario publicar comunidad

- [ ] Bot pide nombre de comunidad.
- [ ] Bot pide descripción.
- [ ] Bot pide link o usuario.
- [ ] Bot pide contacto.
- [ ] Bot guarda solicitud.
- [ ] Bot confirma al usuario.
- [ ] Propietario recibe aviso.
- [ ] Aviso incluye botón para revisar solicitud.

## 4. Formulario bot personalizado

- [ ] Bot pide nombre del proyecto.
- [ ] Bot pide nombre deseado del bot.
- [ ] Bot pide username de BotFather o permite `no tengo`.
- [ ] Bot pide descripción.
- [ ] Bot pide contacto.
- [ ] Bot guarda solicitud.
- [ ] Bot confirma al usuario.
- [ ] Propietario recibe aviso.

## 5. Solicitudes comerciales admin

Cuenta super admin.

- [ ] Aparece botón de solicitudes comerciales.
- [ ] Lista solicitudes pendientes.
- [ ] Puede revisar una solicitud.
- [ ] Puede aprobar prueba de 1 día.
- [ ] Puede aprobar bot personalizado.
- [ ] Puede rechazar solicitud.
- [ ] Usuario recibe aviso al aprobar.
- [ ] Usuario recibe aviso al rechazar.

## 6. Prueba de 1 día

- [ ] Al aprobar, status cambia a `trial_active`.
- [ ] Se guarda `trial_starts_at`.
- [ ] Se guarda `trial_ends_at`.
- [ ] El usuario recibe explicación clara.
- [ ] No se crea grupo automáticamente si faltan datos.

## 7. Panel admin por jerarquía

### Super admin

- [ ] Ve panel global.
- [ ] Ve usuarios.
- [ ] Ve accesos.
- [ ] Ve grupos.
- [ ] Ve pagos.
- [ ] Ve negocio.
- [ ] Ve logs.
- [ ] Ve solicitudes comerciales.

### Admin parcial

- [ ] Ve solo secciones permitidas.
- [ ] No ve secciones sin permiso.
- [ ] Si fuerza callback sin permiso, recibe bloqueo.

### Usuario normal

- [ ] No ve panel.
- [ ] Si fuerza callback admin, recibe bloqueo.

## 8. IA contextual

- [ ] `/ia` funciona.
- [ ] `/asistente` funciona.
- [ ] Ayuda comercial responde sobre prueba de 1 día.
- [ ] Ayuda comercial responde sobre bot personalizado.
- [ ] Ayuda comercial no inventa precios.
- [ ] `/salir` desactiva IA.
- [ ] `/salir` devuelve al usuario a un menú útil.

## 9. Compra de grupos existente

- [ ] `group_{id}` sigue funcionando.
- [ ] Selección de plan sigue funcionando.
- [ ] Checkout Stripe sigue funcionando.
- [ ] Mis suscripciones sigue funcionando.
- [ ] Reenvío de acceso sigue funcionando.

## 10. Logs esperados

- [ ] No hay `AttributeError`.
- [ ] No hay `KeyError` de callback.
- [ ] No hay `psycopg2.errors.UndefinedColumn`.
- [ ] No hay `psycopg2.errors.UndefinedTable`.
- [ ] No hay `telegram.error.BadRequest` por editar mensaje inexistente.
