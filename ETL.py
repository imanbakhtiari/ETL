from flask import Flask, render_template, request, jsonify, flash
from apscheduler.schedulers.background import BackgroundScheduler
import psycopg2
from psycopg2 import sql
import threading
import time

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database connection configurations
SOURCE_DB1 = {
    'dbname': 'wallet',
    'user': 'postgres',
    'password': 'password',
    'host': '10.130.4.60',
    'port': '5432',
}

SOURCE_DB2 = {
    'dbname': 'kc',
    'user': 'postgres',
    'password': 'password',
    'host': '10.130.4.60',
    'port': '5432',
}

TARGET_DB = {
    'dbname': 'mamadali',
    'user': 'postgres',
    'password': 'password',
    'host': '10.130.4.60',
    'port': '5432',
}

sync_status = {'running': False, 'message': ''}

def get_connection(config):
    """Create a connection to the database."""
    return psycopg2.connect(
        dbname=config['dbname'],
        user=config['user'],
        password=config['password'],
        host=config['host'],
        port=config['port']
    )

def get_all_tables(cursor):
    """Fetch all table names from the public schema."""
    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    tables = cursor.fetchall()
    return [table[0] for table in tables]

def get_table_schema(cursor, table_name):
    """Fetch the schema of a table."""
    cursor.execute(sql.SQL("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = %s
        AND table_schema = 'public'
    """), [table_name])
    return cursor.fetchall()

def create_table(target_cursor, table_name, schema):
    """Create a table in the target database if it does not exist."""
    columns = ', '.join([f"{col[0]} {col[1]}" for col in schema])
    create_table_query = f"""
        CREATE TABLE {sql.Identifier(table_name).as_string(target_cursor.connection)} (
            {columns}
        )
    """
    target_cursor.execute(create_table_query)

def fetch_data(cursor, table_name):
    """Fetch data from a specified table."""
    try:
        cursor.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table_name)))
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return columns, rows
    except psycopg2.errors.UndefinedTable:
        print(f"Table {table_name} does not exist in the source database.")
        return [], []
    except Exception as e:
        print(f"An error occurred while fetching data from table {table_name}: {e}")
        return [], []

def sync_table(source_cursor, target_cursor, table_name):
    """Synchronize a single table from the source to the target database."""
    columns, rows = fetch_data(source_cursor, table_name)
    if not columns:
        print(f"Skipping table {table_name} as it does not exist or has no data.")
        return

    try:
        # Fetch schema and check if table exists in target database
        source_schema = get_table_schema(source_cursor, table_name)
        target_schema = get_table_schema(target_cursor, table_name)

        if not target_schema:
            print(f"Creating table: {table_name}")
            create_table(target_cursor, table_name, source_schema)

        # Clear the target table before inserting new data
        target_cursor.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table_name)))

        for row in rows:
            target_cursor.execute(
                sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table_name),
                    sql.SQL(', '.join(columns)),
                    sql.SQL(', '.join(['%s'] * len(columns)))
                ),
                row
            )
        # Commit after each table is processed
        target_cursor.connection.commit()

    except Exception as e:
        print(f"An error occurred while syncing table {table_name}: {e}")
        target_cursor.connection.rollback()

def sync_databases():
    """Main function to synchronize data between source and target databases."""
    global sync_status
    sync_status['running'] = True
    sync_status['message'] = 'Synchronization in progress...'

    source_db1_conn = get_connection(SOURCE_DB1)
    source_db2_conn = get_connection(SOURCE_DB2)
    target_db_conn = get_connection(TARGET_DB)

    source_cursor1 = source_db1_conn.cursor()
    source_cursor2 = source_db2_conn.cursor()
    target_cursor = target_db_conn.cursor()

    try:
        # Fetch and sync tables from both source databases
        for source_cursor, db_name in [(source_cursor1, 'source_db1'), (source_cursor2, 'source_db2')]:
            print(f"Fetching tables to sync from {db_name}...")
            tables_to_sync = get_all_tables(source_cursor)

            print(f"Starting synchronization from {db_name}...")
            for table_name in tables_to_sync:
                print(f"Syncing table: {table_name}")

                # Sync table data
                sync_table(source_cursor, target_cursor, table_name)

        # Commit after processing all tables from both sources
        target_db_conn.commit()
        sync_status['message'] = 'Synchronization complete!'
    except Exception as e:
        sync_status['message'] = f'Error: {e}'
        print(f"An error occurred: {e}")
    finally:
        sync_status['running'] = False
        source_cursor1.close()
        source_cursor2.close()
        target_cursor.close()
        source_db1_conn.close()
        source_db2_conn.close()
        target_db_conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sync', methods=['POST'])
def sync():
    """Trigger synchronization and return response."""
    if sync_status['running']:
        return jsonify({'message': 'Synchronization is already running.'}), 400

    def background_sync():
        """Function to run synchronization in a background thread."""
        sync_databases()

    # Start synchronization in a background thread
    threading.Thread(target=background_sync).start()

    return jsonify({'message': 'Synchronization started.'}), 200

@app.route('/status', methods=['GET'])
def status():
    """Get the current status of synchronization."""
    return jsonify(sync_status)

@app.route('/set_interval', methods=['POST'])
def set_interval():
    data = request.get_json()
    interval = data.get('interval', 3600)
    scheduler.modify_job(job_id='sync_databases', trigger='interval', seconds=interval)
    return jsonify({'message': f'Scheduler interval updated to {interval} seconds.'})

# Setup scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=sync_databases, trigger="interval", seconds=1800, id='sync_databases')
scheduler.start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

