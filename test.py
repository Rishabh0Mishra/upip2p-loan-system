# from sqlalchemy import inspect
# from database import SessionLocal

# db = SessionLocal()
# inspector = inspect(db.bind)
# print(inspector.get_columns('payments'))

# manual_trigger.py
# from database import SessionLocal
# from models import Loan
# from emi_scheduler import create_repayment_schedule

# db = SessionLocal()

# loan = db.query(Loan).filter(Loan.id == 10).first()

# if loan:
#     create_repayment_schedule(db, loan)
# else:
#     print("❌ Loan not found")


# nuke_db.py

# nuke_and_seed.py

# nuke_and_seed.py

# from sqlalchemy import create_engine, text
# from models import Base, payment_status_enum  # import the enum explicitly
# from config import settings

# def nuke_and_reset():
#     engine = create_engine(settings.database_url)

#     with engine.connect() as conn:
#         conn.execution_options(isolation_level="AUTOCOMMIT")
#         print("💣 Dropping schema...")
#         conn.execute(text("DROP SCHEMA public CASCADE"))
#         print("✅ Schema dropped.")
#         conn.execute(text("CREATE SCHEMA public"))
#         print("🛠️ Schema recreated.")

#     # Bind metadata to engine and create enums BEFORE creating tables
#     Base.metadata.bind = engine
#     print("🔁 Creating ENUMs...")
#     payment_status_enum.create(engine, checkfirst=True)

#     print("📦 Recreating tables...")
#     Base.metadata.create_all(engine)
#     print("🎉 Done. DB nuked & rebuilt with enums.")

# if __name__ == "__main__":
#     nuke_and_reset()

