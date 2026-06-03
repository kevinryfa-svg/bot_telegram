from audit_log_service import log_event
from db import conn


OWNER_ADDON_ACTIVE_STATUSES = ("active", "trialing")
OWNER_ADDON_MANAGEMENT_STATUSES = (
    "active",
    "trialing",
    "past_due",
    "unpaid",
    "incomplete",
    "checkout_pending",
    "canceled"
)

OWNER_ADDON_FEATURE_MAP = {
    "ad_promo": ("ad_promo", "bundle_ads_backups"),
    "backups": ("backups", "bundle_ads_backups"),
    "guardian": ("guardian",)
}

OWNER_ADDON_PRODUCT_FIELDS = [
    "id",
    "code",
    "name",
    "description",
    "monthly_price_cents",
    "currency",
    "stripe_price_id",
    "is_active",
    "created_at",
    "updated_at"
]

OWNER_ADDON_SUBSCRIPTION_FIELDS = [
    "id",
    "owner_user_id",
    "group_id",
    "addon_code",
    "stripe_customer_id",
    "stripe_subscription_id",
    "stripe_price_id",
    "status",
    "current_period_start",
    "current_period_end",
    "cancel_at_period_end",
    "created_at",
    "updated_at"
]

DEFAULT_OWNER_ADDON_PRODUCTS = [
    {
        "code": "ad_promo",
        "name": "Publicidad automática",
        "description": "Publica vídeos promocionales de tu comunidad en canales/grupos publicitarios.",
        "monthly_price_cents": 1999,
        "currency": "eur"
    },
    {
        "code": "backups",
        "name": "Backups automáticos",
        "description": "Guarda copias de seguridad periódicas de la configuración y datos operativos de tu comunidad.",
        "monthly_price_cents": 999,
        "currency": "eur"
    },
    {
        "code": "bundle_ads_backups",
        "name": "Pack Publicidad + Backups",
        "description": "Incluye publicidad automática y backups automáticos para tu comunidad.",
        "monthly_price_cents": 2499,
        "currency": "eur"
    }
]


def row_to_owner_addon_product(row):

    return dict(zip(OWNER_ADDON_PRODUCT_FIELDS, row)) if row else None


def row_to_owner_addon_subscription(row):

    return dict(zip(OWNER_ADDON_SUBSCRIPTION_FIELDS, row)) if row else None


def ensure_owner_addon_products_seeded():

    with conn.cursor() as cur:

        for product in DEFAULT_OWNER_ADDON_PRODUCTS:

            cur.execute("""

                INSERT INTO owner_addon_products
                (
                    code,
                    name,
                    description,
                    monthly_price_cents,
                    currency
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (code) DO NOTHING

            """, (
                product["code"],
                product["name"],
                product["description"],
                product["monthly_price_cents"],
                product["currency"]
            ))


        conn.commit()


def fetch_owner_addon_products(active_only=True):

    filters = []

    if active_only:

        filters.append("is_active=TRUE")


    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_PRODUCT_FIELDS)}
            FROM owner_addon_products
            {where_sql}
            ORDER BY monthly_price_cents ASC,
                     id ASC

        """)

        rows = cur.fetchall()


    return [
        row_to_owner_addon_product(row)
        for row in rows
    ]


def fetch_owner_addon_product(code):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_PRODUCT_FIELDS)}
            FROM owner_addon_products
            WHERE code=%s
            LIMIT 1

        """, (code,))

        row = cur.fetchone()


    return row_to_owner_addon_product(row)


def activate_owner_addon_manual_trial(
    owner_user_id,
    group_id,
    feature_code,
    days=30,
    activated_by_user_id=None
):

    try:

        owner_user_id = int(owner_user_id)
        group_id = int(group_id)
        days = int(days)
        feature_code = (feature_code or "").strip()

    except Exception:

        return {
            "ok": False,
            "reason": "invalid_input"
        }


    if feature_code != "guardian" or days <= 0:

        return {
            "ok": False,
            "reason": "invalid_feature_or_days"
        }


    try:

        with conn.cursor() as cur:

            cur.execute("""

                SELECT g.id,
                       a.user_id AS owner_user_id
                FROM groups g
                LEFT JOIN admins a
                  ON a.group_id = g.id
                 AND a.role = 'GROUP_OWNER'
                 AND COALESCE(a.is_active, TRUE)=TRUE
                WHERE g.id=%s
                LIMIT 1

            """, (group_id,))

            group_row = cur.fetchone()

            if not group_row:

                conn.rollback()
                return {
                    "ok": False,
                    "reason": "group_not_found"
                }


            group_owner_user_id = group_row[1]

            if not group_owner_user_id or int(group_owner_user_id) != int(owner_user_id):

                conn.rollback()
                return {
                    "ok": False,
                    "reason": "owner_group_mismatch",
                    "group_owner_user_id": group_owner_user_id
                }


            cur.execute("""

                SELECT id,
                       code
                FROM owner_addon_products
                WHERE COALESCE(is_active, TRUE)=TRUE
                AND code=%s
                ORDER BY id ASC
                LIMIT 1

            """, (feature_code,))

            product_row = cur.fetchone()

            if not product_row:

                conn.rollback()
                return {
                    "ok": False,
                    "reason": "product_not_found"
                }


            product_id, addon_code = product_row

            cur.execute("""

                SELECT id
                FROM owner_addon_subscriptions
                WHERE owner_user_id=%s
                AND group_id=%s
                AND addon_code=%s
                ORDER BY updated_at DESC,
                         id DESC
                LIMIT 1

            """, (
                owner_user_id,
                group_id,
                addon_code
            ))

            existing_row = cur.fetchone()

            if existing_row:

                cur.execute(f"""

                    UPDATE owner_addon_subscriptions
                    SET status='active',
                        current_period_start=NOW(),
                        current_period_end=NOW() + (%s * INTERVAL '1 day'),
                        cancel_at_period_end=FALSE,
                        updated_at=NOW()
                    WHERE id=%s
                    RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

                """, (
                    days,
                    existing_row[0]
                ))

            else:

                cur.execute(f"""

                    INSERT INTO owner_addon_subscriptions
                    (
                        owner_user_id,
                        group_id,
                        addon_code,
                        status,
                        current_period_start,
                        current_period_end,
                        cancel_at_period_end,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, 'active', NOW(), NOW() + (%s * INTERVAL '1 day'), FALSE, NOW(), NOW())
                    RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

                """, (
                    owner_user_id,
                    group_id,
                    addon_code,
                    days
                ))


            subscription_row = cur.fetchone()
            conn.commit()

        subscription = row_to_owner_addon_subscription(subscription_row)

        log_event(
            "owner_addon_manual_trial_activated",
            category="billing",
            severity="info",
            scope="group",
            group_id=group_id,
            actor_user_id=activated_by_user_id,
            target_user_id=owner_user_id,
            message="Addon owner activado manualmente por superadmin.",
            metadata={
                "owner_user_id": owner_user_id,
                "group_id": group_id,
                "feature_code": feature_code,
                "addon_code": addon_code,
                "days": days,
                "subscription_id": subscription.get("id"),
                "product_id": product_id,
                "current_period_end": subscription.get("current_period_end"),
                "activated_by_user_id": activated_by_user_id,
                "manual_trial": True,
                "payments_created": False
            }
        )

        return {
            "ok": True,
            "subscription_id": subscription.get("id"),
            "product_id": product_id,
            "addon_code": addon_code,
            "current_period_end": subscription.get("current_period_end")
        }

    except Exception as e:

        try:

            conn.rollback()

        except Exception:

            pass

        return {
            "ok": False,
            "reason": "error",
            "error": str(e)[:500]
        }


def fetch_owner_addon_subscriptions(owner_user_id, group_id=None, active_only=False):

    filters = ["owner_user_id=%s"]
    params = [owner_user_id]

    if group_id is not None:

        filters.append("(group_id=%s OR group_id IS NULL)")
        params.append(group_id)


    if active_only:

        filters.append("status = ANY(%s)")
        params.append(list(OWNER_ADDON_ACTIVE_STATUSES))


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}
            FROM owner_addon_subscriptions
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC,
                     id DESC

        """, params)

        rows = cur.fetchall()


    return [
        row_to_owner_addon_subscription(row)
        for row in rows
    ]


def fetch_active_owner_addon_subscription(owner_user_id, addon_code, group_id=None):

    filters = [
        "owner_user_id=%s",
        "addon_code=%s",
        "status = ANY(%s)",
        "(current_period_end IS NULL OR current_period_end > NOW())"
    ]
    params = [
        owner_user_id,
        addon_code,
        list(OWNER_ADDON_ACTIVE_STATUSES)
    ]

    if group_id is not None:

        filters.append("(group_id=%s OR group_id IS NULL)")
        params.append(group_id)


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}
            FROM owner_addon_subscriptions
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC,
                     id DESC
            LIMIT 1

        """, params)

        row = cur.fetchone()


    return row_to_owner_addon_subscription(row)


def fetch_owner_addon_subscription_by_stripe_subscription_id(stripe_subscription_id):

    if not stripe_subscription_id:

        return None


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}
            FROM owner_addon_subscriptions
            WHERE stripe_subscription_id=%s
            LIMIT 1

        """, (stripe_subscription_id,))

        row = cur.fetchone()


    return row_to_owner_addon_subscription(row)


def fetch_owner_addon_subscription(subscription_id):

    if not subscription_id:

        return None


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}
            FROM owner_addon_subscriptions
            WHERE id=%s
            LIMIT 1

        """, (subscription_id,))

        row = cur.fetchone()


    return row_to_owner_addon_subscription(row)


def fetch_owner_addon_subscriptions_for_management(owner_user_id, group_id=None):

    filters = [
        "owner_user_id=%s",
        "status = ANY(%s)"
    ]
    params = [
        owner_user_id,
        list(OWNER_ADDON_MANAGEMENT_STATUSES)
    ]

    if group_id is not None:

        filters.append("(group_id=%s OR group_id IS NULL)")
        params.append(group_id)


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}
            FROM owner_addon_subscriptions
            WHERE {" AND ".join(filters)}
            ORDER BY
                CASE
                    WHEN status IN ('active', 'trialing') THEN 0
                    WHEN status IN ('past_due', 'unpaid') THEN 1
                    WHEN status='checkout_pending' THEN 2
                    WHEN status='incomplete' THEN 3
                    WHEN status='canceled' THEN 4
                    ELSE 5
                END,
                updated_at DESC,
                id DESC

        """, params)

        rows = cur.fetchall()


    return [
        row_to_owner_addon_subscription(row)
        for row in rows
    ]


def upsert_owner_addon_checkout_pending(
    owner_user_id,
    group_id,
    addon_code,
    stripe_price_id,
    stripe_customer_id=None
):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT id
            FROM owner_addon_subscriptions
            WHERE owner_user_id=%s
            AND group_id=%s
            AND addon_code=%s
            AND status='checkout_pending'
            ORDER BY updated_at DESC,
                     id DESC
            LIMIT 1

        """, (
            owner_user_id,
            group_id,
            addon_code
        ))

        row = cur.fetchone()


        if row:

            cur.execute(f"""

                UPDATE owner_addon_subscriptions
                SET stripe_customer_id=COALESCE(%s, stripe_customer_id),
                    stripe_subscription_id=NULL,
                    stripe_price_id=%s,
                    status='checkout_pending',
                    updated_at=NOW()
                WHERE id=%s
                RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

            """, (
                stripe_customer_id,
                stripe_price_id,
                row[0]
            ))

        else:

            cur.execute(f"""

                INSERT INTO owner_addon_subscriptions
                (
                    owner_user_id,
                    group_id,
                    addon_code,
                    stripe_customer_id,
                    stripe_price_id,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, 'checkout_pending', NOW(), NOW())
                RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

            """, (
                owner_user_id,
                group_id,
                addon_code,
                stripe_customer_id,
                stripe_price_id
            ))


        pending_row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(pending_row)


def activate_owner_addon_subscription_from_stripe(
    owner_user_id,
    group_id,
    addon_code,
    stripe_customer_id=None,
    stripe_subscription_id=None,
    stripe_price_id=None,
    current_period_start=None,
    current_period_end=None,
    cancel_at_period_end=False,
    status="active"
):

    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT id
            FROM owner_addon_subscriptions
            WHERE owner_user_id=%s
            AND group_id=%s
            AND addon_code=%s
            AND (
                status='checkout_pending'
                OR stripe_subscription_id=%s
            )
            ORDER BY updated_at DESC,
                     id DESC
            LIMIT 1

        """, (
            owner_user_id,
            group_id,
            addon_code,
            stripe_subscription_id
        ))

        row = cur.fetchone()


        if row:

            cur.execute(f"""

                UPDATE owner_addon_subscriptions
                SET stripe_customer_id=COALESCE(%s, stripe_customer_id),
                    stripe_subscription_id=COALESCE(%s, stripe_subscription_id),
                    stripe_price_id=COALESCE(%s, stripe_price_id),
                    status=%s,
                    current_period_start=COALESCE(%s, current_period_start),
                    current_period_end=COALESCE(%s, current_period_end),
                    cancel_at_period_end=%s,
                    updated_at=NOW()
                WHERE id=%s
                RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

            """, (
                stripe_customer_id,
                stripe_subscription_id,
                stripe_price_id,
                status,
                current_period_start,
                current_period_end,
                cancel_at_period_end,
                row[0]
            ))

        else:

            cur.execute(f"""

                INSERT INTO owner_addon_subscriptions
                (
                    owner_user_id,
                    group_id,
                    addon_code,
                    stripe_customer_id,
                    stripe_subscription_id,
                    stripe_price_id,
                    status,
                    current_period_start,
                    current_period_end,
                    cancel_at_period_end,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

            """, (
                owner_user_id,
                group_id,
                addon_code,
                stripe_customer_id,
                stripe_subscription_id,
                stripe_price_id,
                status,
                current_period_start,
                current_period_end,
                cancel_at_period_end
            ))


        subscription_row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(subscription_row)


def update_owner_addon_subscription_from_stripe(
    stripe_subscription_id,
    stripe_customer_id=None,
    stripe_price_id=None,
    status=None,
    current_period_start=None,
    current_period_end=None,
    cancel_at_period_end=None
):

    if not stripe_subscription_id:

        return None


    updates = []
    params = []

    for field, value in [
        ("stripe_customer_id", stripe_customer_id),
        ("stripe_price_id", stripe_price_id),
        ("status", status),
        ("current_period_start", current_period_start),
        ("current_period_end", current_period_end),
        ("cancel_at_period_end", cancel_at_period_end)
    ]:

        if value is not None:

            updates.append(f"{field}=%s")
            params.append(value)


    if not updates:

        return fetch_owner_addon_subscription_by_stripe_subscription_id(stripe_subscription_id)


    updates.append("updated_at=NOW()")
    params.append(stripe_subscription_id)

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE owner_addon_subscriptions
            SET {", ".join(updates)}
            WHERE stripe_subscription_id=%s
            RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

        """, params)

        row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(row)


def mark_owner_addon_subscription_payment_failed(
    stripe_subscription_id,
    stripe_customer_id=None,
    status="past_due"
):

    return update_owner_addon_subscription_from_stripe(
        stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
        status=status or "past_due"
    )


def cancel_owner_addon_subscription_from_stripe(
    stripe_subscription_id,
    status="canceled",
    cancel_at_period_end=None
):

    return update_owner_addon_subscription_from_stripe(
        stripe_subscription_id,
        status=status or "canceled",
        cancel_at_period_end=cancel_at_period_end
    )


def update_owner_addon_cancel_at_period_end(subscription_id, cancel_at_period_end):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE owner_addon_subscriptions
            SET cancel_at_period_end=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

        """, (
            cancel_at_period_end,
            subscription_id
        ))

        row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(row)


def update_owner_addon_status(subscription_id, status):

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE owner_addon_subscriptions
            SET status=%s,
                updated_at=NOW()
            WHERE id=%s
            RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

        """, (
            status,
            subscription_id
        ))

        row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(row)


def update_owner_addon_plan_from_stripe(
    subscription_id,
    addon_code,
    stripe_price_id,
    status=None,
    current_period_start=None,
    current_period_end=None,
    cancel_at_period_end=None
):

    updates = [
        "addon_code=%s",
        "stripe_price_id=%s"
    ]
    params = [
        addon_code,
        stripe_price_id
    ]

    for field, value in [
        ("status", status),
        ("current_period_start", current_period_start),
        ("current_period_end", current_period_end),
        ("cancel_at_period_end", cancel_at_period_end)
    ]:

        if value is not None:

            updates.append(f"{field}=%s")
            params.append(value)


    updates.append("updated_at=NOW()")
    params.append(subscription_id)

    with conn.cursor() as cur:

        cur.execute(f"""

            UPDATE owner_addon_subscriptions
            SET {", ".join(updates)}
            WHERE id=%s
            RETURNING {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}

        """, params)

        row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(row)


def owner_has_active_addon(owner_user_id, addon_code, group_id=None):

    filters = [
        "owner_user_id=%s",
        "addon_code=%s",
        "status = ANY(%s)"
    ]
    params = [
        owner_user_id,
        addon_code,
        list(OWNER_ADDON_ACTIVE_STATUSES)
    ]

    if group_id is not None:

        filters.append("(group_id=%s OR group_id IS NULL)")
        params.append(group_id)


    with conn.cursor() as cur:

        cur.execute(f"""

            SELECT 1
            FROM owner_addon_subscriptions
            WHERE {" AND ".join(filters)}
            LIMIT 1

        """, params)

        return cur.fetchone() is not None


def owner_has_feature(owner_user_id, feature_code, group_id=None):

    addon_codes = OWNER_ADDON_FEATURE_MAP.get(feature_code, (feature_code,))

    for addon_code in addon_codes:

        if owner_has_active_addon(owner_user_id, addon_code, group_id=group_id):

            return True


    return False


def owner_addon_is_purchase_allowed(owner_user_id, addon_code, group_id=None):

    if fetch_active_owner_addon_subscription(owner_user_id, addon_code, group_id=group_id):

        return False


    feature_code = None

    if addon_code == "ad_promo":

        feature_code = "ad_promo"

    elif addon_code == "backups":

        feature_code = "backups"


    if feature_code and owner_has_feature(owner_user_id, feature_code, group_id=group_id):

        return False


    return True
