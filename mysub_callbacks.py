"""
mysub_callbacks: tramo extraído de callback_router.py.

Prefijos: mysub_

El despacho se queda donde estaba la primera rama, no al principio de
button(): por encima hay puertas de permisos que caen a propósito hacia
aquí, y subirlo se las saltaría.

Antes de mover nada se comprobó que ninguna otra rama de button() puede
capturar un callback de esta región, y que ninguna de estas puede capturar
uno ajeno. Sin esas dos propiedades el orden importaría.
"""

import time

from audit_log_service import log_event
from commercial_catalog import CALLBACK_SUBSCRIPTIONS_HELP
from db import conn
from formatters import format_tiempo_restante
from group_delivery_health_service import recheck_group_delivery_live
from group_subscription_service import (
    fetch_renewal_state,
    set_renewal_enabled,
)
from paypal_subscription_controls import (
    cancel_paypal_renewal,
    fetch_paypal_renewal_state,
)
from group_service import (
    format_community_kind,
    normalize_community_type,
)
from i18n_service import (
    load_user_language,
    t,
)
from invite_link_service import (
    ACCESS_LINK_EXPIRE_SECONDS,
    create_telegram_invite_link,
    format_access_link_validity,
)
from owner_publicity_callbacks import TOKEN
from rbac_helpers import get_group_owner_user_id
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


# revoke_link NO es una constante: es un marcador que main.py rellena en
# caliente con `callback_router_module.revoke_link = ...`. Si el None viviera
# aquí, este módulo se quedaría con él para siempre y el botón reventaría con
# "NoneType is not callable". Se lee del router EN EL MOMENTO de la llamada.
def revoke_link(*args, **kwargs):
    from callback_router import revoke_link as impl
    return impl(*args, **kwargs)



# =========================
# LO QUE SE QUEDA EN EL ROUTER
# =========================
# El import va dentro de la función porque callback_router importa este
# módulo: arriba sería circular.

def build_group_recovery_keyboard(*args, **kwargs):
    from callback_router import build_group_recovery_keyboard as impl
    return impl(*args, **kwargs)


def reply_with_recover_navigation(*args, **kwargs):
    from callback_router import reply_with_recover_navigation as impl
    return impl(*args, **kwargs)


def resolve_group_access_state_for_user(*args, **kwargs):
    from callback_router import resolve_group_access_state_for_user as impl
    return impl(*args, **kwargs)



# =========================
# AYUDANTES DE ESTE TRAMO
# =========================

async def report_access_link_unavailable(context, query, user_id, group_id,
                                        group_name, telegram_group_id,
                                        community_kind):
    """
    Tiene el acceso pagado y activo, y el enlace no se puede crear.

    Es el mismo fallo que vigila el repaso periódico de entrega, pero aquí hay una
    persona esperando delante, así que hace falta algo más que apuntarlo:

      - al cliente se le dice lo que le sirve —que no es cosa suya, que no ha
        perdido nada y que hay alguien mirándolo—, con botones. Antes se le daba
        una instrucción interna sobre un grupo que no es el suyo;
      - a quien puede arreglarlo se le avisa de que un cliente que ha pagado está
        fuera, que es lo único que mueve a alguien a mirarlo hoy;
      - y se vuelve a preguntar a Telegram para dejar el estado de entrega al día:
        acabamos de tener la prueba de que algo no va.
    """

    language = load_user_language(user_id)

    await query.message.reply_text(
        t("access.link_unavailable", language, group=group_name or community_kind),
        reply_markup=build_group_recovery_keyboard(group_id)
    )


    log_event(
        "access_link_unavailable_for_paid_user",
        category="access",
        severity="critical",
        scope="group",
        group_id=group_id,
        actor_user_id=user_id,
        target_user_id=user_id,
        message="Un usuario con acceso activo no ha podido recibir su enlace.",
        metadata={
            "telegram_group_id": telegram_group_id,
            "group_name": str(group_name or "")[:80]
        }
    )


    aviso = (
        "🚨 Un cliente con acceso pagado no puede entrar\n\n"
        f"Comunidad: {group_name or group_id}\n"
        f"Usuario: {user_id}\n\n"
        "El bot no ha podido crear su enlace de invitación. Lo más habitual es "
        "que haya perdido el permiso «Invitar usuarios mediante enlace» en el "
        "grupo.\n\n"
        "Mientras siga así, nadie puede entrar en esta comunidad."
    )

    try:

        owner_user_id = get_group_owner_user_id(group_id)

        if owner_user_id:

            await context.bot.send_message(chat_id=owner_user_id, text=aviso)

    except Exception as e:

        print("Enlace no disponible: no se pudo avisar al propietario:", str(e)[:200])


    try:

        await recheck_group_delivery_live(
            context,
            group_id,
            group_name or f"Comunidad {group_id}",
            telegram_group_id
        )

    except Exception as e:

        print("Enlace no disponible: fallo la reconsulta de entrega:", str(e)[:200])



# =========================
# LAS RAMAS
# =========================
# NOT_HANDLED distingue "atendido" de "no es mío" sin tocar ningún return
# del código movido. No se usa guardián por prefijo: un prefijo puede
# tragarse callbacks ajenos que solo comparten las primeras letras.

NOT_HANDLED = object()


def _resolver_grupo_por_ref(ref):
    """(group_id, name, telegram_group_id) desde un id interno o de Telegram."""

    with conn.cursor() as cur:

        cur.execute("""

            SELECT id, name, telegram_group_id
            FROM groups
            WHERE telegram_group_id=%s OR id=%s
            LIMIT 1

        """, (ref, ref))

        return cur.fetchone()


async def handle_mysub_callbacks(update, context, query, user_id, data):

    # =========================
    # EL INTERRUPTOR DE LA RENOVACIÓN
    # =========================
    # Estas ramas van ANTES que la genérica mysub_: comparten su prefijo y la
    # genérica esperaría un número donde aquí hay un verbo. Y dentro de ellas,
    # el "yes" antes que su confirmación: también comparten prefijo.

    if data.startswith("mysub_receipts_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_receipts_"):]
        language = load_user_language(user_id)

        grupo = _resolver_grupo_por_ref(int(ref)) if ref.lstrip("-").isdigit() else None

        if not grupo:

            await reply_with_recover_navigation(
                query,
                t("mysub.not_found", language)
            )

            return

        with conn.cursor() as cur:

            cur.execute("""

                SELECT payment_date, amount, currency, status, plan
                FROM payments
                WHERE user_id=%s AND group_id=%s
                ORDER BY payment_date DESC NULLS LAST, id DESC
                LIMIT 10

            """, (user_id, grupo[0]))

            pagos = cur.fetchall()

        lineas = [t("mysub.receipts_title", language,
                    group=grupo[1] or ""), ""]

        if not pagos:

            lineas.append(t("mysub.receipts_empty", language))

        else:

            for fecha, amount, currency, status, plan in pagos:

                try:
                    fecha_txt = fecha.strftime("%d/%m/%Y")
                except Exception:
                    fecha_txt = "—"

                try:
                    importe = f"{int(amount) / 100:.2f} {(currency or 'EUR').upper()}"
                except Exception:
                    importe = "—"

                sello = "✅" if (status or "").lower() in ("paid", "completed")                     else ("↩️" if (status or "").lower() == "refunded" else "•")

                lineas.append(f"{sello} {fecha_txt} — {importe} · {plan or ''}")

            lineas.extend(["", t("mysub.receipts_footer", language)])

        await query.message.reply_text(
            "\n".join(lineas),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]])
        )

        return


    if data.startswith("mysub_switch_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_switch_"):]
        language = load_user_language(user_id)

        grupo = _resolver_grupo_por_ref(int(ref)) if ref.lstrip("-").isdigit() else None

        if not grupo:

            await reply_with_recover_navigation(
                query,
                t("mysub.not_found", language)
            )

            return

        from plan_switch_service import (
            build_switch_text,
            fetch_current_plan_name,
            fetch_switch_options,
            switch_is_allowed,
        )

        permitido, motivo = switch_is_allowed(user_id, grupo[0])

        if not permitido:

            # PayPal no puede apagar la anterior al anclar la nueva: se le
            # dice qué hacer y en qué orden, en vez de dejarle pulsar hacia
            # dos suscripciones cobrando.
            clave = ("mysub.switch_paypal" if motivo == "paypal"
                     else "mysub.switch_no_access")

            await query.message.reply_text(
                t(clave, language, group=grupo[1] or ""),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("mysub.btn_back_access", language),
                        callback_data=f"mysub_{ref}"
                    )
                ]])
            )

            return

        opciones = fetch_switch_options(user_id, grupo[0])

        if not opciones:

            await query.message.reply_text(
                t("mysub.switch_empty", language, group=grupo[1] or ""),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("mysub.btn_back_access", language),
                        callback_data=f"mysub_{ref}"
                    )
                ]])
            )

            return

        teclado = [
            [InlineKeyboardButton(
                f"{nombre} — {amount} {currency}",
                callback_data=f"switchplan_{grupo[0]}_{plan_id}"
            )]
            for plan_id, nombre, amount, currency, _dias, _price, _prov in opciones
        ]

        teclado.append([InlineKeyboardButton(
            t("mysub.btn_back_access", language),
            callback_data=f"mysub_{ref}"
        )])

        await query.message.reply_text(
            build_switch_text(
                grupo[1] or "",
                opciones,
                current_plan=fetch_current_plan_name(user_id, grupo[0])
            ),
            reply_markup=InlineKeyboardMarkup(teclado)
        )

        return


    if data.startswith("mysub_invite_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_invite_"):]
        language = load_user_language(user_id)

        grupo = _resolver_grupo_por_ref(int(ref)) if ref.lstrip("-").isdigit() else None

        if not grupo:

            await reply_with_recover_navigation(
                query,
                t("mysub.not_found", language)
            )

            return

        from referral_service import (
            REFERRAL_DAYS,
            build_referral_link,
            fetch_referral_stats,
        )

        estadisticas = fetch_referral_stats(user_id, grupo[0])

        texto = t(
            "mysub.invite_text", language,
            group=grupo[1] or "",
            days=REFERRAL_DAYS,
            link=build_referral_link(user_id, grupo[0]),
            invited=estadisticas["invitados"],
            converted=estadisticas["convertidos"],
            earned=estadisticas["dias"],
        )

        await query.message.reply_text(
            texto,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]]),
            disable_web_page_preview=True
        )

        return


    if data.startswith("mysub_pause_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_pause_"):]
        language = load_user_language(user_id)

        grupo = _resolver_grupo_por_ref(int(ref)) if ref.lstrip("-").isdigit() else None

        from group_subscription_service import pause_renewal

        if grupo and pause_renewal(user_id, grupo[0]):

            await query.answer("Renovación pausada ⏸", show_alert=False)

            await query.message.reply_text(
                t("mysub.pause_done", language),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("mysub.btn_back_access", language),
                        callback_data=f"mysub_{ref}"
                    )
                ]])
            )

            return

        await query.message.reply_text(
            t("mysub.pause_error", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]])
        )

        return


    if data.startswith("mysub_resume_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_resume_"):]
        language = load_user_language(user_id)

        grupo = _resolver_grupo_por_ref(int(ref)) if ref.lstrip("-").isdigit() else None

        from group_subscription_service import resume_renewal

        if grupo and resume_renewal(user_id, grupo[0]):

            await query.answer("Renovación reanudada ▶️", show_alert=False)

            await query.message.reply_text(
                t("mysub.resume_done", language),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("mysub.btn_back_access", language),
                        callback_data=f"mysub_{ref}"
                    )
                ]])
            )

            return

        await query.message.reply_text(
            t("mysub.toggle_error_on", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]])
        )

        return


    if data.startswith("mysub_saveoffer_yes_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_saveoffer_yes_"):]
        language = load_user_language(user_id)

        grupo = _resolver_grupo_por_ref(int(ref)) if ref.lstrip("-").isdigit() else None

        from retention_offer_service import (
            RETENTION_DISCOUNT_PERCENT,
            apply_save_discount,
        )

        if grupo and apply_save_discount(user_id, grupo[0]):

            await query.answer("Descuento aplicado 🎉", show_alert=False)

            await query.message.reply_text(
                t("mysub.save_offer_done", language,
                  group=grupo[1] or "tu comunidad",
                  percent=RETENTION_DISCOUNT_PERCENT),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        t("mysub.btn_back_access", language),
                        callback_data=f"mysub_{ref}"
                    )
                ]])
            )

            return

        await query.message.reply_text(
            t("mysub.save_offer_error", language),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    t("mysub.save_offer_btn_take", language),
                    callback_data=f"mysub_saveoffer_yes_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.save_offer_btn_leave", language),
                    callback_data=f"mysub_stoprenew_go_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.btn_back", language),
                    callback_data=f"mysub_{ref}"
                )],
            ])
        )

        return


    if data.startswith("mysub_stoprenew_go_"):

        # La confirmación clásica, después de haber visto (y rechazado) la
        # oferta de salvamento.
        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_stoprenew_go_"):]
        language = load_user_language(user_id)

        await query.message.reply_text(

            t("mysub.stoprenew_confirm", language),

            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    t("mysub.pause_btn", language),
                    callback_data=f"mysub_pause_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.btn_yes_off", language),
                    callback_data=f"mysub_stoprenew_yes_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.btn_back", language),
                    callback_data=f"mysub_{ref}"
                )],
            ])
        )

        return


    if data.startswith("mysub_stoprenew_yes_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_stoprenew_yes_"):]

        if ref.lstrip("-").isdigit():

            grupo = _resolver_grupo_por_ref(int(ref))

            if grupo and set_renewal_enabled(user_id, grupo[0], False):

                # El webhook de Stripe (subscription.updated) manda la
                # confirmación completa con la fecha; esto es el acuse
                # inmediato del botón.
                await query.answer("Renovación desactivada ✅", show_alert=False)

                language = load_user_language(user_id)

                await query.message.reply_text(
                    t("mysub.stoprenew_done", language),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            t("mysub.btn_back_access", language),
                            callback_data=f"mysub_{ref}"
                        )
                    ]])
                )

                return

        language = load_user_language(user_id)

        await query.message.reply_text(
            t("mysub.toggle_error_off", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]])
        )

        return


    if data.startswith("mysub_stoprenew_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_stoprenew_"):]
        language = load_user_language(user_id)

        # LA OFERTA DE SALVAMENTO, una sola vez por persona y acceso: se
        # registra al MOSTRARSE (quien la rechazó no la vuelve a ver), y solo
        # si de verdad hay una suscripción de Stripe que salvar.
        from retention_offer_service import (
            RETENTION_DISCOUNT_PERCENT,
            RETENTION_OFFER_ENABLED,
            record_offer_shown,
        )

        grupo_oferta = (_resolver_grupo_por_ref(int(ref))
                        if ref.lstrip("-").isdigit() else None)

        sub_id = None

        if RETENTION_OFFER_ENABLED and grupo_oferta:

            with conn.cursor() as cur:

                cur.execute(
                    "SELECT stripe_subscription_id FROM users "
                    "WHERE user_id=%s AND group_id=%s "
                    "AND stripe_subscription_id IS NOT NULL",
                    (user_id, grupo_oferta[0])
                )

                fila = cur.fetchone()
                sub_id = fila[0] if fila else None

        if sub_id and record_offer_shown(user_id, grupo_oferta[0], sub_id):

            await query.message.reply_text(

                t("mysub.save_offer", language,
                  group=grupo_oferta[1] or "tu comunidad",
                  percent=RETENTION_DISCOUNT_PERCENT),

                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        t("mysub.save_offer_btn_take", language),
                        callback_data=f"mysub_saveoffer_yes_{ref}"
                    )],
                    [InlineKeyboardButton(
                        t("mysub.pause_btn", language),
                        callback_data=f"mysub_pause_{ref}"
                    )],
                    [InlineKeyboardButton(
                        t("mysub.save_offer_btn_leave", language),
                        callback_data=f"mysub_stoprenew_go_{ref}"
                    )],
                    [InlineKeyboardButton(
                        t("mysub.btn_back", language),
                        callback_data=f"mysub_{ref}"
                    )],
                ])
            )

            return

        await query.message.reply_text(

            t("mysub.stoprenew_confirm", language),

            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    t("mysub.pause_btn", language),
                    callback_data=f"mysub_pause_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.btn_yes_off", language),
                    callback_data=f"mysub_stoprenew_yes_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.btn_back", language),
                    callback_data=f"mysub_{ref}"
                )],
            ])
        )

        return


    if data.startswith("mysub_pprenewoff_yes_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_pprenewoff_yes_"):]

        if ref.lstrip("-").isdigit():

            grupo = _resolver_grupo_por_ref(int(ref))

            if grupo and cancel_paypal_renewal(user_id, grupo[0]):

                await query.answer("Renovación desactivada ✅", show_alert=False)

                # El mismo evento que registra Stripe al apagar la renovación:
                # así el detector de picos de bajas cuenta ambos proveedores.
                log_event(
                    "group_subscription_autorenew_off",
                    category="payment",
                    severity="info",
                    scope="group",
                    group_id=grupo[0],
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    message="Renovación PayPal apagada por el comprador.",
                    metadata={"provider": "paypal"}
                )

                language = load_user_language(user_id)

                await query.message.reply_text(
                    t("mysub.pp_done", language),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            t("mysub.btn_back_access", language),
                            callback_data=f"mysub_{ref}"
                        )
                    ]])
                )

                return

        language = load_user_language(user_id)

        await query.message.reply_text(
            t("mysub.toggle_error_off", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]])
        )

        return


    if data.startswith("mysub_pprenewoff_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_pprenewoff_"):]
        language = load_user_language(user_id)

        await query.message.reply_text(

            t("mysub.pp_confirm", language),

            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    t("mysub.btn_yes_off", language),
                    callback_data=f"mysub_pprenewoff_yes_{ref}"
                )],
                [InlineKeyboardButton(
                    t("mysub.btn_back", language),
                    callback_data=f"mysub_{ref}"
                )],
            ])
        )

        return


    if data.startswith("mysub_renewon_"):

        try:
            await query.message.delete()
        except:
            pass

        ref = data[len("mysub_renewon_"):]

        if ref.lstrip("-").isdigit():

            grupo = _resolver_grupo_por_ref(int(ref))

            if grupo and set_renewal_enabled(user_id, grupo[0], True):

                await query.answer("Renovación reactivada ✅", show_alert=False)

                language = load_user_language(user_id)

                await query.message.reply_text(
                    t("mysub.renewon_done", language),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            t("mysub.btn_back_access", language),
                            callback_data=f"mysub_{ref}"
                        )
                    ]])
                )

                return

        language = load_user_language(user_id)

        await query.message.reply_text(
            t("mysub.toggle_error_on", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    t("mysub.btn_back_access", language),
                    callback_data=f"mysub_{ref}"
                )
            ]])
        )

        return


    if data.startswith("mysub_"):

        try:

            await query.message.delete()

        except:

            pass


        user_id = query.from_user.id
        language = load_user_language(user_id)
        mysub_parts = data.split("_")


        if len(mysub_parts) < 2 or not mysub_parts[1].lstrip("-").isdigit():

            await reply_with_recover_navigation(
                query,
                t("mysub.unavailable", language)
            )

            return

        requested_group_ref = int(
            mysub_parts[1]
        )


        try:

            with conn.cursor() as cur:

                # =========================
                # OBTENER COMUNIDAD
                # =========================

                cur.execute("""

                    SELECT id,
                           name,
                           telegram_group_id,
                           COALESCE(community_type, 'group')

                    FROM groups

                    WHERE telegram_group_id=%s
                    OR id=%s
                    LIMIT 1

                """, (
                    requested_group_ref,
                    requested_group_ref
                ))

                group_row = cur.fetchone()


                if not group_row:

                    # Sin botones, esta pantalla era un callejón sin salida: y es
                    # justo la que se le ofrece a quien acaba de pagar.
                    await reply_with_recover_navigation(
                        query,
                        t("mysub.not_found", language)
                    )

                    return


                real_group_id = group_row[0]
                group_name = group_row[1]
                telegram_group_id = group_row[2]
                community_type = normalize_community_type(group_row[3])
                community_kind = format_community_kind(community_type)


                # =========================
                # OBTENER EXPIRATION
                # =========================

                cur.execute("""

                    SELECT expiration

                    FROM users

                    WHERE user_id=%s
                    AND group_id=%s
                    AND COALESCE(subscription_active, FALSE)=TRUE
                    AND (
                        expiration IS NULL
                        OR expiration > NOW()
                    )

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id

                ))

                user_row = cur.fetchone()


                access_state = await resolve_group_access_state_for_user(
                    context,
                    user_id,
                    real_group_id
                )


                if not user_row and not access_state.get("has_active_access"):

                    log_event(
                        "access_recovery_denied_no_active_access",
                        category="access",
                        severity="info",
                        scope="group",
                        group_id=real_group_id,
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        message="Recuperación de acceso denegada por no tener acceso activo.",
                        metadata={
                            "user_id": user_id,
                            "group_id": real_group_id,
                            "telegram_group_id": telegram_group_id,
                            "access_source": access_state.get("access_source"),
                            "reason": access_state.get("reason")
                        }
                    )

                    await reply_with_recover_navigation(
                        query,
                        t("mysub.no_active", language, kind=community_kind)
                    )

                    return


                expiration = user_row[0] if user_row else access_state.get("expires_at")


                if access_state.get("has_active_access") and expiration is None:

                    log_event(
                        "access_recovery_permanent_access_allowed",
                        category="access",
                        severity="info",
                        scope="group",
                        group_id=real_group_id,
                        actor_user_id=user_id,
                        target_user_id=user_id,
                        message="Recuperación permitida por acceso permanente/free activo.",
                        metadata={
                            "user_id": user_id,
                            "group_id": real_group_id,
                            "telegram_group_id": telegram_group_id,
                            "access_source": access_state.get("access_source"),
                            "reason": access_state.get("reason")
                        }
                    )


                # =========================
                # OBTENER LINK ACTUAL
                # =========================

                cur.execute("""

                    SELECT invite_link

                    FROM invite_links

                    WHERE user_id=%s
                    AND (
                        group_id=%s
                        OR telegram_group_id=%s
                        OR group_id=%s
                    )
                    AND is_active=TRUE

                    ORDER BY created_at DESC

                    LIMIT 1

                """, (

                    user_id,
                    real_group_id,
                    telegram_group_id,
                    telegram_group_id

                ))

                link_row = cur.fetchone()


        except Exception as e:

            print("Error cargando detalle suscripción:", e)

            await reply_with_recover_navigation(
                query,
                t("mysub.load_error", language)
            )

            return


        # =========================
        # FORMATEAR TIEMPO
        # =========================

        tiempo_texto = format_tiempo_restante(
            expiration,
            language=language
        )


        # =========================
        # REVOCAR LINKS ANTIGUOS
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                SELECT invite_link

                FROM invite_links

                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                telegram_group_id

            ))

            old_links = cur.fetchall()


            for (old_link,) in old_links:

                try:

                    revoke_link(
                        telegram_group_id,
                        old_link
                    )

                    cur.execute("""

                        UPDATE invite_links

                        SET is_active=FALSE,
                            revoked_at=NOW()

                        WHERE invite_link=%s

                    """, (old_link,))

                except Exception as e:

                    print(
                        "Error revocando link:",
                        e
                    )


            cur.execute("""

                DELETE FROM invite_links

                WHERE user_id=%s
                AND (
                    group_id=%s
                    OR telegram_group_id=%s
                    OR group_id=%s
                )

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                telegram_group_id

            ))

            conn.commit()


        # =========================
        # CALCULAR EXPIRACIÓN REAL
        # =========================

        # 24 h por defecto (ACCESS_LINK_EXPIRE_SECONDS) en vez de 180 s: el
        # enlace es de un solo uso y al entrar se comprueba el acceso, así que
        # los tres minutos solo dejaban fuera a clientes que ya habían pagado.
        max_expire = int(time.time()) + max(ACCESS_LINK_EXPIRE_SECONDS, 60)

        if expiration is None:

            expire_timestamp = max_expire

        else:

            subscription_expire = int(
                expiration.timestamp()
            )

            expire_timestamp = min(
                max_expire,
                subscription_expire
            )


        # =========================
        # CREAR LINK NUEVO
        # =========================

        expire_seconds = max(
            60,
            expire_timestamp - int(time.time())
        )


        link = create_telegram_invite_link(
            TOKEN,
            telegram_group_id,
            expire_seconds=expire_seconds,
            member_limit=1,
            community_type=community_type
        )


        if not link:

            # Antes esto le decía al CLIENTE que se asegurase de que el bot es
            # administrador del grupo: una instrucción interna, sobre un grupo que
            # no es suyo. Ahora se le dice lo que le sirve y se avisa a quien
            # puede arreglarlo de verdad.
            await report_access_link_unavailable(
                context,
                query,
                user_id,
                real_group_id,
                group_name,
                telegram_group_id,
                community_kind
            )

            return


        # =========================
        # GUARDAR LINK NUEVO
        # =========================

        with conn.cursor() as cur:

            cur.execute("""

                INSERT INTO invite_links
                (user_id, group_id, telegram_group_id, invite_link)

                VALUES (%s, %s, %s, %s)

            """, (

                user_id,
                real_group_id,
                telegram_group_id,
                link

            ))

            conn.commit()


        keyboard = [

            [

                # Si el enlace caduca, antes había que volver atrás y entrar de
                # nuevo en la comunidad para conseguir otro. Desde aquí es un
                # solo toque, que es lo que hace falta cuando alguien que ha
                # pagado se ha quedado fuera.
                InlineKeyboardButton(

                    t("mysub.btn_another_link", language),

                    callback_data=f"mysub_{telegram_group_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    t("mysub.btn_receipts", language),

                    callback_data=f"mysub_receipts_{telegram_group_id}"

                )

            ],

            [

                # El canal de venta más barato: un socio contento con un
                # enlace en la mano.
                InlineKeyboardButton(

                    t("mysub.btn_invite", language),

                    callback_data=f"mysub_invite_{telegram_group_id}"

                )

            ],

            [

                # Cambiar de plan sin pasar por «ya tienes acceso»: el
                # camino que faltaba para el que quiere pagar MÁS.
                InlineKeyboardButton(

                    t("mysub.btn_switch", language),

                    callback_data=f"mysub_switch_{telegram_group_id}"

                )

            ],

            [

                InlineKeyboardButton(

                    t("mysub.btn_help", language),

                    callback_data=CALLBACK_SUBSCRIPTIONS_HELP

                )

            ],

            [

                InlineKeyboardButton(

                    t("mysub.btn_back", language),

                    callback_data="mis_subs"

                )

            ]

        ]


        access_intro = (
            t("mysub.permanent_intro", language, kind=community_kind)
            if expiration is None
            else ""
        )


        # Renovación automática: si este acceso es una suscripción, la
        # pantalla lo dice y ofrece el interruptor. Cancelar nunca corta el
        # periodo ya pagado; solo apaga los cobros siguientes.
        renovacion = fetch_renewal_state(user_id, real_group_id)
        linea_renovacion = ""

        if renovacion:

            if renovacion.get("paused"):

                try:
                    hasta_pausa = renovacion["resumes_at"].strftime("%d/%m/%Y")
                except Exception:
                    hasta_pausa = "-"

                linea_renovacion = t("mysub.renewal_paused_line", language,
                                     until=hasta_pausa)

                keyboard.insert(1, [
                    InlineKeyboardButton(
                        t("mysub.resume_btn", language),
                        callback_data=f"mysub_resume_{telegram_group_id}"
                    )
                ])

            elif renovacion["cancel_at_period_end"]:

                linea_renovacion = t("mysub.renewal_off", language)

                keyboard.insert(1, [
                    InlineKeyboardButton(
                        t("mysub.btn_renew_on", language),
                        callback_data=f"mysub_renewon_{telegram_group_id}"
                    )
                ])

            else:

                linea_renovacion = t("mysub.renewal_active", language)

                keyboard.insert(1, [
                    InlineKeyboardButton(
                        t("mysub.btn_renew_off", language),
                        callback_data=f"mysub_stoprenew_{telegram_group_id}"
                    )
                ])

        else:

            # PayPal: sus planes de grupo siempre fueron suscripciones. La
            # diferencia con Stripe es que allí cancelar es DEFINITIVO (PayPal
            # no reactiva canceladas), así que no hay botón de reactivar.
            renovacion_pp = fetch_paypal_renewal_state(user_id, real_group_id)

            if renovacion_pp and renovacion_pp["activa"]:

                linea_renovacion = t("mysub.renewal_pp_active", language)

                keyboard.insert(1, [
                    InlineKeyboardButton(
                        t("mysub.btn_renew_off", language),
                        callback_data=f"mysub_pprenewoff_{telegram_group_id}"
                    )
                ])

            elif renovacion_pp and renovacion_pp["cancelada"]:

                linea_renovacion = t("mysub.renewal_pp_off", language)


        mensaje = t(
            "mysub.screen",
            language,
            group=group_name,
            intro=access_intro,
            remaining=tiempo_texto,
            renewal=linea_renovacion,
            validity=format_access_link_validity(expire_seconds, language),
            link=link,
        )


        await query.message.reply_text(

            mensaje,

            reply_markup=InlineKeyboardMarkup(keyboard)

        )

        return

    return NOT_HANDLED
