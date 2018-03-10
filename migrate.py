import importlib.util
import os
import re
import sys

import dotenv
import redis


migrations_dir = os.path.join(os.path.dirname(__file__), 'migrations')
redis_address = os.environ.get('REDIS_ADDRESS', dotenv.get_key('.env', 'REDIS_ADDRESS'))
if redis_address is None:
    print('REDIS_ADDRESS not defined in env var or .env file', file=sys.stderr)
    sys.exit(1)

conn = redis.from_url(redis_address)

migration_files = sorted(filter(lambda f: re.match('^[0-9]{10}_[a-zA-Z0-9_]+\.py$', f) is not None,
                         os.listdir(migrations_dir)))
latest_migration_timestamp = int((conn.get('latest_migration_timestamp') or 0))
print(f'Latest migration timestamp: {latest_migration_timestamp}')
for i, migration_file in enumerate(migration_files):
    timestamp = int(migration_file[:10])
    if timestamp <= latest_migration_timestamp:
        print(f'Skipping migration file: {migration_file}')
        continue
    print(f'Found new migration file: {migration_file}')
    spec = importlib.util.spec_from_file_location(f'migration_{i}', os.path.join(migrations_dir, migration_file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pipe = conn.pipeline(transaction=True)
    module.run(conn, pipe)
    pipe.execute()
    conn.set('latest_migration_timestamp', str(timestamp))
    print(f'Finished running migration file: {migration_file}')
