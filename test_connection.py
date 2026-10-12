
import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="jobid",
        user="postgres",
        password=input("Enter PostgreSQL password: ")
    )

    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """)

    print("\nTables found in your database:")
    for row in cursor.fetchall():
        print("-", row[0])

    cursor.close()
    conn.close()

except Exception as e:
    print("Connection failed:", e)
