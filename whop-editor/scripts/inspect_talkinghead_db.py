import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='whop_editor', user='postgres')
with conn.cursor() as cur:
    print('--- VIDEO ---')
    cur.execute("SELECT id, status, file_path FROM videos WHERE id='vid_86fdbf93f0';")
    print(cur.fetchone())
    
    print('\n--- KNOWLEDGE ---')
    cur.execute("SELECT id, event_type, action_type, confidence, parameters_json FROM knowledge WHERE id='know_punchin_c5a39a0c';")
    print(cur.fetchone())
    
    print('\n--- EVIDENCE ---')
    cur.execute("SELECT id, knowledge_id, video_id, outcome_note, metric_value FROM evidence WHERE knowledge_id='know_punchin_c5a39a0c';")
    print(cur.fetchone())
    
    print('\n--- AUDIT LOG ---')
    cur.execute("SELECT id, action, target, detail, created_at FROM audit_log WHERE target='vid_86fdbf93f0';")
    for row in cur.fetchall():
        print(row)
conn.close()
