import duckdb


def get_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(db_path)


def init_db(db_path: str) -> None:
    con = get_connection(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            detected_at     TIMESTAMP,
            file_path       VARCHAR,
            common_name     VARCHAR,
            scientific_name VARCHAR,
            confidence      FLOAT,
            lat             FLOAT,
            lon             FLOAT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS export_log (
            exported_at TIMESTAMP DEFAULT current_timestamp,
            row_count   INTEGER
        )
    """)
    con.close()
