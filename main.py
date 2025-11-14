from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
import csv
from datetime import datetime
from functools import wraps
from io import StringIO, BytesIO

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')

DATA_FILE = 'data.json'
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    raise ValueError("ADMIN_PASSWORD environment variable must be set. Please configure this secret before starting the application.")
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)
CHURCH_NAME = 'ETOTC'
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 
          'July', 'August', 'September', 'October', 'November', 'December']
MINIMUM_MONTHLY_PAYMENT = 30

def load_data():
    """Load data from JSON file with error handling"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return initialize_data()
                if 'members' not in data:
                    data['members'] = []
                if 'next_member_id' not in data:
                    data['next_member_id'] = 1
                if 'next_receipt_number' not in data:
                    data['next_receipt_number'] = 1
                return data
        except (json.JSONDecodeError, IOError) as e:
            flash(f'Error loading data file: {str(e)}. Starting with empty data.', 'warning')
            return initialize_data()
    return initialize_data()

def initialize_data():
    """Initialize empty data structure"""
    return {
        'members': [],
        'next_member_id': 1,
        'next_receipt_number': 1
    }

def save_data(data):
    """Save data to JSON file with error handling"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        flash(f'Error saving data: {str(e)}', 'danger')
        raise

def generate_member_id(data):
    """Generate next member ID in format CH001, CH002, etc."""
    next_id = data.get('next_member_id', 1)
    member_id = f"CH{next_id:03d}"
    data['next_member_id'] = next_id + 1
    return member_id

def generate_receipt_number(data):
    """Generate receipt number in format RCPT-YYYY-NNNN"""
    current_year = datetime.now().year
    next_num = data.get('next_receipt_number', 1)
    receipt = f"RCPT-{current_year}-{next_num:04d}"
    data['next_receipt_number'] = next_num + 1
    return receipt

def initialize_year_contributions(year):
    """Initialize 12 months of unpaid contributions for a year"""
    contributions = {}
    for month in MONTHS:
        contributions[month] = {
            'status': 'Unpaid',
            'amount': 0,
            'date': '',
            'receipt': ''
        }
    return contributions

def admin_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Please log in as admin to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def member_required(f):
    """Decorator to require member login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('member_id'):
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('member_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    """Landing page"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['is_admin'] = True
            session['username'] = username
            flash('Successfully logged in as admin!', 'success')
            return redirect(url_for('admin_home'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')
    
    return render_template('login.html')

@app.route('/member-login', methods=['GET', 'POST'])
def member_login():
    """Member login with ID and password"""
    if request.method == 'POST':
        member_id = request.form.get('member_id', '').strip().upper()
        password = request.form.get('password')
        
        data = load_data()
        member = next((m for m in data['members'] if m['id'] == member_id), None)
        
        if member and check_password_hash(member.get('password_hash', ''), password):
            session['member_id'] = member_id
            session['member_name'] = member['name']
            flash(f'Welcome, {member["name"]}!', 'success')
            return redirect(url_for('member_dashboard'))
        else:
            flash('Invalid Member ID or Password. Please try again.', 'danger')
    
    return render_template('member_login.html')

@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/admin/home')
@admin_required
def admin_home():
    """Admin home page with member list"""
    data = load_data()
    return render_template('admin_home.html', members=data['members'])

@app.route('/admin/add-member', methods=['GET', 'POST'])
@admin_required
def add_member():
    """Add new member with auto-generated ID"""
    data = load_data()
    
    if request.method == 'POST':
        try:
            # Get form data
            custom_id = request.form.get('custom_id', '').strip().upper()
            first_name = request.form.get('first_name', '').strip()
            middle_name = request.form.get('middle_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '').strip()
            monthly_payment = request.form.get('monthly_payment', '').strip()
            
            # Combine name parts
            name_parts = [first_name, middle_name, last_name] if middle_name else [first_name, last_name]
            name = ' '.join(name_parts)
            
            # Validation
            if not all([first_name, last_name, phone, email, password, monthly_payment]):
                flash('All required fields must be filled.', 'danger')
                return render_template('add_member.html', suggested_id=generate_member_id(data))
            
            try:
                monthly_amount = float(monthly_payment)
                if monthly_amount < MINIMUM_MONTHLY_PAYMENT:
                    flash(f'Monthly payment must be at least ${MINIMUM_MONTHLY_PAYMENT}.', 'danger')
                    return render_template('add_member.html', suggested_id=generate_member_id(data))
            except ValueError:
                flash('Monthly payment must be a valid number.', 'danger')
                return render_template('add_member.html', suggested_id=generate_member_id(data))
            
            # Generate or use custom ID
            if custom_id:
                if any(m['id'] == custom_id for m in data['members']):
                    flash('This Member ID already exists. Please use a different ID.', 'danger')
                    return render_template('add_member.html', suggested_id=generate_member_id(data))
                member_id = custom_id
            else:
                member_id = generate_member_id(data)
            
            # Create member
            current_year = str(datetime.now().year)
            new_member = {
                'id': member_id,
                'name': name,
                'email': email,
                'phone': phone,
                'password_hash': generate_password_hash(password),
                'monthly_payment': monthly_amount,
                'contributions': {
                    current_year: initialize_year_contributions(current_year)
                },
                'donations': [],
                'transactions': []
            }
            
            data['members'].append(new_member)
            save_data(data)
            
            flash(f'Member {name} added successfully with ID {member_id}!', 'success')
            return redirect(url_for('admin_home'))
            
        except Exception as e:
            flash(f'Error adding member: {str(e)}', 'danger')
            return render_template('add_member.html', suggested_id=generate_member_id(data))
    
    suggested_id = generate_member_id(data)
    return render_template('add_member.html', suggested_id=suggested_id)

@app.route('/admin/edit-member/<member_id>', methods=['GET', 'POST'])
@admin_required
def edit_member(member_id):
    """Edit member information"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    if request.method == 'POST':
        try:
            new_id = request.form.get('member_id', '').strip().upper()
            name = request.form.get('name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            monthly_payment = request.form.get('monthly_payment', '').strip()
            
            if not all([new_id, name, phone, email, monthly_payment]):
                flash('All fields are required.', 'danger')
                return render_template('edit_member.html', member=member)
            
            # Check if ID is being changed and if new ID already exists
            if new_id != member_id and any(m['id'] == new_id for m in data['members']):
                flash('This Member ID already exists. Please use a different ID.', 'danger')
                return render_template('edit_member.html', member=member)
            
            try:
                monthly_amount = float(monthly_payment)
                if monthly_amount < MINIMUM_MONTHLY_PAYMENT:
                    flash(f'Monthly payment must be at least ${MINIMUM_MONTHLY_PAYMENT}.', 'danger')
                    return render_template('edit_member.html', member=member)
            except ValueError:
                flash('Monthly payment must be a valid number.', 'danger')
                return render_template('edit_member.html', member=member)
            
            member['id'] = new_id
            member['name'] = name
            member['phone'] = phone
            member['email'] = email
            member['monthly_payment'] = monthly_amount
            
            save_data(data)
            flash(f'Member information updated successfully!', 'success')
            return redirect(url_for('admin_home'))
            
        except Exception as e:
            flash(f'Error updating member: {str(e)}', 'danger')
            return render_template('edit_member.html', member=member)
    
    return render_template('edit_member.html', member=member)

@app.route('/admin/delete-member/<member_id>')
@admin_required
def delete_member(member_id):
    """Delete member"""
    data = load_data()
    data['members'] = [m for m in data['members'] if m['id'] != member_id]
    save_data(data)
    flash('Member deleted successfully!', 'success')
    return redirect(url_for('admin_home'))

@app.route('/admin/member-details/<member_id>')
@admin_required
def member_details(member_id):
    """View member details with 12-month breakdown"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    current_year = str(datetime.now().year)
    selected_year = request.args.get('year', current_year)
    
    # Ensure year exists
    if selected_year not in member['contributions']:
        member['contributions'][selected_year] = initialize_year_contributions(selected_year)
        save_data(data)
    
    contributions = member['contributions'][selected_year]
    available_years = sorted(member['contributions'].keys(), reverse=True)
    
    # Calculate stats
    paid_months = sum(1 for month in MONTHS if contributions[month]['status'] == 'Paid')
    total_paid = sum(contributions[month]['amount'] for month in MONTHS if contributions[month]['status'] == 'Paid')
    
    return render_template('member_details.html', 
                         member=member,
                         contributions=contributions,
                         months=MONTHS,
                         selected_year=selected_year,
                         available_years=available_years,
                         paid_months=paid_months,
                         total_paid=total_paid)

@app.route('/admin/donations')
@admin_required
def admin_donations():
    """Admin donations dashboard"""
    data = load_data()
    
    # Collect all donations from all members
    all_donations = []
    for member in data['members']:
        for donation in member.get('donations', []):
            all_donations.append({
                **donation,
                'member_name': member['name'],
                'member_id': member['id']
            })
    
    # Sort by date (newest first)
    all_donations.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate total
    total_donations = sum(d['amount'] for d in all_donations)
    
    return render_template('admin_donations.html', 
                         donations=all_donations,
                         total_donations=total_donations)

@app.route('/admin/export-csv/<export_type>')
@admin_required
def export_csv(export_type):
    """Export data to CSV"""
    data = load_data()
    
    output = StringIO()
    
    if export_type == 'members':
        writer = csv.writer(output)
        writer.writerow(['Member ID', 'Name', 'Email', 'Phone', 'Monthly Payment'])
        
        for member in data['members']:
            writer.writerow([
                member['id'],
                member['name'],
                member['email'],
                member['phone'],
                f"${member['monthly_payment']:.2f}"
            ])
        
        filename = f'members_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
    elif export_type == 'contributions':
        writer = csv.writer(output)
        writer.writerow(['Member ID', 'Member Name', 'Year', 'Month', 'Status', 'Amount', 'Date', 'Receipt'])
        
        for member in data['members']:
            for year, year_data in member.get('contributions', {}).items():
                for month in MONTHS:
                    if month in year_data:
                        contrib = year_data[month]
                        writer.writerow([
                            member['id'],
                            member['name'],
                            year,
                            month,
                            contrib['status'],
                            f"${contrib['amount']:.2f}" if contrib['amount'] > 0 else '$0.00',
                            contrib['date'],
                            contrib['receipt']
                        ])
        
        filename = f'contributions_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
    elif export_type == 'donations':
        writer = csv.writer(output)
        writer.writerow(['Member ID', 'Member Name', 'Date', 'Amount', 'Reason', 'Receipt'])
        
        for member in data['members']:
            for donation in member.get('donations', []):
                writer.writerow([
                    member['id'],
                    member['name'],
                    donation['date'],
                    f"${donation['amount']:.2f}",
                    donation['reason'],
                    donation['receipt']
                ])
        
        filename = f'donations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    else:
        flash('Invalid export type.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    
    return response

@app.route('/member/dashboard')
@member_required
def member_dashboard():
    """Member dashboard with 12-month view"""
    data = load_data()
    member_id = session.get('member_id')
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        session.clear()
        flash('Member account not found.', 'danger')
        return redirect(url_for('member_login'))
    
    current_year = str(datetime.now().year)
    selected_year = request.args.get('year', current_year)
    
    # Ensure year exists
    if selected_year not in member['contributions']:
        member['contributions'][selected_year] = initialize_year_contributions(selected_year)
        save_data(data)
    
    contributions = member['contributions'][selected_year]
    available_years = sorted(member['contributions'].keys(), reverse=True)
    
    # Find next unpaid month
    next_unpaid_month = None
    for month in MONTHS:
        if contributions[month]['status'] == 'Unpaid':
            next_unpaid_month = month
            break
    
    # Calculate stats
    paid_months = sum(1 for month in MONTHS if contributions[month]['status'] == 'Paid')
    total_paid = sum(contributions[month]['amount'] for month in MONTHS if contributions[month]['status'] == 'Paid')
    
    return render_template('member_dashboard.html',
                         member=member,
                         contributions=contributions,
                         months=MONTHS,
                         selected_year=selected_year,
                         available_years=available_years,
                         next_unpaid_month=next_unpaid_month,
                         paid_months=paid_months,
                         total_paid=total_paid,
                         current_year=current_year)

@app.route('/member/pay-month/<year>/<month>', methods=['POST'])
@member_required
def pay_month(year, month):
    """Process monthly payment"""
    data = load_data()
    member_id = session.get('member_id')
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('member_dashboard'))
    
    # Validate month
    if month not in MONTHS:
        flash('Invalid month.', 'danger')
        return redirect(url_for('member_dashboard'))
    
    # Ensure year exists
    if year not in member['contributions']:
        member['contributions'][year] = initialize_year_contributions(year)
    
    contributions = member['contributions'][year]
    
    # Check if already paid
    if contributions[month]['status'] == 'Paid':
        flash('This month has already been paid.', 'warning')
        return redirect(url_for('member_dashboard', year=year))
    
    # Check if previous months are paid (for current year)
    if year == str(datetime.now().year):
        month_index = MONTHS.index(month)
        for i in range(month_index):
            if contributions[MONTHS[i]]['status'] == 'Unpaid':
                flash(f'Please pay {MONTHS[i]} first. Payments must be made in order.', 'warning')
                return redirect(url_for('member_dashboard', year=year))
    
    # Process payment
    receipt_number = generate_receipt_number(data)
    payment_date = datetime.now().strftime('%Y-%m-%d')
    
    contributions[month] = {
        'status': 'Paid',
        'amount': member['monthly_payment'],
        'date': payment_date,
        'receipt': receipt_number
    }
    
    # Add to transactions
    transaction = {
        'type': 'contribution',
        'month': month,
        'amount': member['monthly_payment'],
        'date': payment_date,
        'receipt': receipt_number
    }
    member['transactions'].append(transaction)
    
    save_data(data)
    
    # Show receipt
    flash(f'Payment successful! Receipt: {receipt_number}', 'success')
    return render_template('payment_confirmation.html',
                         member=member,
                         transaction_type='Monthly Contribution',
                         month=month,
                         amount=member['monthly_payment'],
                         date=payment_date,
                         receipt=receipt_number)

@app.route('/member/donate', methods=['GET', 'POST'])
@member_required
def make_donation():
    """Make a donation"""
    data = load_data()
    member_id = session.get('member_id')
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('member_dashboard'))
    
    if request.method == 'POST':
        try:
            amount_str = request.form.get('amount', '').strip()
            reason = request.form.get('reason', '').strip()
            confirm_no_reason = request.form.get('confirm_no_reason', '')
            
            if not amount_str:
                flash('Amount is required.', 'danger')
                return render_template('donate.html', member=member)
            
            try:
                amount = float(amount_str)
                if amount <= 0:
                    flash('Amount must be greater than zero.', 'danger')
                    return render_template('donate.html', member=member)
            except ValueError:
                flash('Amount must be a valid number.', 'danger')
                return render_template('donate.html', member=member)
            
            # Check if reason is empty and not confirmed
            if not reason and confirm_no_reason != 'yes':
                return render_template('donate.html', member=member, 
                                     show_confirmation=True, amount=amount)
            
            # Process donation
            receipt_number = generate_receipt_number(data)
            donation_date = datetime.now().strftime('%Y-%m-%d')
            
            donation = {
                'date': donation_date,
                'amount': amount,
                'reason': reason if reason else 'General Donation',
                'receipt': receipt_number
            }
            
            member['donations'].append(donation)
            
            # Add to transactions
            transaction = {
                'type': 'donation',
                'amount': amount,
                'reason': donation['reason'],
                'date': donation_date,
                'receipt': receipt_number
            }
            member['transactions'].append(transaction)
            
            save_data(data)
            
            flash(f'Thank you for your donation! Receipt: {receipt_number}', 'success')
            return render_template('payment_confirmation.html',
                                 member=member,
                                 transaction_type='Donation',
                                 reason=donation['reason'],
                                 amount=amount,
                                 date=donation_date,
                                 receipt=receipt_number)
            
        except Exception as e:
            flash(f'Error processing donation: {str(e)}', 'danger')
            return render_template('donate.html', member=member)
    
    return render_template('donate.html', member=member)

@app.route('/member/transactions')
@member_required
def member_transactions():
    """View transaction history"""
    data = load_data()
    member_id = session.get('member_id')
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('member_dashboard'))
    
    # Sort transactions by date (newest first)
    transactions = sorted(member.get('transactions', []), 
                         key=lambda x: x['date'], reverse=True)
    
    return render_template('member_transactions.html',
                         member=member,
                         transactions=transactions)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
