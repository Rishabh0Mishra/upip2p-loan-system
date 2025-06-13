import time
from sqlalchemy.orm import Session
from database import SessionLocal
from emi_processor import process_due_emis

def run_worker():
    print("🚀 EMI Worker started. Polling every 60 seconds...")
    while True:
        try:
            db: Session = SessionLocal()
            process_due_emis(db)
            db.close()
        except Exception as e:
            print(f"🔥 Error during EMI processing: {e}")
        time.sleep(60)  # poll interval in seconds

if __name__ == "__main__":
    run_worker()
