import hashlib
import json

from dotenv import load_dotenv
from loguru import logger

res = load_dotenv()
if not res:
    logger.warning("No .env file found")


def get_dict_hash(obj: dict) -> str:
    """
    Generate a unique hash for dict.
    Returns a hex string representation of the hash.
    """
    hash_string = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(hash_string.encode()).hexdigest()
