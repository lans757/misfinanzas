import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app import User, Transaction, SessionLocal as NeonSession

# Nos conectamos a la base de datos local SQLite antigua
sqlite_engine = create_engine("sqlite:///finanzas.db")
SqliteSession = sessionmaker(bind=sqlite_engine)

def migrate():
    sqlite_db = SqliteSession()
    neon_db = NeonSession()

    try:
        # Validamos si ya hay datos en Neon para no duplicar por error
        if neon_db.query(User).count() > 0:
            print("⚠️ Ya existen usuarios en Neon. La base de datos no está vacía.")
            print("Si quieres migrar de nuevo, vacía las tablas en Neon primero.")
            return

        users = sqlite_db.query(User).all()
        if not users:
            print("No hay usuarios en la base SQLite local.")
            return
            
        print(f"Migrando {len(users)} usuarios...")
        for u in users:
            neon_db.execute(
                User.__table__.insert().values(
                    id=u.id,
                    username=u.username,
                    hashed_password=u.hashed_password,
                    created_at=u.created_at
                )
            )
        
        transactions = sqlite_db.query(Transaction).all()
        print(f"Migrando {len(transactions)} transacciones...")
        for t in transactions:
            neon_db.execute(
                Transaction.__table__.insert().values(
                    id=t.id,
                    user_id=t.user_id,
                    date=t.date,
                    description=t.description,
                    category=t.category,
                    type=t.type,
                    amount=t.amount,
                    currency=t.currency,
                    payment_method=t.payment_method,
                    exchange_rate_bcv=t.exchange_rate_bcv,
                    exchange_rate_binance=t.exchange_rate_binance,
                    amount_ves=t.amount_ves,
                    amount_usd=t.amount_usd,
                    amount_usdt=t.amount_usdt,
                    notes=t.notes
                )
            )

        neon_db.commit()
        print("✅ Datos copiados correctamente.")

        # En PostgreSQL, al insertar IDs manualmente, la secuencia autoincremental no se actualiza.
        # Necesitamos sincronizar las secuencias para que los próximos registros no choquen.
        print("🔄 Sincronizando secuencias de PostgreSQL...")
        neon_db.execute(text("SELECT setval('users_id_seq', COALESCE((SELECT MAX(id) + 1 FROM users), 1), false);"))
        neon_db.execute(text("SELECT setval('transactions_id_seq', COALESCE((SELECT MAX(id) + 1 FROM transactions), 1), false);"))
        neon_db.commit()

        print("🚀 Migración completada con éxito.")

    except Exception as e:
        neon_db.rollback()
        print(f"❌ Error durante la migración: {e}")
    finally:
        sqlite_db.close()
        neon_db.close()

if __name__ == "__main__":
    migrate()
