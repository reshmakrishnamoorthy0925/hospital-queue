class BedManager:
    def __init__(self):
        self.beds = {
            'ICU': [
                {'id': 1, 'status': 'available', 'patient': None},
                {'id': 2, 'status': 'available', 'patient': None},
                {'id': 3, 'status': 'available', 'patient': None},
                {'id': 4, 'status': 'cleaning', 'patient': None},
                {'id': 5, 'status': 'available', 'patient': None}
            ],
            'General': [
                {'id': 1, 'status': 'available', 'patient': None},
                {'id': 2, 'status': 'available', 'patient': None},
                {'id': 3, 'status': 'available', 'patient': None},
                {'id': 4, 'status': 'available', 'patient': None},
                {'id': 5, 'status': 'cleaning', 'patient': None}
            ],
            'Private': [
                {'id': 1, 'status': 'available', 'patient': None},
                {'id': 2, 'status': 'available', 'patient': None},
                {'id': 3, 'status': 'available', 'patient': None}
            ]
        }
    
    def get_all_beds(self):
        """Get all beds with status"""
        return self.beds
    
    def get_available_beds(self):
        """Get count of available beds by ward"""
        available = {}
        for ward, beds in self.beds.items():
            available[ward] = len([b for b in beds if b['status'] == 'available'])
        return available
    
    def assign_bed(self, ward_type, patient_name):
        """Assign a bed to a patient"""
        if ward_type not in self.beds:
            return {'success': False, 'message': 'Invalid ward type'}
        
        for bed in self.beds[ward_type]:
            if bed['status'] == 'available':
                bed['status'] = 'occupied'
                bed['patient'] = patient_name
                return {
                    'success': True, 
                    'ward': ward_type, 
                    'bed_id': bed['id'],
                    'message': f'Bed assigned in {ward_type} Ward'
                }
        
        return {'success': False, 'message': f'No beds available in {ward_type} Ward'}
    
    def discharge_patient(self, ward_type, bed_id):
        """Discharge patient and free up bed"""
        for bed in self.beds[ward_type]:
            if bed['id'] == bed_id:
                bed['status'] = 'cleaning'
                bed['patient'] = None
                return {'success': True, 'message': 'Patient discharged, bed under cleaning'}
        return {'success': False, 'message': 'Bed not found'}
    
    def mark_bed_clean(self, ward_type, bed_id):
        """Mark bed as available after cleaning"""
        for bed in self.beds[ward_type]:
            if bed['id'] == bed_id and bed['status'] == 'cleaning':
                bed['status'] = 'available'
                return {'success': True, 'message': 'Bed is now available'}
        return {'success': False, 'message': 'Bed not found or not under cleaning'}