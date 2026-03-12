from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, make_response
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
import csv
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps

PACIFIC_TZ = ZoneInfo('America/Los_Angeles')

def get_current_time():
    """Get current time in Pacific timezone"""
    return datetime.now(PACIFIC_TZ)

def get_current_date():
    """Get current date in Pacific timezone"""
    return datetime.now(PACIFIC_TZ).date()
from io import StringIO, BytesIO
from models import db, User, Member, Contribution, Donation, ChangeLog, SequenceCounter, NonMemberTransaction, Spouse, Child, UserRole, PaymentMethod, PaymentStatus, SystemSetting

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')

# Session configuration
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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
MINIMUM_MONTHLY_PAYMENT = 25

# Helper functions for database-backed ID generation
def get_next_member_id():
    """Generate next member ID using database sequence counter"""
    counter = SequenceCounter.query.filter_by(counter_name='member_id').first()
    if not counter:
        counter = SequenceCounter(counter_name='member_id', counter_value=1)
        db.session.add(counter)
    
    member_id = f"ETOTC-{counter.counter_value:04d}"
    counter.counter_value += 1
    db.session.commit()
    return member_id

def get_next_member_id_preview():
    """Preview next member ID without incrementing counter"""
    counter = SequenceCounter.query.filter_by(counter_name='member_id').first()
    if not counter:
        return "ETOTC-0001"
    return f"ETOTC-{counter.counter_value:04d}"

def get_next_receipt_number():
    """Generate next receipt number using database sequence counter"""
    counter = SequenceCounter.query.filter_by(counter_name='receipt_number').first()
    if not counter:
        counter = SequenceCounter(counter_name='receipt_number', counter_value=1)
        db.session.add(counter)
    
    current_year = get_current_time().year
    receipt = f"RCPT-{current_year}-{counter.counter_value:04d}"
    counter.counter_value += 1
    db.session.commit()
    return receipt

def get_next_nonmember_receipt_number():
    """Generate next receipt number for non-member transactions with NM prefix"""
    counter = SequenceCounter.query.filter_by(counter_name='nonmember_receipt_number').first()
    if not counter:
        counter = SequenceCounter(counter_name='nonmember_receipt_number', counter_value=1)
        db.session.add(counter)
    
    current_year = get_current_time().year
    receipt = f"NM-{current_year}-{counter.counter_value:04d}"
    counter.counter_value += 1
    db.session.commit()
    return receipt

def is_valid_phone(phone_number):
    """Check if phone number is a valid 10-digit number"""
    if not phone_number:
        return True  # Empty phone is okay
    # Remove all non-digit characters
    digits_only = re.sub(r'\D', '', phone_number)
    # Check if it's exactly 10 digits
    return len(digits_only) == 10

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
    """Generate next member ID in format ETOTC-0001, ETOTC-0002, etc."""
    next_id = data.get('next_member_id', 1)
    member_id = f"ETOTC-{next_id:04d}"
    data['next_member_id'] = next_id + 1
    return member_id

def generate_receipt_number(data):
    """Generate receipt number in format RCPT-YYYY-NNNN"""
    current_year = get_current_time().year
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
    """Decorator to require admin, cashier, accountant, or IT support login"""
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
        
        # Verify user has staff role (admin, cashier, accountant, or IT support)
        if user.role not in [UserRole.ADMIN, UserRole.CASHIER, UserRole.ACCOUNTANT, UserRole.IT_SUPPORT]:
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

def accountant_or_admin(f):
    """Decorator to require admin, accountant, or IT support login (for financial reports)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        
        # Verify user exists and has admin, accountant, or IT support role
        user = User.query.get(user_id)
        if not user or user.role not in [UserRole.ADMIN, UserRole.ACCOUNTANT, UserRole.IT_SUPPORT] or not user.is_active:
            session.clear()
            flash('Admin, Accountant, or IT Support access required.', 'danger')
            return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    return decorated_function

def admin_or_it_support(f):
    """Decorator to require admin or IT support login (for user management and archive)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        
        # Verify user exists and has admin or IT support role
        user = User.query.get(user_id)
        if not user or user.role not in [UserRole.ADMIN, UserRole.IT_SUPPORT] or not user.is_active:
            session.clear()
            flash('Admin or IT Support access required.', 'danger')
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
    """Landing page - redirect to admin login"""
    if session.get('is_staff'):
        return redirect(url_for('admin_home'))
    if session.get('member_id'):
        return redirect(url_for('member_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Admin/Cashier/Accountant login"""
    # If already logged in, redirect to dashboard
    if session.get('is_staff'):
        return redirect(url_for('admin_home'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Find user in database
        user = User.query.filter_by(username=username).first()
        
        if user and user.is_active and check_password_hash(user.password_hash, password):
            # Clear any existing session data first
            session.clear()
            
            # Set session variables
            session.permanent = True
            session['user_id'] = user.id
            session['username'] = user.username
            session['user_role'] = user.role.value
            session['user_name'] = user.full_name or user.username
            session['is_staff'] = True
            session.modified = True
            
            role_map = {
                UserRole.ADMIN: "Admin",
                UserRole.CASHIER: "Cashier",
                UserRole.ACCOUNTANT: "Accountant"
            }
            role_display = role_map.get(user.role, "Staff")
            flash(f'Successfully logged in as {role_display}!', 'success')
            return redirect(url_for('admin_home'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')
    
    return render_template('login.html')

@app.route('/member-login', methods=['GET', 'POST'])
def member_login():
    """Member login with ID and password"""
    # If already logged in, redirect to dashboard
    if session.get('member_id'):
        return redirect(url_for('member_dashboard'))
    
    if request.method == 'POST':
        member_id = request.form.get('member_id', '').strip().upper()
        password = request.form.get('password')
        
        # Find member in database
        member = Member.query.filter_by(member_id=member_id).first()
        
        if member and member.is_active and check_password_hash(member.password_hash, password):
            # Clear session before setting new session data
            session.clear()
            session.permanent = True
            session['member_id'] = member.id
            session['member_code'] = member.member_id
            session['member_name'] = member.full_name
            session.modified = True
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
    """Admin/Cashier/Accountant home page with member list"""
    members = Member.query.filter_by(is_active=True).order_by(Member.first_name, Member.last_name).all()
    current_user = get_current_user()
    current_calendar_year = get_current_time().year
    
    member_ids = [m.id for m in members]
    
    if member_ids:
        month_order = db.case(
            (Contribution.month == 'January', 1),
            (Contribution.month == 'February', 2),
            (Contribution.month == 'March', 3),
            (Contribution.month == 'April', 4),
            (Contribution.month == 'May', 5),
            (Contribution.month == 'June', 6),
            (Contribution.month == 'July', 7),
            (Contribution.month == 'August', 8),
            (Contribution.month == 'September', 9),
            (Contribution.month == 'October', 10),
            (Contribution.month == 'November', 11),
            (Contribution.month == 'December', 12),
            else_=0
        )
        
        totals = db.session.query(
            Contribution.member_id,
            db.func.sum(Contribution.amount)
        ).filter(
            Contribution.member_id.in_(member_ids),
            Contribution.status == PaymentStatus.PAID
        ).group_by(Contribution.member_id).all()
        totals_map = {mid: total for mid, total in totals}
        
        last_paid = db.session.query(
            Contribution.member_id,
            db.func.max(Contribution.year * 100 + month_order)
        ).filter(
            Contribution.member_id.in_(member_ids),
            Contribution.status == PaymentStatus.PAID
        ).group_by(Contribution.member_id).all()
        last_paid_map = {mid: val // 100 for mid, val in last_paid}
        
        first_unpaid = db.session.query(
            Contribution.member_id,
            db.func.min(Contribution.year)
        ).filter(
            Contribution.member_id.in_(member_ids),
            Contribution.status == PaymentStatus.UNPAID
        ).group_by(Contribution.member_id).all()
        first_unpaid_map = {mid: yr for mid, yr in first_unpaid}
        
        current_year_map = {}
        for m in members:
            if m.id in last_paid_map:
                current_year_map[m.id] = last_paid_map[m.id]
            elif m.id in first_unpaid_map:
                current_year_map[m.id] = first_unpaid_map[m.id]
            else:
                current_year_map[m.id] = current_calendar_year
        
        needed_years = set()
        for mid, yr in current_year_map.items():
            needed_years.add((mid, yr))
        
        all_contribs = Contribution.query.filter(
            db.or_(*[
                db.and_(Contribution.member_id == mid, Contribution.year == yr)
                for mid, yr in needed_years
            ])
        ).all()
        
        contrib_map = {}
        for c in all_contribs:
            if c.member_id not in contrib_map:
                contrib_map[c.member_id] = {}
            contrib_map[c.member_id][c.month] = c.status == PaymentStatus.PAID
        
        for member in members:
            member.total_contributions = totals_map.get(member.id, 0)
            member.current_year = current_year_map.get(member.id, current_calendar_year)
            member.month_status = contrib_map.get(member.id, {})
    else:
        for member in members:
            member.total_contributions = 0
            member.current_year = current_calendar_year
            member.month_status = {}
    
    return render_template('admin_home.html', members=members, current_user=current_user, months=MONTHS)

@app.route('/admin/add-member', methods=['GET', 'POST'])
@staff_required
def add_member():
    """Add new member with auto-generated ID"""
    suggested_id = get_next_member_id_preview()
    
    if request.method == 'POST':
        try:
            # Get basic form data
            custom_id = request.form.get('custom_id', '').strip().upper()
            first_name = request.form.get('first_name', '').strip()
            father_name = request.form.get('father_name', '').strip() or None
            middle_name = request.form.get('middle_name', '').strip() or None
            last_name = request.form.get('last_name', '').strip()
            baptismal_name = request.form.get('baptismal_name', '').strip() or None
            date_of_birth_str = request.form.get('date_of_birth', '').strip()
            gender_str = request.form.get('gender', '').strip()
            address = request.form.get('address', '').strip() or None
            city = request.form.get('city', '').strip() or None
            state = request.form.get('state', '').strip() or 'WA'
            zip_code = request.form.get('zip_code', '').strip() or None
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip() or None
            confession_name = request.form.get('confession_name', '').strip() or None
            marital_status_str = request.form.get('marital_status', 'single').strip()
            password = request.form.get('password', '').strip()
            monthly_payment = request.form.get('monthly_payment', '').strip()
            
            # Validation
            if not all([first_name, last_name, phone, password, monthly_payment]):
                flash('First name, last name, phone, password, and monthly payment are required.', 'danger')
                return render_template('add_member.html', suggested_id=suggested_id)
            
            try:
                monthly_amount = float(monthly_payment)
                if monthly_amount < MINIMUM_MONTHLY_PAYMENT:
                    flash(f'Monthly payment must be at least ${MINIMUM_MONTHLY_PAYMENT}.', 'danger')
                    return render_template('add_member.html', suggested_id=suggested_id)
            except ValueError:
                flash('Monthly payment must be a valid number.', 'danger')
                return render_template('add_member.html', suggested_id=suggested_id)
            
            # Parse date of birth
            date_of_birth = None
            if date_of_birth_str:
                try:
                    date_of_birth = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            
            # Parse gender and marital status (use simple strings)
            gender = gender_str if gender_str in ['male', 'female'] else None
            marital_status = marital_status_str if marital_status_str in ['single', 'married', 'single_with_children'] else 'single'
            
            # Generate or use custom ID
            if custom_id:
                if Member.query.filter_by(member_id=custom_id).first():
                    flash('This Member ID already exists. Please use a different ID.', 'danger')
                    return render_template('add_member.html', suggested_id=suggested_id)
                member_id = custom_id
            else:
                member_id = get_next_member_id()
            
            # Create member in database
            new_member = Member(
                member_id=member_id,
                first_name=first_name,
                father_name=father_name,
                middle_name=middle_name,
                last_name=last_name,
                baptismal_name=baptismal_name,
                date_of_birth=date_of_birth,
                gender=gender,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                email=email,
                phone=phone,
                confession_name=confession_name,
                marital_status=marital_status,
                password_hash=generate_password_hash(password),
                monthly_payment=monthly_amount
            )
            db.session.add(new_member)
            db.session.flush()
            
            # Add spouse if married and spouse info provided
            if marital_status == 'married':
                spouse_first_name = request.form.get('spouse_first_name', '').strip()
                spouse_last_name = request.form.get('spouse_last_name', '').strip()
                
                # Only create spouse record if at least first name is provided
                if spouse_first_name:
                    spouse_middle_name = request.form.get('spouse_middle_name', '').strip() or None
                    spouse_baptismal_name = request.form.get('spouse_baptismal_name', '').strip() or None
                    spouse_dob_str = request.form.get('spouse_date_of_birth', '').strip()
                    spouse_gender_str = request.form.get('spouse_gender', '').strip()
                    spouse_phone = request.form.get('spouse_phone', '').strip() or None
                    spouse_email = request.form.get('spouse_email', '').strip() or None
                    
                    spouse_dob = None
                    if spouse_dob_str:
                        try:
                            spouse_dob = datetime.strptime(spouse_dob_str, '%Y-%m-%d').date()
                        except ValueError:
                            pass
                    
                    spouse_gender = spouse_gender_str if spouse_gender_str in ['male', 'female'] else None
                    
                    spouse = Spouse(
                        member_id=new_member.id,
                        first_name=spouse_first_name,
                        middle_name=spouse_middle_name,
                        last_name=spouse_last_name or None,
                        baptismal_name=spouse_baptismal_name,
                        date_of_birth=spouse_dob,
                        gender=spouse_gender,
                        phone=spouse_phone,
                        email=spouse_email
                    )
                    db.session.add(spouse)
                
                # Add children - only if full name is provided (minimum required field)
                for i in range(1, 11):
                    child_name = request.form.get(f'child_name_{i}', '').strip()
                    if child_name and len(child_name) >= 2:  # Require at least 2 characters for valid name
                        child_baptismal = request.form.get(f'child_baptismal_{i}', '').strip() or None
                        child_dob_str = request.form.get(f'child_dob_{i}', '').strip()
                        child_gender_str = request.form.get(f'child_gender_{i}', '').strip()
                        
                        child_dob = None
                        if child_dob_str:
                            try:
                                child_dob = datetime.strptime(child_dob_str, '%Y-%m-%d').date()
                            except ValueError:
                                pass
                        
                        child_gender = child_gender_str if child_gender_str in ['male', 'female'] else None
                        
                        child = Child(
                            member_id=new_member.id,
                            full_name=child_name,
                            baptismal_name=child_baptismal,
                            date_of_birth=child_dob,
                            gender=child_gender
                        )
                        db.session.add(child)
            
            db.session.commit()
            
            # Initialize contributions starting from the month they signed up
            current_date = get_current_time()
            current_year = current_date.year
            current_month_index = current_date.month - 1  # 0-indexed
            
            for i, month in enumerate(MONTHS):
                status = PaymentStatus.UNPAID
                # If the month is before the current signup month, mark as 'N/A' or just don't create?
                # User said "members start payment on the month they signed up on", 
                # implying preceding months are not owed.
                
                contribution = Contribution(
                    member_id=new_member.id,
                    year=current_year,
                    month=month,
                    status=status,
                    amount=0
                )
                
                # If month is before signup, we can mark it differently or set amount to 0
                # Here we just ensure they are created as Unpaid but they will only start paying from now
                if i < current_month_index:
                    # Mark as Paid with 0 amount to effectively "open" the later months
                    # or keep as Unpaid but the UI should handle it. 
                    # The user says "open the months that precede", likely meaning 
                    # they shouldn't be blocked by them.
                    contribution.status = PaymentStatus.PAID
                    contribution.payment_comment = "Pre-registration month"
                
                db.session.add(contribution)
            db.session.commit()
            
            flash(f'Member {new_member.full_name} added successfully with ID {member_id}!', 'success')
            return redirect(url_for('admin_home'))
            
        except Exception as e:
            db.session.rollback()
            
            # Build error message and identify problematic fields
            error_str = str(e)
            error_fields = []
            friendly_error = 'Unable to save member information. Please verify all fields are filled correctly.'
            
            # For database errors, identify which field is problematic and give specific messages
            # System-provided inputs (dates, selects) are formatted correctly by the browser
            # NOTE: Do NOT check for spouse name errors (first_name, last_name, father_name)
            if 'spouse' in error_str.lower():
                if 'phone' in error_str.lower():
                    # Only show error if phone is NOT valid 10-digit number
                    spouse_phone = request.form.get('spouse_phone', '').strip() or None
                    if spouse_phone and not is_valid_phone(spouse_phone):
                        error_fields.append('spouse_phone')
                        friendly_error = 'There is an issue with the Spouse Phone Number. Please check and try again.'
                elif 'email' in error_str.lower():
                    error_fields.append('spouse_email')
                    friendly_error = 'There is an issue with the Spouse Email. Please check and try again.'
                elif 'date' in error_str.lower():
                    error_fields.append('spouse_date_of_birth')
                    friendly_error = 'There is an issue with the Spouse Date of Birth. Please check and try again.'
                elif 'baptismal' in error_str.lower():
                    error_fields.append('spouse_baptismal_name')
                    friendly_error = 'There is an issue with the Spouse Baptismal Name. Please check and try again.'
            
            flash(friendly_error, 'danger')
            
            # Pass form data and error fields back to template
            return render_template('add_member.html', 
                                 suggested_id=suggested_id,
                                 form_data=request.form,
                                 error_fields=error_fields)
    
    return render_template('add_member.html', suggested_id=suggested_id)

@app.route('/admin/edit-member/<member_id>', methods=['GET', 'POST'])
@admin_required
def edit_member(member_id):
    """Edit member information"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    if request.method == 'POST':
        try:
            new_id = request.form.get('member_id', '').strip().upper()
            marital_status_str = request.form.get('marital_status', 'single').strip()
            marital_status = marital_status_str if marital_status_str in ['single', 'married', 'single_with_children'] else 'single'
            
            first_name = request.form.get('first_name', '').strip()
            middle_name = request.form.get('middle_name', '').strip() or None
            last_name = request.form.get('last_name', '').strip()
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            monthly_payment = request.form.get('monthly_payment', '').strip()
            
            if not all([new_id, first_name, last_name, phone, email, monthly_payment]):
                flash('All required fields must be filled.', 'danger')
                return render_template('edit_member.html', member=member)
            
            try:
                monthly_amount = float(monthly_payment)
                if monthly_amount < 25:
                    flash(f'Monthly payment must be at least $25.', 'danger')
                    return render_template('edit_member.html', member=member)
            except ValueError:
                flash('Monthly payment must be a valid number.', 'danger')
                return render_template('edit_member.html', member=member)
            
            member.member_id = new_id
            member.marital_status = marital_status
            member.first_name = first_name
            member.middle_name = middle_name
            member.last_name = last_name
            member.phone = phone
            member.email = email
            member.monthly_payment = monthly_amount
            
            db.session.commit()
            flash(f'Member information updated successfully!', 'success')
            return redirect(url_for('admin_home'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating member: {str(e)}', 'danger')
            return render_template('edit_member.html', member=member)
    
    return render_template('edit_member.html', member=member)

@app.route('/admin/delete-member/<member_id>')
@admin_required
def delete_member(member_id):
    """Delete member (soft delete)"""
    member = Member.query.filter_by(member_id=member_id).first()
    if member:
        member.is_active = False
        db.session.commit()
        flash('Member deleted successfully!', 'success')
    else:
        flash('Member not found.', 'danger')
    return redirect(url_for('admin_home'))

@app.route('/admin/member-details/<member_id>')
@staff_required
def member_details(member_id):
    """View member details with 12-month breakdown"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    current_year = get_current_time().year
    selected_year = int(request.args.get('year', current_year))
    
    # Get contributions for selected year
    contributions_list = Contribution.query.filter_by(
        member_id=member.id, 
        year=selected_year
    ).all()
    
    # If no contributions for year, create them
    if not contributions_list:
        for month in MONTHS:
            contribution = Contribution(
                member_id=member.id,
                year=selected_year,
                month=month,
                status=PaymentStatus.UNPAID,
                amount=0
            )
            db.session.add(contribution)
        db.session.commit()
        contributions_list = Contribution.query.filter_by(
            member_id=member.id,
            year=selected_year
        ).all()
    
    # Convert to dict for template compatibility
    contributions = {}
    for c in contributions_list:
        contributions[c.month] = {
            'status': 'Paid' if c.status == PaymentStatus.PAID else 'Unpaid',
            'amount': c.amount or 0,
            'date': c.payment_date.strftime('%Y-%m-%d') if c.payment_date else '',
            'receipt': c.receipt_number or '',
            'payment_method': c.payment_method.value if c.payment_method else None,
            'processed_by': c.processed_by_user.full_name if c.processed_by_user else None
        }
    
    # Ensure all 12 months exist
    for month in MONTHS:
        if month not in contributions:
            contributions[month] = {
                'status': 'Unpaid',
                'amount': 0,
                'date': '',
                'receipt': ''
            }
    
    # Get available years for this member
    years = db.session.query(db.distinct(Contribution.year)).filter_by(
        member_id=member.id
    ).all()
    available_years = sorted([str(y[0]) for y in years], reverse=True)
    if str(current_year) not in available_years:
        available_years.insert(0, str(current_year))
    
    # Calculate stats
    paid_months = sum(1 for month in MONTHS if contributions.get(month, {}).get('status') == 'Paid')
    total_paid = sum(contributions.get(month, {}).get('amount', 0) for month in MONTHS if contributions.get(month, {}).get('status') == 'Paid')
    
    # Check if previous year is fully paid (for disabling checkboxes on new years)
    previous_year = selected_year - 1
    previous_year_exists = Contribution.query.filter(
        Contribution.member_id == member.id,
        Contribution.year == previous_year
    ).count() > 0
    
    if previous_year_exists:
        previous_year_paid = Contribution.query.filter(
            Contribution.member_id == member.id,
            Contribution.year == previous_year,
            Contribution.status == PaymentStatus.PAID
        ).count()
        previous_year_complete = previous_year_paid >= 12
    else:
        previous_year_complete = True
    
    # Fetch next year contributions for cross-year payments
    next_year = selected_year + 1
    next_year_contributions_list = Contribution.query.filter_by(
        member_id=member.id,
        year=next_year
    ).all()
    
    # Convert next year contributions to dict
    next_year_contributions = {}
    for c in next_year_contributions_list:
        next_year_contributions[c.month] = {
            'status': 'Paid' if c.status == PaymentStatus.PAID else 'Unpaid',
            'amount': c.amount or 0,
            'date': c.payment_date.strftime('%Y-%m-%d') if c.payment_date else '',
            'receipt': c.receipt_number or '',
            'payment_method': c.payment_method.value if c.payment_method else None,
            'processed_by': c.processed_by_user.full_name if c.processed_by_user else None
        }
    
    # Ensure all 12 months exist for next year too
    for month in MONTHS:
        if month not in next_year_contributions:
            next_year_contributions[month] = {
                'status': 'Unpaid',
                'amount': 0,
                'date': '',
                'receipt': ''
            }
    
    # Get receipt data from session if available (after payment)
    receipt_data = session.pop('receipt_data', None)
    
    # Convert member to dict-like object for template compatibility
    member_dict = {
        'id': member.member_id,
        'member_id': member.member_id,
        'name': member.full_name,
        'email': member.email,
        'phone': member.phone,
        'monthly_payment': member.monthly_payment,
        'db_id': member.id
    }
    
    return render_template('member_details.html', 
                         member=member_dict,
                         contributions=contributions,
                         next_year_contributions=next_year_contributions,
                         months=MONTHS,
                         selected_year=str(selected_year),
                         next_year=str(next_year),
                         available_years=available_years,
                         paid_months=paid_months,
                         total_paid=total_paid,
                         receipt_data=receipt_data,
                         previous_year_complete=previous_year_complete)

@app.route('/admin/household/<member_id>')
@staff_required
def household_information(member_id):
    """View full household information (spouse and children)"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Get spouse and children information
    spouse = Spouse.query.filter_by(member_id=member.id).first()
    children = Child.query.filter_by(member_id=member.id).all()
    
    # Get current user to check if admin
    current_user = get_current_user()
    
    return render_template('household_information.html', 
                         member=member,
                         spouse=spouse,
                         children=children,
                         current_user=current_user)

@app.route('/admin/edit-household/<member_id>', methods=['GET', 'POST'])
@admin_required
def edit_household(member_id):
    """Edit household information (spouse and children) - admin only"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    if request.method == 'POST':
        try:
            # Update member information
            member.first_name = request.form.get('first_name', '').strip()
            member.father_name = request.form.get('father_name', '').strip() or None
            member.middle_name = request.form.get('middle_name', '').strip() or None
            member.last_name = request.form.get('last_name', '').strip()
            member.baptismal_name = request.form.get('baptismal_name', '').strip() or None
            member.confession_name = request.form.get('confession_name', '').strip() or None
            
            dob_str = request.form.get('date_of_birth', '').strip()
            if dob_str:
                try:
                    member.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            
            member.gender = request.form.get('gender', '').strip() or None
            member.address = request.form.get('address', '').strip() or None
            member.city = request.form.get('city', '').strip() or None
            member.state = request.form.get('state', '').strip() or 'WA'
            member.zip_code = request.form.get('zip_code', '').strip() or None
            member.email = request.form.get('email', '').strip() or None
            member.phone = request.form.get('phone', '').strip()
            
            # Get spouse information from form
            spouse_first_name = request.form.get('spouse_first_name', '').strip() or None
            spouse = Spouse.query.filter_by(member_id=member.id).first()
            
            # If spouse info provided, create or update
            if spouse_first_name:
                spouse_father_name = request.form.get('spouse_father_name', '').strip() or None
                spouse_last_name = request.form.get('spouse_last_name', '').strip() or None
                spouse_baptismal_name = request.form.get('spouse_baptismal_name', '').strip() or None
                spouse_dob_str = request.form.get('spouse_date_of_birth', '').strip()
                spouse_gender = request.form.get('spouse_gender', '').strip() or None
                spouse_phone = request.form.get('spouse_phone', '').strip() or None
                spouse_email = request.form.get('spouse_email', '').strip() or None
                
                spouse_dob = None
                if spouse_dob_str:
                    try:
                        spouse_dob = datetime.strptime(spouse_dob_str, '%Y-%m-%d').date()
                    except ValueError:
                        pass
                
                if spouse:
                    spouse.first_name = spouse_first_name
                    spouse.middle_name = spouse_middle_name
                    spouse.last_name = spouse_last_name
                    spouse.baptismal_name = spouse_baptismal_name
                    spouse.date_of_birth = spouse_dob
                    spouse.gender = spouse_gender
                    spouse.phone = spouse_phone
                    spouse.email = spouse_email
                else:
                    spouse = Spouse(
                        member_id=member.id,
                        first_name=spouse_first_name,
                        middle_name=spouse_middle_name,
                        last_name=spouse_last_name,
                        baptismal_name=spouse_baptismal_name,
                        date_of_birth=spouse_dob,
                        gender=spouse_gender,
                        phone=spouse_phone,
                        email=spouse_email
                    )
                    db.session.add(spouse)
            elif spouse:
                # Delete spouse if no name provided
                db.session.delete(spouse)
            
            # Handle children - delete those marked for deletion
            children_to_delete = request.form.getlist('delete_child')
            for child_id in children_to_delete:
                try:
                    child = Child.query.filter_by(id=int(child_id), member_id=member.id).first()
                    if child:
                        db.session.delete(child)
                except (ValueError, TypeError):
                    pass
            
            # Handle existing children updates
            existing_children = Child.query.filter_by(member_id=member.id).all()
            for child in existing_children:
                child_baptismal = request.form.get(f'child_baptismal_{child.id}', '').strip() or None
                child_dob_str = request.form.get(f'child_dob_{child.id}', '').strip()
                child_gender = request.form.get(f'child_gender_{child.id}', '').strip() or None
                
                child_dob = None
                if child_dob_str:
                    try:
                        child_dob = datetime.strptime(child_dob_str, '%Y-%m-%d').date()
                    except ValueError:
                        pass
                
                child.baptismal_name = child_baptismal
                child.date_of_birth = child_dob
                child.gender = child_gender
            
            # Handle new children
            new_children_count = int(request.form.get('new_children_count', 0))
            for i in range(new_children_count):
                child_name = request.form.get(f'new_child_name_{i}', '').strip()
                if child_name:
                    child_baptismal = request.form.get(f'new_child_baptismal_{i}', '').strip() or None
                    child_dob_str = request.form.get(f'new_child_dob_{i}', '').strip()
                    child_gender = request.form.get(f'new_child_gender_{i}', '').strip() or None
                    
                    child_dob = None
                    if child_dob_str:
                        try:
                            child_dob = datetime.strptime(child_dob_str, '%Y-%m-%d').date()
                        except ValueError:
                            pass
                    
                    child = Child(
                        member_id=member.id,
                        full_name=child_name,
                        baptismal_name=child_baptismal,
                        date_of_birth=child_dob,
                        gender=child_gender
                    )
                    db.session.add(child)
            
            db.session.commit()
            flash('Household information updated successfully!', 'success')
            return redirect(url_for('household_information', member_id=member.member_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating household information: {str(e)}', 'danger')
            spouse = Spouse.query.filter_by(member_id=member.id).first()
            children = Child.query.filter_by(member_id=member.id).all()
            return render_template('edit_household.html', member=member, spouse=spouse, children=children)
    
    # GET request - load current data
    spouse = Spouse.query.filter_by(member_id=member.id).first()
    children = Child.query.filter_by(member_id=member.id).all()
    
    return render_template('edit_household.html', member=member, spouse=spouse, children=children)

@app.route('/admin/pay-month/<member_id>/<year>/<month>', methods=['POST'])
@staff_required
def admin_pay_month(member_id, year, month):
    """Admin processes a monthly payment for a member with payment method tracking"""
    current_user = get_current_user()
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Validate month
    if month not in MONTHS:
        flash('Invalid month.', 'danger')
        return redirect(url_for('member_details', member_id=member_id, year=year))
    
    year_int = int(year)
    
    # Get or create contribution record
    contribution = Contribution.query.filter_by(
        member_id=member.id,
        year=year_int,
        month=month
    ).first()
    
    if not contribution:
        contribution = Contribution(
            member_id=member.id,
            year=year_int,
            month=month,
            status=PaymentStatus.UNPAID,
            amount=0
        )
        db.session.add(contribution)
    
    # Check if already paid
    if contribution.status == PaymentStatus.PAID:
        flash('This month has already been paid.', 'warning')
        return redirect(url_for('member_details', member_id=member_id, year=year))
    
    # Get payment method from form
    payment_method_str = request.form.get('payment_method', 'cash')
    payment_method = PaymentMethod(payment_method_str) if payment_method_str else PaymentMethod.CASH
    payment_comment = request.form.get('payment_comment', '').strip()
    
    # Process payment
    receipt_number = get_next_receipt_number()
    payment_date = get_current_time()
    
    contribution.status = PaymentStatus.PAID
    contribution.amount = member.monthly_payment
    contribution.payment_date = payment_date
    contribution.receipt_number = receipt_number
    contribution.payment_method = payment_method
    contribution.payment_comment = payment_comment
    contribution.processed_by_id = current_user.id
    
    db.session.commit()
    
    # Check paid months count after payment and auto-generate next year's sheet
    paid_count = Contribution.query.filter_by(
        member_id=member.id,
        year=year_int,
        status=PaymentStatus.PAID
    ).count()
    
    if paid_count >= 11:
        # Create next year's contributions if they don't exist
        next_year = year_int + 1
        existing = Contribution.query.filter_by(member_id=member.id, year=next_year).first()
        if not existing:
            for m in MONTHS:
                new_contrib = Contribution(
                    member_id=member.id,
                    year=next_year,
                    month=m,
                    status=PaymentStatus.UNPAID,
                    amount=0
                )
                db.session.add(new_contrib)
            db.session.commit()
            flash(f'Next year ({next_year}) contribution sheet has been created!', 'info')
    
    # Check if year is now complete
    is_year_complete = paid_count == 12
    year_sheet_html = None
    
    if is_year_complete:
        # Build contributions dict for certificate
        contributions_dict = {}
        contribs = Contribution.query.filter_by(member_id=member.id, year=year_int).all()
        for c in contribs:
            contributions_dict[c.month] = {
                'amount': c.amount,
                'receipt': c.receipt_number or ''
            }
        member_dict = {'name': member.full_name, 'id': member.member_id}
        year_sheet_html = generate_year_completion_sheet(member_dict, year, contributions_dict)
        flash(f'Congratulations! {member.full_name} has completed all contributions for {year}!', 'success')
    
    # Store receipt data in session for display
    receipt_data = {
        'receipt_number': receipt_number,
        'date': payment_date.strftime('%Y-%m-%d'),
        'member_name': member.full_name,
        'member_id': member.member_id,
        'member_email': member.email or '',
        'payments': [{
            'month': month,
            'amount': member.monthly_payment
        }],
        'total': member.monthly_payment,
        'year': year,
        'is_year_complete': is_year_complete,
        'payment_method': payment_method.value,
        'processed_by': current_user.full_name or current_user.username
    }
    session['receipt_data'] = receipt_data
    
    # Store year sheet in session if complete
    if is_year_complete and year_sheet_html:
        session['year_sheet'] = year_sheet_html
    
    # Send email automatically
    if member.email:
        email_sent = send_receipt_email(
            member.email, 
            member.full_name, 
            receipt_data,
            is_year_complete,
            year_sheet_html
        )
        if email_sent:
            flash(f'Receipt emailed to {member.email}', 'info')
    
    flash(f'Payment processed successfully for {month}! Receipt: {receipt_number}', 'success')
    return redirect(url_for('member_details', member_id=member_id, year=year))

@app.route('/admin/add-donation/<member_id>', methods=['POST'])
@staff_required
def admin_add_donation(member_id):
    """Admin processes a donation/special payment"""
    current_user = get_current_user()
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    try:
        donation_reason = request.form.get('donation_reason', '').strip()
        amount_str = request.form.get('donation_amount', '').strip()
        payment_method_str = request.form.get('donation_payment_method', 'cash')
        payment_comment = request.form.get('donation_comment', '').strip()
        
        if not donation_reason or not amount_str:
            flash('Payment type and amount are required.', 'danger')
            return redirect(url_for('member_details', member_id=member_id))
        
        try:
            amount = float(amount_str)
            if amount <= 0:
                flash('Amount must be greater than zero.', 'danger')
                return redirect(url_for('member_details', member_id=member_id))
        except ValueError:
            flash('Invalid amount.', 'danger')
            return redirect(url_for('member_details', member_id=member_id))
        
        # Create donation record
        donation = Donation(
            member_id=member.id,
            amount=amount,
            purpose=donation_reason.title(),
            donation_date=get_current_time(),
            payment_method=PaymentMethod(payment_method_str) if payment_method_str else PaymentMethod.CASH,
            payment_comment=payment_comment,
            processed_by_id=current_user.id,
            receipt_number=get_next_receipt_number()
        )
        db.session.add(donation)
        db.session.commit()
        
        # Store receipt data in session for display
        receipt_data = {
            'receipt_number': donation.receipt_number,
            'date': donation.donation_date.strftime('%Y-%m-%d'),
            'member_name': member.full_name,
            'member_id': member.member_id,
            'member_email': member.email or '',
            'payments': [{
                'type': 'donation',
                'reason': donation.purpose,
                'amount': donation.amount
            }],
            'total': donation.amount,
            'payment_method': donation.payment_method.value,
            'processed_by': current_user.full_name or current_user.username,
            'payment_reason': donation_reason
        }
        session['receipt_data'] = receipt_data
        
        # Send email automatically
        if member.email:
            email_sent = send_receipt_email(
                member.email,
                member.full_name,
                receipt_data,
                False,
                None
            )
            if email_sent:
                flash(f'Receipt emailed to {member.email}', 'info')
        
        flash(f'Donation processed successfully! Receipt: {donation.receipt_number}', 'success')
        return redirect(url_for('member_details', member_id=member_id))
        
    except Exception as e:
        flash(f'Error processing donation: {str(e)}', 'danger')
        return redirect(url_for('member_details', member_id=member_id))

@app.route('/admin/bulk-pay/<member_id>/<year>', methods=['POST'])
@staff_required
def admin_bulk_pay(member_id, year):
    """Admin processes bulk payments for multiple months (including cross-year) with ONE receipt"""
    current_user = get_current_user()
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Get selected months from form - can include cross-year months in format "YEAR-MONTH"
    selected_items = request.form.getlist('month_year')
    
    if not selected_items:
        # Fallback to old format for backward compatibility
        selected_months = request.form.getlist('months')
        selected_items = [f"{year}-{m}" for m in selected_months if m in MONTHS]
    
    if not selected_items:
        flash('Please select at least one month to pay.', 'warning')
        return redirect(url_for('member_details', member_id=member_id, year=year))
    
    # Get payment method from form
    payment_method_str = request.form.get('payment_method', 'cash')
    payment_method = PaymentMethod(payment_method_str) if payment_method_str else PaymentMethod.CASH
    payment_comment = request.form.get('payment_comment', '').strip()
    
    payment_date = get_current_time()
    processed_payments = []
    skipped_months = []
    years_involved = set()
    
    # Collect valid months first (parsing YEAR-MONTH format)
    valid_months = []
    for item in selected_items:
        # Parse YEAR-MONTH format
        if '-' in item:
            parts = item.rsplit('-', 1)
            if len(parts) == 2:
                try:
                    item_year = int(parts[0])
                    month = parts[1]
                except (ValueError, IndexError):
                    continue
            else:
                continue
        else:
            # Fallback: assume it's just month name with year from parameter
            month = item
            item_year = int(year)
        
        if month not in MONTHS:
            continue
        
        years_involved.add(item_year)
        
        contrib = Contribution.query.filter_by(
            member_id=member.id,
            year=item_year,
            month=month
        ).first()
        if contrib and contrib.status == PaymentStatus.PAID:
            skipped_months.append(f"{month} {item_year}")
            continue
        valid_months.append((item_year, month))
    
    if valid_months:
        # Generate ONE receipt for all months in this transaction
        receipt_number = get_next_receipt_number()
        total_amount = len(valid_months) * member.monthly_payment
        
        for item_year, month in valid_months:
            # Get or create contribution record
            contribution = Contribution.query.filter_by(
                member_id=member.id,
                year=item_year,
                month=month
            ).first()
            
            if not contribution:
                contribution = Contribution(
                    member_id=member.id,
                    year=item_year,
                    month=month
                )
                db.session.add(contribution)
            
            contribution.status = PaymentStatus.PAID
            contribution.amount = member.monthly_payment
            contribution.payment_date = payment_date
            contribution.receipt_number = receipt_number
            contribution.payment_method = payment_method
            contribution.payment_comment = payment_comment
            contribution.processed_by_id = current_user.id
            
            processed_payments.append({
                'month': month,
                'year': item_year,
                'amount': member.monthly_payment
            })
        
        db.session.commit()
        
        # Check paid months count after payment for each year involved and auto-generate next year's sheet as needed
        for check_year in years_involved:
            paid_count = Contribution.query.filter_by(
                member_id=member.id,
                year=check_year,
                status=PaymentStatus.PAID
            ).count()
            
            if paid_count >= 11:
                next_year = check_year + 1
                existing = Contribution.query.filter_by(member_id=member.id, year=next_year).first()
                if not existing:
                    for m in MONTHS:
                        new_contrib = Contribution(
                            member_id=member.id,
                            year=next_year,
                            month=m,
                            status=PaymentStatus.UNPAID,
                            amount=0
                        )
                        db.session.add(new_contrib)
                    db.session.commit()
                    flash(f'Next year ({next_year}) contribution sheet has been created!', 'info')
        
        # Check if primary year is now complete (for receipt message)
        primary_year = int(year)
        primary_paid_count = Contribution.query.filter_by(
            member_id=member.id,
            year=primary_year,
            status=PaymentStatus.PAID
        ).count()
        is_year_complete = primary_paid_count == 12
        year_sheet_html = None
        
        if is_year_complete:
            contributions_dict = {}
            contribs = Contribution.query.filter_by(member_id=member.id, year=year_int).all()
            for c in contribs:
                contributions_dict[c.month] = {
                    'amount': c.amount,
                    'receipt': c.receipt_number or ''
                }
            member_dict = {'name': member.full_name, 'id': member.member_id}
            year_sheet_html = generate_year_completion_sheet(member_dict, year, contributions_dict)
            flash(f'Congratulations! {member.full_name} has completed all contributions for {year}!', 'success')
        
        # Store receipt data in session for display
        receipt_data = {
            'receipt_number': receipt_number,
            'date': payment_date.strftime('%Y-%m-%d'),
            'member_name': member.full_name,
            'member_id': member.member_id,
            'member_email': member.email or '',
            'payments': processed_payments,
            'total': total_amount,
            'year': year,
            'is_year_complete': is_year_complete,
            'payment_method': payment_method.value,
            'processed_by': current_user.full_name or current_user.username
        }
        session['receipt_data'] = receipt_data
        
        # Store year sheet in session if complete
        if is_year_complete and year_sheet_html:
            session['year_sheet'] = year_sheet_html
        
        # Send email automatically
        if member.email:
            email_sent = send_receipt_email(
                member.email, 
                member.full_name, 
                receipt_data,
                is_year_complete,
                year_sheet_html
            )
            if email_sent:
                flash(f'Receipt emailed to {member.email}', 'info')
        
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
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Collect all transactions grouped by receipt from contributions
    receipts = {}
    contributions = Contribution.query.filter(
        Contribution.member_id == member.id,
        Contribution.status == PaymentStatus.PAID,
        Contribution.receipt_number.isnot(None)
    ).all()
    
    for contrib in contributions:
        receipt_num = contrib.receipt_number
        if receipt_num:
            if receipt_num not in receipts:
                receipts[receipt_num] = {
                    'receipt_number': receipt_num,
                    'date': contrib.payment_date.strftime('%Y-%m-%d') if contrib.payment_date else '',
                    'payments': [],
                    'total': 0,
                    'payment_method': contrib.payment_method.value if contrib.payment_method else 'cash',
                    'processed_by': contrib.processed_by_user.full_name if contrib.processed_by_user else None
                }
            receipts[receipt_num]['payments'].append({
                'type': 'contribution',
                'month': contrib.month,
                'amount': contrib.amount
            })
            receipts[receipt_num]['total'] += contrib.amount
    
    # Add donations
    donations = Donation.query.filter(
        Donation.member_id == member.id,
        Donation.receipt_number.isnot(None)
    ).all()
    
    for donation in donations:
        receipt_num = donation.receipt_number
        if receipt_num:
            if receipt_num not in receipts:
                receipts[receipt_num] = {
                    'receipt_number': receipt_num,
                    'date': donation.donation_date.strftime('%Y-%m-%d') if donation.donation_date else '',
                    'payments': [],
                    'total': 0,
                    'payment_method': donation.payment_method.value if donation.payment_method else 'cash',
                    'processed_by': donation.processed_by_user.full_name if donation.processed_by_user else None
                }
            receipts[receipt_num]['payments'].append({
                'type': 'donation',
                'reason': donation.purpose or '',
                'amount': donation.amount
            })
            receipts[receipt_num]['total'] += donation.amount
    
    # Convert to list and sort by date (newest first)
    receipt_list = sorted(receipts.values(), key=lambda x: x['date'], reverse=True)
    
    # Get completed years
    completed_years = []
    years = db.session.query(db.distinct(Contribution.year)).filter_by(member_id=member.id).all()
    for (year,) in years:
        paid_count = Contribution.query.filter_by(
            member_id=member.id,
            year=year,
            status=PaymentStatus.PAID
        ).count()
        if paid_count == 12:
            total = db.session.query(db.func.sum(Contribution.amount)).filter_by(
                member_id=member.id,
                year=year,
                status=PaymentStatus.PAID
            ).scalar() or 0
            completed_years.append({'year': str(year), 'total': total})
    completed_years.sort(key=lambda x: x['year'], reverse=True)
    
    member_dict = {
        'id': member.member_id,
        'name': member.full_name
    }
    
    return render_template('admin_member_transactions.html',
                          member=member_dict,
                          receipts=receipt_list,
                          completed_years=completed_years)

@app.route('/admin/member/<member_id>/receipt/<receipt_number>')
@staff_required
def view_receipt(member_id, receipt_number):
    """View/reprint a specific receipt"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    # Find contributions for this receipt
    payments = []
    receipt_date = ''
    payment_method = None
    processed_by = None
    
    contributions = Contribution.query.filter_by(
        member_id=member.id,
        receipt_number=receipt_number
    ).all()
    
    for contrib in contributions:
        payments.append({
            'type': 'contribution',
            'month': contrib.month,
            'amount': contrib.amount
        })
        if not receipt_date and contrib.payment_date:
            receipt_date = contrib.payment_date.strftime('%Y-%m-%d')
            payment_method = contrib.payment_method.value if contrib.payment_method else 'cash'
            processed_by = contrib.processed_by_user.full_name if contrib.processed_by_user else None
    
    # Also check donations
    donations = Donation.query.filter_by(
        member_id=member.id,
        receipt_number=receipt_number
    ).all()
    
    for donation in donations:
        payments.append({
            'type': 'donation',
            'reason': donation.purpose or '',
            'amount': donation.amount
        })
        if not receipt_date and donation.donation_date:
            receipt_date = donation.donation_date.strftime('%Y-%m-%d')
            payment_method = donation.payment_method.value if donation.payment_method else 'cash'
            processed_by = donation.processed_by_user.full_name if donation.processed_by_user else None
    
    if not payments:
        flash('Receipt not found.', 'danger')
        return redirect(url_for('admin_member_transactions', member_id=member_id))
    
    total = sum(p['amount'] for p in payments)
    
    # Determine payment reason
    payment_reason = 'membership'  # Default to membership
    has_donation = any(p['type'] == 'donation' for p in payments)
    
    if has_donation:
        # Check if all payments are donations
        all_donations = all(p['type'] == 'donation' for p in payments)
        if all_donations:
            donation_reasons = [p.get('reason', '').lower() for p in payments if p.get('reason')]
            if 'baptism' in donation_reasons:
                payment_reason = 'baptism'
            elif 'fithat' in donation_reasons:
                payment_reason = 'fithat'
            elif 'sunday offering' in donation_reasons or 'sunday' in donation_reasons:
                payment_reason = 'sunday_offering'
            else:
                payment_reason = 'donation'
    
    receipt_data = {
        'receipt_number': receipt_number,
        'date': receipt_date,
        'member_name': member.full_name,
        'member_id': member.member_id,
        'member_email': member.email or '',
        'payments': payments,
        'total': total,
        'payment_method': payment_method,
        'processed_by': processed_by,
        'payment_reason': payment_reason
    }
    
    member_dict = {'id': member.member_id, 'name': member.full_name}
    
    return render_template('view_receipt.html',
                          member=member_dict,
                          receipt=receipt_data)

@app.route('/admin/member/<member_id>/year-certificate/<year>')
@staff_required
def view_year_certificate(member_id, year):
    """View/print year completion certificate"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    year_int = int(year)
    
    # Check if year is complete
    paid_count = Contribution.query.filter_by(
        member_id=member.id,
        year=year_int,
        status=PaymentStatus.PAID
    ).count()
    
    if paid_count != 12:
        flash('Year is not complete yet.', 'warning')
        return redirect(url_for('admin_member_transactions', member_id=member_id))
    
    # Build contributions dict for certificate
    contributions = {}
    contribs = Contribution.query.filter_by(member_id=member.id, year=year_int).all()
    for c in contribs:
        contributions[c.month] = {
            'amount': c.amount,
            'receipt': c.receipt_number or ''
        }
    
    member_dict = {'name': member.full_name, 'id': member.member_id}
    
    # Generate the certificate HTML
    certificate_html = generate_year_completion_sheet(member_dict, year, contributions)
    
    return render_template('view_certificate.html',
                          member=member_dict,
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
@admin_or_it_support
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
        
        filename = f'members_{get_current_time().strftime("%Y%m%d_%H%M%S")}.csv'
        
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
        
        filename = f'contributions_{get_current_time().strftime("%Y%m%d_%H%M%S")}.csv'
        
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
        
        filename = f'donations_{get_current_time().strftime("%Y%m%d_%H%M%S")}.csv'
    
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
    
    current_year = str(get_current_time().year)
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
    if year == str(get_current_time().year):
        month_index = MONTHS.index(month)
        for i in range(month_index):
            if contributions[MONTHS[i]]['status'] == 'Unpaid':
                flash(f'Please pay {MONTHS[i]} first. Payments must be made in order.', 'warning')
                return redirect(url_for('member_dashboard', year=year))
    
    # Process payment
    receipt_number = generate_receipt_number(data)
    payment_date = get_current_time().strftime('%Y-%m-%d')
    
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
            donation_date = get_current_time().strftime('%Y-%m-%d')
            
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

# =============================================================================
# CASHIER MANAGEMENT (Admin Only)
# =============================================================================

@app.route('/admin/users')
@admin_or_it_support
def admin_users():
    """Manage admin and cashier users"""
    users = User.query.filter_by(is_active=True).order_by(User.role, User.username).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@admin_or_it_support
def add_user():
    """Add new admin or cashier user"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'cashier')
        
        if not all([username, password, full_name]):
            flash('Username, password, and full name are required.', 'danger')
            return render_template('add_user.html')
        
        # Check if username exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('add_user.html')
        
        try:
            role_map = {'admin': UserRole.ADMIN, 'cashier': UserRole.CASHIER, 'accountant': UserRole.ACCOUNTANT}
            user_role = role_map.get(role, UserRole.CASHIER)
            new_user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=user_role,
                full_name=full_name,
                email=email
            )
            db.session.add(new_user)
            db.session.commit()
            
            flash(f'{user_role.value.capitalize()} "{username}" created successfully!', 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'danger')
    
    return render_template('add_user.html')

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@admin_or_it_support
def edit_user(user_id):
    """Edit admin or cashier user"""
    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))
    
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'cashier')
        new_password = request.form.get('password', '').strip()
        
        if not full_name:
            flash('Full name is required.', 'danger')
            return render_template('edit_user.html', user=user)
        
        try:
            user.full_name = full_name
            user.email = email
            role_map = {'admin': UserRole.ADMIN, 'cashier': UserRole.CASHIER, 'accountant': UserRole.ACCOUNTANT}
            user.role = role_map.get(role, UserRole.CASHIER)
            
            if new_password:
                user.password_hash = generate_password_hash(new_password)
            
            db.session.commit()
            flash('User updated successfully!', 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating user: {str(e)}', 'danger')
    
    return render_template('edit_user.html', user=user)

@app.route('/admin/users/delete/<int:user_id>')
@admin_or_it_support
def delete_user(user_id):
    """Delete (deactivate) admin or cashier user"""
    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))
    
    # Prevent deleting the current user
    if user.id == session.get('user_id'):
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_users'))
    
    user.is_active = False
    db.session.commit()
    flash(f'User "{user.username}" has been deactivated.', 'success')
    return redirect(url_for('admin_users'))

# =============================================================================
# ARCHIVE MANAGEMENT
# =============================================================================

@app.route('/admin/archive')
@admin_or_it_support
def archive():
    """View archived members and users"""
    archived_members = Member.query.filter_by(is_active=False).all()
    archived_users = User.query.filter_by(is_active=False).all()
    
    # Calculate contribution statistics for each member
    for member in archived_members:
        # Get all contributions
        contributions = Contribution.query.filter_by(member_id=member.id).all()
        paid_contributions = [c for c in contributions if c.status == PaymentStatus.PAID]
        
        # Calculate totals
        member.total_contributions = sum(c.amount for c in paid_contributions)
        member.paid_months = len(paid_contributions)
        member.total_months = len(contributions)
        
        # Get years active
        years = sorted(set(c.year for c in contributions))
        member.years_active = ', '.join(str(y) for y in years) if years else 'None'
        
        # Get last payment date
        if paid_contributions:
            member.last_payment_date = max(c.payment_date for c in paid_contributions if c.payment_date)
        else:
            member.last_payment_date = None
    
    return render_template('archive.html', 
                         archived_members=archived_members,
                         archived_users=archived_users)

@app.route('/admin/restore-member/<member_id>')
@admin_or_it_support
def restore_member(member_id):
    """Restore an archived member"""
    member = Member.query.filter_by(member_id=member_id).first()
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('archive'))
    
    member.is_active = True
    db.session.commit()
    flash(f'Member "{member.full_name}" has been restored.', 'success')
    return redirect(url_for('archive'))

@app.route('/admin/restore-user/<int:user_id>')
@admin_or_it_support
def restore_user(user_id):
    """Restore an archived user"""
    user = User.query.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('archive'))
    
    user.is_active = True
    db.session.commit()
    flash(f'User "{user.username}" has been restored.', 'success')
    return redirect(url_for('archive'))

# =============================================================================
# ADMIN CORRECTIONS WITH CHANGE LOGGING
# =============================================================================

@app.route('/admin/correction/<member_id>/<int:year>/<month>', methods=['GET', 'POST'])
@admin_required
def admin_correction(member_id, year, month):
    """Admin correction of a contribution with mandatory comment"""
    member = Member.query.filter_by(member_id=member_id).first()
    
    if not member:
        flash('Member not found.', 'danger')
        return redirect(url_for('admin_home'))
    
    contribution = Contribution.query.filter_by(
        member_id=member.id,
        year=year,
        month=month
    ).first()
    
    if not contribution:
        flash('Contribution record not found.', 'danger')
        return redirect(url_for('member_details', member_id=member_id, year=str(year)))
    
    current_user = get_current_user()
    
    if request.method == 'POST':
        new_amount = request.form.get('amount', '').strip()
        new_status = request.form.get('status', contribution.status.value)
        new_payment_method = request.form.get('payment_method', '')
        correction_comment = request.form.get('comment', '').strip()
        
        if not correction_comment:
            flash('A comment explaining the correction is required.', 'danger')
            return render_template('admin_correction.html', 
                                 member=member, 
                                 contribution=contribution,
                                 year=year,
                                 month=month,
                                 payment_methods=PaymentMethod)
        
        try:
            # Log changes
            changes_made = []
            
            if new_amount:
                new_amount_float = float(new_amount)
                if new_amount_float != contribution.amount:
                    log = ChangeLog(
                        contribution_id=contribution.id,
                        changed_by_id=current_user.id,
                        change_type='amount_correction',
                        old_value=str(contribution.amount),
                        new_value=str(new_amount_float),
                        comment=correction_comment
                    )
                    db.session.add(log)
                    contribution.amount = new_amount_float
                    changes_made.append('amount')
            
            if new_status:
                new_status_enum = PaymentStatus(new_status)
                if new_status_enum != contribution.status:
                    log = ChangeLog(
                        contribution_id=contribution.id,
                        changed_by_id=current_user.id,
                        change_type='status_change',
                        old_value=contribution.status.value,
                        new_value=new_status_enum.value,
                        comment=correction_comment
                    )
                    db.session.add(log)
                    contribution.status = new_status_enum
                    changes_made.append('status')
            
            if new_payment_method and contribution.payment_method:
                new_method_enum = PaymentMethod(new_payment_method)
                if new_method_enum != contribution.payment_method:
                    log = ChangeLog(
                        contribution_id=contribution.id,
                        changed_by_id=current_user.id,
                        change_type='payment_method_change',
                        old_value=contribution.payment_method.value,
                        new_value=new_method_enum.value,
                        comment=correction_comment
                    )
                    db.session.add(log)
                    contribution.payment_method = new_method_enum
                    changes_made.append('payment method')
            
            if changes_made:
                db.session.commit()
                flash(f'Correction applied: {", ".join(changes_made)} updated. Change logged.', 'success')
            else:
                flash('No changes were made.', 'info')
            
            return redirect(url_for('member_details', member_id=member_id, year=str(year)))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error applying correction: {str(e)}', 'danger')
    
    # Get change history for this contribution
    change_history = ChangeLog.query.filter_by(
        contribution_id=contribution.id
    ).order_by(ChangeLog.changed_at.desc()).all()
    
    return render_template('admin_correction.html', 
                         member=member, 
                         contribution=contribution,
                         year=year,
                         month=month,
                         payment_methods=PaymentMethod,
                         change_history=change_history)

# =============================================================================
# DAILY REPORTS
# =============================================================================

def get_month_range_display(months_list, year):
    """Convert list of months to range display like 'January to March 2024'"""
    month_order = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    
    if not months_list:
        return ""
    
    sorted_months = sorted(months_list, key=lambda m: month_order.index(m) if m in month_order else 0)
    
    if len(sorted_months) == 1:
        return f"{sorted_months[0]} {year}"
    else:
        return f"{sorted_months[0]} to {sorted_months[-1]} {year}"

@app.route('/admin/reports/daily')
@staff_required
def daily_report():
    """Daily report showing transactions - all staff for admins, only own for cashiers"""
    from datetime import timedelta
    
    current_user = get_current_user()
    is_admin = current_user.role == UserRole.ADMIN
    is_accountant = current_user.role == UserRole.ACCOUNTANT
    
    # For admins, allow toggling between all_staff and admin_only views
    report_view = request.args.get('view', 'all_staff')
    if not is_admin:
        report_view = 'own'  # Cashiers always see their own
    
    report_date = request.args.get('date', get_current_time().strftime('%Y-%m-%d'))
    try:
        target_date = datetime.strptime(report_date, '%Y-%m-%d')
    except ValueError:
        target_date = get_current_time()
    
    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    
    # Build base queries
    contrib_query = Contribution.query.filter(
        Contribution.payment_date >= start_of_day,
        Contribution.payment_date < end_of_day,
        Contribution.status == PaymentStatus.PAID
    )
    
    donation_query = Donation.query.filter(
        Donation.donation_date >= start_of_day,
        Donation.donation_date < end_of_day
    )
    
    non_member_query = NonMemberTransaction.query.filter(
        NonMemberTransaction.transaction_date >= start_of_day,
        NonMemberTransaction.transaction_date < end_of_day
    )
    
    # Apply filters based on user role and view preference
    if report_view == 'admin_only':
        # Admin viewing only their transactions
        contrib_query = contrib_query.filter(Contribution.processed_by_id == current_user.id)
        donation_query = donation_query.filter(Donation.processed_by_id == current_user.id)
        non_member_query = non_member_query.filter(NonMemberTransaction.processed_by_id == current_user.id)
    elif report_view == 'own':
        # Cashiers always see only their transactions
        contrib_query = contrib_query.filter(Contribution.processed_by_id == current_user.id)
        donation_query = donation_query.filter(Donation.processed_by_id == current_user.id)
        non_member_query = non_member_query.filter(NonMemberTransaction.processed_by_id == current_user.id)
    # else: all_staff (default for admins) - no filter, show all
    
    contributions = contrib_query.all()
    donations = donation_query.all()
    non_member_txns = non_member_query.all()
    
    receipts = {}
    total_amount = 0
    totals_by_method = {'cash': 0, 'zelle': 0, 'venmo': 0, 'credit_card': 0, 'other': 0}
    
    for contrib in contributions:
        receipt_num = contrib.receipt_number or 'No Receipt'
        if receipt_num not in receipts:
            receipts[receipt_num] = {
                'receipt_number': receipt_num,
                'member': contrib.member.full_name if contrib.member else 'Unknown',
                'member_id': contrib.member.member_id if contrib.member else 'N/A',
                'is_member': True,
                'months': [],
                'year': contrib.year,
                'total': 0,
                'payment_method': contrib.payment_method.value if contrib.payment_method else 'N/A',
                'processed_by': contrib.processed_by_user.full_name if contrib.processed_by_user else 'Unknown',
                'time': contrib.payment_date.strftime('%H:%M') if contrib.payment_date else '',
                'description': '',
                'payment_reason': 'membership'
            }
        receipts[receipt_num]['months'].append(contrib.month)
        receipts[receipt_num]['total'] += contrib.amount
        total_amount += contrib.amount
        if contrib.payment_method:
            totals_by_method[contrib.payment_method.value] = totals_by_method.get(contrib.payment_method.value, 0) + contrib.amount
    
    for receipt_num, receipt_data in receipts.items():
        if receipt_data.get('months'):
            receipt_data['description'] = get_month_range_display(receipt_data['months'], receipt_data['year'])
    
    for donation in donations:
        receipt_num = donation.receipt_number or f'DON-{donation.id}'
        # Determine payment reason based on donation purpose
        donation_purpose = (donation.purpose or 'donation').lower()
        payment_reason = 'donation'
        if 'membership' in donation_purpose:
            payment_reason = 'membership'
        elif 'baptism' in donation_purpose:
            payment_reason = 'baptism'
        elif 'fithat' in donation_purpose:
            payment_reason = 'fithat'
        elif 'sunday' in donation_purpose or 'offering' in donation_purpose:
            payment_reason = 'sunday_offering'
        elif 'building' in donation_purpose:
            payment_reason = 'building_donation'
        
        if receipt_num not in receipts:
            receipts[receipt_num] = {
                'receipt_number': receipt_num,
                'member': donation.member.full_name if donation.member else 'Unknown',
                'member_id': donation.member.member_id if donation.member else 'N/A',
                'is_member': True,
                'months': [],
                'year': None,
                'total': 0,
                'payment_method': donation.payment_method.value if donation.payment_method else 'N/A',
                'processed_by': donation.processed_by_user.full_name if donation.processed_by_user else 'Unknown',
                'time': donation.donation_date.strftime('%H:%M') if donation.donation_date else '',
                'description': f"Donation: {donation.purpose or 'General'}",
                'payment_reason': payment_reason
            }
        receipts[receipt_num]['total'] += donation.amount
        total_amount += donation.amount
        if donation.payment_method:
            totals_by_method[donation.payment_method.value] = totals_by_method.get(donation.payment_method.value, 0) + donation.amount
    
    for txn in non_member_txns:
        receipt_num = txn.receipt_number or f'NM-{txn.id}'
        # Determine payment reason based on purpose
        purpose = (txn.purpose or 'other').lower()
        payment_reason = 'other'
        if 'membership' in purpose:
            payment_reason = 'membership'
        elif 'baptism' in purpose:
            payment_reason = 'baptism'
        elif 'fithat' in purpose:
            payment_reason = 'fithat'
        elif 'sunday' in purpose or 'offering' in purpose:
            payment_reason = 'sunday_offering'
        elif 'building' in purpose:
            payment_reason = 'building_donation'
        elif 'donation' in purpose:
            payment_reason = 'donation'
        
        receipts[receipt_num] = {
            'receipt_number': receipt_num,
            'member': txn.full_name,
            'member_id': 'Non-Member',
            'is_member': False,
            'txn_id': txn.id,
            'months': [],
            'year': None,
            'total': txn.amount,
            'payment_method': txn.payment_method.value if txn.payment_method else 'N/A',
            'processed_by': txn.processed_by_user.full_name if txn.processed_by_user else 'Unknown',
            'time': txn.transaction_date.strftime('%H:%M') if txn.transaction_date else '',
            'description': txn.purpose or 'General',
            'payment_reason': payment_reason
        }
        total_amount += txn.amount
        if txn.payment_method:
            totals_by_method[txn.payment_method.value] = totals_by_method.get(txn.payment_method.value, 0) + txn.amount
    
    # Group receipts by processed_by (staff member)
    grouped_receipts = {}
    for receipt in receipts.values():
        staff_name = receipt['processed_by']
        if staff_name not in grouped_receipts:
            grouped_receipts[staff_name] = {
                'staff_name': staff_name,
                'total': 0,
                'receipts': []
            }
        grouped_receipts[staff_name]['total'] += receipt['total']
        grouped_receipts[staff_name]['receipts'].append(receipt)
    
    # Sort by staff name
    sorted_groups = sorted(grouped_receipts.values(), key=lambda x: x['staff_name'])
    
    return render_template('daily_report.html',
                         report_date=target_date.strftime('%Y-%m-%d'),
                         receipt_groups=sorted_groups,
                         total_amount=total_amount,
                         totals_by_method=totals_by_method,
                         receipt_count=len(receipts),
                         is_admin=is_admin,
                         report_view=report_view)

# =============================================================================
# FINANCIAL REPORTS (Accountant & Admin Access)
# =============================================================================

@app.route('/admin/reports/dashboard')
@accountant_or_admin
def financial_dashboard():
    """Financial Dashboard with overview cards and key metrics"""
    current_user = get_current_user()
    current_year = get_current_time().year
    current_month = get_current_time().month
    
    # Total active members
    total_members = Member.query.filter_by(is_active=True).count()
    
    # Year-to-date contributions
    ytd_contributions = db.session.query(db.func.sum(Contribution.amount)).filter(
        Contribution.year == current_year,
        Contribution.status == PaymentStatus.PAID
    ).scalar() or 0
    
    # Year-to-date donations
    ytd_donations = db.session.query(db.func.sum(Donation.amount)).filter(
        db.extract('year', Donation.donation_date) == current_year
    ).scalar() or 0
    
    # Current month contributions
    month_contributions = db.session.query(db.func.sum(Contribution.amount)).filter(
        Contribution.year == current_year,
        Contribution.status == PaymentStatus.PAID,
        db.extract('month', Contribution.payment_date) == current_month
    ).scalar() or 0
    
    # Non-member transactions YTD
    ytd_non_member = db.session.query(db.func.sum(NonMemberTransaction.amount)).filter(
        db.extract('year', NonMemberTransaction.transaction_date) == current_year
    ).scalar() or 0
    
    # Payment method breakdown for current year
    payment_methods = db.session.query(
        Contribution.payment_method,
        db.func.sum(Contribution.amount)
    ).filter(
        Contribution.year == current_year,
        Contribution.status == PaymentStatus.PAID
    ).group_by(Contribution.payment_method).all()
    
    method_breakdown = {pm.value if pm else 'unknown': amt or 0 for pm, amt in payment_methods}
    
    # Monthly trend for current year
    monthly_data = []
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    for i in range(1, 13):
        month_total = db.session.query(db.func.sum(Contribution.amount)).filter(
            Contribution.year == current_year,
            Contribution.status == PaymentStatus.PAID,
            db.extract('month', Contribution.payment_date) == i
        ).scalar() or 0
        monthly_data.append({'month': month_names[i-1], 'amount': float(month_total)})
    
    # Payment reason breakdown
    reason_data = {
        'membership': float(ytd_contributions),
        'donations': float(ytd_donations),
        'non_member': float(ytd_non_member)
    }
    
    return render_template('financial_dashboard.html',
                         current_year=current_year,
                         total_members=total_members,
                         ytd_contributions=ytd_contributions,
                         ytd_donations=ytd_donations,
                         month_contributions=month_contributions,
                         ytd_non_member=ytd_non_member,
                         ytd_total=ytd_contributions + ytd_donations + ytd_non_member,
                         method_breakdown=method_breakdown,
                         monthly_data=monthly_data,
                         reason_data=reason_data)

@app.route('/admin/reports/monthly')
@accountant_or_admin
def monthly_summary_report():
    """Monthly Financial Summary Report with trends and breakdowns"""
    current_user = get_current_user()
    
    year = request.args.get('year', get_current_time().year, type=int)
    month = request.args.get('month', get_current_time().month, type=int)
    
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    
    # Contributions for selected month
    contributions = Contribution.query.filter(
        Contribution.year == year,
        Contribution.status == PaymentStatus.PAID,
        db.extract('month', Contribution.payment_date) == month
    ).all()
    
    # Donations for selected month
    donations = Donation.query.filter(
        db.extract('year', Donation.donation_date) == year,
        db.extract('month', Donation.donation_date) == month
    ).all()
    
    # Non-member transactions for selected month
    non_member_txns = NonMemberTransaction.query.filter(
        db.extract('year', NonMemberTransaction.transaction_date) == year,
        db.extract('month', NonMemberTransaction.transaction_date) == month
    ).all()
    
    # Calculate totals
    total_contributions = sum(c.amount for c in contributions)
    total_donations = sum(d.amount for d in donations)
    total_non_member = sum(t.amount for t in non_member_txns)
    
    # Payment method breakdown
    method_totals = {}
    for c in contributions:
        method = c.payment_method.value if c.payment_method else 'unknown'
        method_totals[method] = method_totals.get(method, 0) + c.amount
    for d in donations:
        method = d.payment_method.value if d.payment_method else 'unknown'
        method_totals[method] = method_totals.get(method, 0) + d.amount
    for t in non_member_txns:
        method = t.payment_method.value if t.payment_method else 'unknown'
        method_totals[method] = method_totals.get(method, 0) + t.amount
    
    # Previous month comparison
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    
    prev_contributions = db.session.query(db.func.sum(Contribution.amount)).filter(
        Contribution.year == prev_year,
        Contribution.status == PaymentStatus.PAID,
        db.extract('month', Contribution.payment_date) == prev_month
    ).scalar() or 0
    
    change_percent = 0
    if prev_contributions > 0:
        change_percent = ((total_contributions - prev_contributions) / prev_contributions) * 100
    
    return render_template('monthly_summary_report.html',
                         year=year,
                         month=month,
                         month_name=month_names[month-1],
                         total_contributions=total_contributions,
                         total_donations=total_donations,
                         total_non_member=total_non_member,
                         grand_total=total_contributions + total_donations + total_non_member,
                         method_totals=method_totals,
                         contribution_count=len(contributions),
                         donation_count=len(donations),
                         prev_month_total=prev_contributions,
                         change_percent=change_percent,
                         month_names=month_names)

@app.route('/admin/reports/member-contributions')
@accountant_or_admin
def member_contribution_report():
    """Member Contribution Analysis Report"""
    current_user = get_current_user()
    year = request.args.get('year', get_current_time().year, type=int)
    
    members = Member.query.filter_by(is_active=True).order_by(Member.first_name, Member.last_name).all()
    
    member_data = []
    for member in members:
        contributions = Contribution.query.filter_by(
            member_id=member.id,
            year=year,
            status=PaymentStatus.PAID
        ).all()
        
        total_paid = sum(c.amount for c in contributions)
        months_paid = len(contributions)
        expected = member.monthly_payment * 12
        
        member_data.append({
            'member': member,
            'total_paid': total_paid,
            'months_paid': months_paid,
            'expected': expected,
            'balance': expected - total_paid,
            'completion_rate': (total_paid / expected * 100) if expected > 0 else 0
        })
    
    # Sort by completion rate descending
    member_data.sort(key=lambda x: x['completion_rate'], reverse=True)
    
    # Summary stats
    total_expected = sum(m['expected'] for m in member_data)
    total_collected = sum(m['total_paid'] for m in member_data)
    
    return render_template('member_contribution_report.html',
                         year=year,
                         member_data=member_data,
                         total_expected=total_expected,
                         total_collected=total_collected,
                         collection_rate=(total_collected / total_expected * 100) if total_expected > 0 else 0,
                         member_count=len(members))

@app.route('/admin/reports/donations')
@accountant_or_admin
def donation_report():
    """Donation & Special Giving Report"""
    current_user = get_current_user()
    year = request.args.get('year', get_current_time().year, type=int)
    
    donations = Donation.query.filter(
        db.extract('year', Donation.donation_date) == year
    ).order_by(Donation.donation_date.desc()).all()
    
    non_member_txns = NonMemberTransaction.query.filter(
        db.extract('year', NonMemberTransaction.transaction_date) == year
    ).order_by(NonMemberTransaction.transaction_date.desc()).all()
    
    # Categorize by purpose
    categories = {
        'membership': {'total': 0, 'count': 0},
        'baptism': {'total': 0, 'count': 0},
        'fithat': {'total': 0, 'count': 0},
        'sunday_offering': {'total': 0, 'count': 0},
        'donation': {'total': 0, 'count': 0},
        'building_donation': {'total': 0, 'count': 0},
        'other': {'total': 0, 'count': 0}
    }
    
    for d in donations:
        purpose = (d.purpose or 'donation').lower()
        category = 'donation'
        if 'membership' in purpose:
            category = 'membership'
        elif 'baptism' in purpose:
            category = 'baptism'
        elif 'fithat' in purpose:
            category = 'fithat'
        elif 'sunday' in purpose or 'offering' in purpose:
            category = 'sunday_offering'
        elif 'building' in purpose:
            category = 'building_donation'
        
        categories[category]['total'] += d.amount
        categories[category]['count'] += 1
    
    for t in non_member_txns:
        purpose = (t.purpose or 'other').lower()
        category = 'other'
        if 'membership' in purpose:
            category = 'membership'
        elif 'baptism' in purpose:
            category = 'baptism'
        elif 'fithat' in purpose:
            category = 'fithat'
        elif 'sunday' in purpose or 'offering' in purpose:
            category = 'sunday_offering'
        elif 'building' in purpose:
            category = 'building_donation'
        elif 'donation' in purpose:
            category = 'donation'
        
        categories[category]['total'] += t.amount
        categories[category]['count'] += 1
    
    total_donations = sum(d.amount for d in donations)
    total_non_member = sum(t.amount for t in non_member_txns)
    
    return render_template('donation_report.html',
                         year=year,
                         donations=donations,
                         non_member_txns=non_member_txns,
                         categories=categories,
                         total_donations=total_donations,
                         total_non_member=total_non_member,
                         grand_total=total_donations + total_non_member)

@app.route('/admin/reports/delinquent')
@accountant_or_admin
def delinquent_report():
    """Delinquent Members Report - members with unpaid months"""
    current_user = get_current_user()
    year = request.args.get('year', get_current_time().year, type=int)
    
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    
    current_month_idx = get_current_time().month if year == get_current_time().year else 12
    
    members = Member.query.filter_by(is_active=True).order_by(Member.first_name, Member.last_name).all()
    
    delinquent_members = []
    for member in members:
        paid_months = set()
        contributions = Contribution.query.filter_by(
            member_id=member.id,
            year=year,
            status=PaymentStatus.PAID
        ).all()
        
        for c in contributions:
            paid_months.add(c.month)
        
        unpaid_months = []
        for i in range(current_month_idx):
            month = month_names[i]
            if month not in paid_months:
                unpaid_months.append(month)
        
        if unpaid_months:
            amount_owed = len(unpaid_months) * member.monthly_payment
            delinquent_members.append({
                'member': member,
                'unpaid_months': unpaid_months,
                'months_behind': len(unpaid_months),
                'amount_owed': amount_owed
            })
    
    # Sort by amount owed descending
    delinquent_members.sort(key=lambda x: x['amount_owed'], reverse=True)
    
    total_owed = sum(m['amount_owed'] for m in delinquent_members)
    
    return render_template('delinquent_report.html',
                         year=year,
                         delinquent_members=delinquent_members,
                         total_owed=total_owed,
                         delinquent_count=len(delinquent_members),
                         total_members=len(members))

@app.route('/admin/reports/year-end')
@accountant_or_admin
def year_end_report():
    """Year-End Financial Summary Report"""
    current_user = get_current_user()
    year = request.args.get('year', get_current_time().year, type=int)
    
    # Total contributions
    total_contributions = db.session.query(db.func.sum(Contribution.amount)).filter(
        Contribution.year == year,
        Contribution.status == PaymentStatus.PAID
    ).scalar() or 0
    
    # Total donations
    total_donations = db.session.query(db.func.sum(Donation.amount)).filter(
        db.extract('year', Donation.donation_date) == year
    ).scalar() or 0
    
    # Total non-member
    total_non_member = db.session.query(db.func.sum(NonMemberTransaction.amount)).filter(
        db.extract('year', NonMemberTransaction.transaction_date) == year
    ).scalar() or 0
    
    # Members with complete payments
    members = Member.query.filter_by(is_active=True).all()
    complete_count = 0
    partial_count = 0
    
    for member in members:
        paid_count = Contribution.query.filter_by(
            member_id=member.id,
            year=year,
            status=PaymentStatus.PAID
        ).count()
        
        if paid_count >= 12:
            complete_count += 1
        elif paid_count > 0:
            partial_count += 1
    
    # Monthly breakdown
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    
    monthly_breakdown = []
    for i in range(1, 13):
        month_contrib = db.session.query(db.func.sum(Contribution.amount)).filter(
            Contribution.year == year,
            Contribution.status == PaymentStatus.PAID,
            db.extract('month', Contribution.payment_date) == i
        ).scalar() or 0
        
        month_donations = db.session.query(db.func.sum(Donation.amount)).filter(
            db.extract('year', Donation.donation_date) == year,
            db.extract('month', Donation.donation_date) == i
        ).scalar() or 0
        
        monthly_breakdown.append({
            'month': month_names[i-1],
            'contributions': float(month_contrib),
            'donations': float(month_donations),
            'total': float(month_contrib) + float(month_donations)
        })
    
    # Compare to previous year
    prev_year = year - 1
    prev_contributions = db.session.query(db.func.sum(Contribution.amount)).filter(
        Contribution.year == prev_year,
        Contribution.status == PaymentStatus.PAID
    ).scalar() or 0
    
    yoy_change = 0
    if prev_contributions > 0:
        yoy_change = ((total_contributions - prev_contributions) / prev_contributions) * 100
    
    return render_template('year_end_report.html',
                         year=year,
                         total_contributions=total_contributions,
                         total_donations=total_donations,
                         total_non_member=total_non_member,
                         grand_total=total_contributions + total_donations + total_non_member,
                         complete_count=complete_count,
                         partial_count=partial_count,
                         no_payment_count=len(members) - complete_count - partial_count,
                         total_members=len(members),
                         monthly_breakdown=monthly_breakdown,
                         prev_year_total=prev_contributions,
                         yoy_change=yoy_change)

@app.route('/admin/reports/reconciliation')
@accountant_or_admin
def reconciliation_report():
    """Cash Flow & Bank Reconciliation Report"""
    current_user = get_current_user()
    
    start_date = request.args.get('start_date', (get_current_time() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', get_current_time().strftime('%Y-%m-%d'))
    
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        start = get_current_time() - timedelta(days=30)
        end = get_current_time()
    
    # Get all transactions in date range
    contributions = Contribution.query.filter(
        Contribution.payment_date >= start,
        Contribution.payment_date <= end,
        Contribution.status == PaymentStatus.PAID
    ).order_by(Contribution.payment_date).all()
    
    donations = Donation.query.filter(
        Donation.donation_date >= start,
        Donation.donation_date <= end
    ).order_by(Donation.donation_date).all()
    
    non_member_txns = NonMemberTransaction.query.filter(
        NonMemberTransaction.transaction_date >= start,
        NonMemberTransaction.transaction_date <= end
    ).order_by(NonMemberTransaction.transaction_date).all()
    
    # Group by payment method for reconciliation
    method_summary = {
        'cash': {'count': 0, 'total': 0, 'transactions': []},
        'zelle': {'count': 0, 'total': 0, 'transactions': []},
        'venmo': {'count': 0, 'total': 0, 'transactions': []},
        'credit_card': {'count': 0, 'total': 0, 'transactions': []},
        'cheque': {'count': 0, 'total': 0, 'transactions': []},
        'other': {'count': 0, 'total': 0, 'transactions': []}
    }
    
    for c in contributions:
        method = c.payment_method.value if c.payment_method else 'other'
        if method not in method_summary:
            method = 'other'
        method_summary[method]['count'] += 1
        method_summary[method]['total'] += c.amount
        method_summary[method]['transactions'].append({
            'date': c.payment_date,
            'type': 'Contribution',
            'description': f"{c.member.full_name if c.member else 'Unknown'} - {c.month} {c.year}",
            'amount': c.amount,
            'receipt': c.receipt_number
        })
    
    for d in donations:
        method = d.payment_method.value if d.payment_method else 'other'
        if method not in method_summary:
            method = 'other'
        method_summary[method]['count'] += 1
        method_summary[method]['total'] += d.amount
        method_summary[method]['transactions'].append({
            'date': d.donation_date,
            'type': 'Donation',
            'description': f"{d.member.full_name if d.member else 'Unknown'} - {d.purpose or 'General'}",
            'amount': d.amount,
            'receipt': d.receipt_number
        })
    
    for t in non_member_txns:
        method = t.payment_method.value if t.payment_method else 'other'
        if method not in method_summary:
            method = 'other'
        method_summary[method]['count'] += 1
        method_summary[method]['total'] += t.amount
        method_summary[method]['transactions'].append({
            'date': t.transaction_date,
            'type': 'Non-Member',
            'description': f"{t.full_name} - {t.purpose or 'General'}",
            'amount': t.amount,
            'receipt': t.receipt_number
        })
    
    # Sort transactions by date
    for method in method_summary:
        method_summary[method]['transactions'].sort(key=lambda x: x['date'] or datetime.min)
    
    grand_total = sum(m['total'] for m in method_summary.values())
    total_transactions = sum(m['count'] for m in method_summary.values())
    
    return render_template('reconciliation_report.html',
                         start_date=start.strftime('%Y-%m-%d'),
                         end_date=end.strftime('%Y-%m-%d'),
                         method_summary=method_summary,
                         grand_total=grand_total,
                         total_transactions=total_transactions)

# =============================================================================
# NON-MEMBER TRANSACTIONS
# =============================================================================

@app.route('/admin/non-member-transactions')
@staff_required
def non_member_transactions():
    """List all non-member transactions"""
    transactions = NonMemberTransaction.query.order_by(NonMemberTransaction.transaction_date.desc()).all()
    return render_template('non_member_transactions.html', transactions=transactions)

def sanitize_input(text, max_length=200):
    """Sanitize user input by limiting length and escaping HTML entities"""
    if not text:
        return text
    from markupsafe import escape
    text = str(text)[:max_length]
    text = str(escape(text))
    text = text.strip()
    return text if text else None

@app.route('/admin/non-member-transaction/add', methods=['GET', 'POST'])
@staff_required
def add_non_member_transaction():
    """Add a new non-member transaction"""
    current_user = get_current_user()
    
    if request.method == 'POST':
        try:
            first_name = sanitize_input(request.form.get('first_name', ''), 100)
            last_name = sanitize_input(request.form.get('last_name', ''), 100)
            email = sanitize_input(request.form.get('email', ''), 200) or None
            phone = sanitize_input(request.form.get('phone', ''), 50) or None
            amount = float(request.form.get('amount', 0))
            purpose = sanitize_input(request.form.get('purpose', ''), 200) or 'General'
            payment_method = request.form.get('payment_method', 'cash')
            payment_comment = sanitize_input(request.form.get('payment_comment', ''), 500) or None
            
            if not first_name or not last_name:
                flash('First name and last name are required.', 'danger')
                return render_template('add_non_member_transaction.html', payment_methods=PaymentMethod)
            
            if len(first_name) < 2 or len(last_name) < 2:
                flash('First name and last name must be at least 2 characters.', 'danger')
                return render_template('add_non_member_transaction.html', payment_methods=PaymentMethod)
            
            if amount <= 0:
                flash('Amount must be greater than 0.', 'danger')
                return render_template('add_non_member_transaction.html', payment_methods=PaymentMethod)
            
            receipt_number = get_next_nonmember_receipt_number()
            
            txn = NonMemberTransaction(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                amount=amount,
                purpose=purpose,
                transaction_date=datetime.utcnow(),
                receipt_number=receipt_number,
                payment_method=PaymentMethod(payment_method),
                payment_comment=payment_comment,
                processed_by_id=current_user.id if current_user else None
            )
            db.session.add(txn)
            db.session.commit()
            
            flash(f'Transaction recorded for {first_name} {last_name}. Receipt: {receipt_number}', 'success')
            
            session['non_member_receipt_data'] = {
                'receipt_number': receipt_number,
                'name': f"{first_name} {last_name}",
                'amount': amount,
                'purpose': purpose,
                'payment_method': payment_method.capitalize(),
                'date': get_current_time().strftime('%Y-%m-%d %H:%M')
            }
            
            return redirect(url_for('non_member_transactions'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding transaction: {str(e)}', 'danger')
    
    return render_template('add_non_member_transaction.html', payment_methods=PaymentMethod)

@app.route('/admin/non-member-transaction/<int:txn_id>/receipt')
@staff_required
def view_non_member_receipt(txn_id):
    """View receipt for non-member transaction"""
    txn = db.session.get(NonMemberTransaction, txn_id)
    if not txn:
        flash('Transaction not found.', 'danger')
        return redirect(url_for('non_member_transactions'))
    
    receipt_data = {
        'receipt_number': txn.receipt_number,
        'name': txn.full_name,
        'email': txn.email,
        'phone': txn.phone,
        'is_member': False,
        'line_items': [{
            'description': txn.purpose or 'General',
            'amount': txn.amount
        }],
        'total': txn.amount,
        'payment_method': txn.payment_method.value if txn.payment_method else 'N/A',
        'payment_comment': txn.payment_comment,
        'date': txn.transaction_date.strftime('%Y-%m-%d %H:%M') if txn.transaction_date else '',
        'processed_by': txn.processed_by_user.full_name if txn.processed_by_user else 'Unknown'
    }
    
    return render_template('view_non_member_receipt.html', receipt=receipt_data)

# ---------------------------------------------------------------------------
# Thermal Printer Routes
# ---------------------------------------------------------------------------

@app.route('/admin/printer-config', methods=['GET', 'POST'])
@admin_required
def printer_config():
    """Thermal printer settings page (Admin only)."""
    if request.method == 'POST':
        printer_ip   = request.form.get('printer_ip', '').strip()
        printer_port = request.form.get('printer_port', '9100').strip()
        paper_width  = request.form.get('paper_width', '80mm').strip()
        timeout      = request.form.get('timeout', '5').strip()

        SystemSetting.set('printer_ip', printer_ip)
        SystemSetting.set('printer_port', printer_port)
        SystemSetting.set('paper_width', paper_width)
        SystemSetting.set('timeout', timeout)
        db.session.commit()
        flash('Printer settings saved successfully.', 'success')
        return redirect(url_for('printer_config'))

    settings = {
        'printer_ip':   SystemSetting.get('printer_ip', ''),
        'printer_port': SystemSetting.get('printer_port', '9100'),
        'paper_width':  SystemSetting.get('paper_width', '80mm'),
        'timeout':      SystemSetting.get('timeout', '5'),
    }
    return render_template('printer_config.html', settings=settings)


@app.route('/admin/thermal-print/test', methods=['POST'])
@admin_required
def thermal_test_print():
    """Send a test page to the configured thermal printer."""
    from thermal_printer import test_printer_connection
    ip      = SystemSetting.get('printer_ip', '')
    port    = int(SystemSetting.get('printer_port', '9100'))
    timeout = int(SystemSetting.get('timeout', '5'))

    if not ip:
        return jsonify(success=False, message='No printer configured. Please set the IP address in Printer Settings first.')

    success, message = test_printer_connection(ip, port, timeout)
    return jsonify(success=success, message=message)


@app.route('/admin/thermal-print/member/<receipt_number>', methods=['POST'])
@staff_required
def thermal_print_member_receipt(receipt_number):
    """Send a member receipt to the configured thermal printer."""
    from thermal_printer import print_member_receipt

    ip         = SystemSetting.get('printer_ip', '')
    port       = int(SystemSetting.get('printer_port', '9100'))
    paper_width = SystemSetting.get('paper_width', '80mm')
    timeout    = int(SystemSetting.get('timeout', '5'))

    if not ip:
        return jsonify(success=False, message='No thermal printer configured. Go to Admin → Printer Settings to set one up.')

    # Fetch the receipt data from the database
    contributions = Contribution.query.filter_by(receipt_number=receipt_number).all()
    donations     = Donation.query.filter_by(receipt_number=receipt_number).all()

    if not contributions and not donations:
        return jsonify(success=False, message='Receipt not found.')

    member = None
    payments = []
    receipt_date = ''
    payment_method = None
    processed_by = None

    for c in contributions:
        if not member:
            member = c.member
        payments.append({'type': 'contribution', 'month': c.month, 'amount': c.amount})
        if not receipt_date and c.payment_date:
            receipt_date   = c.payment_date.strftime('%Y-%m-%d')
            payment_method = c.payment_method.value if c.payment_method else 'Cash'
            processed_by   = c.processed_by_user.full_name if c.processed_by_user else None

    for d in donations:
        if not member:
            member = d.member
        payments.append({'type': 'donation', 'reason': d.purpose or '', 'amount': d.amount})
        if not receipt_date and d.donation_date:
            receipt_date   = d.donation_date.strftime('%Y-%m-%d')
            payment_method = d.payment_method.value if d.payment_method else 'Cash'
            processed_by   = d.processed_by_user.full_name if d.processed_by_user else None

    if not member:
        return jsonify(success=False, message='Member not found for this receipt.')

    receipt_data = {
        'receipt_number': receipt_number,
        'date':           receipt_date,
        'member_name':    member.full_name,
        'member_id':      member.member_id,
        'payments':       payments,
        'total':          sum(p['amount'] for p in payments),
        'payment_method': payment_method,
        'processed_by':   processed_by,
    }

    success, message = print_member_receipt(receipt_data, ip, port, paper_width, timeout)
    return jsonify(success=success, message=message)


@app.route('/admin/thermal-print/non-member/<receipt_number>', methods=['POST'])
@staff_required
def thermal_print_non_member_receipt(receipt_number):
    """Send a non-member/guest receipt to the configured thermal printer."""
    from thermal_printer import print_non_member_receipt

    ip          = SystemSetting.get('printer_ip', '')
    port        = int(SystemSetting.get('printer_port', '9100'))
    paper_width = SystemSetting.get('paper_width', '80mm')
    timeout     = int(SystemSetting.get('timeout', '5'))

    if not ip:
        return jsonify(success=False, message='No thermal printer configured. Go to Admin → Printer Settings to set one up.')

    txn = NonMemberTransaction.query.filter_by(receipt_number=receipt_number).first()
    if not txn:
        return jsonify(success=False, message='Transaction not found.')

    receipt_data = {
        'receipt_number':  txn.receipt_number,
        'name':            txn.full_name,
        'email':           txn.email or '',
        'phone':           txn.phone or '',
        'line_items':      [{'description': txn.purpose or 'General', 'amount': txn.amount}],
        'total':           txn.amount,
        'payment_method':  txn.payment_method.value if txn.payment_method else 'Cash',
        'payment_comment': txn.payment_comment or '',
        'date':            txn.transaction_date.strftime('%Y-%m-%d') if txn.transaction_date else '',
        'processed_by':    txn.processed_by_user.full_name if txn.processed_by_user else 'Unknown',
    }

    success, message = print_non_member_receipt(receipt_data, ip, port, paper_width, timeout)
    return jsonify(success=success, message=message)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
