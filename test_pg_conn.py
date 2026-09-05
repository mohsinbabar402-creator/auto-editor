import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='postgres', user='postgres')
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute('SELECT version();')
    print('PostgreSQL Connected:', cur.fetchone()[0])
    cur.execute("SELECT 1 FROM pg_database WHERE datname='whop_editor';")
    if not cur.fetchone():
        cur.execute('CREATE DATABASE whop_editor;')
        print('Created database whop_editor')
    else:
        print('Database whop_editor already exists')
conn.close()
print('SUCCESS!')
