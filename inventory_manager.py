from datetime import datetime, timedelta

class InventoryManager:
    def __init__(self):
        self.medicines = {
            'Paracetamol': {
                'quantity': 500, 
                'threshold': 50, 
                'expiry': (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d'),
                'unit_price': 5.0
            },
            'Amoxicillin': {
                'quantity': 300, 
                'threshold': 30, 
                'expiry': (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d'),
                'unit_price': 12.0
            },
            'Insulin': {
                'quantity': 100, 
                'threshold': 20, 
                'expiry': (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
                'unit_price': 45.0
            },
            'Aspirin': {
                'quantity': 1000, 
                'threshold': 100, 
                'expiry': (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d'),
                'unit_price': 2.5
            },
            'Cough Syrup': {
                'quantity': 150, 
                'threshold': 40, 
                'expiry': (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d'),
                'unit_price': 8.0
            }
        }
        self.usage_history = []
    
    def get_all_medicines(self):
        """Get all medicines with details"""
        return self.medicines
    
    def get_low_stock_alerts(self):
        """Get medicines with low stock"""
        low_stock = []
        for medicine, details in self.medicines.items():
            if details['quantity'] <= details['threshold']:
                low_stock.append({
                    'name': medicine,
                    'current': details['quantity'],
                    'threshold': details['threshold']
                })
        return low_stock
    
    def get_expiry_alerts(self):
        """Get medicines expiring soon (within 30 days)"""
        expiring = []
        today = datetime.now().date()
        
        for medicine, details in self.medicines.items():
            expiry_date = datetime.strptime(details['expiry'], '%Y-%m-%d').date()
            days_left = (expiry_date - today).days
            
            if days_left <= 30:
                expiring.append({
                    'name': medicine,
                    'expiry_date': details['expiry'],
                    'days_left': days_left,
                    'quantity': details['quantity']
                })
        return expiring
    
    def dispense_medicine(self, medicine_name, quantity, patient_name):
        """Dispense medicine to patient"""
        if medicine_name not in self.medicines:
            return {'success': False, 'message': 'Medicine not found'}
        
        if self.medicines[medicine_name]['quantity'] < quantity:
            return {'success': False, 'message': 'Insufficient stock'}
        
        self.medicines[medicine_name]['quantity'] -= quantity
        
        # Record usage
        self.usage_history.append({
            'medicine': medicine_name,
            'quantity': quantity,
            'patient': patient_name,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        return {
            'success': True, 
            'message': f'Dispensed {quantity} units of {medicine_name}',
            'remaining': self.medicines[medicine_name]['quantity']
        }
    
    def restock_medicine(self, medicine_name, quantity):
        """Add stock to medicine"""
        if medicine_name not in self.medicines:
            return {'success': False, 'message': 'Medicine not found'}
        
        self.medicines[medicine_name]['quantity'] += quantity
        return {
            'success': True,
            'message': f'Added {quantity} units of {medicine_name}',
            'new_quantity': self.medicines[medicine_name]['quantity']
        }
    
    def get_usage_statistics(self):
        """Get medicine usage statistics"""
        stats = {}
        for record in self.usage_history[-50:]:  # Last 50 records
            med = record['medicine']
            if med not in stats:
                stats[med] = 0
            stats[med] += record['quantity']
        return stats