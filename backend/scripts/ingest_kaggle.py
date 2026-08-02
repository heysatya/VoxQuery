import os
import argparse
import pandas as pd
import zipfile
import tempfile
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from dotenv import load_dotenv

# Load .env variables
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def get_snowflake_connection():
    dsn = os.getenv("SNOWFLAKE_DSN")
    if not dsn or dsn == "dummy_dsn":
        raise ValueError("Please set a valid SNOWFLAKE_DSN in your backend/.env file.")

    # Expected DSN format: user:password@account_identifier/database/schema?warehouse=warehouse_name&role=role_name
    import urllib.parse

    parsed = urllib.parse.urlparse(f"snowflake://{dsn}")

    user = urllib.parse.unquote(parsed.username)
    password = urllib.parse.unquote(parsed.password)
    account = parsed.hostname

    path_parts = parsed.path.strip("/").split("/")
    database = path_parts[0] if len(path_parts) > 0 else None
    schema = path_parts[1] if len(path_parts) > 1 else "PUBLIC"

    query_params = urllib.parse.parse_qs(parsed.query)
    warehouse = query_params.get("warehouse", [None])[0]
    role = query_params.get("role", [None])[0]

    print(f"Connecting to Snowflake account: {account}, DB: {database}, Schema: {schema}")

    return snowflake.connector.connect(
        user=user,
        password=password,
        account=account,
        warehouse=warehouse,
        database=database,
        schema=schema,
        role=role,
    )


def ingest_csv(conn, csv_path: str, table_name: str):
    print(f"Loading {os.path.basename(csv_path)} into pandas...")
    df = pd.read_csv(csv_path)

    # Standardize column names for Snowflake (uppercase, no spaces)
    df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]

    print(f"Writing {len(df)} rows to Snowflake table '{table_name.upper()}'...")
    success, nchunks, nrows, _ = write_pandas(
        conn, df, table_name.upper(), auto_create_table=True, quote_identifiers=False
    )
    if success:
        print(f"✅ Successfully ingested {nrows} rows into {table_name.upper()}!")
    else:
        print(f"❌ Ingestion failed for {table_name.upper()}.")


def process_path(input_path: str):
    conn = get_snowflake_connection()
    try:
        if input_path.endswith(".zip"):
            print(f"Extracting zip file {input_path}...")
            with tempfile.TemporaryDirectory() as tmpdirname:
                with zipfile.ZipFile(input_path, "r") as zip_ref:
                    zip_ref.extractall(tmpdirname)

                # Find all CSVs in the extracted directory
                csv_files = []
                for root, dirs, files in os.walk(tmpdirname):
                    for file in files:
                        if file.endswith(".csv"):
                            csv_files.append(os.path.join(root, file))

                if not csv_files:
                    print("No CSV files found in the zip archive.")
                    return

                for csv_file in csv_files:
                    # Use filename without extension as the table name
                    base_name = os.path.basename(csv_file)
                    table_name = os.path.splitext(base_name)[0]
                    ingest_csv(conn, csv_file, table_name)

        elif os.path.isdir(input_path):
            csv_files = [
                os.path.join(input_path, f) for f in os.listdir(input_path) if f.endswith(".csv")
            ]
            if not csv_files:
                print("No CSV files found in the directory.")
                return
            for csv_file in csv_files:
                table_name = os.path.splitext(os.path.basename(csv_file))[0]
                ingest_csv(conn, csv_file, table_name)

        elif input_path.endswith(".csv"):
            table_name = os.path.splitext(os.path.basename(input_path))[0]
            ingest_csv(conn, input_path, table_name)

        else:
            print(
                "Unsupported file format. Please provide a .zip file, a directory containing .csv files, or a single .csv file."
            )

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest Kaggle datasets (ZIP, Folder, or CSV) into Snowflake"
    )
    parser.add_argument(
        "path", help="Path to the Kaggle .zip file, folder of CSVs, or single .csv file"
    )

    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Error: Path {args.path} not found.")
        exit(1)

    process_path(args.path)
