from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import String, Float, Integer, DateTime, Text, ForeignKey, Enum
from datetime import datetime
import enum

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

class UserRole(enum.Enum):
    ADMIN = "admin"
    CASHIER = "cashier"
    ACCOUNTANT = "accountant"
    IT_SUPPORT = "it_support"

class PaymentMethod(enum.Enum):
    CASH = "cash"
    ZELLE = "zelle"
    VENMO = "venmo"
    CREDIT_CARD = "credit_card"
    CHEQUE = "cheque"
    OTHER = "other"

class PaymentStatus(enum.Enum):
    PAID = "Paid"
    UNPAID = "Unpaid"

class User(db.Model):
    """Admin, Cashier, Accountant, and IT Support staff users"""
    __tablename__ = 'users'
    
    id = db.Column(Integer, primary_key=True)
    username = db.Column(String(100), unique=True, nullable=False)
    password_hash = db.Column(String(255), nullable=False)
    role = db.Column(Enum(UserRole), nullable=False, default=UserRole.CASHIER)
    full_name = db.Column(String(200))
    email = db.Column(String(200))
    created_at = db.Column(DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    contributions_processed = relationship('Contribution', back_populates='processed_by_user', foreign_keys='Contribution.processed_by_id')
    donations_processed = relationship('Donation', back_populates='processed_by_user', foreign_keys='Donation.processed_by_id')
    change_logs = relationship('ChangeLog', back_populates='changed_by_user')

class Member(db.Model):
    """Church members"""
    __tablename__ = 'members'
    
    id = db.Column(Integer, primary_key=True)
    member_id = db.Column(String(20), unique=True, nullable=False)  # CH001, CH002, etc.
    first_name = db.Column(String(100), nullable=False)
    father_name = db.Column(String(100))
    last_name = db.Column(String(100), nullable=False)
    middle_name = db.Column(String(100))
    baptismal_name = db.Column(String(100))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(String(20))
    address = db.Column(String(200))
    city = db.Column(String(100))
    state = db.Column(String(50), default='WA')
    zip_code = db.Column(String(20))
    email = db.Column(String(200))
    phone = db.Column(String(50))
    confession_name = db.Column(String(100))
    marital_status = db.Column(String(20), default='single')
    password_hash = db.Column(String(255), nullable=False)
    monthly_payment = db.Column(Float, nullable=False, default=25.0)
    created_at = db.Column(DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    contributions = relationship('Contribution', back_populates='member', cascade='all, delete-orphan')
    donations = relationship('Donation', back_populates='member', cascade='all, delete-orphan')
    spouse = relationship('Spouse', back_populates='member', uselist=False, cascade='all, delete-orphan')
    children = relationship('Child', back_populates='member', cascade='all, delete-orphan')
    
    @property
    def full_name(self):
        """Generate full name from first, middle, last"""
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name}"
        return f"{self.first_name} {self.last_name}"


class Spouse(db.Model):
    """Spouse information for married members"""
    __tablename__ = 'spouses'
    
    id = db.Column(Integer, primary_key=True)
    member_id = db.Column(Integer, ForeignKey('members.id'), nullable=False, unique=True)
    first_name = db.Column(String(100), nullable=False)
    father_name = db.Column(String(100))
    middle_name = db.Column(String(100))
    last_name = db.Column(String(100))
    baptismal_name = db.Column(String(100))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(String(20))
    phone = db.Column(String(50))
    email = db.Column(String(200))
    created_at = db.Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    member = relationship('Member', back_populates='spouse')
    
    @property
    def full_name(self):
        if self.middle_name:
            return f"{self.first_name} {self.middle_name} {self.last_name or ''}"
        return f"{self.first_name} {self.last_name or ''}"


class Child(db.Model):
    """Children information for members"""
    __tablename__ = 'children'
    
    id = db.Column(Integer, primary_key=True)
    member_id = db.Column(Integer, ForeignKey('members.id'), nullable=False)
    full_name = db.Column(String(200), nullable=False)
    baptismal_name = db.Column(String(100))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(String(20))
    created_at = db.Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    member = relationship('Member', back_populates='children')

class Contribution(db.Model):
    """Monthly contributions"""
    __tablename__ = 'contributions'
    
    id = db.Column(Integer, primary_key=True)
    member_id = db.Column(Integer, ForeignKey('members.id'), nullable=False)
    year = db.Column(Integer, nullable=False)
    month = db.Column(String(20), nullable=False)  # January, February, etc.
    status = db.Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.UNPAID)
    amount = db.Column(Float, default=0.0)
    payment_date = db.Column(DateTime)
    receipt_number = db.Column(String(50))
    payment_method = db.Column(Enum(PaymentMethod))
    payment_comment = db.Column(Text)  # For cash, zelle, venmo, etc. details
    processed_by_id = db.Column(Integer, ForeignKey('users.id'))  # Admin or Cashier who processed
    created_at = db.Column(DateTime, default=datetime.utcnow)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Stripe payment tracking
    stripe_payment_intent_id = db.Column(String(100))
    
    # Relationships
    member = relationship('Member', back_populates='contributions')
    processed_by_user = relationship('User', back_populates='contributions_processed', foreign_keys=[processed_by_id])
    change_logs = relationship('ChangeLog', back_populates='contribution', cascade='all, delete-orphan')
    
    # Unique constraint: one record per member, year, month
    __table_args__ = (
        db.UniqueConstraint('member_id', 'year', 'month', name='unique_member_year_month'),
    )

class Donation(db.Model):
    """One-time donations"""
    __tablename__ = 'donations'
    
    id = db.Column(Integer, primary_key=True)
    member_id = db.Column(Integer, ForeignKey('members.id'), nullable=False)
    amount = db.Column(Float, nullable=False)
    purpose = db.Column(String(200))
    donation_date = db.Column(DateTime, nullable=False, default=datetime.utcnow)
    receipt_number = db.Column(String(50), unique=True)
    payment_method = db.Column(Enum(PaymentMethod))
    payment_comment = db.Column(Text)
    processed_by_id = db.Column(Integer, ForeignKey('users.id'))
    created_at = db.Column(DateTime, default=datetime.utcnow)
    
    # Stripe payment tracking
    stripe_payment_intent_id = db.Column(String(100))
    
    # Relationships
    member = relationship('Member', back_populates='donations')
    processed_by_user = relationship('User', back_populates='donations_processed', foreign_keys=[processed_by_id])

class ChangeLog(db.Model):
    """Track all changes made by admin/cashier to contributions"""
    __tablename__ = 'change_logs'
    
    id = db.Column(Integer, primary_key=True)
    contribution_id = db.Column(Integer, ForeignKey('contributions.id'), nullable=False)
    changed_by_id = db.Column(Integer, ForeignKey('users.id'), nullable=False)
    change_type = db.Column(String(50), nullable=False)  # 'amount_correction', 'payment_method_change', 'status_change'
    old_value = db.Column(Text)
    new_value = db.Column(Text)
    comment = db.Column(Text, nullable=False)  # Mandatory comment explaining the change
    changed_at = db.Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    contribution = relationship('Contribution', back_populates='change_logs')
    changed_by_user = relationship('User', back_populates='change_logs')

class SequenceCounter(db.Model):
    """Store sequence counters for IDs and receipts"""
    __tablename__ = 'sequence_counters'
    
    id = db.Column(Integer, primary_key=True)
    counter_name = db.Column(String(50), unique=True, nullable=False)
    counter_value = db.Column(Integer, nullable=False, default=1)
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NonMemberTransaction(db.Model):
    """Transactions for non-members (guests, visitors)"""
    __tablename__ = 'non_member_transactions'
    
    id = db.Column(Integer, primary_key=True)
    first_name = db.Column(String(100), nullable=False)
    last_name = db.Column(String(100), nullable=False)
    email = db.Column(String(200))
    phone = db.Column(String(50))
    amount = db.Column(Float, nullable=False)
    purpose = db.Column(String(200))  # Donation, Tithe, Offering, etc.
    transaction_date = db.Column(DateTime, nullable=False, default=datetime.utcnow)
    receipt_number = db.Column(String(50), unique=True)
    payment_method = db.Column(Enum(PaymentMethod))
    payment_comment = db.Column(Text)
    processed_by_id = db.Column(Integer, ForeignKey('users.id'))
    created_at = db.Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    processed_by_user = relationship('User', backref='non_member_transactions_processed')
    
    @property
    def full_name(self):
        """Generate full name from first and last"""
        return f"{self.first_name} {self.last_name}"
