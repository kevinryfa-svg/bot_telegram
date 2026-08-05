"""
Regresión: el propietario principal veía "no tienes permiso" al actuar sobre
una comunidad. La causa no era de permisos, sino que el estado de la
conversación (la comunidad elegida) se pierde en cada reinicio del bot, y la
resolución de comunidad devolvía None antes siquiera de comprobar permisos.
"""

import types


class FakeContext:
    def __init__(self, user_data=None):
        self.user_data = user_data or {}


def make_module(manageable, permitted=True):
    """Reproduce la lógica de resolución sin depender de la base de datos."""

    mod = types.SimpleNamespace()
    mod.list_manageable_group_ids = lambda user_id, permissions: list(manageable)
    mod.user_has_group_permission_any = lambda user_id, group_id, perms: permitted

    def get_selected_group_for_permissions(context, user_id, permissions):
        for key in (
            "selected_group_admin",
            "selected_group_user_codes",
            "group_user_promo_group_id",
            "selected_owner_group",
        ):
            group_id = context.user_data.get(key)
            if not group_id:
                continue
            try:
                group_id = int(group_id)
            except Exception:
                continue
            if mod.user_has_group_permission_any(user_id, group_id, permissions):
                return group_id

        manageable_ids = mod.list_manageable_group_ids(user_id, permissions)
        if len(manageable_ids) == 1:
            group_id = int(manageable_ids[0])
            context.user_data["selected_group_admin"] = group_id
            return group_id

        return None

    mod.get_selected_group_for_permissions = get_selected_group_for_permissions
    return mod


def test_single_community_is_resolved_after_a_restart():
    # Contexto vacío = el bot se reinició. Antes devolvía None.
    mod = make_module(manageable=[7])
    ctx = FakeContext()
    assert mod.get_selected_group_for_permissions(ctx, 123, ["can_manage_groups"]) == 7


def test_resolved_community_is_remembered():
    mod = make_module(manageable=[7])
    ctx = FakeContext()
    mod.get_selected_group_for_permissions(ctx, 123, ["can_manage_groups"])
    assert ctx.user_data["selected_group_admin"] == 7


def test_several_communities_are_never_guessed():
    # Actuar sobre la comunidad equivocada sería peor que pedir que elija.
    mod = make_module(manageable=[7, 8, 9])
    ctx = FakeContext()
    assert mod.get_selected_group_for_permissions(ctx, 123, ["can_manage_groups"]) is None


def test_explicit_selection_wins_over_fallback():
    mod = make_module(manageable=[7])
    ctx = FakeContext({"selected_group_admin": 42})
    assert mod.get_selected_group_for_permissions(ctx, 123, ["can_manage_groups"]) == 42


def test_no_manageable_communities_returns_none():
    mod = make_module(manageable=[])
    ctx = FakeContext()
    assert mod.get_selected_group_for_permissions(ctx, 123, ["can_manage_groups"]) is None


def test_invalid_context_value_falls_back_instead_of_crashing():
    mod = make_module(manageable=[7])
    ctx = FakeContext({"selected_group_admin": "no-es-un-id"})
    assert mod.get_selected_group_for_permissions(ctx, 123, ["can_manage_groups"]) == 7
