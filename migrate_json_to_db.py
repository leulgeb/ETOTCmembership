"""
Migration script to import data from data.json to PostgreSQL database.
This script should be run once after setting up the database.
"""
import json
import os
from datetime import datetime
from werkzeug.security import generate_password_hash
from main import app
from models import db, User, Member, Contribution, Donation, SequenceCounter, UserRole, PaymentMethod, PaymentStatus

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 
          'July', 'August', 'September', 'October', 'November', 'December']

def split_name(full_name):
    """Split full name into first, middle, last"""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], '', parts[0]  # Use same name for first and last if only one part
    elif len(parts) == 2:
        return parts[0], '', parts[1]
    else:
        # First, all middle parts, last
        return parts[0], ' '.join(parts[1:-1]), parts[-1]

def load_json_data():
    """Load data from JSON file"""
    if not os.path.exists('data.json'):
        print("❌ data.json not found!")
        return None
    
    try:
        with open('data.json', 'r') as f:
            data = json.load(f)
        print(f"✅ Loaded data.json successfully")
        return data
    except Exception as e:
        print(f"❌ Error loading data.json: {e}")
        return None

def migrate_data(dry_run=True):
    """Migrate data from JSON to PostgreSQL"""
    
    print("\n" + "="*60)
    print("ETOTC Church - JSON to PostgreSQL Migration")
    print("="*60 + "\n")
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be saved\n")
    else:
        print("⚠️  LIVE MODE - Changes will be committed to database\n")
    
    # Load JSON data
    json_data = load_json_data()
    if not json_data:
        return False
    
    with app.app_context():
        try:
            # Statistics
            stats = {
                'members_migrated': 0,
                'contributions_migrated': 0,
                'donations_migrated': 0,
                'users_created': 0
            }
            
            print("📊 JSON Data Summary:")
            print(f"   - Members: {len(json_data.get('members', []))}")
            print(f"   - Next Member ID: {json_data.get('next_member_id', 1)}")
            print(f"   - Next Receipt Number: {json_data.get('next_receipt_number', 1)}")
            print()
            
            # Step 1: Create Admin User (if not exists)
            print("👤 Step 1: Creating users...")
            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
                admin_user = User(
                    username='admin',
                    password_hash=generate_password_hash(admin_password),
                    role=UserRole.ADMIN,
                    full_name='System Administrator',
                    email='admin@etotc.org'
                )
                db.session.add(admin_user)
                stats['users_created'] += 1
                print(f"   ✓ Created admin user")
            else:
                print(f"   ℹ  Admin user already exists")
            
            # Step 2: Migrate Members
            print("\n👥 Step 2: Migrating members...")
            for json_member in json_data.get('members', []):
                # Check if member already exists
                existing_member = Member.query.filter_by(member_id=json_member['id']).first()
                if existing_member:
                    print(f"   ⚠  Member {json_member['id']} already exists, skipping")
                    continue
                
                # Split name into first, middle, last
                first_name, middle_name, last_name = split_name(json_member['name'])
                
                # Create member
                member = Member(
                    member_id=json_member['id'],
                    first_name=first_name,
                    middle_name=middle_name,
                    last_name=last_name,
                    email=json_member.get('email', ''),
                    phone=json_member.get('phone', ''),
                    password_hash=json_member.get('password_hash', generate_password_hash('default123')),
                    monthly_payment=json_member.get('monthly_payment', 30.0)
                )
                db.session.add(member)
                stats['members_migrated'] += 1
                print(f"   ✓ Migrated member: {json_member['id']} - {json_member['name']}")
                
                # Flush to get member.id for relationships
                db.session.flush()
                
                # Step 3: Migrate Contributions
                print(f"      💰 Migrating contributions for {json_member['id']}...")
                for year, year_data in json_member.get('contributions', {}).items():
                    for month in MONTHS:
                        if month in year_data:
                            contrib_data = year_data[month]
                            
                            # Determine status
                            status = PaymentStatus.PAID if contrib_data['status'] == 'Paid' else PaymentStatus.UNPAID
                            
                            # Parse payment date
                            payment_date = None
                            if contrib_data.get('date'):
                                try:
                                    payment_date = datetime.strptime(contrib_data['date'], '%Y-%m-%d')
                                except:
                                    pass
                            
                            # Create contribution
                            contribution = Contribution(
                                member_id=member.id,
                                year=int(year),
                                month=month,
                                status=status,
                                amount=contrib_data.get('amount', 0.0),
                                payment_date=payment_date,
                                receipt_number=contrib_data.get('receipt', ''),
                                payment_method=None,  # Legacy data doesn't have payment method
                                processed_by_id=admin_user.id if status == PaymentStatus.PAID else None
                            )
                            db.session.add(contribution)
                            stats['contributions_migrated'] += 1
                
                # Step 4: Migrate Donations
                if 'donations' in json_member:
                    print(f"      🎁 Migrating donations for {json_member['id']}...")
                    for donation_data in json_member['donations']:
                        # Parse donation date
                        donation_date = datetime.utcnow()
                        if 'date' in donation_data:
                            try:
                                donation_date = datetime.strptime(donation_data['date'], '%Y-%m-%d')
                            except:
                                pass
                        
                        donation = Donation(
                            member_id=member.id,
                            amount=donation_data.get('amount', 0.0),
                            purpose=donation_data.get('purpose', ''),
                            donation_date=donation_date,
                            receipt_number=donation_data.get('receipt', ''),
                            payment_method=None,  # Legacy data doesn't have payment method
                            processed_by_id=admin_user.id
                        )
                        db.session.add(donation)
                        stats['donations_migrated'] += 1
            
            # Step 5: Set up sequence counters
            print("\n🔢 Step 5: Setting up sequence counters...")
            
            # Member ID counter
            member_id_counter = SequenceCounter.query.filter_by(counter_name='member_id').first()
            if not member_id_counter:
                member_id_counter = SequenceCounter(
                    counter_name='member_id',
                    counter_value=json_data.get('next_member_id', 1)
                )
                db.session.add(member_id_counter)
                print(f"   ✓ Set member_id counter to {json_data.get('next_member_id', 1)}")
            
            # Receipt number counter
            receipt_counter = SequenceCounter.query.filter_by(counter_name='receipt_number').first()
            if not receipt_counter:
                receipt_counter = SequenceCounter(
                    counter_name='receipt_number',
                    counter_value=json_data.get('next_receipt_number', 1)
                )
                db.session.add(receipt_counter)
                print(f"   ✓ Set receipt_number counter to {json_data.get('next_receipt_number', 1)}")
            
            # Verification
            print("\n📋 Step 6: Verification...")
            db_member_count = Member.query.count()
            db_contribution_count = Contribution.query.count()
            db_donation_count = Donation.query.count()
            
            print(f"   Database members: {db_member_count}")
            print(f"   Database contributions: {db_contribution_count}")
            print(f"   Database donations: {db_donation_count}")
            
            # Migration summary
            print("\n" + "="*60)
            print("MIGRATION SUMMARY")
            print("="*60)
            print(f"Users created: {stats['users_created']}")
            print(f"Members migrated: {stats['members_migrated']}")
            print(f"Contributions migrated: {stats['contributions_migrated']}")
            print(f"Donations migrated: {stats['donations_migrated']}")
            print("="*60 + "\n")
            
            if dry_run:
                db.session.rollback()
                print("🔍 DRY RUN COMPLETE - No changes were saved")
                print("   Run with --live to commit changes to database\n")
            else:
                db.session.commit()
                print("✅ MIGRATION COMPLETE - All changes committed!")
                print("   You can now use the database-backed application\n")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ ERROR during migration: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    import sys
    
    # Check for --live flag
    live_mode = '--live' in sys.argv
    
    if live_mode:
        confirm = input("\n⚠️  You are about to run migration in LIVE mode. Continue? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Migration cancelled.")
            sys.exit(0)
    
    success = migrate_data(dry_run=not live_mode)
    sys.exit(0 if success else 1)
