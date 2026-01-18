# seed.py
from app import app, db, User, Product, Gift
from werkzeug.security import generate_password_hash

with app.app_context():  # <-- this is the fix
    db.create_all()

    # Create owner
    if not User.query.filter_by(email='owner@urmil.local').first():
        owner = User(
            name='Owner',
            email='owner@urmil.local',
            password_hash=generate_password_hash('ownerpass'),
            role='owner',
            is_admin=True
        )
        db.session.add(owner)

    # Create electrician
    if not User.query.filter_by(email='elec@demo.local').first():
        elec = User(
            name='Electrician',
            email='elec@demo.local',
            phone='9999999999',
            password_hash=generate_password_hash('elecpass'),
            role='electrician'
        )
        db.session.add(elec)

    # Sample products
    if Product.query.count() == 0:
        p1 = Product(name='LED Bulb 9W', price=120, stock=50)
        p2 = Product(name='Switch 1-gang', price=60, stock=100)
        p3 = Product(name='Wire 2.5 sqmm', price=45, stock=1000)
        db.session.add_all([p1, p2, p3])

    # Sample gifts
    if Gift.query.count() == 0:
        g1 = Gift(name='Tool Kit', points_required=50)
        g2 = Gift(name='Coffee Mug', points_required=10)
        db.session.add_all([g1, g2])

    db.session.commit()
    print("Seeding done.")
