from neo3.core import types, cryptography
from neo3.wallet import utils as walletutils
from neo3.wallet.types import NeoAddress


def as_uint160(data: bytes, *args) -> types.UInt160:
    """
    Convert the data to a UInt160

    Args:
        data: a serialized UInt160
    """
    return types.UInt160(data)


def as_uint256(data: bytes) -> types.UInt256:
    """
    Convert the data to a UInt256

    Args:
        data: a serialized UInt256
    """
    return types.UInt256(data)


def as_int(data: bytes) -> int:
    """
    Convert the data to an integer
    """
    return int(types.BigInteger(data))


def as_str(data: bytes) -> str:
    """
    Convert the data to a UTF-8 encoded string
    """
    return data.decode()


def as_address(data: bytes) -> NeoAddress:
    """
    Convert the data to a Neo address string

    Args:
        data: a serialized UInt160
    """
    return walletutils.script_hash_to_address(types.UInt160(data))


def as_public_key(data: bytes) -> cryptography.ECPoint:
    """
    Convert the data to a public key

    Args:
        data: a serialized compressed public key
    """
    return cryptography.ECPoint.deserialize_from_bytes(data)

