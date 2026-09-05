import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='whop_editor', user='postgres')
with conn.cursor() as cur:
    print('--- RECENT CAMPAIGN JOBS ---')
    cur.execute("SELECT id, campaign_id, job_type, status, assigned_worker_id FROM jobs ORDER BY created_at DESC LIMIT 3;")
    for r in cur.fetchall(): print(' ', r)
    
    print('\n--- RECENT REVIEWS ---')
    cur.execute("SELECT id, job_id, attempt, reviewer_type, verdict, overall_score FROM reviews ORDER BY created_at DESC LIMIT 3;")
    for r in cur.fetchall(): print(' ', r)
    
    print('\n--- RECENT AUDIT LOGS ---')
    cur.execute("SELECT id, action, target, detail FROM audit_log ORDER BY created_at DESC LIMIT 5;")
    for r in cur.fetchall(): print(' ', r)
conn.close()
