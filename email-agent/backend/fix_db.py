import sqlite3

db_path = './data/email_agent.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("UPDATE emails SET is_processed = 0 WHERE summary LIKE 'Summary error:%'")
mod = cur.rowcount
conn.commit()
conn.close()

print(f'Updated {mod} emails back to unprocessed.')
