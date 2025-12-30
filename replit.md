# ETOTC Church - Contribution Management System

## Overview
A comprehensive Flask web application for ETOTC Church to manage monthly member contributions and additional donations. The system features admin/cashier portals with role-based authentication, receipt tracking, bulk payment processing, automatic email receipts, payment method tracking, admin corrections with audit logging, and year completion certificates.

## Project Architecture

### Technology Stack
- **Backend**: Flask (Python 3.11) with Flask-Mail, Flask-SQLAlchemy
- **Frontend**: Bootstrap 5, Jinja2 templates
- **Database**: PostgreSQL (via DATABASE_URL)
- **ORM**: SQLAlchemy with PostgreSQL
- **Email**: Flask-Mail with SMTP configuration
- **Session Management**: Flask sessions with secure secret key

### Database Models (models.py)
- **User**: Admin and Cashier staff accounts with role-based access
- **Member**: Church members with full profile (name, address, baptismal name, marital status)
- **Spouse**: Spouse information for married members
- **Child**: Children living with members
- **Contribution**: Monthly payment records with payment method tracking
- **Donation**: Additional one-time donations
- **ChangeLog**: Audit log for admin corrections
- **NonMemberTransaction**: Transactions for guests/visitors (not church members)

### File Structure
```
.
├── main.py                 # Flask application entry point
├── models.py               # SQLAlchemy database models
├── data.json              # Legacy JSON data (migrated to PostgreSQL)
├── templates/
│   ├── base.html          # Base template with role-based navigation
│   ├── index.html         # Landing page
│   ├── login.html         # Staff (Admin/Cashier) login page
│   ├── member_login.html  # Member login page
│   ├── admin_home.html    # Staff dashboard
│   ├── member_details.html # Member contribution details with payment UI
│   ├── admin_users.html   # User management (Admin only)
│   ├── add_user.html      # Add new user form
│   ├── edit_user.html     # Edit user form
│   ├── admin_correction.html # Admin correction with change history
│   ├── daily_report.html  # Daily collections report with payment method breakdown
│   ├── non_member_transactions.html  # Non-member transaction list
│   ├── add_non_member_transaction.html  # Add non-member transaction form
│   ├── view_non_member_receipt.html  # View non-member transaction receipt
│   └── ...                # Other templates
└── static/
    └── css/               # Static assets (Bootstrap CDN used)
```

## Features

### Admin Features
- Database-backed authentication with role management
- Create, edit, delete cashier and admin users
- View all members and their total contributions
- Add, edit, delete members
- Process single and bulk monthly payments
- Track payment methods (Cash, Zelle, Venmo, Credit Card, Other)
- Make corrections to paid contributions with mandatory comments
- View change history for all corrections
- Generate daily reports by processor
- Export members, contributions, and donations to CSV
- Automatic email receipt sending

### Cashier Features
- Login with username/password
- View all members and contributions
- Process single and bulk payments
- Track payment methods
- View but not edit member details

### Member Features
- Login using Member ID and password
- View personal information
- View contribution history
- View total contributions and payment details

## Payment Methods
- **Cash**: Physical cash payments
- **Zelle**: Electronic bank transfer
- **Venmo**: Mobile payment service
- **Credit Card**: Card payments (Stripe integration pending)
- **Other**: Check, money order, etc.

## Recent Changes
- **December 30, 2025**: Added comprehensive Financial Reports system with 7 reports:
  - Financial Dashboard (overview cards, YTD metrics, monthly trends)
  - Monthly Summary Report (monthly totals with payment method breakdown)
  - Member Contribution Analysis (individual member payment status and completion rates)
  - Donation & Special Giving Report (donations categorized by purpose)
  - Delinquent Members Report (members with unpaid months and amounts owed)
  - Year-End Financial Summary (annual totals with YoY comparison)
  - Cash Flow & Bank Reconciliation (transactions grouped by payment method)
- **December 30, 2025**: Added Reports dropdown menu in navigation for Accountants and Admins
- **December 29, 2025**: Added archive management system for members and users with restore functionality
- **December 29, 2025**: Created Archive page accessible from Admin dropdown menu with two tabs (Members & Users)
- **December 29, 2025**: Added restore capabilities for archived members and users (soft delete with `is_active` flag)
- **December 29, 2025**: Fixed member edit navigation error (using member.member_id instead of member.id)
- **December 29, 2025**: Fixed UndefinedError in edit_member template by using individual name fields
- **December 29, 2025**: Centered logo on both member and non-member receipts for professional appearance
- **December 18, 2025**: Added "For" section on receipts with payment reason checkboxes (Membership, Baptism, Fithat, Sunday Offering, Donation, Other)
- **December 18, 2025**: Fixed receipt "Back to Member" button navigation
- **December 18, 2025**: Unified receipt format across point-of-sale and historical receipt views with EIN and payment method details
- **December 18, 2025**: Enhanced session handling with proper persistence (24-hour lifetime, secure cookies, permanent session flag)
- **December 18, 2025**: Fixed logged-in users seeing login pages - now redirects to dashboard
- **December 1, 2025**: Enhanced member registration form with full church membership fields
- **December 1, 2025**: Added spouse and children information for married members
- **December 1, 2025**: Conditional spouse section - only shows when "Married" is selected
- **December 1, 2025**: Fixed receipt 404 error when clicking on previous transactions
- **December 1, 2025**: Added non-member transaction feature for guests/visitors
- **December 1, 2025**: Daily report now shows month ranges (e.g., "January to March 2024")
- **December 1, 2025**: Daily report displays payment method breakdown (Cash, Zelle totals)
- **December 1, 2025**: New year payments require previous year to be fully completed
- **December 1, 2025**: Fixed cashier access to member details page
- **December 1, 2025**: Added input sanitization for security
- **November 30, 2025**: Added role-based navigation with Admin/Cashier badges
- **November 30, 2025**: Added admin correction feature with mandatory comments and change log
- **November 30, 2025**: Added daily reports showing contributions grouped by processor
- **November 30, 2025**: Added user management (create, edit, delete admin/cashier users)
- **November 30, 2025**: Added payment method tracking for all payments (single and bulk)
- **November 30, 2025**: Updated member details page with payment method selection
- **November 30, 2025**: Migrated authentication to database-backed User model
- **November 30, 2025**: Added transaction history view with receipt grouping
- **November 30, 2025**: Auto-generates next year contribution sheet when 11th month is paid
- **November 30, 2025**: Bulk payments now generate ONE receipt for all months

## Environment Variables

### Required
- **DATABASE_URL**: PostgreSQL connection string (auto-configured by Replit)
- **ADMIN_PASSWORD**: Initial admin password

### Optional
- **SESSION_SECRET**: Flask session secret key (auto-generated if not set)
- **MAIL_SERVER**: SMTP server for email receipts
- **MAIL_PORT**: SMTP port (default: 587)
- **MAIL_USERNAME**: SMTP username
- **MAIL_PASSWORD**: SMTP password
- **MAIL_USE_TLS**: Enable TLS (default: True)

## Workflow
- **Development**: `uv run python main.py` on port 5000
- **Production**: `uv run gunicorn --bind=0.0.0.0:5000 --reuse-port main:app`

## User Roles

### Admin
- Full system access
- User management (create, edit, delete users)
- Make corrections to any payment
- View daily reports
- Export data

### Cashier
- Process payments
- View members and contributions
- Cannot manage users
- Cannot make corrections
- Cannot export data

## Security Notes
- Passwords hashed using Werkzeug's generate_password_hash
- Role-based access control implemented
- All corrections logged with mandatory comments
- Session management with secure secret key

## Pending Features
- Stripe integration for credit card processing
- Member self-service payment portal
- Monthly/annual reports with charts
- Email notification preferences
