# ETOTC Church - Contribution Management System

## Overview
A comprehensive Flask web application for ETOTC Church to manage monthly member contributions and additional donations. The system features admin/cashier portals with role-based authentication, receipt tracking, bulk payment processing, automatic email receipts, and year completion certificates.

## Project Architecture

### Technology Stack
- **Backend**: Flask (Python 3.11) with Flask-Mail, Flask-SQLAlchemy
- **Frontend**: Bootstrap 5, Jinja2 templates
- **Database**: PostgreSQL (via DATABASE_URL), JSON fallback for legacy data
- **Email**: Flask-Mail with SMTP configuration
- **Session Management**: Flask sessions with secure secret key

### File Structure
```
.
├── main.py                 # Flask application entry point
├── data.json              # JSON database for members and contributions
├── templates/             # HTML templates
│   ├── base.html         # Base template with navigation
│   ├── index.html        # Landing page
│   ├── login.html        # Admin login page
│   ├── member_login.html # Member login page
│   ├── admin_dashboard.html
│   ├── member_dashboard.html
│   ├── add_member.html
│   ├── edit_member.html
│   ├── add_contribution.html
│   └── view_contributions.html
└── static/
    └── css/              # Static assets (unused currently, styling via Bootstrap CDN)
```

## Features

### Admin Features
- Login with hardcoded credentials (username: `admin`, password: `admin123`)
- View all members and their total contributions
- Add new members with validation (name, phone, email, member ID)
- Edit existing member information with validation
- Delete members (also removes their contributions)
- Record monthly contributions with comprehensive validation
- Edit existing contributions (month and amount)
- Delete individual contributions
- View detailed contribution history for each member
- Dashboard statistics (total members, total contributions, averages)

### Member Features
- Login using unique Member ID
- View personal information
- View contribution history
- View total contributions and contribution count

## Data Structure

### Members
```json
{
  "member_id": "M001",
  "name": "Sarah Johnson",
  "phone": "(555) 123-4567",
  "email": "sarah.johnson@email.com"
}
```

### Contributions
```json
{
  "id": 1,
  "member_id": "M001",
  "month": "2025-01",
  "amount": 150.0,
  "date_recorded": "2025-01-15 10:30:00"
}
```

## Recent Changes
- **November 30, 2025**: Added transaction history view with receipt grouping - "View History" button on member details page
- **November 30, 2025**: Added view/reprint functionality for receipts and year completion certificates anytime
- **November 30, 2025**: Auto-generates next year contribution sheet when 11th month is paid
- **November 30, 2025**: Fixed KeyError bugs with legacy data through normalize_year_contributions() helper
- **November 30, 2025**: Added automatic email receipt sending after every payment
- **November 30, 2025**: Bulk payments now generate ONE receipt for all months in a single transaction
- **November 30, 2025**: Added year completion detection and certificate generation when all 12 months are paid
- **November 30, 2025**: Configured Flask-Mail with SMTP environment variables for email functionality
- **November 14, 2025**: Made member names clickable in admin home view for easier navigation to member details
- **November 14, 2025**: Imported to Replit environment, configured workflow for Flask app on port 5000, set up deployment with Gunicorn, added .gitignore for Python, configured secure environment variables (ADMIN_PASSWORD, SESSION_SECRET)
- **October 18, 2025**: Initial project setup with Flask application, authentication system, admin and member dashboards, and sample data
- **October 18, 2025**: Added full CRUD support for contributions (edit/delete), improved data validation and error handling across all forms, enhanced JSON file operations with comprehensive error handling

## Sample Data
The application includes 5 sample members (CH001-CH005) with contribution and donation records for testing purposes.

**Note:** The sample members have encrypted passwords that aren't documented. To test the member portal:
1. Log in as admin (username: `admin`, password: your ADMIN_PASSWORD secret)
2. Create a new member with a password you choose
3. Log out and test member login with that new member's credentials

Alternatively, you can use the admin panel to view and manage the existing sample members.

## Replit Configuration

### Environment Variables
- **ADMIN_PASSWORD**: Admin login password (required, stored in Replit Secrets)
- **SESSION_SECRET**: Flask session secret key (optional, auto-generated if not set)
- **ADMIN_USERNAME**: Admin username (defaults to "admin")

### Workflow
- **Development**: Flask development server runs on port 5000 with debug mode
- **Command**: `uv run python main.py`

### Deployment
- **Target**: Autoscale (stateless web application)
- **Production Server**: Gunicorn WSGI server
- **Command**: `uv run gunicorn --bind=0.0.0.0:5000 --reuse-port main:app`

### Dependencies
Managed via uv (pyproject.toml):
- flask>=3.1.2
- gunicorn>=23.0.0
- werkzeug>=3.1.3
- pdf2image>=1.17.0
- pillow>=12.0.0
- pypdf2>=3.0.1

## Security Notes
- Admin credentials secured via environment variables (ADMIN_PASSWORD)
- Password hashing implemented using Werkzeug's generate_password_hash/check_password_hash
- Session secret should be set via SESSION_SECRET environment variable for production

## Future Enhancements
- Replace JSON storage with PostgreSQL database (Replit DB integration)
- Add contribution filtering and advanced reports
- Create monthly reports with charts
- Add email notifications
- Implement payment gateway integration
