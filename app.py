from werkzeug.utils import secure_filename
import os
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    current_user, login_required
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView

# -------------------- APP SETUP --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'change_this_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'urmil.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# -------------------- MODELS --------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(40), unique=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(40), default='customer')  # customer / electrician / shopkeeper
    points = db.Column(db.Integer, default=0)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

    def get_identifier(self):
        return self.email or self.phone or str(self.id)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    price = db.Column(db.Integer)
    stock = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    image_filename = db.Column(db.String(400))


class Gift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    points_required = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_filename = db.Column(db.String(400))

from datetime import datetime

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User', backref='orders')

    total_amount = db.Column(db.Float)
    status = db.Column(db.String(50))
    payment_method = db.Column(db.String(50))
    address = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('OrderItem', backref='order', lazy=True)

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    gift_id = db.Column(db.Integer, db.ForeignKey('gift.id'), nullable=True)

    quantity = db.Column(db.Integer)
    price = db.Column(db.Float)

    product = db.relationship('Product')
    gift = db.relationship('Gift')

class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))



class OrderModelView(MyModelView):
    column_list = ('id', 'user_id', 'total_amount', 'payment_method', 'status', 'created_at')
    form_columns = ('user_id', 'total_amount', 'payment_method', 'status')

    def after_model_change(self, form, model, is_created):
        if model.status == 'Delivered':
            award_points_for_order(model)




# -------------------- LOGIN MANAGER --------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------------------- HELPERS --------------------
def cart_total_and_items():
    cart = session.get('cart', {})
    items = []
    total = 0
    for pid_str, qty in cart.items():
        product = Product.query.get(int(pid_str))
        if product:
            subtotal = product.price * qty
            items.append({'product': product, 'qty': qty, 'subtotal': subtotal})
            total += subtotal
    return total, items


def award_points_for_order(order):
    user = order.user
    if user and user.role == 'electrician':
        pts = order.total_amount // 100
        if pts > 0:
            user.points += pts
            db.session.commit()


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'warning')
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper


# -------------------- ROUTES --------------------
@app.route('/')
def index():
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template('index.html', products=products)


@app.route('/product/<int:pid>')
def product_detail(pid):
    p = Product.query.get_or_404(pid)
    return render_template('product.html', product=p)


@app.route('/gifts')
@login_required
def gifts_page():
    gifts = Gift.query.all()
    return render_template('gifts.html', gifts=gifts)


@app.route('/cart')
def cart_view():
    total, items = cart_total_and_items()
    return render_template('cart.html', items=items, total=total)


# -------------------- FIXED: ADD TO CART USING POST --------------------
@app.route('/add_to_cart/<int:pid>', methods=['POST'])
@login_required
def add_to_cart(pid):
    qty = int(request.form.get('qty', 1))   # 👈 get quantity from HTML

    cart = session.get('cart', {})

    if str(pid) in cart:
        cart[str(pid)] += qty
    else:
        cart[str(pid)] = qty

    session['cart'] = cart
    flash('Added to cart!', 'success')
    return redirect(url_for('cart_view'))

# -------------------- REMOVE ITEM (POST ONLY) --------------------
@app.route('/remove_from_cart/<int:pid>', methods=['POST'])
@login_required
def remove_from_cart(pid):
    cart = session.get('cart', {})
    cart.pop(str(pid), None)
    session['cart'] = cart
    flash('Item removed', 'info')
    return redirect(url_for('cart_view'))


# -------------------- CHECKOUT --------------------
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    total, items = cart_total_and_items()

    if request.method == 'POST':
        address = request.form['address']
        payment = request.form['payment']

        order = Order(
            user_id=current_user.id,
            total_amount=total,
            payment_method=payment,
            status='Pending',
            address=address
        )

        db.session.add(order)
        db.session.commit()   # VERY IMPORTANT — get order.id

        for it in items:
            oi = OrderItem(
                order_id=order.id,
                product_id=it['product'].id,
                quantity=it['qty'],
                price=it['product'].price
            )
            db.session.add(oi)

        db.session.commit()

        session['cart'] = {}
        flash('Order placed successfully!', 'success')
        return redirect(url_for('orders_page'))

    return render_template('checkout.html', total=total, items=items)

# -------------------- AUTH --------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        role = request.form.get("role")
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        password = generate_password_hash(request.form['password'])

        if role == "customer":
            approved = True
        else:
            approved = False   # electrician & shopkeeper need admin approval

        user = User(
            name=name,
            email=email,
            phone=phone,
            password_hash=password,
            role=role,
            is_approved=approved
        )

        db.session.add(user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.is_approved:
                flash("Your account is waiting for admin approval.", "warning")
                return redirect(url_for("login"))

            login_user(user)
            flash('Login successful!', 'success')

            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('index'))
        else:
            flash('Invalid credentials!', 'danger')

    return render_template('login.html')



@app.route('/logout')
def logout():
    logout_user()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    orders = current_user.orders
    return render_template('profile.html', orders=orders)


# -------------------- ADMIN PANEL --------------------
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    return render_template('admin_dashboard.html')


class MyAdminIndex(AdminIndexView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))


class MyModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin
    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))


class OrderModelView(MyModelView):
    column_list = ('id', 'user', 'total_amount', 'payment_method', 'status', 'created_at')
    form_columns = ('user', 'total_amount', 'payment_method', 'status')

    def after_model_change(self, form, model, is_created):
        if model.status == 'Delivered':
            award_points_for_order(model)


admin = Admin(app, name='Urmil Admin', index_view=MyAdminIndex())
admin.add_view(MyModelView(User, db.session))
admin.add_view(MyModelView(Product, db.session))
admin.add_view(MyModelView(Gift, db.session))
admin.add_view(OrderModelView(Order, db.session))
admin.add_view(MyModelView(OrderItem, db.session))


from werkzeug.utils import secure_filename

@app.route('/add_product', methods=['GET', 'POST'])
@login_required
@admin_required
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = int(request.form['price'])
        stock = int(request.form.get('stock', 0))
        desc = request.form.get('description')

        image = request.files['image']
        filename = secure_filename(image.filename)
        image.save(os.path.join('static/uploads', filename))

        product = Product(
            name=name,
            price=price,
            stock=stock,
            description=desc,
            image_filename=filename
        )
        db.session.add(product)
        db.session.commit()

        flash('Product added successfully')
        return redirect(url_for('index'))

    return render_template('add_product.html')


@app.route('/delete_product/<int:pid>', methods=['POST'])
@login_required
@admin_required
def delete_product(pid):
    product = Product.query.get_or_404(pid)
    db.session.delete(product)
    db.session.commit()
    flash('❌ Product deleted successfully', 'info')
    return redirect(url_for('index'))
@app.route('/add_gift', methods=['GET', 'POST'])
@login_required
@admin_required
def add_gift():
    if request.method == 'POST':
        name = request.form['name']
        points = int(request.form['points_required'])
        desc = request.form.get('description', '')

        file = request.files['image']
        filename = None

        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        gift = Gift(
            name=name,
            points_required=points,
            description=desc,
            image_filename=filename
        )

        db.session.add(gift)
        db.session.commit()

        flash('🎁 Gift added successfully!', 'success')
        return redirect(url_for('gifts_page'))

    return render_template('add_gift.html')

@app.route('/orders')
@login_required
def orders_page():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('order.html', orders=orders)
@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin_orders.html', orders=orders)
@app.route('/admin/order/<int:oid>/status', methods=['POST'])
@login_required
@admin_required
def update_order_status(oid):
    order = Order.query.get_or_404(oid)
    order.status = request.form['status']
    db.session.commit()
    flash('Order status updated', 'success')
    return redirect(url_for('admin_orders'))
@app.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)

    # User can only see their own order, admin can see all
    if not current_user.is_admin and order.user_id != current_user.id:
        flash("Access denied", "danger")
        return redirect(url_for('index'))

    return render_template('order_detail.html', order=order)

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.id.asc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/approve_users')
@login_required
@admin_required
def approve_users():
    users = User.query.filter_by(is_approved=False).all()
    return render_template('approve_users.html', users=users)


@app.route('/admin/approve/<int:user_id>')
@login_required
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash("User approved!", "success")
    return redirect(url_for('approve_users'))



# -------------------- RUN --------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)