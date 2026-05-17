# Arquitectura objetivo del bot

Este documento define cómo separar el bot para que sea mantenible, comercial y seguro por jerarquías.

## Objetivo principal

Reducir `callback_router.py` y separar responsabilidades por módulos. Ningún usuario debe ver ni ejecutar funciones que no correspondan a su jerarquía real.

## Estructura objetivo

```text
bot_telegram/
├── main.py
├── db.py
├── bot_config.py
├── callback_router.py
├── start_handler.py
├── commercial_catalog.py
├── commercial_form_handler.py
├── rbac_helpers.py
├── admin_permission_map.py
│
├── admin/
│   ├── __init__.py
│   ├── panel.py
│   ├── users.py
│   ├── codes.py
│   ├── groups.py
│   ├── plans.py
│   ├── payments.py
│   ├── stats.py
│   ├── logs.py
│   └── permissions.py
│
├── commercial/
│   ├── __init__.py
│   ├── callbacks.py
│   ├── forms.py
│   ├── notifications.py
│   └── texts.py
│
├── subscriptions/
│   ├── __init__.py
│   ├── callbacks.py
│   ├── access.py
│   └── payments.py
│
├── groups/
│   ├── __init__.py
│   ├── callbacks.py
│   ├── plans.py
│   └── invite_links.py
│
├── ai/
│   ├── __init__.py
│   ├── contexts.py
│   └── prompts.py
│
└── utils/
    ├── __init__.py
    ├── formatters.py
    └── telegram_messages.py
```

## Reglas de jerarquía

### Usuario público

Puede ver:

- comunidades disponibles;
- sus accesos;
- soporte;
- ayuda IA;
- soluciones comerciales para su comunidad.

No puede ver panel de gestión.

### Usuario suscrito

Puede ver lo mismo que usuario público y además gestionar su acceso si tiene suscripciones activas.

### Admin de grupo

Solo puede ver las secciones para las que tenga permisos reales en la tabla `admins`.

Ejemplos:

- `can_view_users` o `can_manage_users`: usuarios;
- `can_manage_codes`: accesos/códigos;
- `can_manage_groups`: grupos;
- `can_manage_plans`: planes;
- `can_view_payments` o `can_manage_payments`: pagos;
- `can_view_stats`: estadísticas;
- `can_view_logs`: logs.

### Propietario de comunidad

Debe poder gestionar su comunidad, grupos, planes, usuarios, accesos, pagos y admins delegados según permisos asignados.

### Super admin

Puede ver y ejecutar todo.

## Regla crítica de seguridad

El menú visible no es suficiente. Cada callback admin debe comprobar permisos antes de ejecutar la acción.

## Mapa de permisos

El archivo `admin_permission_map.py` centraliza qué permisos requiere cada callback o familia de callbacks.

## Fases recomendadas

### Fase 1

Conectar `admin_permission_map.py` con `callback_router.py` sin mover lógica.

### Fase 2

Extraer menú admin principal a `admin/panel.py`.

### Fase 3

Extraer usuarios a `admin/users.py`.

### Fase 4

Extraer códigos/accesos a `admin/codes.py`.

### Fase 5

Extraer grupos y planes a `admin/groups.py` y `admin/plans.py`.

### Fase 6

Extraer pagos, estadísticas y logs.

### Fase 7

Separar comercial en carpeta `commercial/`.

### Fase 8

Separar suscripciones y acceso de usuarios en `subscriptions/`.

## Normas para Codex

- No cambiar textos salvo que se pida.
- No cambiar callbacks existentes salvo que se pida.
- No tocar Stripe sin fase específica.
- No tocar SQL salvo moverlo igual o crear migración clara.
- No mezclar refactor con funcionalidades nuevas.
- Ejecutar siempre `py_compile`.
- Ejecutar siempre `git diff --check`.
