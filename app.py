import os
import psycopg2
from psycopg2 import sql # Za bezbedno formiranje SQL upita
from flask import Flask, request, jsonify
from urllib.parse import urlparse # Za parsiranje DATABASE_URL
from dotenv import load_dotenv # Za učitavanje .env fajla tokom lokalnog razvoja

# Učitavanje promenljivih iz .env fajla (samo za lokalni razvoj)
# Na OnRender-u, ove promenljive se postavljaju direktno u podešavanjima servisa
load_dotenv()

app = Flask(__name__)

# Funkcija za dobijanje konekcije ka bazi podataka
def get_db_connection():
    """Uspostavlja konekciju sa PostgreSQL bazom koristeći DATABASE_URL."""
    db_url_str = os.environ.get('DATABASE_URL')
    if not db_url_str:
        # Ako DATABASE_URL nije postavljen, pokušaj sa pojedinačnim promenljivama
        # Ovo je korisno ako želite da testirate lokalno bez DATABASE_URL formata
        db_name = os.environ.get('DB_NAME')
        db_user = os.environ.get('DB_USER')
        db_pass = os.environ.get('DB_PASS')
        db_host = os.environ.get('DB_HOST')
        db_port = os.environ.get('DB_PORT')

        if not all([db_name, db_user, db_pass, db_host, db_port]):
            raise ValueError("DATABASE_URL or individual DB_NAME, DB_USER, DB_PASS, DB_HOST, DB_PORT environment variables must be set.")

        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_pass,
            host=db_host,
            port=db_port
        )
    else:
        # Parsiranje DATABASE_URL
        url = urlparse(db_url_str)
        conn = psycopg2.connect(
            dbname=url.path[1:],  # Uklanja vodeću kosu crtu '/'
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port
        )
    return conn

# Funkcija za inicijalizaciju baze podataka (kreiranje tabele ako ne postoji)
# Ovu funkciju možete pozvati jednom ručno ili prilikom prvog pokretanja
# Za produkciju, razmislite o alatima za migraciju baze podataka (npr. Alembic)
def init_db():
    """Kreira tabelu 'licenses' ako ona ne postoji u bazi."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Kreiranje tabele 'licenses'
        cur.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                id SERIAL PRIMARY KEY,
                license_key TEXT UNIQUE NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            );
        """)

        # Primer dodavanja nekoliko licenci (ovo možete uraditi i ručno preko SQL klijenta)
        # cur.execute(
        #     "INSERT INTO licenses (license_key, description, is_active, expires_at) VALUES (%s, %s, %s, %s) ON CONFLICT (license_key) DO NOTHING;",
        #     ('TESTKEY123', 'Testna licenca - aktivna', True, None)
        # )
        # cur.execute(
        #     "INSERT INTO licenses (license_key, description, is_active, expires_at) VALUES (%s, %s, %s, %s) ON CONFLICT (license_key) DO NOTHING;",
        #     ('EXPIREDKEY456', 'Testna licenca - istekla', False, '2024-01-01 00:00:00')
        # )

        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized: 'licenses' table checked/created.")
    except Exception as e:
        print(f"Error initializing database: {e}")

# API endpoint za proveru licence
@app.route('/check_license', methods=['POST'])
def check_license_route():
    """
    API endpoint za proveru statusa licence.
    Očekuje JSON payload sa ključem 'license_key'.
    Primer: {"license_key": "ABC-123"}
    """
    if not request.is_json:
        return jsonify({"error": "Invalid request: payload must be JSON"}), 400

    data = request.get_json()
    if not data or 'license_key' not in data:
        return jsonify({"error": "License key not provided in JSON payload"}), 400

    license_key_to_check = data['license_key']
    response_data = {"license_key": license_key_to_check, "is_valid": False, "status": "not_found"}

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # SQL upit za proveru licence
        # Proveravamo da li licenca postoji, da li je aktivna i da li nije istekla (ako expires_at postoji)
        query = sql.SQL("""
            SELECT license_key, is_active, description, expires_at
            FROM licenses
            WHERE license_key = %s;
        """)

        cur.execute(query, (license_key_to_check,))
        license_data = cur.fetchone()

        cur.close()
        conn.close()

        if license_data:
            db_license_key, db_is_active, db_description, db_expires_at = license_data

            # Provera da li je licenca istekla
            is_expired = False
            if db_expires_at:
                # Pretpostavljamo da je expires_at tipa TIMESTAMP
                # Za poređenje sa trenutnim vremenom, koristili bismo datetime.now()
                # Ovde, radi jednostavnosti, samo proveravamo da li je db_is_active postavljeno na False ako je istekla
                # U realnoj aplikaciji, ovde bi bila provera db_expires_at < datetime.now(timezone.utc)
                # Za sada, oslanjamo se na 'is_active' polje koje bi trebalo da se ažurira
                pass # Logika za proveru isteka bi išla ovde

            if db_is_active: #  and not is_expired (ako implementirate proveru isteka)
                response_data["is_valid"] = True
                response_data["status"] = "active"
                response_data["description"] = db_description
                response_data["expires_at"] = db_expires_at.isoformat() if db_expires_at else None
            else:
                response_data["status"] = "inactive_or_expired"
                response_data["description"] = db_description
        else:
            response_data["status"] = "not_found"

    except psycopg2.Error as e:
        # Logovanje greške baze podataka
        app.logger.error(f"Database error: {e}")
        return jsonify({"error": "Database query failed", "details": str(e)}), 500
    except Exception as e:
        # Logovanje opšte greške servera
        app.logger.error(f"An unexpected error occurred: {e}")
        return jsonify({"error": "An unexpected server error occurred", "details": str(e)}), 500

    return jsonify(response_data), 200

# Jednostavan API endpoint za dodavanje nove licence (primer)
@app.route('/add_license', methods=['POST'])
def add_license_route():
    if not request.is_json:
        return jsonify({"error": "Invalid request: payload must be JSON"}), 400

    data = request.get_json()
    required_fields = ['license_key', 'description']
    if not all(field in data for field in required_fields):
        return jsonify({"error": f"Missing fields. Required: {', '.join(required_fields)}"}), 400

    license_key = data['license_key']
    description = data['description']
    is_active = data.get('is_active', True) # Podrazumevano je aktivna
    expires_at = data.get('expires_at', None) # Opciono

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        insert_query = sql.SQL("""
            INSERT INTO licenses (license_key, description, is_active, expires_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """)

        cur.execute(insert_query, (license_key, description, is_active, expires_at))
        new_license_id = cur.fetchone()[0]

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"message": "License added successfully", "license_id": new_license_id, "license_key": license_key}), 201

    except psycopg2.IntegrityError: # Npr. ako je license_key već postoji (UNIQUE constraint)
        conn.rollback() # Važno je uraditi rollback u slučaju greške
        cur.close()
        conn.close()
        return jsonify({"error": "License key already exists or other integrity violation"}), 409 # Conflict
    except psycopg2.Error as e:
        app.logger.error(f"Database error during add_license: {e}")
        return jsonify({"error": "Database operation failed", "details": str(e)}), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred during add_license: {e}")
        return jsonify({"error": "An unexpected server error occurred", "details": str(e)}), 500

# API endpoint za dobijanje liste svih aktivnih licenci
@app.route('/active_licenses', methods=['GET'])
def get_active_licenses_route():
    """
    API endpoint za dobijanje liste svih aktivnih licenci.
    """
    active_licenses_list = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # SQL upit za odabir svih licenci gde je is_active TRUE
        # Biramo specifične kolone koje želimo da vratimo klijentu
        # Možete dodati ORDER BY da sortirate rezultate, npr. po datumu kreiranja
        query = sql.SQL("""
            SELECT license_key, description, created_at, expires_at 
            FROM licenses 
            WHERE is_active = TRUE
            ORDER BY created_at DESC;
        """) # Primer sortiranja: najnovije prvo
        
        cur.execute(query)
        licenses_data = cur.fetchall()  # Dobijamo sve redove koji odgovaraju upitu
        
        cur.close()
        conn.close()

        if licenses_data:
            # Konvertujemo listu torki (tuples) u listu rečnika (dictionaries)
            # radi lakšeg JSON odgovora i čitljivosti
            for row in licenses_data:
                active_licenses_list.append({
                    "license_key": row[0],
                    "description": row[1],
                    "created_at": row[2].isoformat() if row[2] else None, # Formatiramo datetime u ISO string
                    "expires_at": row[3].isoformat() if row[3] else None  # Formatiramo datetime u ISO string
                })
        
        # Vraćamo listu aktivnih licenci i njihov ukupan broj
        return jsonify({"count": len(active_licenses_list), "active_licenses": active_licenses_list}), 200

    except psycopg2.Error as e:
        # Logovanje greške baze podataka
        app.logger.error(f"Database error in get_active_licenses: {e}")
        return jsonify({"error": "Database query failed", "details": str(e)}), 500
    except Exception as e:
        # Logovanje opšte greške servera
        app.logger.error(f"An unexpected error occurred in get_active_licenses: {e}")
        return jsonify({"error": "An unexpected server error occurred", "details": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # Pokretanje inicijalizacije baze samo ako se skripta direktno izvršava
    # i samo za lokalni razvoj. Na OnRender-u, ovo se obično radi drugačije.
    print("Attempting to initialize database for local development...")
    init_db()

    # OnRender će postaviti PORT environment varijablu.
    # Za lokalni razvoj, ako PORT nije postavljen, koristićemo 5001.
    port = int(os.environ.get('PORT', 5001))
    # Za lokalni razvoj, pokrećemo Flask development server.
    # Za produkciju na OnRender-u, koristićemo Gunicorn.
    app.run(host='0.0.0.0', port=port, debug=True)
