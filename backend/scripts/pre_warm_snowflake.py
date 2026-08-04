import os
import sys
import logging
from sqlalchemy import create_engine, text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("snowflake_pre_warm")

def pre_warm():
    # Read your exact DSN from the environment
    dsn = os.getenv("SNOWFLAKE_DSN")
    
    if not dsn:
        logger.error("CRITICAL: SNOWFLAKE_DSN environment variable is missing on Railway.")
        sys.exit(1)
        
    logger.info("Initializing SQLAlchemy engine with your Snowflake DSN...")
    
    try:
        # create_engine uses snowflake-sqlalchemy to automatically parse:
        # - username & password
        # - GCP host: vz67168.me-central2.gcp
        # - database: VOXQUERY_DB
        # - schema: PUBLIC
        # - warehouse: COMPUTE_WH
        # - role: ACCOUNTADMIN
        engine = create_engine(dsn)
        
        logger.info("Pinging Snowflake compute cluster to wake it up...")
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1;")).fetchone()
            logger.info(f"Pre-warm query successful! Response: {result}")
            logger.info("Snowflake compute cluster is successfully awake and primed for production.")
            
    except Exception as e:
        logger.error(f"Failed to pre-warm Snowflake warehouse: {e}")
        sys.exit(1)

if __name__ == "__main__":
    pre_warm()
