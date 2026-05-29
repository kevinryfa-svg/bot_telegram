from db import conn


OWNER_ADDON_ACTIVE_STATUSES = ("active", "trialing")

OWNER_ADDON_FEATURE_MAP = {
    "ad_promo": ("ad_promo", "bundle_ads_backups"),
    "backups": ("backups", "bundle_ads_backups")
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

            SELECT {", ".join(OWNER_ADDON_SUBSCRIPTION_FIELDS)}
            FROM owner_addon_subscriptions
            WHERE {" AND ".join(filters)}
            ORDER BY updated_at DESC,
                     id DESC
            LIMIT 1

        """, params)

        row = cur.fetchone()


    return row_to_owner_addon_subscription(row)


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
                    cancel_at_period_end=FALSE,
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
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW(), NOW())
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
                current_period_end
            ))


        subscription_row = cur.fetchone()
        conn.commit()


    return row_to_owner_addon_subscription(subscription_row)


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
