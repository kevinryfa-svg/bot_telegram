import base64
import hashlib
import hmac
import json
import os
import secrets


SECRET_STATUS_NOT_CONFIGURED = "not_configured"
SECRET_STATUS_PENDING = "pending"
SECRET_STATUS_ACTIVE = "active"
SECRET_STATUS_ERROR = "error"
SECRET_STATUS_DISABLED = "disabled"

SENSITIVE_CONFIG_FIELDS = (
    "client_secret",
    "secret",
    "webhook_secret",
    "api_key",
    "private_key",
    "access_token",
    "refresh_token"
)


class PaymentSecretStoreUnavailable(Exception):

    pass


def has_payment_encryption_key():

    return bool(os.environ.get("PAYMENT_CONFIG_ENCRYPTION_KEY"))


def get_payment_encryption_key():

    raw_key = os.environ.get("PAYMENT_CONFIG_ENCRYPTION_KEY")


    if not raw_key:

        raise PaymentSecretStoreUnavailable(
            "PAYMENT_CONFIG_ENCRYPTION_KEY no está configurada."
        )


    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def build_keystream(key, nonce, length):

    output = b""
    counter = 0


    while len(output) < length:

        counter_bytes = counter.to_bytes(4, "big")
        output += hmac.new(
            key,
            nonce + counter_bytes,
            hashlib.sha256
        ).digest()
        counter += 1


    return output[:length]


def validate_safe_provider_config(data):

    if not isinstance(data, dict):

        return False, "La configuración debe ser un diccionario."


    for key, value in data.items():

        if value is None:

            continue


        if not isinstance(key, str):

            return False, "Las claves de configuración deben ser texto."


        if not isinstance(value, (str, int, float, bool)):

            return False, "Los valores de configuración deben ser simples."


        if isinstance(value, str) and len(value) > 2000:

            return False, "Un valor de configuración es demasiado largo."


    return True, None


def encrypt_provider_config(data):

    is_valid, error = validate_safe_provider_config(data)


    if not is_valid:

        raise ValueError(error)


    key = get_payment_encryption_key()
    nonce = secrets.token_bytes(16)
    plaintext = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":")
    ).encode("utf-8")
    keystream = build_keystream(key, nonce, len(plaintext))
    ciphertext = bytes(
        plain_byte ^ key_byte
        for plain_byte, key_byte in zip(plaintext, keystream)
    )
    version = b"v1"
    signature = hmac.new(
        key,
        version + nonce + ciphertext,
        hashlib.sha256
    ).digest()

    return base64.urlsafe_b64encode(
        version + nonce + signature + ciphertext
    ).decode("ascii")


def decrypt_provider_config(encrypted_value):

    if not encrypted_value:

        return {}


    key = get_payment_encryption_key()
    raw_value = base64.urlsafe_b64decode(
        encrypted_value.encode("ascii")
    )
    version = raw_value[:2]


    if version != b"v1":

        raise ValueError("Versión de secreto no soportada.")


    nonce = raw_value[2:18]
    signature = raw_value[18:50]
    ciphertext = raw_value[50:]
    expected_signature = hmac.new(
        key,
        version + nonce + ciphertext,
        hashlib.sha256
    ).digest()


    if not hmac.compare_digest(signature, expected_signature):

        raise ValueError("La configuración cifrada no es válida.")


    keystream = build_keystream(key, nonce, len(ciphertext))
    plaintext = bytes(
        cipher_byte ^ key_byte
        for cipher_byte, key_byte in zip(ciphertext, keystream)
    )

    return json.loads(plaintext.decode("utf-8"))


def mask_secret_value(value):

    if value is None:

        return None


    text = str(value)


    if len(text) <= 8:

        return "***"


    return f"{text[:4]}...{text[-4:]}"


def mask_provider_config(data):

    if not isinstance(data, dict):

        return {}


    masked = {}


    for key, value in data.items():

        key_text = str(key)


        if any(term in key_text.lower() for term in SENSITIVE_CONFIG_FIELDS):

            masked[key_text] = mask_secret_value(value)

        else:

            masked[key_text] = value


    return masked
