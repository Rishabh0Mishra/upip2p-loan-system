import redis
import json
from functools import wraps
import functools
import json
import hashlib


# Redis setup
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

def cache_result(expiration=1800):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 🔑 Generate unique cache key
            key_base = f"{func.__name__}:{args}:{kwargs}"
            cache_key = hashlib.sha256(key_base.encode()).hexdigest()

            # 🚀 Try fetching from Redis
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

            # 🧠 Get fresh result
            result = func(*args, **kwargs)

            # 🧼 Serialize result safely
            def serialize(obj):
                if hasattr(obj, "model_dump"):  # Pydantic V2
                    return obj.model_dump()
                elif hasattr(obj, "dict"):  # Pydantic V1
                    return obj.dict()
                elif hasattr(obj, "__dict__") and not isinstance(obj, type):  # SQLAlchemy model
                    return {k: serialize(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
                elif isinstance(obj, list):
                    return [serialize(i) for i in obj]
                elif isinstance(obj, dict):
                    return {k: serialize(v) for k, v in obj.items()}
                else:
                    return obj

            safe_result = serialize(result)

            # 💾 Store in Redis
            redis_client.setex(cache_key, expiration, json.dumps(safe_result, default=str))
            return safe_result

        return wrapper
    return decorator

def invalidate_cache(func_name: str):
    """
    Invalidate all cache keys related to a given function name.
    """
    pattern = f"{func_name}:*"
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)
