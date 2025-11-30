from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, make_response
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
import csv
from datetime import datetime
from functools import wraps
from io import StringIO, BytesIO
from models import db, User, Member, Contribution, Donation, ChangeLog, SequenceCounter, UserRole, PaymentMethod, PaymentStatus

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')

# Email configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@etotc.org')
mail = Mail(app)

# Database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
db.init_app(app)

# Create all database tables
with app.app_context():
    db.create_all()
    
    # Create default admin user if not exists
    admin_user = User.query.filter_by(username='admin').first()
    if not admin_user:
        admin_password = os.environ.get('ADMIN_PASSWORD')
        if admin_password:
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash(admin_password),
                role=UserRole.ADMIN,
                full_name='System Administrator',
                email='admin@etotc.org'
            )
            db.session.add(admin_user)
            db.session.commit()

DATA_FILE = 'data.json'  # Legacy JSON file - now in read-only mode for backup
CHURCH_NAME = 'ETOTC'
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 
          'July', 'August', 'September', 'October', 'November', 'December']
MINIMUM_MONTHLY_PAYMENT = 30

# Helper functions for database-backed ID generation
def get_next_member_id():
    """Generate next member ID using database sequence counter"""
    counter = SequenceCounter.query.filter_by(counter_name='member_id').first()
    if not counter:
        counter = SequenceCounter(counter_name='member_id', counter_value=1)
        db.session.add(counter)
    
    member_id = f"CH{counter.counter_value:03d}"
    counter.counter_value += 1
    db.session.commit()
    return member_id

def get_next_receipt_number():
    """Generate next receipt number using database sequence counter"""
    counter = SequenceCounter.query.filter_by(counter_name='receipt_number').first()
    if not counter:
        counter = SequenceCounter(counter_name='receipt_number', counter_value=1)
        db.session.add(counter)
    
    current_year = datetime.now().year
    receipt = f"RCPT-{current_year}-{counter.counter_value:04d}"
    counter.counter_value += 1
    db.session.commit()
    return receipt

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

def check_year_complete(contributions):
    """Check if all 12 months are paid for a year, safely handling missing months"""
    for month in MONTHS:
        if month not in contributions:
            return False
        if contributions[month].get('status') != 'Paid':
            return False
    return True

def count_paid_months(contributions):
    """Count how many months are paid for a year, safely handling missing months"""
    count = 0
    for month in MONTHS:
        if month in contributions and contributions[month].get('status') == 'Paid':
            count += 1
    return count

def ensure_next_year_sheet(member, current_year):
    """Create next year's contribution sheet if it doesn't exist"""
    next_year = str(int(current_year) + 1)
    if next_year not in member.get('contributions', {}):
        if 'contributions' not in member:
            member['contributions'] = {}
        member['contributions'][next_year] = initialize_year_contributions(next_year)
        return next_year
    return None

def normalize_year_contributions(contributions):
    """Ensure all 12 months exist in the contributions dict, backfilling missing months"""
    for month in MONTHS:
        if month not in contributions:
            contributions[month] = {
                'status': 'Unpaid',
                'amount': 0,
                'date': '',
                'receipt': ''
            }
    return contributions

def generate_receipt_html(receipt_data, is_year_complete=False):
    """Generate HTML for receipt email"""
    payments_html = ""
    for payment in receipt_data['payments']:
        payments_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{payment['month']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #ddd; text-align: right;">${payment['amount']:.2f}</td>
        </tr>
        """
    
    year_complete_section = ""
    if is_year_complete:
        year_complete_section = f"""
        <div style="background: #28a745; color: white; padding: 20px; margin-top: 20px; border-radius: 8px; text-align: center;">
            <h2 style="margin: 0;">🎉 Congratulations!</h2>
            <p style="margin: 10px 0 0 0; font-size: 1.1em;">
                You have completed all contributions for {receipt_data.get('year', datetime.now().year)}!
            </p>
        </div>
        """
    
    html = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; border-bottom: 2px solid #2c3e50; padding-bottom: 15px; margin-bottom: 20px;">
            <h1 style="margin: 0; color: #2c3e50;">ETOTC Church</h1>
            <p style="margin: 5px 0; color: #666;">Contribution Receipt</p>
        </div>
        
        <div style="display: flex; justify-content: space-between; margin-bottom: 20px;">
            <div>
                <strong>Receipt Number:</strong><br>
                <span style="font-size: 1.2em; color: #27ae60;">{receipt_data['receipt_number']}</span>
            </div>
            <div style="text-align: right;">
                <strong>Date:</strong><br>
                {receipt_data['date']}
            </div>
        </div>
        
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
            <h3 style="margin-top: 0;">Member Information</h3>
            <p style="margin: 5px 0;"><strong>Name:</strong> {receipt_data['member_name']}</p>
            <p style="margin: 5px 0;"><strong>Member ID:</strong> {receipt_data['member_id']}</p>
        </div>
        
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
            <thead>
                <tr style="background: #2c3e50; color: white;">
                    <th style="padding: 10px; text-align: left;">Month</th>
                    <th style="padding: 10px; text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {payments_html}
            </tbody>
            <tfoot>
                <tr style="background: #f8f9fa; font-weight: bold;">
                    <td style="padding: 10px;">Total</td>
                    <td style="padding: 10px; text-align: right;">${receipt_data['total']:.2f}</td>
                </tr>
            </tfoot>
        </table>
        
        {year_complete_section}
        
        <div style="text-align: center; color: #666; font-size: 0.9em; border-top: 1px solid #ddd; padding-top: 15px; margin-top: 20px;">
            <p style="margin: 5px 0;">Thank you for your contribution!</p>
            <p style="margin: 5px 0;">God bless you.</p>
        </div>
    </body>
    </html>
    """
    return html

def generate_year_completion_sheet(member, year, contributions):
    """Generate HTML for year completion certificate/sheet"""
    total_paid = sum(contributions[month]['amount'] for month in MONTHS)
    
    html = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 40px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
        <div style="background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.3);">
            <div style="text-align: center; border-bottom: 3px solid #27ae60; padding-bottom: 20px; margin-bottom: 30px;">
                <h1 style="margin: 0; color: #2c3e50; font-size: 2.5em;">⛪ ETOTC Church</h1>
                <h2 style="margin: 10px 0; color: #27ae60;">Certificate of Completion</h2>
                <p style="color: #666; font-size: 1.1em;">Annual Contribution Record</p>
            </div>
            
            <div style="text-align: center; margin-bottom: 30px;">
                <p style="font-size: 1.2em; color: #333;">This certifies that</p>
                <h2 style="font-size: 2em; color: #2c3e50; margin: 10px 0; border-bottom: 2px solid #27ae60; display: inline-block; padding-bottom: 5px;">
                    {member['name']}
                </h2>
                <p style="color: #666;">Member ID: {member['id']}</p>
            </div>
            
            <div style="text-align: center; margin-bottom: 30px;">
                <p style="font-size: 1.1em; color: #333;">
                    has successfully completed all monthly contributions for the year
                </p>
                <h1 style="font-size: 3em; color: #27ae60; margin: 10px 0;">{year}</h1>
            </div>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 10px; margin-bottom: 30px;">
                <h3 style="text-align: center; margin-top: 0; color: #2c3e50;">Payment Summary</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: #2c3e50; color: white;">
                            <th style="padding: 10px; text-align: left;">Month</th>
                            <th style="padding: 10px; text-align: right;">Amount</th>
                            <th style="padding: 10px; text-align: center;">Receipt #</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    for month in MONTHS:
        contrib = contributions[month]
        html += f"""
                        <tr style="border-bottom: 1px solid #ddd;">
                            <td style="padding: 8px;">{month}</td>
                            <td style="padding: 8px; text-align: right;">${contrib['amount']:.2f}</td>
                            <td style="padding: 8px; text-align: center;">{contrib['receipt']}</td>
                        </tr>
        """
    
    html += f"""
                    </tbody>
                    <tfoot>
                        <tr style="background: #27ae60; color: white; font-weight: bold;">
                            <td style="padding: 10px;">Total Annual Contribution</td>
                            <td style="padding: 10px; text-align: right;">${total_paid:.2f}</td>
                            <td style="padding: 10px;"></td>
                        </tr>
                    </tfoot>
                </table>
            </div>
            
            <div style="text-align: center; color: #666; padding-top: 20px; border-top: 1px solid #ddd;">
                <p style="margin: 5px 0;">May God bless you abundantly for your faithful giving.</p>
                <p style="margin: 15px 0; font-style: italic;">"Each of you should give what you have decided in your heart to give, not reluctantly or under compulsion, for God loves a cheerful giver." - 2 Corinthians 9:7</p>
                <p style="margin-top: 20px; color: #999; font-size: 0.9em;">Generated on {datetime.now().strftime('%B %d, %Y')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html

def send_receipt_email(member_email, member_name, receipt_data, is_year_complete=False, year_sheet_html=None):
    """Send receipt email to member"""
    if not app.config['MAIL_USERNAME'] or not member_email:
        return False
    
    try:
        subject = f"ETOTC Church - Payment Receipt {receipt_data['receipt_number']}"
        if is_year_complete:
            subject = f"ETOTC Church - Year {receipt_data.get('year', datetime.now().year)} Completed! 🎉"
        
        msg = Message(
            subject=subject,
            recipients=[member_email],
            html=generate_receipt_html(receipt_data, is_year_complete)
        )
        
        # Attach year completion sheet if year is complete
        if is_year_complete and year_sheet_html:
            msg.attach(
                f"ETOTC_Year_{receipt_data.get('year', datetime.now().year)}_Certificate.html",
                "text/html",
                year_sheet_html
            )
        
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error(f"Failed to send email: {str(e)}")
        return False

def staff_required(f):
    """Decorator to require admin or cashier login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        
        # Verify user exists and has valid role from database
        user = User.query.get(user_id)
        if not user or not user.is_active:
            session.clear()
            flash('Invalid session. Please log in again.', 'danger')
            return redirect(url_for('login'))
        
        # Verify user has staff role (admin or cashier)
        if user.role not in [UserRole.ADMIN, UserRole.CASHIER]:
            session.clear()
            flash('Staff access required.', 'danger')
            return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin login (admin-only features)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in as admin to access this page.', 'danger')
            return redirect(url_for('login'))
        
        # Verify user exists and is admin from database
        user = User.query.get(user_id)
        if not user or user.role != UserRole.ADMIN or not user.is_active:
            session.clear()
            flash('Admin access required.', 'danger')
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

def get_current_user():
    """Get the current logged-in staff user (admin or cashier)"""
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

@app.route('/')
def index():
    """Landing page"""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Admin/Cashier login"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Find user in database
        user = User.query.filter_by(username=username).first()
        
        if user and user.is_active and check_password_hash(user.password_hash, password):
            # Clear any existing session data first
            session.clear()
            
            # Set session variables
            session['user_id'] = user.id
            session['username'] = user.username
            session['user_role'] = user.role.value
            session['user_name'] = user.full_name or user.username
            session['is_staff'] = True
            session.permanent = True
            session.modified = True
            
            role_display = "Admin" if user.role == UserRole.ADMIN else "Cashier"
            flash(f'Successfully logged in as {role_display}!', 'success')
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
        
        # Find member in database
        member = Member.query.filter_by(member_id=member_id).first()
        
        if member and member.is_active and check_password_hash(member.password_hash, password):
            session['member_id'] = member.id
            session['member_code'] = member.member_id
            session['member_name'] = member.full_name
            flash(f'Welcome, {member.full_name}!', 'success')
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
@staff_required
def admin_home():
    """Admin/Cashier home page with member list"""
    members = Member.query.filter_by(is_active=True).all()
    current_user = get_current_user()
    
    # Calculate total contributions for each member
    for member in members:
        total = db.session.query(db.func.sum(Contribution.amount)).filter(
            Contribution.member_id == member.id,
            Contribution.status == PaymentStatus.PAID
        ).scalar() or 0
        member.total_contributions = total
    
    return render_template('admin_home.html', members=members, current_user=current_user)

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
            first_name = request.form.get('first_name', '').strip()
            middle_name = request.form.get('middle_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            monthly_payment = request.form.get('monthly_payment', '').strip()
            
            # Combine name parts
            name_parts = [first_name, middle_name, last_name] if middle_name else [first_name, last_name]
            name = ' '.join(name_parts)
            
            if not all([new_id, first_name, last_name, phone, email, monthly_payment]):
                flash('All required fields must be filled.', 'danger')
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
    
    # Ensure year exists and normalize contributions
    if selected_year not in member['contributions']:
        member['contributions'][selected_year] = initialize_year_contributions(selected_year)
        save_data(data)
    
    contributions = member['contributions'][selected_year]
    normalize_year_contributions(contributions)
    available_years = sorted(member['contributions'].keys(), reverse=True)
    
    # Calculate stats using safe .get() accessors
    paid_months = sum(1 for month in MONTHS if contributions.get(month, {}).get('status') == 'Paid')
    total_paid = sum(contributions.get(month, {}).get('amount', 0) for month in MONTHS if contributions.get(month, {}).get('status') == 'Paid')
    
    # Get receipt data from session if available (after payment)
    receipt_data = session.pop('receipt_data', None)
    
    return render_template('member_details.html', 
                         member=member,
                         contributions=contributions,
                         months=MONTHS,
                         selected_year=selected_year,
                         available_years=available_years,
                         paid_months=paid_months,
                         total_paid=total_paid,
                         receipt_data=receipt_data)

@app.route('/admin/pay-month/<member_id>/<year>/<month>', methods=['POST'])
@staff_required
def admin_pay_month(member_id, year, month):
    """Admin processes a monthly payment for a member"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Validate month
    if month not in MONTHS:
        flash('Invalid month.', 'danger')
        return redirect(url_for('member_details', member_id=member_id, year=year))
    
    # Ensure year exists and normalize contributions
    if year not in member['contributions']:
        member['contributions'][year] = initialize_year_contributions(year)
    
    contributions = member['contributions'][year]
    normalize_year_contributions(contributions)
    
    # Check if already paid
    if contributions[month]['status'] == 'Paid':
        flash('This month has already been paid.', 'warning')
        return redirect(url_for('member_details', member_id=member_id, year=year))
    
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
    if 'transactions' not in member:
        member['transactions'] = []
    
    transaction = {
        'type': 'contribution',
        'month': month,
        'amount': member['monthly_payment'],
        'date': payment_date,
        'receipt': receipt_number
    }
    member['transactions'].append(transaction)
    
    save_data(data)
    
    # Check paid months count after payment and auto-generate next year's sheet
    paid_count = count_paid_months(contributions)
    if paid_count >= 11:
        new_year = ensure_next_year_sheet(member, year)
        if new_year:
            save_data(data)  # Save again with new year sheet
            flash(f'Next year ({new_year}) contribution sheet has been created!', 'info')
    
    # Check if year is now complete
    is_year_complete = check_year_complete(contributions)
    year_sheet_html = None
    
    if is_year_complete:
        year_sheet_html = generate_year_completion_sheet(member, year, contributions)
        flash(f'🎉 Congratulations! {member["name"]} has completed all contributions for {year}!', 'success')
    
    # Store receipt data in session for display
    receipt_data = {
        'receipt_number': receipt_number,
        'date': payment_date,
        'member_name': member['name'],
        'member_id': member['id'],
        'member_email': member.get('email', ''),
        'payments': [{
            'month': month,
            'amount': member['monthly_payment']
        }],
        'total': member['monthly_payment'],
        'year': year,
        'is_year_complete': is_year_complete
    }
    session['receipt_data'] = receipt_data
    
    # Store year sheet in session if complete
    if is_year_complete and year_sheet_html:
        session['year_sheet'] = year_sheet_html
    
    # Send email automatically
    member_email = member.get('email')
    if member_email:
        email_sent = send_receipt_email(
            member_email, 
            member['name'], 
            receipt_data,
            is_year_complete,
            year_sheet_html
        )
        if email_sent:
            flash(f'Receipt emailed to {member_email}', 'info')
    
    flash(f'Payment processed successfully for {month}! Receipt: {receipt_number}', 'success')
    return redirect(url_for('member_details', member_id=member_id, year=year))


@app.route('/admin/bulk-pay/<member_id>/<year>', methods=['POST'])
@staff_required
def admin_bulk_pay(member_id, year):
    """Admin processes bulk payments for multiple months with ONE receipt"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Get selected months from form
    selected_months = request.form.getlist('months')
    
    if not selected_months:
        flash('Please select at least one month to pay.', 'warning')
        return redirect(url_for('member_details', member_id=member_id, year=year))
    
    # Ensure year exists and normalize contributions
    if year not in member['contributions']:
        member['contributions'][year] = initialize_year_contributions(year)
    
    contributions = member['contributions'][year]
    normalize_year_contributions(contributions)
    
    # Add transactions list if not exists
    if 'transactions' not in member:
        member['transactions'] = []
    
    payment_date = datetime.now().strftime('%Y-%m-%d')
    processed_payments = []
    skipped_months = []
    
    # Collect valid months first
    valid_months = []
    for month in selected_months:
        if month not in MONTHS:
            continue
        if contributions[month]['status'] == 'Paid':
            skipped_months.append(month)
            continue
        valid_months.append(month)
    
    if valid_months:
        # Generate ONE receipt for all months in this transaction
        receipt_number = generate_receipt_number(data)
        total_amount = len(valid_months) * member['monthly_payment']
        
        for month in valid_months:
            contributions[month] = {
                'status': 'Paid',
                'amount': member['monthly_payment'],
                'date': payment_date,
                'receipt': receipt_number  # Same receipt for all months
            }
            
            # Add transaction
            transaction = {
                'type': 'contribution',
                'month': month,
                'amount': member['monthly_payment'],
                'date': payment_date,
                'receipt': receipt_number
            }
            member['transactions'].append(transaction)
            
            processed_payments.append({
                'month': month,
                'amount': member['monthly_payment']
            })
        
        save_data(data)
        
        # Check paid months count after payment and auto-generate next year's sheet
        paid_count = count_paid_months(contributions)
        if paid_count >= 11:
            new_year = ensure_next_year_sheet(member, year)
            if new_year:
                save_data(data)  # Save again with new year sheet
                flash(f'Next year ({new_year}) contribution sheet has been created!', 'info')
        
        # Check if year is now complete
        is_year_complete = check_year_complete(contributions)
        year_sheet_html = None
        
        if is_year_complete:
            year_sheet_html = generate_year_completion_sheet(member, year, contributions)
            flash(f'🎉 Congratulations! {member["name"]} has completed all contributions for {year}!', 'success')
        
        # Store receipt data in session for display
        receipt_data = {
            'receipt_number': receipt_number,
            'date': payment_date,
            'member_name': member['name'],
            'member_id': member['id'],
            'member_email': member.get('email', ''),
            'payments': processed_payments,
            'total': total_amount,
            'year': year,
            'is_year_complete': is_year_complete
        }
        session['receipt_data'] = receipt_data
        
        # Store year sheet in session if complete
        if is_year_complete and year_sheet_html:
            session['year_sheet'] = year_sheet_html
        
        # Send email automatically
        member_email = member.get('email')
        if member_email:
            email_sent = send_receipt_email(
                member_email, 
                member['name'], 
                receipt_data,
                is_year_complete,
                year_sheet_html
            )
            if email_sent:
                flash(f'Receipt emailed to {member_email}', 'info')
        
        months_str = ', '.join([p['month'] for p in processed_payments])
        flash(f'Payment processed! Receipt {receipt_number} for {months_str}', 'success')
        
        # Notify about skipped months if any
        if skipped_months:
            skipped_str = ', '.join(skipped_months)
            flash(f'Skipped {len(skipped_months)} already paid month(s): {skipped_str}', 'info')
    else:
        flash('No payments were processed. All selected months were already paid.', 'warning')
    
    return redirect(url_for('member_details', member_id=member_id, year=year))

@app.route('/admin/member/<member_id>/transactions')
@staff_required
def admin_member_transactions(member_id):
    """View all transactions/receipts for a member"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Collect all transactions grouped by receipt
    receipts = {}
    for transaction in member.get('transactions', []):
        receipt_num = transaction.get('receipt', '')
        if receipt_num:
            if receipt_num not in receipts:
                receipts[receipt_num] = {
                    'receipt_number': receipt_num,
                    'date': transaction['date'],
                    'payments': [],
                    'total': 0
                }
            receipts[receipt_num]['payments'].append({
                'type': transaction.get('type', 'contribution'),
                'month': transaction.get('month', ''),
                'amount': transaction['amount']
            })
            receipts[receipt_num]['total'] += transaction['amount']
    
    # Convert to list and sort by date (newest first)
    receipt_list = sorted(receipts.values(), key=lambda x: x['date'], reverse=True)
    
    # Get completed years
    completed_years = []
    for year, contributions in member.get('contributions', {}).items():
        if check_year_complete(contributions):
            total = sum(contributions.get(month, {}).get('amount', 0) for month in MONTHS)
            completed_years.append({'year': year, 'total': total})
    completed_years.sort(key=lambda x: x['year'], reverse=True)
    
    return render_template('admin_member_transactions.html',
                          member=member,
                          receipts=receipt_list,
                          completed_years=completed_years)

@app.route('/admin/member/<member_id>/receipt/<receipt_number>')
@staff_required
def view_receipt(member_id, receipt_number):
    """View/reprint a specific receipt"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Find transactions for this receipt
    payments = []
    receipt_date = ''
    for transaction in member.get('transactions', []):
        if transaction.get('receipt') == receipt_number:
            payments.append({
                'type': transaction.get('type', 'contribution'),
                'month': transaction.get('month', ''),
                'reason': transaction.get('reason', ''),
                'amount': transaction['amount']
            })
            if not receipt_date:
                receipt_date = transaction['date']
    
    if not payments:
        flash('Receipt not found.', 'danger')
        return redirect(url_for('admin_member_transactions', member_id=member_id))
    
    total = sum(p['amount'] for p in payments)
    
    receipt_data = {
        'receipt_number': receipt_number,
        'date': receipt_date,
        'member_name': member['name'],
        'member_id': member['id'],
        'member_email': member.get('email', ''),
        'payments': payments,
        'total': total
    }
    
    return render_template('view_receipt.html',
                          member=member,
                          receipt=receipt_data)

@app.route('/admin/member/<member_id>/year-certificate/<year>')
@staff_required
def view_year_certificate(member_id, year):
    """View/print year completion certificate"""
    data = load_data()
    member = next((m for m in data['members'] if m['id'] == member_id), None)
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    if year not in member.get('contributions', {}):
        flash('Year not found.', 'danger')
        return redirect(url_for('admin_member_transactions', member_id=member_id))
    
    contributions = member['contributions'][year]
    
    if not check_year_complete(contributions):
        flash('Year is not complete yet.', 'warning')
        return redirect(url_for('admin_member_transactions', member_id=member_id))
    
    # Generate the certificate HTML
    certificate_html = generate_year_completion_sheet(member, year, contributions)
    
    return render_template('view_certificate.html',
                          member=member,
                          year=year,
                          certificate_html=certificate_html)

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
