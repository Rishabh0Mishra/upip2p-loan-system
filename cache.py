import redis
import json
from functools import wraps

# Redis setup
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

def cache_result(expiration: int = 3600):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
            result = func(*args, **kwargs)
            redis_client.setex(cache_key, expiration, json.dumps(result, default=str))
            return result
        return wrapper
    return decorator

def invalidate_cache(func_name: str):
    """
    Invalidate all cache keys related to a given function name.
    """
    pattern = f"{func_name}:*"
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)
