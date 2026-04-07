from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime, timedelta
import heapq
import hashlib
from collections import deque
from bed_manager import BedManager
from inventory_manager import InventoryManager
from functools import wraps
from database import save_patient, get_statistics, init_db, export_to_csv, get_all_patients
import json
import os
from flask_socketio import SocketIO
import eventlet
eventlet.monkey_patch()
app = Flask(__name__)
app.secret_key = 'hospital_management_system_secret_key_2024'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# Initialize managers
bed_manager = BedManager()
inventory_manager = InventoryManager()
init_db()

# ========== USER CLASSES ==========

class Patient:
    def __init__(self, id, name, priority, token_no, arrival_time, phone=None, age=None, symptoms=None):
        self.id = id
        self.name = name
        self.priority = priority
        self.token_no = token_no
        self.arrival_time = arrival_time
        self.start_time = None
        self.end_time = None
        self.phone = phone
        self.age = age
        self.symptoms = symptoms or []
        self.checked_in = False
        
    def get_priority_value(self):
        priorities = {'emergency': 1, 'senior': 2, 'regular': 3}
        return priorities.get(self.priority, 3)

class PriorityQueue:
    def __init__(self):
        self.heap = []
        self.counter = 0
        
    def push(self, patient):
        priority_val = patient.get_priority_value()
        heapq.heappush(self.heap, (priority_val, self.counter, patient))
        self.counter += 1
        
    def pop(self):
        if self.heap:
            return heapq.heappop(self.heap)[2]
        return None
    
    def size(self):
        return len(self.heap)
    
    def get_all(self):
        return [p[2] for p in sorted(self.heap)]
    
    def remove_by_token(self, token):
        """Remove patient by token"""
        self.heap = [p for p in self.heap if p[2].token_no != token]
        heapq.heapify(self.heap)
        return True

class AppointmentScheduler:
    def __init__(self):
        self.appointments = {}
        self.time_slots = ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00']
        
    def book_appointment(self, patient_name, date, time_slot, doctor_type='general'):
        if date not in self.appointments:
            self.appointments[date] = []
        
        # Check if slot is already booked
        if any(apt['time'] == time_slot for apt in self.appointments[date]):
            return {'success': False, 'error': 'Time slot already booked'}
        
        appointment = {
            'id': len(self.appointments[date]) + 1,
            'patient_name': patient_name,
            'date': date,
            'time': time_slot,
            'doctor_type': doctor_type,
            'status': 'scheduled',
            'booking_time': datetime.now().isoformat()
        }
        self.appointments[date].append(appointment)
        return {'success': True, 'appointment': appointment}
    
    def get_available_slots(self, date):
        booked_slots = [apt['time'] for apt in self.appointments.get(date, [])]
        available = [slot for slot in self.time_slots if slot not in booked_slots]
        return available
    
    def get_appointments_by_date(self, date):
        return self.appointments.get(date, [])

class QueueManager:
    def __init__(self):
        self.priority_queue = PriorityQueue()
        self.current_token = 0
        self.completed_patients = []
        self.doctor_available = True
        self.doctor_current_patient = None
        self.doctor_speed = 12
        self.patient_history = []
        self.wait_time_history = []
        
    def add_patient(self, name, priority, phone=None, age=None, symptoms=None):
        self.current_token += 1
        patient = Patient(
            id=self.current_token,
            name=name,
            priority=priority,
            token_no=f"T{self.current_token:04d}",
            arrival_time=datetime.now(),
            phone=phone,
            age=age,
            symptoms=symptoms
        )
        self.priority_queue.push(patient)
        
        # Calculate predicted wait time
        queue_size = self.priority_queue.size()
        priority_multiplier = {'emergency': 0.3, 'senior': 0.7, 'regular': 1.0}
        predicted_time = int(queue_size * self.doctor_speed * priority_multiplier[priority])
        predicted_time = max(2, min(60, predicted_time))
        
        # Save to database
        save_patient(patient.token_no, name, priority, datetime.now())
        
        return {
            'token': patient.token_no,
            'predicted_time': predicted_time,
            'position': queue_size,
            'patient_id': patient.id
        }
    
    def call_next_patient(self):
        if not self.doctor_available:
            return None
            
        patient = self.priority_queue.pop()
        if patient:
            patient.start_time = datetime.now()
            patient.checked_in = True
            self.doctor_current_patient = patient
            self.doctor_available = False
            return {
                'token': patient.token_no,
                'name': patient.name,
                'priority': patient.priority,
                'age': patient.age,
                'symptoms': patient.symptoms
            }
        return None
    
    def complete_current_patient(self):
        if self.doctor_current_patient:
            self.doctor_current_patient.end_time = datetime.now()
            wait_time = (self.doctor_current_patient.end_time - 
                        self.doctor_current_patient.arrival_time).total_seconds() / 60
            self.completed_patients.append(wait_time)
            self.wait_time_history.append(wait_time)
            
            # Store in history
            self.patient_history.append({
                'token': self.doctor_current_patient.token_no,
                'name': self.doctor_current_patient.name,
                'priority': self.doctor_current_patient.priority,
                'wait_time': round(wait_time, 1),
                'completion_time': self.doctor_current_patient.end_time.isoformat()
            })
            
            # Update doctor speed
            if len(self.completed_patients) > 5:
                self.doctor_speed = sum(self.completed_patients[-10:]) / min(10, len(self.completed_patients[-10:]))
            
            self.doctor_available = True
            current = self.doctor_current_patient
            self.doctor_current_patient = None
            return True
        return False
    
    def get_queue_status(self):
        queue_list = []
        for patient in self.priority_queue.get_all():
            wait_time = int((datetime.now() - patient.arrival_time).total_seconds() / 60)
            queue_list.append({
                'token': patient.token_no,
                'name': patient.name,
                'priority': patient.priority.upper(),
                'wait_time': wait_time,
                'position': queue_list.__len__() + 1 if queue_list else 1
            })
        
        return {
            'queue_size': self.priority_queue.size(),
            'queue_list': queue_list,
            'doctor_available': self.doctor_available,
            'current_patient': {
                'token': self.doctor_current_patient.token_no if self.doctor_current_patient else None,
                'name': self.doctor_current_patient.name if self.doctor_current_patient else None,
                'priority': self.doctor_current_patient.priority if self.doctor_current_patient else None
            } if self.doctor_current_patient else None,
            'doctor_speed': round(self.doctor_speed, 1),
            'last_5_wait_times': [round(w, 1) for w in self.wait_time_history[-5:]]
        }
    
    def get_statistics(self):
        avg_wait = sum(self.wait_time_history) / len(self.wait_time_history) if self.wait_time_history else 0
        return {
            'total_patients_served': len(self.completed_patients),
            'average_wait_time': round(avg_wait, 1),
            'doctor_efficiency': round(60 / self.doctor_speed, 1) if self.doctor_speed > 0 else 0,
            'current_queue': self.priority_queue.size(),
            'peak_hour': self.get_peak_hour()
        }
    
    def get_peak_hour(self):
        if not self.patient_history:
            return "No data"
        hours = {}
        for patient in self.patient_history:
            hour = datetime.fromisoformat(patient['completion_time']).hour
            hours[hour] = hours.get(hour, 0) + 1
        if hours:
            peak = max(hours, key=hours.get)
            return f"{peak}:00 - {peak+1}:00"
        return "No data"
    
    def search_patient(self, query):
        """Search patient by name or token"""
        results = []
        # Search in waiting queue
        for patient in self.priority_queue.get_all():
            if query.lower() in patient.name.lower() or query.upper() in patient.token_no:
                results.append({
                    'token': patient.token_no,
                    'name': patient.name,
                    'priority': patient.priority,
                    'status': 'Waiting',
                    'wait_time': int((datetime.now() - patient.arrival_time).total_seconds() / 60)
                })
        
        # Search in completed patients
        for patient in self.patient_history:
            if query.lower() in patient['name'].lower() or query.upper() in patient['token']:
                results.append({
                    'token': patient['token'],
                    'name': patient['name'],
                    'priority': patient['priority'],
                    'status': 'Completed',
                    'wait_time': patient['wait_time']
                })
        
        return results

# Create global instances
manager = QueueManager()
scheduler = AppointmentScheduler()

# ========== LOGIN REQUIRED DECORATOR ==========
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ========== ROUTES ==========

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Simple login for demo"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Demo credentials
        if username == 'admin' and password == 'admin123':
            session['is_authenticated'] = True
            session['username'] = username
            session['role'] = 'admin'
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials!', 'error')
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - Hospital Queue System</title>
        <style>
            body { font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
            .login-container { background: white; padding: 40px; border-radius: 10px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); width: 300px; }
            input { width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; }
            button { width: 100%; padding: 10px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; }
            .error { color: red; margin: 10px 0; }
            .success { color: green; }
        </style>
    </head>
    <body>
        <div class="login-container">
            <h2>🏥 Hospital Login</h2>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
            <p style="margin-top: 20px; font-size: 12px; color: #666;">Demo: admin / admin123</p>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('login'))

# ========== QUEUE MANAGEMENT API ==========

@app.route('/api/add_patient', methods=['POST'])
def add_patient():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    name = data.get('name', 'Anonymous')
    priority = data.get('priority', 'regular')
    phone = data.get('phone')
    age = data.get('age')
    symptoms = data.get('symptoms', '').split(',') if data.get('symptoms') else []
    
    result = manager.add_patient(name, priority, phone, age, symptoms)
    
    return jsonify({
        'success': True,
        'token': result['token'],
        'predicted_wait_time': result['predicted_time'],
        'position': result['position'],
        'message': f"Patient {name} added to queue with token {result['token']}"
    })

@app.route('/api/call_next', methods=['POST'])
def call_next():
    patient = manager.call_next_patient()
    return jsonify({
        'success': True,
        'patient': patient,
        'message': f"Calling patient {patient['name'] if patient else 'No patients in queue'}"
    })

@app.route('/api/complete_patient', methods=['POST'])
def complete_patient():
    success = manager.complete_current_patient()
    return jsonify({
        'success': success,
        'message': 'Patient consultation completed' if success else 'No active patient'
    })

@app.route('/api/queue_status', methods=['GET'])
def queue_status():
    return jsonify(manager.get_queue_status())

@app.route('/api/statistics', methods=['GET'])
def statistics():
    stats = manager.get_statistics()
    db_stats = get_statistics()
    
    return jsonify({
        'total_patients_served': stats['total_patients_served'],
        'average_wait_time': stats['average_wait_time'],
        'doctor_efficiency': stats['doctor_efficiency'],
        'current_queue': stats['current_queue'],
        'peak_hour': stats['peak_hour'],
        'database_total': db_stats['total_patients'],
        'db_avg_wait': db_stats['average_wait_time']
    })

@app.route('/api/search_patient', methods=['GET'])
def search_patient():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify({'results': [], 'message': 'Enter at least 2 characters'})
    
    results = manager.search_patient(query)
    return jsonify({'results': results, 'count': len(results)})

@app.route('/api/export', methods=['GET'])
def export_data():
    csv_data = export_to_csv()
    return jsonify({
        'success': True,
        'data': csv_data,
        'filename': f'hospital_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    })

@app.route('/api/all_patients', methods=['GET'])
def all_patients():
    patients = get_all_patients()
    patient_list = []
    for patient in patients:
        patient_list.append({
            'id': patient[0],
            'token': patient[1],
            'name': patient[2],
            'priority': patient[3],
            'arrival_time': patient[4],
            'wait_time': patient[5],
            'status': patient[6]
        })
    return jsonify(patient_list)

# ========== APPOINTMENT MANAGEMENT ==========

@app.route('/api/book_appointment', methods=['POST'])
def book_appointment():
    data = request.json
    result = scheduler.book_appointment(
        data['patient_name'],
        data['date'],
        data['time_slot'],
        data.get('doctor_type', 'general')
    )
    return jsonify(result)

@app.route('/api/available_slots', methods=['GET'])
def available_slots():
    date = request.args.get('date')
    if not date:
        return jsonify({'error': 'Date required'}), 400
    
    available = scheduler.get_available_slots(date)
    return jsonify({
        'date': date,
        'available_slots': available,
        'all_slots': scheduler.time_slots
    })

@app.route('/api/appointments', methods=['GET'])
def get_appointments():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    appointments = scheduler.get_appointments_by_date(date)
    return jsonify({
        'date': date,
        'appointments': appointments,
        'count': len(appointments)
    })

# ========== BED MANAGEMENT API ==========

@app.route('/api/beds', methods=['GET'])
def get_beds():
    return jsonify(bed_manager.get_all_beds())

@app.route('/api/available_beds', methods=['GET'])
def get_available_beds():
    return jsonify(bed_manager.get_available_beds())

@app.route('/api/assign_bed', methods=['POST'])
def assign_bed():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    result = bed_manager.assign_bed(data['ward_type'], data['patient_name'])
    return jsonify(result)

@app.route('/api/discharge_patient', methods=['POST'])
def discharge_patient():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    result = bed_manager.discharge_patient(data['ward_type'], data['bed_id'])
    return jsonify(result)

@app.route('/api/bed_statistics', methods=['GET'])
def bed_statistics():
    all_beds = bed_manager.get_all_beds()
    total = len(all_beds)
    occupied = sum(1 for bed in all_beds if bed['status'] == 'occupied')
    
    return jsonify({
        'total_beds': total,
        'occupied_beds': occupied,
        'available_beds': total - occupied,
        'occupancy_rate': round((occupied / total) * 100, 1) if total > 0 else 0
    })

# ========== INVENTORY MANAGEMENT API ==========

@app.route('/api/medicines', methods=['GET'])
def get_medicines():
    return jsonify(inventory_manager.get_all_medicines())

@app.route('/api/low_stock_alerts', methods=['GET'])
def low_stock_alerts():
    return jsonify(inventory_manager.get_low_stock_alerts())

@app.route('/api/expiry_alerts', methods=['GET'])
def expiry_alerts():
    return jsonify(inventory_manager.get_expiry_alerts())

@app.route('/api/dispense_medicine', methods=['POST'])
def dispense_medicine():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    result = inventory_manager.dispense_medicine(
        data['medicine_name'], 
        int(data['quantity']), 
        data['patient_name']
    )
    return jsonify(result)

@app.route('/api/restock_medicine', methods=['POST'])
def restock_medicine():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    result = inventory_manager.restock_medicine(data['medicine_name'], int(data['quantity']))
    return jsonify(result)

@app.route('/api/inventory_summary', methods=['GET'])
def inventory_summary():
    medicines = inventory_manager.get_all_medicines()
    low_stock = [m for m in medicines if m['stock'] < m['threshold']]
    expiring_soon = inventory_manager.get_expiry_alerts()
    
    return jsonify({
        'total_medicines': len(medicines),
        'low_stock_count': len(low_stock),
        'expiring_soon_count': len(expiring_soon),
        'total_value': sum(m['price'] * m['stock'] for m in medicines)
    })

# ========== DASHBOARD API ==========

@app.route('/api/dashboard_summary', methods=['GET'])
def dashboard_summary():
    """Combined dashboard data"""
    queue_status = manager.get_queue_status()
    stats = manager.get_statistics()
    bed_stats = bed_statistics()
    inventory_summary_data = inventory_summary()
    
    return jsonify({
        'queue': {
            'size': queue_status['queue_size'],
            'current_patient': queue_status['current_patient'],
            'doctor_available': queue_status['doctor_available']
        },
        'statistics': stats,
        'beds': bed_stats,
        'inventory': inventory_summary_data,
        'timestamp': datetime.now().isoformat()
    })

# ========== HELPER ROUTES ==========

@app.route('/show-routes')
def show_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(str(rule))
    return {'routes': routes, 'total': len(routes)}
@app.route('/healthz')
def health():
    return 'OK', 200

@app.route('/test')
def test():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Hospital Queue Management System</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; margin-bottom: 10px; }
            .subtitle { color: #666; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
            .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .card h3 { margin-bottom: 15px; color: #667eea; }
            .input-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; color: #333; font-weight: 500; }
            input, select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
            button { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 14px; margin: 5px; transition: transform 0.2s; }
            button:hover { transform: translateY(-2px); background: #5a67d8; }
            .queue-item { background: #f7f7f7; padding: 10px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #667eea; }
            .emergency { border-left-color: red; }
            .senior { border-left-color: orange; }
            .regular { border-left-color: green; }
            .status { padding: 10px; border-radius: 5px; margin-top: 10px; }
            .available { background: #d4edda; color: #155724; }
            .busy { background: #f8d7da; color: #721c24; }
            pre { background: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; font-size: 12px; margin-top: 10px; }
            .stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 10px; }
            .stat-box { background: #f0f0f0; padding: 10px; border-radius: 5px; text-align: center; }
            .stat-value { font-size: 24px; font-weight: bold; color: #667eea; }
            .stat-label { font-size: 12px; color: #666; margin-top: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🏥 Hospital Queue Management System</h1>
                <p class="subtitle">Complete Hospital Management Dashboard</p>
            </div>
            
            <div class="grid">
                <!-- Add Patient Card -->
                <div class="card">
                    <h3>➕ Add New Patient</h3>
                    <div class="input-group">
                        <label>Patient Name</label>
                        <input type="text" id="patientName" placeholder="Enter patient name">
                    </div>
                    <div class="input-group">
                        <label>Priority</label>
                        <select id="priority">
                            <option value="regular">Regular</option>
                            <option value="senior">Senior Citizen</option>
                            <option value="emergency">Emergency</option>
                        </select>
                    </div>
                    <div class="input-group">
                        <label>Phone (Optional)</label>
                        <input type="tel" id="phone" placeholder="Phone number">
                    </div>
                    <button onclick="addPatient()">Add to Queue</button>
                    <div id="addResult"></div>
                </div>
                
                <!-- Queue Status Card -->
                <div class="card">
                    <h3>📋 Current Queue</h3>
                    <div id="queueList">Loading...</div>
                    <button onclick="refreshQueue()">🔄 Refresh Queue</button>
                </div>
                
                <!-- Doctor Actions Card -->
                <div class="card">
                    <h3>👨‍⚕️ Doctor Panel</h3>
                    <div id="doctorStatus">Loading...</div>
                    <button onclick="callNextPatient()">📢 Call Next Patient</button>
                    <button onclick="completePatient()">✅ Complete Current Patient</button>
                    <div id="callResult"></div>
                </div>
                
                <!-- Statistics Card -->
                <div class="card">
                    <h3>📊 Statistics</h3>
                    <div id="stats">Loading...</div>
                    <button onclick="refreshStats()">🔄 Refresh Stats</button>
                </div>
            </div>
            
            <!-- Search Card -->
            <div class="card">
                <h3>🔍 Search Patient</h3>
                <div class="input-group">
                    <input type="text" id="searchQuery" placeholder="Enter name or token (e.g., John or T0001)" onkeyup="searchPatient()">
                </div>
                <div id="searchResults"></div>
            </div>
        </div>
        
        <script>
            async function addPatient() {
                const name = document.getElementById('patientName').value;
                const priority = document.getElementById('priority').value;
                const phone = document.getElementById('phone').value;
                
                if (!name) {
                    alert('Please enter patient name');
                    return;
                }
                
                const response = await fetch('/api/add_patient', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name, priority, phone})
                });
                const data = await response.json();
                
                document.getElementById('addResult').innerHTML = `
                    <div class="status available" style="margin-top: 10px;">
                        ✅ ${data.message}<br>
                        📍 Position: ${data.position}<br>
                        ⏱️ Est. Wait: ${data.predicted_wait_time} minutes
                    </div>
                `;
                document.getElementById('patientName').value = '';
                refreshQueue();
                refreshStats();
            }
            
            async function refreshQueue() {
                const response = await fetch('/api/queue_status');
                const data = await response.json();
                
                let queueHtml = `<div class="stats-grid">
                    <div class="stat-box">
                        <div class="stat-value">${data.queue_size}</div>
                        <div class="stat-label">In Queue</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-value">${data.doctor_speed}</div>
                        <div class="stat-label">Avg Consult (min)</div>
                    </div>
                </div>`;
                
                if (data.queue_list && data.queue_list.length > 0) {
                    queueHtml += '<h4>Waiting Patients:</h4>';
                    data.queue_list.forEach(patient => {
                        queueHtml += `<div class="queue-item ${patient.priority.toLowerCase()}">
                            <strong>${patient.token}</strong> - ${patient.name}<br>
                            Priority: ${patient.priority} | Wait: ${patient.wait_time} min
                        </div>`;
                    });
                } else {
                    queueHtml += '<p>No patients in queue</p>';
                }
                
                document.getElementById('queueList').innerHTML = queueHtml;
                
                // Update doctor status
                const doctorStatus = document.getElementById('doctorStatus');
                if (data.current_patient && data.current_patient.name) {
                    doctorStatus.innerHTML = `
                        <div class="status busy">
                            🔴 Currently Serving: ${data.current_patient.name} (${data.current_patient.token})<br>
                            Priority: ${data.current_patient.priority}
                        </div>
                    `;
                } else {
                    doctorStatus.innerHTML = `<div class="status available">🟢 Doctor Available</div>`;
                }
            }
            
            async function callNextPatient() {
                const response = await fetch('/api/call_next', {method: 'POST'});
                const data = await response.json();
                
                if (data.patient) {
                    document.getElementById('callResult').innerHTML = `
                        <div class="status available" style="margin-top: 10px;">
                            📢 Called: ${data.patient.name} (${data.patient.token})
                        </div>
                    `;
                    refreshQueue();
                } else {
                    document.getElementById('callResult').innerHTML = `
                        <div class="status busy" style="margin-top: 10px;">
                            No patients in queue!
                        </div>
                    `;
                }
            }
            
            async function completePatient() {
                const response = await fetch('/api/complete_patient', {method: 'POST'});
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('callResult').innerHTML = `
                        <div class="status available" style="margin-top: 10px;">
                            ✅ Patient consultation completed
                        </div>
                    `;
                    refreshQueue();
                    refreshStats();
                }
            }
            
            async function refreshStats() {
                const response = await fetch('/api/statistics');
                const data = await response.json();
                
                document.getElementById('stats').innerHTML = `
                    <div class="stats-grid">
                        <div class="stat-box">
                            <div class="stat-value">${data.total_patients_served}</div>
                            <div class="stat-label">Patients Served</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-value">${data.average_wait_time}</div>
                            <div class="stat-label">Avg Wait (min)</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-value">${data.doctor_efficiency}</div>
                            <div class="stat-label">Patients/Hour</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-value">${data.current_queue}</div>
                            <div class="stat-label">In Queue</div>
                        </div>
                    </div>
                    <div class="stat-box" style="margin-top: 10px;">
                        <div class="stat-value">${data.peak_hour}</div>
                        <div class="stat-label">Peak Hour</div>
                    </div>
                `;
            }
            
            async function searchPatient() {
                const query = document.getElementById('searchQuery').value;
                if (query.length < 2) {
                    document.getElementById('searchResults').innerHTML = '';
                    return;
                }
                
                const response = await fetch(`/api/search_patient?q=${encodeURIComponent(query)}`);
                const data = await response.json();
                
                if (data.results && data.results.length > 0) {
                    let html = '<h4>Search Results:</h4>';
                    data.results.forEach(patient => {
                        html += `<div class="queue-item">
                            <strong>${patient.token}</strong> - ${patient.name}<br>
                            Priority: ${patient.priority} | Status: ${patient.status} | Wait: ${patient.wait_time} min
                        </div>`;
                    });
                    document.getElementById('searchResults').innerHTML = html;
                } else {
                    document.getElementById('searchResults').innerHTML = '<p>No patients found</p>';
                }
            }
            
            // Auto-refresh every 10 seconds
            setInterval(() => {
                refreshQueue();
                refreshStats();
            }, 10000);
            
            // Initial load
            refreshQueue();
            refreshStats();
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    print("=" * 60)
    print("🏥 HOSPITAL QUEUE MANAGEMENT SYSTEM")
    print("=" * 60)
    
    print("\n📋 Registered API Endpoints:")
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith('/api'):
            methods = ','.join(rule.methods - {'HEAD', 'OPTIONS'})
            print(f"   {methods:10} {rule.rule}")
    
    print("\n✅ Server is running!")
    print("📍 Main Dashboard: http://127.0.0.1:5000/test")
    print("📍 Login: http://127.0.0.1:5000/login")
    print("📍 API Routes: http://127.0.0.1:5000/show-routes")
    print("\n🔐 Demo Credentials:")
    print("   Username: admin")
    print("   Password: admin123")
    print("\n💡 Features Included:")
    print("   ✓ Patient Queue Management")
    print("   ✓ Priority-based Queue (Emergency > Senior > Regular)")
    print("   ✓ Real-time Dashboard")
    print("   ✓ Patient Search")
    print("   ✓ Statistics & Analytics")
    print("   ✓ Bed Management API")
    print("   ✓ Inventory Management API")
    print("   ✓ Appointment Scheduling API")
    print("\n" + "=" * 60)
    
    app.run(debug=True, port=5000,host="0.0.0.0", use_reloader=False)
