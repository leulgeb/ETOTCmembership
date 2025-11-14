# ETOTC Church - Contribution Management System

## Overview
A comprehensive Flask web application for ETOTC Church to manage monthly member contributions and additional donations. The system features admin and member portals with auto-generated IDs, receipt tracking, payment management, and CSV export capabilities.

## Project Architecture

### Technology Stack
- **Backend**: Flask (Python 3.11)
- **Frontend**: Bootstrap 5, Jinja2 templates
- **Data Storage**: JSON file (data.json)
- **Session Management**: Flask sessions with secret key

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
- **October 18, 2025**: Initial project setup with Flask application, authentication system, admin and member dashboards, and sample data
- **October 18, 2025**: Added full CRUD support for contributions (edit/delete), improved data validation and error handling across all forms, enhanced JSON file operations with comprehensive error handling

## Sample Data
The application includes 5 sample members (M001-M005) with 13 contribution records for testing purposes.

## Security Notes
- Admin credentials are currently hardcoded (not suitable for production)
- Session secret should be set via SESSION_SECRET environment variable
- No password hashing implemented (future enhancement)

## Future Enhancements
- Replace JSON storage with SQLite/PostgreSQL database
- Implement secure password hashing
- Add contribution filtering and CSV export
- Create monthly reports with charts
- Add email notifications
