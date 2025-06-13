# redis_config.py
import redis.asyncio as redis

db_redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
