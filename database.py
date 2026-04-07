import sqlite3
import os
from datetime import datetime

# Get the directory where this file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'hospital.db')

def init_db():
    """Initialize the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create patients table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL,
            name TEXT NOT NULL,
            priority TEXT NOT NULL,
            arrival_time TIMESTAMP NOT NULL,
            wait_time INTEGER,
            status TEXT DEFAULT 'waiting'
        )
    ''')
    
    # Create users table for authentication
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'staff'
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at: {DB_PATH}")

def save_patient(token, name, priority, arrival_time):
    """Save patient to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO patients (token, name, priority, arrival_time, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, name, priority, arrival_time, 'waiting'))
    conn.commit()
    conn.close()

def update_patient_status(token, status, wait_time=None):
    """Update patient status"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if wait_time:
        cursor.execute('''
            UPDATE patients 
            SET status = ?, wait_time = ? 
            WHERE token = ?
        ''', (status, wait_time, token))
    else:
        cursor.execute('''
            UPDATE patients 
            SET status = ? 
            WHERE token = ?
        ''', (status, token))
    conn.commit()
    conn.close()

def get_all_patients():
    """Get all patients from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM patients ORDER BY id DESC LIMIT 50')
    patients = cursor.fetchall()
    conn.close()
    return patients

def get_waiting_patients():
    """Get all waiting patients"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM patients WHERE status = "waiting" ORDER BY id ASC')
    patients = cursor.fetchall()
    conn.close()
    return patients

def get_completed_patients():
    """Get all completed patients"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM patients WHERE status = "completed" ORDER BY id DESC')
    patients = cursor.fetchall()
    conn.close()
    return patients

def add_user(username, password, role='staff'):
    """Add a new user"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO users (username, password, role)
            VALUES (?, ?, ?)
        ''', (username, password, role))
        conn.commit()
        print(f"✅ User {username} added successfully!")
        return True
    except sqlite3.IntegrityError:
        print(f"❌ User {username} already exists!")
        return False
    finally:
        conn.close()

def verify_user(username, password):
    """Verify user credentials"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM users 
        WHERE username = ? AND password = ?
    ''', (username, password))
    user = cursor.fetchone()
    conn.close()
    return user is not None

def get_statistics():
    """Get statistics from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get total patients
    cursor.execute('SELECT COUNT(*) FROM patients')
    total = cursor.fetchone()[0]
    
    # Get average wait time
    cursor.execute('SELECT AVG(wait_time) FROM patients WHERE wait_time IS NOT NULL')
    avg_wait = cursor.fetchone()[0]
    
    # Get patients by priority
    cursor.execute('''
        SELECT priority, COUNT(*) 
        FROM patients 
        GROUP BY priority
    ''')
    priority_stats = cursor.fetchall()
    
    conn.close()
    
    return {
        'total_patients': total,
        'average_wait_time': round(avg_wait, 1) if avg_wait else 0,
        'priority_breakdown': dict(priority_stats)
    }

def export_to_csv():
    """Export all patients to CSV format"""
    import csv
    from io import StringIO
    
    patients = get_all_patients()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['ID', 'Token', 'Name', 'Priority', 'Arrival Time', 'Wait Time (min)', 'Status'])
    
    # Write data
    for patient in patients:
        writer.writerow([
            patient[0], patient[1], patient[2], patient[3], 
            patient[4], patient[5] if patient[5] else 'N/A', patient[6]
        ])
    
    return output.getvalue()

def clear_all_patients():
    """Clear all patients from database (for testing)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM patients')
    conn.commit()
    conn.close()
    print("✅ All patients cleared from database")

# Initialize database when script is run directly
if __name__ == '__main__':
    init_db()
    # Add default users
    add_user('admin', 'admin123', 'admin')
    add_user('doctor', 'doctor123', 'doctor')
    add_user('staff', 'staff123', 'staff')
    
    print("\n" + "="*50)
    print("📊 DATABASE SETUP COMPLETE!")
    print("="*50)
    print("Default users:")
    print("  👤 Username: admin, Password: admin123 (Admin)")
    print("  👤 Username: doctor, Password: doctor123 (Doctor)")
    print("  👤 Username: staff, Password: staff123 (Staff)")
    print("="*50)
    
    # Show some stats
    stats = get_statistics()
    print(f"\n📈 Current Statistics:")
    print(f"   Total patients: {stats['total_patients']}")
    print(f"   Average wait time: {stats['average_wait_time']} minutes")